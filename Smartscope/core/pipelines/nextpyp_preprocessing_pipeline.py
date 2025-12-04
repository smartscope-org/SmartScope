import asyncio
import logging
import multiprocessing
import os
import shutil
import time
from pathlib import Path
from time import sleep
from types import SimpleNamespace
from typing import Dict, List
import threading
import subprocess

import pandas as pd
from django.db import transaction

from Smartscope.core.db_manipulations import websocket_update
from Smartscope.core.frames import get_frames_prefix, parse_frames_prefix
from Smartscope.core.models.grid import AutoloaderGrid
from Smartscope.core.models.models_actions import update_fields
from Smartscope.core.models.high_mag import HighMagModel
from Smartscope.core.models.hole import HoleModel

from .preprocessing_pipeline import PreprocessingPipeline
from .nextpyp_preprocessing_cmd_kwargs import NextPYPPreprocessingCmdKwargs
from .nextpyp_preprocessing_pipeline_form import NextPYPPreprocessingPipelineForm

from nextpyp.client import Client
from nextpyp.client.credentials import Credentials
from nextpyp.client.args import block_args, PypArgValues, PypBlock
from PIL import Image
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
        self.pixel_size = self.cmd_data.pixel_size
        self.client = self.initialize_client()
        self.session = None
        self.session_path = None

        self.metadata_by_name = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        
        
    def initialize_client(self):
        return Client(
            url_base='https://research-bartesaghilab-08.oit.duke.edu',
            credentials=Credentials(
                userid=self.nextpyp_userid,
                token=self.token,
            )
        )

    def configure_session_args(self):
        self.pyp_args = PypArgValues(block_args(PypBlock.SESSION_SINGLE_PARTICLE))

        self.pyp_args.data_path = self.frames_directory
        self.pyp_args.gain_reference = '/nfs/bartesaghilab/nextpyp/spr/Gain.mrc'
        self.pyp_args.gain_flipv = True

        self.pyp_args.scope_pixel = self.pixel_size
        self.pyp_args.scope_voltage = 300
        self.pyp_args.scope_cs = self.microscope.spherical_abberation

        self.pyp_args.stream_transfer_operation = "link"
        self.pyp_args.stream_transfer_restart = True

        self.pyp_args.detect_rad = 65.0
        self.pyp_args.detect_method = "all"
        self.pyp_args.detect_dist = 40

        self.pyp_args.class2d_num = 50
        self.pyp_args.class2d_box = 96
        self.pyp_args.class2d_bin = 4

        self.pyp_args.slurm_verbose = True
        self.pyp_args.slurm_tasks = 7
        self.pyp_args.slurm_memory = 14
        self.pyp_args.slurm_daemon_walltime = "0-01:00:00"

    def start(self):
        self.incomplete_processes = self.list_incomplete_processes()
        logger.info(f'Starting NextPYP Preprocessing')
        self.configure_session_args()

        path = self.client.services.sessions.pick_folder()
        args = SingleParticleSessionArgs(
            name='new_test',
            path=path,
            group_id='fmqVThRKDCY7WqgK',
            values=self.pyp_args.write(),
        )
        self.session_path = path

        self.session = self.client.services.single_particle_sessions.create(args)
        assert self.session is not None, "Session not created"

        thread = threading.Thread(
            target=lambda: asyncio.run(self.listen_to_session(self.session.session_id, path)),
            daemon=True
        )
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
                break

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
            
            real_data_root = "/srv/homedir/smartscope"
            png_path = instance.png #.replace('/mnt', real_data_root)
            ctf_path = instance.ctf_img #.replace('/mnt', real_data_root)
            
            if not os.path.exists(os.path.dirname(png_path)):
                logger.warning(f"PNG path does not exist: {os.path.dirname(png_path)}")
            else:
                logger.info(f"PNG path exists: {os.path.dirname(png_path)}")
            if not os.path.exists(os.path.dirname(ctf_path)):
                logger.warning(f"CTF path does not exist: {os.path.dirname(ctf_path)}")
                os.makedirs(os.path.dirname(ctf_path), exist_ok=True)
                logger.info(f"Creating directory for CTF path: {os.path.dirname(ctf_path)}")
            else:
                logger.info(f"CTF path exists: {os.path.dirname(ctf_path)}")
            await asyncio.to_thread(self.wait_and_convert_webp_to_png, micrograph_source_path, png_path, timeout=60)
            await asyncio.to_thread(self.wait_and_convert_webp_to_png, ctf_source_path, ctf_path, timeout=60)
            
            parent = await asyncio.to_thread(lambda: instance.hole_id)
            with self._lock:
                self.to_update += [
                    update_fields(instance, data),
                    update_fields(parent, dict(status='completed'))
                ]

    def copy_file_from_remote(self, remote_path, local_path, user='sh696', host='hpc-bartesaghi-login-01.oit.duke.edu'):
        cmd = [
            "scp",
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            f"{user}@{host}:{remote_path}",
            local_path
        ]
        subprocess.run(cmd, check=True)

    def wait_and_convert_webp_to_png(self, webp_path, target_path, timeout=30, interval=0.5):
        """
        Waits for a .webp file to exist, converts it to PNG, and saves it to target_path.
        """
        target_path_webp = target_path.replace('.png', '.webp')
        logger.info("Copying file from remote host...")
        self.copy_file_from_remote(
            host="hpc-bartesaghi-login-01.oit.duke.edu",
            remote_path=webp_path,
            local_path=target_path_webp
        )
        
        logger.info(f"Waiting for {target_path_webp} to exist...")
        waited = 0
        while not os.path.exists(target_path_webp):
            time.sleep(1)
            waited += 1
            if waited > timeout:
                logger.warning(f"Timeout waiting for {target_path_webp}")
                return False

        try:
            img = Image.open(target_path_webp).convert("RGB")
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            img.save(target_path, "PNG")
            logger.info(f"Saved converted PNG to {target_path}")
            os.remove(target_path_webp)
            logger.info(f"Removed temporary file {target_path_webp}")
            return True
        except Exception as e:
            logger.error(f"Failed to convert {target_path_webp} → {target_path}: {e}")
            return False
    
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
        self._stop_event.set()
        if not self.client or not self.session:
            print("Client or session not initialized, cannot cancel.")
            return

        print(f"Cancelling session with ID: {self.session.session_id}")
        self.client.services.sessions.cancel(self.session.session_id)
        sleep(10)
        print("Session cancelled.")