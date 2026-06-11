import asyncio
import logging
import multiprocessing
import os
import shutil
import time
from pathlib import Path, PureWindowsPath
from time import sleep
from types import SimpleNamespace
from typing import Dict, List
import threading
import subprocess
from glob import glob

import pandas as pd
from django.db import transaction
import starfile

from Smartscope.core.db_manipulations import websocket_update, update_target_label
# from Smartscope.core.frames import get_frames_prefix, parse_frames_prefix
from Smartscope.core.models.grid import AutoloaderGrid
from Smartscope.core.models.models_actions import update_fields
from Smartscope.core.models.high_mag import HighMagModel
from Smartscope.core.models.hole import HoleModel
from Smartscope.core.frames import get_smartscope_frames_dir

from .preprocessing_pipeline import PreprocessingPipeline
from .nextpyp_preprocessing_cmd_kwargs import NextPYPPreprocessingCmdKwargs
from .nextpyp_preprocessing_pipeline_form import NextPYPPreprocessingPipelineForm

from nextpyp.client import Client
from nextpyp.client.credentials import Credentials
from nextpyp.client.args import block_args, PypArgValues, PypBlock
from nextpyp.client.gen import (
    SingleParticleSessionArgs,
    SessionsService,
    RealTimeC2SListenToSession,
    RealTimeS2CSessionStatus,
    RealTimeS2CSessionSmallData,
    RealTimeS2CSessionLargeData,
    RealTimeS2CUpdatedParameters,
    RealTimeS2CSessionMicrograph,
    RealTimeS2CSessionTwoDClasses,
    RealTimeS2CSessionExport,
    RealTimeS2CSessionFilesystems,
    RealTimeS2CSessionTransferInit,
    RealTimeS2CSessionTransferWaiting,
    RealTimeS2CSessionTransferStarted,
    RealTimeS2CSessionTransferProgress,
    RealTimeS2CSessionTransferFinished,
    RealTimeS2CSessionDaemonSubmitted,
    RealTimeS2CSessionDaemonStarted,
    RealTimeS2CSessionDaemonFinished,
    RealTimeS2CSessionJobSubmitted,
    RealTimeS2CSessionJobStarted,
    RealTimeS2CSessionJobFinished,
    SessionDaemon,
    SessionExportResult,
    SessionExportResultSucceeded,
    SessionExportResultSucceededOutputFilter
)

logger = logging.getLogger(__name__)

class NextPYPPreprocessingPipeline(PreprocessingPipeline):
    verbose_name = 'NextPYP Preprocessing Pipeline'
    name = 'nextpypPipeline'
    description = 'Processing pipeline using nextPYP single-particle session'

    to_process_queue = None  # Not needed
    processed_queue = multiprocessing.Queue()
    child_process: List = []
    to_update = []
    incomplete_processes = []
    metadata_by_name = {}

    pipeline_form = NextPYPPreprocessingPipelineForm
    cmdkwargs_handler = NextPYPPreprocessingCmdKwargs

    def __init__(self, grid: AutoloaderGrid, cmd_data: Dict):
        super().__init__(grid=grid)
        self.microscope = grid.session_id.microscope_id
        self.detector = grid.session_id.detector_id
        self.cmd_data = self.cmdkwargs_handler.parse_obj(cmd_data)
        self.path_to_token = self.cmd_data.path_to_token
        self.nextpyp_userid = self.cmd_data.nextpyp_userid

        # Read the token from the file if it exists
        assert os.path.exists(self.path_to_token), f"Token file does not exist: {self.path_to_token}"
        logger.info(f"Reading token from {self.path_to_token}")
        with open(self.path_to_token, 'r') as f:
            self.token = f.read().strip()
            
        self.frames_directory = self.cmd_data.frames_directory
        self.remote_user = self.cmd_data.remote_user
        self.remote_host = self.cmd_data.remote_host

        self.client = self.initialize_client()
        self.session = None
        self.session_path = None

        self.metadata_by_name = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # For keeping track of good vs bad micrographs
        self.good_micrographs = []
        self.bad_micrographs = []
        self.path_to_filter = None
        self.frame_file_extension = None
        
        
        
    def initialize_client(self):
        # print(f"[DEBUG] url base: {self.cmd_data.url_base}, userid: {self.nextpyp_userid}, token: {self.token}")
        return Client(
            url_base=self.cmd_data.url_base,
            credentials=Credentials(
                userid=self.nextpyp_userid,
                token=self.token,
            )
        )

    def configure_session_args(self, pixel_size: float, gain_reference_name: str):
        self.pyp_args = PypArgValues(block_args(PypBlock.SESSION_SINGLE_PARTICLE))

        # logger.info(f"NextPYP data_path: {self.cmd_data.frames_directory}")
        real_frames_directory = os.path.dirname(self.cmd_data.frames_directory)
        self.pyp_args.data_path = self.cmd_data.frames_directory
        self.pyp_args.gain_reference = os.path.join(real_frames_directory, gain_reference_name)
        # logger.info(f"Gain reference path: {self.pyp_args.gain_reference}")
        self.pyp_args.gain_flipv = self.detector.gain_flip

        self.pyp_args.scope_pixel = float(pixel_size)
        self.pyp_args.scope_voltage = self.microscope.voltage
        self.pyp_args.scope_cs = self.microscope.spherical_abberation

        self.pyp_args.stream_transfer_operation = self.cmd_data.stream_transfer_operation
        self.pyp_args.stream_transfer_restart = self.cmd_data.stream_transfer_restart

        self.pyp_args.detect_rad = self.cmd_data.detect_rad
        self.pyp_args.detect_method = self.cmd_data.detect_method
        self.pyp_args.detect_dist = self.cmd_data.detect_dist

        self.pyp_args.class2d_num = self.cmd_data.class2d_num
        self.pyp_args.class2d_box = self.cmd_data.class2d_box
        self.pyp_args.class2d_bin = self.cmd_data.class2d_bin

        self.pyp_args.slurm_verbose = self.cmd_data.slurm_verbose
        self.pyp_args.slurm_tasks = self.cmd_data.slurm_tasks
        self.pyp_args.slurm_memory = self.cmd_data.slurm_memory
        self.pyp_args.slurm_daemon_walltime = self.cmd_data.slurm_daemon_walltime

    def _wait_for_mdoc_fields(self, frames_dir: Path, timeout=600, interval=5):
        """Wait for the first .mdoc file and return (pixel_size, gain_reference_path)."""
        from Smartscope.lib.image.image_file import parse_mdoc
        logger.info(f"Waiting for first .mdoc file in {frames_dir} to determine pixel_size and gain reference...")
        waited = 0
        while waited < timeout:
            if self.is_stop_file():
                raise KeyboardInterrupt("Stop requested while waiting for mdoc fields")
            mdoc_files = list(frames_dir.glob('*.mdoc'))
            if mdoc_files:
                mdoc_file = mdoc_files[0]
                try:
                    metadata = parse_mdoc(str(mdoc_file), movie=True)
                    row = metadata.iloc[0]
                    pixel_size = row.PixelSpacing
                    gain_ref_name = row.GainReference
                    file_type = PureWindowsPath(row.SubFramePath).suffix
                    gain_reference_path = str(frames_dir / gain_ref_name)
                    logger.info(f"Got pixel_size={pixel_size}, gain_reference={gain_ref_name} from {mdoc_file.name}")
                    return pixel_size, gain_ref_name, file_type
                except Exception as e:
                    logger.warning(f"Failed to parse {mdoc_file}: {e}, retrying...")
            time.sleep(interval)
            waited += interval
        raise TimeoutError(f"Timed out after {timeout}s waiting for a .mdoc file in {frames_dir}")

    def start(self):
        self.incomplete_processes = self.list_incomplete_processes()
        logger.info(f'Starting NextPYP Preprocessing')
        smartscope_frames_dir = get_smartscope_frames_dir(self.grid)
        pixel_size, gain_ref_name, self.frame_file_extension = self._wait_for_mdoc_fields(smartscope_frames_dir)
        gain_reference_path = os.path.join(self.frames_directory, gain_ref_name)
        # logger.info("Gain reference path: ", os.path.join(self.cmd_data.frames_directory, gain_ref_name))
        self.configure_session_args(pixel_size, gain_ref_name)

        path = self.client.services.sessions.pick_folder()
        args = SingleParticleSessionArgs(
            name=self.grid.grid_id,
            path=path,
            group_id=self.cmd_data.group_id,
            values=self.pyp_args.write(),
        )
        self.session_path = path

        self.session = self.client.services.single_particle_sessions.create(args)
        assert self.session is not None, "Session not created"

        def _run_listener():
            try:
                asyncio.run(self.listen_to_session(self.session.session_id, path))
            except Exception as e:
                logger.exception(f"Listener thread crashed: {e}")

        thread = threading.Thread(target=_run_listener, daemon=True)
        thread.start()
        logger.info("Started async listener thread for session updates.")
        
        self.client.services.sessions.start(self.session.session_id, SessionDaemon.Streampyp)
        logger.info("Started NextPYP session with ID: %s", self.session.session_id)
        
        while not self.is_stop_file():
            self.incomplete_processes = self.list_incomplete_processes()
            # logger.info(f"[nextpyp][start] Length of processed queue: {self.processed_queue.qsize()}")
            # self.check_for_update()
            time.sleep(0.5)

            if self.grid.status in ['complete', 'error'] and not any(
                x.status in ['acquired', 'skipped'] for x in self.incomplete_processes
            ):
                logger.info("All micrographs processed — exiting start loop.")
                # break

    def list_incomplete_processes(self):
        # print("[nextpyp] Len all processes: ", len(list(self.grid.highmagmodel_set.filter(status__in=['acquired', 'skipped', 'completed', 'error']))))
        # print("[nextpyp] Len filtered processes: ", 
        #       len(list(self.grid.highmagmodel_set.filter(status__in=['acquired', 'skipped']))))
        return list(self.grid.highmagmodel_set
                    .filter(status__in=['acquired', 'skipped'])
                    .order_by('status', 'completion_time'))

    async def listen_to_session(self, session_id, path_to_save):
        async with self.client.realtime_services.single_particle_session as srv:
            await srv.send_listen_to_session(RealTimeC2SListenToSession(session_id))

            while not self._stop_event.is_set():
                await asyncio.to_thread(self.grid.refresh_from_db)
                self.incomplete_processes = await asyncio.to_thread(self.list_incomplete_processes)

                # if not any(x.status in ['acquired', 'skipped'] for x in self.incomplete_processes):
                #     logger.info("All micrographs processed — exiting listen loop.")
                #     break

                msg = await srv.recv()
                # logger.debug(f"[listen_to_session] Received message type: {type(msg).__name__}")
                if isinstance(msg, RealTimeS2CSessionMicrograph):
                    movie = SimpleNamespace(
                        name=msg.micrograph.id,
                        shape_x=msg.micrograph.image_dims.width,
                        shape_y=msg.micrograph.image_dims.height,
                        pixel_size=msg.micrograph.image_dims.pixel_a
                    )
                    self.processed_queue.put(movie)
                    logger.info(f"[nextpyp][listen_to_session] Length of processed queue: {self.processed_queue.qsize()}")
                    logger.info(f"Length of incomplete processes: {len(self.incomplete_processes)}")
                    self.metadata_by_name[movie.name] = msg.micrograph
                    await self.check_for_update()
                    await self.update_processes()
                
                elif isinstance(msg, RealTimeS2CSessionExport):
                    logger.info(msg)
                    if msg.export.result is None:
                        logger.info(f"Export job submitted, waiting for result...")
                    else:
                        result = SessionExportResult.deserialize(msg.export.result)
                        if isinstance(result, SessionExportResultSucceeded):
                            if isinstance(result.output, SessionExportResultSucceededOutputFilter):
                                filter_path = result.output.path  # relative to session folder
                                logger.info(f"Filter exported to: {filter_path}")

                                session_name = Path(self.session_path).name
                                # copy .star file
                                star_src_path = Path(self.session_path, filter_path, f"{session_name}.star")
                                grid_dir = await asyncio.to_thread(lambda: self.grid.directory)
                                star_dest_path = os.path.join(grid_dir, f"{session_name}.star")
                                ok = await asyncio.to_thread(self.scp_file, star_src_path, star_dest_path, timeout=60)
                                if not ok:
                                    logger.warning(f".star file copy failed: {star_dest_path}")
                                
                                await asyncio.to_thread(self.classify_micrographs, star_dest_path)


    def make_dest_paths(self):
        # Path should be: /path/to/data/<group ID>/<session ID>/pngs for micrographs and
        # /path/to/data/<group ID>/<session ID>/<high mag ID> for CTF images
        grid_id = self.grid.grid_id
        session_id = self.session.session_id
        print("[nextpyp] self.grid.directory: ", self.grid.directory)
        
        return None, None
            
    async def check_for_update(self):
        # logger.info('Checking for NextPYP updates')
        while self.processed_queue.qsize() > 0:
            movie = self.processed_queue.get()
            if not movie:
                continue
            logger.info(f"Processing movie: {movie.name}")
            instance = self.incomplete_processes[0] if self.incomplete_processes and len(self.incomplete_processes) > 0 else None
            if instance is None:
                logger.warning(f"No HighMagModel match for {movie.name}")
                continue

            metadata = self.metadata_by_name.get(movie.name)
            if metadata is None:
                logger.warning(f"No metadata found for {movie.name}")
                continue

            data = {
                'defocus': (metadata.defocus1 + metadata.defocus2) / 2,
                'astig': metadata.defocus1 - metadata.defocus2,
                'angast': metadata.angle_astig,
                'ctffit': metadata.ccc,
                'shape_x': movie.shape_x,
                'shape_y': movie.shape_y,
                'pixel_size': movie.pixel_size,
                'status': 'completed'
            }
            
            # Get .webp images and copy them to Smartscope
            nextpyp_filename = f"{metadata.id}"
            micrograph_source_path = os.path.join(self.session_path, "webp", f"{nextpyp_filename}.webp")
            ctf_source_path = os.path.join(self.session_path, "webp", f"{nextpyp_filename}_ctffit.webp")
            # assert os.path.exists(micrograph_source_path), f"Micrograph source path does not exist: {micrograph_source_path}"
            # assert os.path.exists(ctf_source_path), f"CTF source path does not exist: {ctf_source_path}"
            
            # Destination paths: write webp directly, no conversion needed
            png_path = os.path.join(instance.working_dir, 'pngs', f'{instance.name}.webp')
            ctf_path = os.path.join(instance.working_dir, instance.name, 'ctf.webp')

            os.makedirs(os.path.dirname(png_path), exist_ok=True)
            os.makedirs(os.path.dirname(ctf_path), exist_ok=True)

            img_ok  = await asyncio.to_thread(self.scp_file, micrograph_source_path, png_path, timeout=60)
            ctf_ok  = await asyncio.to_thread(self.scp_file, ctf_source_path, ctf_path, timeout=60)
            if not img_ok:
                logger.warning(f"Micrograph image copy failed for {movie.name}")
            if not ctf_ok:
                logger.warning(f"CTF image copy failed for {movie.name}")
            
            parent = await asyncio.to_thread(lambda: instance.hole_id)
            with self._lock:
                self.to_update += [
                    update_fields(instance, data),
                    update_fields(parent, dict(status='completed'))
                ]

    def copy_file_from_remote(self, remote_path, local_path):
        cmd = [
            "scp",
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            f"{self.remote_user}@{self.remote_host}:{remote_path}",
            local_path
        ]
        subprocess.run(cmd, check=True)

    def scp_file(self, remote_webp_path, local_webp_path, timeout=60):
        """
        SCPs a file from the remote nextPYP host to local_webp_path.
        Returns True on success, False on failure.
        """
        try:
            logger.info(f"Copying {remote_webp_path} → {local_webp_path}")
            self.copy_file_from_remote(remote_path=remote_webp_path, local_path=local_webp_path)
        except Exception as e:
            logger.error(f"SCP failed for {remote_webp_path}: {e}")
            return False

        waited = 0
        while not os.path.exists(local_webp_path):
            time.sleep(1)
            waited += 1
            if waited > timeout:
                logger.warning(f"Timeout waiting for {local_webp_path}")
                return False

        logger.info(f"File ready at {local_webp_path}")
        return True
    
    def save_all_updates(self):
        with transaction.atomic():
            for update in self.to_update:
                update.save()

    async def update_processes(self):
        with self._lock:
            if len(self.to_update) == 0:
                logger.info("No updates, sleeping briefly.")
                return await asyncio.to_thread(time.sleep, 1)

            await asyncio.to_thread(self.save_all_updates)
            await asyncio.to_thread(websocket_update, self.to_update, self.grid.grid_id)
            self.to_update = []

    def stop(self):
        logger.info("Stopping NextPYP Preprocessing Pipeline")
        for proc in self.child_process:
            self.to_process_queue.put('exit')
        for proc in self.child_process:
            proc.join()
        logger.debug('Process joined')
        
        self._stop_event.set()
        if not self.client or not self.session:
            logger.info("Client or session not initialized, cannot cancel.")
            return

        logger.info(f"Cancelling session with ID: {self.session.session_id}")
        self.client.services.sessions.cancel(self.session.session_id)
        sleep(10)
        logger.info("Session cancelled.")

    def get_file_name_only(self, arr):
        cleaned = [Path(file).stem for file in arr]
        return cleaned
    
    def classify_micrographs(self, mg_file):
        exported_data = starfile.read(mg_file)
        particles_df = exported_data["particles"]
        good_mg_temp = particles_df["rlnMicrographName"].unique().tolist()
        self.good_micrographs = [Path(file).stem for file in good_mg_temp]
        good_set = set(self.good_micrographs)

        logger.info(f"Found {len(self.good_micrographs)} micrographs that passed the filter")
        logger.info(f"Good files: {self.good_micrographs}")

        # all_hm = HighMagModel.parent_manager.filter(
        #     grid_id=self.grid.pk, 
        #     status__in=['completed']
        # ).values_list('hm_id', 'frames')

        # all_hm = HighMagModel.objects.filter(
        #     hole_id__grid_id=self.grid
        # ).values_list('hm_id', 'frames')
        all_hm = HighMagModel.objects.filter(
            grid_id=self.grid.pk, 
            status__in=['completed']
        ).values_list('hm_id', 'frames')

        logger.info(f"All high-mags: {all_hm}")

        good_pks = []
        bad_pks = []
        for hm_id, frames in all_hm:
            if Path(frames).stem in good_set:
                good_pks.append(hm_id)
            else:
                bad_pks.append(hm_id)

        logger.info(f"Labelling {len(good_pks)} micrographs as Good, {len(bad_pks)} as Bad")
        update_target_label(HighMagModel, good_pks, "Good", "nextPYP Curation")
        update_target_label(HighMagModel, bad_pks, "Bad", "nextPYP Curation")