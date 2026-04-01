
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Set

from django.db import transaction

from Smartscope.core.db_manipulations import websocket_update
from Smartscope.core.frames import get_smartscope_frames_dir
from Smartscope.core.models.grid import AutoloaderGrid
from Smartscope.core.models.high_mag import HighMagModel
from Smartscope.core.models.hole import HoleModel
from Smartscope.core.models.models_actions import update_fields
from Smartscope.core.models import Selector

from .preprocessing_pipeline import PreprocessingPipeline
from .globus_pipeline_config import GlobusPipelineConfig
from .globus_pipeline_form import GlobusPipelineForm

logger = logging.getLogger(__name__)

# Mapping from result JSON keys to Selector plugin names.
# Each entry creates a Selector row per highmag with value from the result.
# Plugin YAMLs in config/smartscope/plugins/ define display (colors, limits, exclude).
RESULT_SELECTORS = {
    'particle_count': 'Particle count',
    'mean_pick_score': 'Pick score',
    'ctf_max_resolution': 'CTF resolution',
    'total_motion': 'Total motion',
    'ice_thickness': 'Ice thickness',
}

TRANSFER_SCOPE = "urn:globus:auth:scope:transfer.api.globus.org:all"
FLOWS_SCOPE = "https://auth.globus.org/scopes/eec9b274-0c81-4334-bdc2-54e90e689b9e/flow_user"



# ---- Globus Auth Helpers ----

def _load_tokens(token_file: str) -> dict:
    path = Path(token_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"No cached Globus tokens at {path}. "
            f"Run: python globus_login.py get-url && python globus_login.py exchange <code>"
        )
    return json.loads(path.read_text())


def _save_tokens(token_file: str, tokens: dict):
    path = Path(token_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2))
    path.chmod(0o600)


def _build_transfer_client(cmd_data: GlobusPipelineConfig):
    from globus_sdk import NativeAppAuthClient, TransferClient, RefreshTokenAuthorizer

    tokens = _load_tokens(cmd_data.token_file)
    transfer_tokens = tokens["transfer.api.globus.org"]

    auth_client = NativeAppAuthClient(cmd_data.globus_client_id)
    authorizer = RefreshTokenAuthorizer(
        transfer_tokens["refresh_token"],
        auth_client,
        access_token=transfer_tokens["access_token"],
        expires_at=transfer_tokens["expires_at_seconds"],
        on_refresh=lambda td: _save_tokens(cmd_data.token_file, {
            **_load_tokens(cmd_data.token_file),
            "transfer.api.globus.org": td.by_resource_server["transfer.api.globus.org"],
        }),
    )
    return TransferClient(authorizer=authorizer)


def _build_flows_client(cmd_data: GlobusPipelineConfig):
    """Build a Globus Flows client (SpecificFlowClient) for running flows."""
    from globus_sdk import NativeAppAuthClient, SpecificFlowClient, RefreshTokenAuthorizer

    tokens = _load_tokens(cmd_data.token_file)
    # The flow-specific scope tokens are keyed by the flow's UUID.
    # Fall back to flows.globus.org if flow-specific tokens aren't available.
    flow_tokens = tokens.get(
        cmd_data.globus_flow_id,
        tokens.get("flows.globus.org", tokens.get("transfer.api.globus.org"))
    )

    auth_client = NativeAppAuthClient(cmd_data.globus_client_id)
    authorizer = RefreshTokenAuthorizer(
        flow_tokens["refresh_token"],
        auth_client,
        access_token=flow_tokens["access_token"],
        expires_at=flow_tokens["expires_at_seconds"],
    )
    return SpecificFlowClient(cmd_data.globus_flow_id, authorizer=authorizer)


# ---- Path Mapping ----

def _container_to_globus_path(container_path: str, source_base_path: str,
                              container_root: str = "") -> str:
    """Convert a container path to a Globus collection path.

    Args:
        container_path: Full path inside the container
        source_base_path: Globus collection prefix (e.g. "/SmartScope")
        container_root: Container-side prefix to strip (e.g. "/mnt/arctica/Superluminal/SmartScope")
                        Derived from detector.frames_directory at runtime.
    """
    rel = container_path
    if container_root and rel.startswith(container_root):
        rel = rel[len(container_root):]
    return f"{source_base_path.rstrip('/')}/{rel.lstrip('/')}"


def _globus_dest_path(container_path: str, destination_base_path: str,
                      project_path: str, square: str, group: str) -> str:
    """Build destination path on HPC.

    e.g. /CryoEM/Projects/Rori_SUN-0018080/Movies/Square-14/Group-42/frame.tif
    """
    filename = Path(container_path).name
    return (f"{destination_base_path.rstrip('/')}/"
            f"{project_path.strip('/')}/"
            f"Movies/{square}/{group}/{filename}")


class GlobusPreprocessingPipeline(PreprocessingPipeline):

    verbose_name = 'Globus Preprocessing Pipeline'
    name = 'globusPipeline'
    description = 'Globus Transfer & Globus Compute via Globus Flows. Users can write and register their own flows to perform any combination of transfer, compute, and return.'

    cmdkwargs_handler = GlobusPipelineConfig
    pipeline_form = GlobusPipelineForm

    incomplete_processes: List = []
    to_update: List = []

    def __init__(self, grid: AutoloaderGrid, cmd_data: Dict):
        super().__init__(grid=grid)
        self.microscope = self.grid.session_id.microscope_id
        self.detector = self.grid.session_id.detector_id
        self.cmd_data = self.cmdkwargs_handler.parse_obj(cmd_data)

        # Resolve this grid's remote project from slot mapping
        self.grid_position = getattr(self.grid, 'position', None)
        self.project_path = ""
        if self.grid_position:
            self.project_path = self.cmd_data.get_project_for_slot(self.grid_position)

        # Frames directory for this grid (where SerialEM writes .tif/.mrc files)
        self.frames_dir = get_smartscope_frames_dir(self.grid)

        # Container-side roots to strip when building Globus paths.
        # Frames and data may be mounted differently but map to the same Globus collection.
        # frames: /mnt/arctica/Superluminal/SmartScope/... -> /SmartScope/...
        # data:   /mnt/data/...                            -> /SmartScope/...
        self.container_frames_root = str(self.detector.frames_directory).rstrip('/')
        self.container_data_root = str(self.grid.directory).rsplit(
            str(self.grid.session_id.working_directory), 1)[0].rstrip('/')

        self._stop = threading.Event()
        self._submitted_groups: Set[str] = set()  # track submitted grouping keys
        self._active_flow_runs: Dict[str, dict] = {}  # flow_run_id -> {batch, group_key}

        self.tc = None       # TransferClient (for transfer_only mode)
        self.fc = None       # SpecificFlowClient (for transfer_and_process mode)
        self.fc_general = None  # FlowsClient (for checking run status)

    # ---- Init ----

    def _init_globus_clients(self):
        self.tc = _build_transfer_client(self.cmd_data)
        logger.info("Globus Transfer client initialized")

        if not self.cmd_data.globus_flow_id:
            logger.info("No flow ID configured — running in transfer-only mode "
                        "(files transferred to HPC, no remote processing)")
        else:
            try:
                self.fc = _build_flows_client(self.cmd_data)
                # Also build a general FlowsClient for checking run status
                from globus_sdk import FlowsClient
                tokens = _load_tokens(self.cmd_data.token_file)
                flows_tokens = tokens.get('flows.globus.org', {})
                if flows_tokens:
                    from globus_sdk import NativeAppAuthClient, RefreshTokenAuthorizer
                    auth_client = NativeAppAuthClient(self.cmd_data.globus_client_id)
                    authorizer = RefreshTokenAuthorizer(
                        flows_tokens['refresh_token'], auth_client,
                        access_token=flows_tokens['access_token'],
                        expires_at=flows_tokens['expires_at_seconds'],
                    )
                    self.fc_general = FlowsClient(authorizer=authorizer)
                logger.info("Globus Flows client initialized")
            except Exception as e:
                logger.warning(f"Could not init Flows client: {e}. Falling back to transfer-only mode.")

    # ---- Grouping Logic ----

    def _group_key(self, hm: HighMagModel) -> str:
        """Return a grouping key for a HighMagModel based on the configured grouping."""
        if self.cmd_data.grouping == 'per_micrograph':
            return str(hm.pk)
        elif self.cmd_data.grouping == 'per_group':
            # BIS group: all holes sharing the same group identifier
            hole = getattr(hm, 'hole_id', None)
            if hole and getattr(hole, 'bis_group', None):
                return str(hole.bis_group)
            return str(hm.pk)
        elif self.cmd_data.grouping == 'per_square':
            # All holes in the same square
            return str(hm.hole_id.square_id.pk) if hm.hole_id else str(hm.pk)
        return str(hm.pk)

    def _group_is_complete(self, group_key: str, group_items: List) -> bool:
        """Check if all items in a group have been acquired (ready to submit).

        For grouped modes, we require a settle period: the newest image in the
        group must be older than ``group_settle_seconds`` so that we don't
        submit a partial BIS group while the microscope is still acquiring.
        """
        if self.cmd_data.grouping == 'per_micrograph':
            return True  # always ready
        if not all(hm.status == 'acquired' for hm in group_items):
            return False
        # Require that the group has been stable (no new images) for N seconds
        from django.utils import timezone
        settle = getattr(self.cmd_data, 'group_settle_seconds', 60)
        newest = max(hm.completion_time for hm in group_items)
        age = (timezone.now() - newest).total_seconds()
        if age < settle:
            return False
        return True

    def _build_groups(self) -> Dict[str, List]:
        """Group incomplete processes by grouping key."""
        groups = {}
        for hm in self.incomplete_processes:
            key = self._group_key(hm)
            groups.setdefault(key, []).append(hm)
        return groups

    # ---- Main loop ----

    def start(self):
        if not self.project_path:
            logger.info(f'Grid {self.grid.grid_id} (slot {self.grid_position}): '
                        f'no remote project assigned, skipping.')
            return

        logger.info(f'Starting Globus pipeline: grouping={self.cmd_data.grouping}, '
                     f'project={self.project_path}, grid={self.grid.grid_id}')
        self._init_globus_clients()

        logger.info(f'Entering main loop. Stop={self._stop.is_set()}, stop_file={self.is_stop_file()}')

        while not self._stop.is_set() and not self.is_stop_file():
            self.list_incomplete_processes()
            logger.debug(f'Incomplete: {len(self.incomplete_processes)} images')

            # Group and submit ready batches (limit concurrent flow runs)
            MAX_CONCURRENT_FLOWS = self.cmd_data.max_concurrent_flows
            groups = self._build_groups()
            for group_key, batch in groups.items():
                if len(self._active_flow_runs) >= MAX_CONCURRENT_FLOWS:
                    logger.debug(f'Max concurrent flows ({MAX_CONCURRENT_FLOWS}) reached, waiting...')
                    break
                if group_key in self._submitted_groups:
                    continue
                if self._group_is_complete(group_key, batch):
                    try:
                        self._submit_group(group_key, batch)
                    except Exception as e:
                        logger.error(f'Failed to submit group {group_key}: {e}')
                        break  # Stop submitting on error, retry next loop

            # Check for completed flow runs
            self._check_flow_runs()

            # Move any thumbnails from frames mount to data mount
            self._sync_thumbnails()

            # Done?
            self.grid.refresh_from_db()
            if self._is_done():
                logger.info('All images processed. Exiting.')
                break

            time.sleep(5)  # brief sleep between loop iterations

    def _is_done(self):
        return (
            self.grid.status in ['complete', 'error']
            and len(self._active_flow_runs) == 0
            and not self.incomplete_processes
        )

    # ---- Process listing ----

    def list_incomplete_processes(self):
        self.incomplete_processes = list(
            HighMagModel.parent_manager
            .filter(grid_id=self.grid.pk, status__in=['acquired', 'skipped'])
            .order_by('status', 'completion_time')
        )

    # ---- Submission ----

    def _flow_label(self, group_key: str, batch: List) -> str:
        """Build a human-readable label like SmartScope_GridName_Square-3_Group-42."""
        grid = self.grid.name
        square = ''
        if batch:
            hole = getattr(batch[0], 'hole_id', None)
            if hole:
                sq = getattr(hole, 'square_id', None)
                if sq:
                    square = f'Square-{sq.number}'
        parts = ['SmartScope', grid]
        if square:
            parts.append(square)
        if self.cmd_data.grouping == 'per_micrograph':
            parts.append(f'Mic-{batch[0].number}' if batch else group_key)
        else:
            parts.append(f'Group-{group_key}')
        return '_'.join(parts)

    def _submit_group(self, group_key: str, batch: List):
        """Submit a group of images as a Globus Flow run (or transfer-only)."""
        label = self._flow_label(group_key, batch)
        logger.info(f'Submitting {label}: {len(batch)} images')
        self._submitted_groups.add(group_key)

        # Get square and group for destination path
        square = 'Unknown'
        if batch:
            hole = getattr(batch[0], 'hole_id', None)
            if hole:
                sq = getattr(hole, 'square_id', None)
                if sq:
                    square = f'Square-{sq.number}'
        group = f'Group-{group_key}'

        # Build file list from actual frame paths (include .mdoc sidecar files)
        file_pairs = []
        gain_ref_added = set()
        for hm in batch:
            if not hm.frames:
                logger.warning(f'No frames file for {hm.pk}, skipping')
                continue
            container_path = str(self.frames_dir / hm.frames)

            src = _container_to_globus_path(container_path, self.cmd_data.source_base_path,
                                                self.container_frames_root)
            dst = _globus_dest_path(container_path, self.cmd_data.destination_base_path,
                                    self.project_path, square, group)
            file_pairs.append((src, dst))

            mdoc_path = container_path + '.mdoc'
            if Path(mdoc_path).exists():
                mdoc_src = _container_to_globus_path(mdoc_path, self.cmd_data.source_base_path,
                                                     self.container_frames_root)
                mdoc_dst = dst + '.mdoc'
                file_pairs.append((mdoc_src, mdoc_dst))

                # Include the gain reference from the mdoc
                if not gain_ref_added:
                    try:
                        with open(mdoc_path) as f:
                            for line in f:
                                if line.strip().startswith('GainReference'):
                                    gain_name = line.split('=', 1)[1].strip()
                                    if gain_name:
                                        frames_dir = str(Path(container_path).parent)
                                        gain_path = str(Path(frames_dir) / gain_name)
                                        if Path(gain_path).exists():
                                            gain_src = _container_to_globus_path(
                                                gain_path, self.cmd_data.source_base_path,
                                                self.container_frames_root)
                                            gain_dst = (f"{self.cmd_data.destination_base_path.rstrip('/')}/"
                                                        f"{self.project_path.strip('/')}/{gain_name}")
                                            file_pairs.append((gain_src, gain_dst))
                                            gain_ref_added.add(gain_name)
                                            logger.info(f'Including gain reference: {gain_name}')
                                    break
                    except Exception:
                        pass

        # Pass gain reference name so it can be included in the manifest config
        gain_ref_name = next(iter(gain_ref_added), "")

        if self.fc:
            self._start_flow_run(group_key, batch, file_pairs, label, gain_ref_name)
        else:
            self._start_transfer_only(group_key, batch, file_pairs, label, gain_ref_name)

    def _build_manifest(self, group_key: str, batch: List, file_pairs: List,
                         flow_run_id: str = "", gain_ref: str = "") -> dict:
        """Build a HPC-side manifest for this batch.

        The manifest tells the HPC compute function:
        - What movies were transferred (relative to remote project dir)
        - The flow_run_id to callback when processing is done
        - Any metadata overrides (pixel size, voltage, etc.)
        """
        batch_id = self._flow_label(group_key, batch)

        # Movie paths relative to remote project dir
        # (SmartScopeMode resolves them to absolute via project_dir)
        dest_globus_base = (f"{self.cmd_data.destination_base_path.rstrip('/')}/"
                            f"{self.project_path.strip('/')}")
        movies = []
        for _, dst in file_pairs:
            # dst is a Globus collection path like /CryoEM/Projects/Rori/Movies/grid/frame.tif
            # Strip the project prefix to get relative path like Movies/grid/frame.tif
            rel = dst
            if rel.startswith(dest_globus_base):
                rel = rel[len(dest_globus_base):].lstrip('/')
            movies.append(rel)

        # Build config dict matching the compute function's expected config
        fs_root = self.cmd_data.destination_filesystem_root.rstrip('/')
        dest_globus = (f"{self.cmd_data.destination_base_path.rstrip('/')}/"
                       f"{self.project_path.strip('/')}")
        project_fs = f"{fs_root}/{dest_globus.lstrip('/')}"
        output_dir = f"{project_fs}/LivePreprocess/job001"

        config = {
            "project_dir": project_fs,
            "output_dir": output_dir,
        }

        # Microscope-derived values (SmartScope provides these automatically)
        if hasattr(self.detector, 'pixel_size') and self.detector.pixel_size:
            config["pixel_size"] = float(self.detector.pixel_size)
        if hasattr(self.microscope, 'voltage') and self.microscope.voltage:
            config["voltage"] = int(self.microscope.voltage)
        if hasattr(self.microscope, 'spherical_abberation') and self.microscope.spherical_abberation:
            config["cs"] = float(self.microscope.spherical_abberation)
        if gain_ref:
            config["gain_reference"] = gain_ref
        if hasattr(self.detector, 'gain_rot') and self.detector.gain_rot is not None:
            config["gain_rotation"] = int(self.detector.gain_rot)
        # gain_flip in DB is IMOD convention; MotionCor3 uses RELION convention (inverted)
        if hasattr(self.detector, 'gain_flip'):
            config["gain_flip"] = int(not self.detector.gain_flip)

        # Merge user-provided extra config (processing params for the compute function)
        config.update(self.cmd_data.extra_config)

        # Map movie filenames to Globus destination paths for thumbnails.
        # The compute function uses this to put thumbnails directly where SmartScope expects them.
        grid_globus = _container_to_globus_path(
            str(self.grid.directory), self.cmd_data.source_base_path,
            self.container_data_root
        )
        thumbnail_map = {}
        for hm in batch:
            if hm.frames:
                movie_name = Path(hm.frames).name
                thumbnail_map[movie_name] = {
                    "png": f"{grid_globus}/pngs/{hm.name}.png",
                    "ctf": f"{grid_globus}/{hm.name}/ctf.png",
                }

        return {
            "batch_id": batch_id,
            "flow_run_id": flow_run_id,
            "movies": movies,
            "config": config,
            "grid_id": self.grid.grid_id,
            "thumbnail_destinations": thumbnail_map,
        }

    def _transfer_manifest(self, manifest: dict):
        """Transfer the manifest JSON to the remote project's Manifests/ dir on HPC."""
        from globus_sdk import TransferData

        batch_id = manifest["batch_id"]
        dest_base = (f"{self.cmd_data.destination_base_path.rstrip('/')}/"
                     f"{self.project_path.strip('/')}")

        # Write manifest to the frames directory (same Globus mount as the frames)
        manifests_dir = self.frames_dir / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        local_path = manifests_dir / f"{batch_id}.json"
        local_path.write_text(json.dumps(manifest, indent=2))

        src_manifest = _container_to_globus_path(
            str(local_path), self.cmd_data.source_base_path,
            self.container_frames_root
        )
        dst_manifest = (f"{dest_base}/LivePreprocess/job001/"
                        f"Manifests/{batch_id}.json")

        td = TransferData(
            source_endpoint=self.cmd_data.source_collection_id,
            destination_endpoint=self.cmd_data.destination_collection_id,
            label=f'Manifest {batch_id}',
        )
        td.add_item(src_manifest, dst_manifest)

        result = self.tc.submit_transfer(td)
        logger.info(f'Manifest transfer submitted: {result["task_id"]} '
                     f'for batch {batch_id}')

    def _start_flow_run(self, group_key: str, batch: List, file_pairs: List, label: str = "", gain_ref: str = ""):
        """Start a Globus Flow run: transfer frames+manifest -> compute -> transfer back."""
        # Globus collection path (for transfers)
        dest_globus_dir = (f"{self.cmd_data.destination_base_path.rstrip('/')}/"
                           f"{self.project_path.strip('/')}")
        # HPC filesystem path (for compute function)
        fs_root = self.cmd_data.destination_filesystem_root.rstrip('/')
        dest_fs_dir = f"{fs_root}/{dest_globus_dir.lstrip('/')}"

        batch_id = self._flow_label(group_key, batch)
        manifest_globus_path = (f"{dest_globus_dir}/LivePreprocess/job001/"
                                f"Manifests/{batch_id}.json")
        manifest_path_on_hpc = (f"{dest_fs_dir}/LivePreprocess/job001/"
                                f"Manifests/{batch_id}.json")

        # Build manifest and write it to the frames directory (same Globus mount)
        manifest = self._build_manifest(group_key, batch, file_pairs, gain_ref=gain_ref)
        manifests_dir = self.frames_dir / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        local_path = manifests_dir / f"{batch_id}.json"
        local_path.write_text(json.dumps(manifest, indent=2))

        # Add manifest to the same transfer as the frames
        src_manifest = _container_to_globus_path(
            str(local_path), self.cmd_data.source_base_path,
            self.container_frames_root
        )
        all_items = [{"source_path": s, "destination_path": d} for s, d in file_pairs]
        all_items.append({"source_path": src_manifest, "destination_path": manifest_globus_path})

        flow_input = {
            "source_collection": self.cmd_data.source_collection_id,
            "destination_collection": self.cmd_data.destination_collection_id,
            "compute_endpoint": self.cmd_data.globus_compute_endpoint_id,
            "compute_function": self.cmd_data.globus_compute_function_id,
            "compute_kwargs": {
                "manifest_path": manifest_path_on_hpc,
                "project_dir": dest_fs_dir,
                "source_collection": self.cmd_data.source_collection_id,
                "destination_collection": self.cmd_data.destination_collection_id,
                "source_base_path": self.cmd_data.source_base_path,
                "destination_base_path": self.cmd_data.destination_base_path,
                "destination_filesystem_root": self.cmd_data.destination_filesystem_root,
            },
            "transfer_items": all_items,
            "label": label,
            "results_label": f"Results {label}",
        }

        run = self.fc.run_flow(body={"input": flow_input}, label=label[:64])
        run_id = run["run_id"]
        self._active_flow_runs[run_id] = {"batch": batch, "group_key": group_key}
        logger.info(f'Flow run started: {run_id} for {label}')

    def _start_transfer_only(self, group_key: str, batch: List, file_pairs: List, label: str = "", gain_ref: str = ""):
        """Transfer-only mode: just move files to HPC.

        Also writes a manifest for HPC processing
        if the user starts a Live job manually.
        """
        from globus_sdk import TransferData

        td = TransferData(
            source_endpoint=self.cmd_data.source_collection_id,
            destination_endpoint=self.cmd_data.destination_collection_id,
            label=label,
        )
        for src, dst in file_pairs:
            td.add_item(src, dst)

        result = self.tc.submit_transfer(td)
        task_id = result['task_id']
        self._active_flow_runs[task_id] = {"batch": batch, "group_key": group_key, "transfer_only": True}
        logger.info(f'Transfer submitted: {task_id} for {label}')

        # Write manifest (no flow_run_id — no callback expected)
        manifest = self._build_manifest(group_key, batch, file_pairs, gain_ref=gain_ref)
        self._transfer_manifest(manifest)

    # ---- Flow run status ----

    def _check_flow_runs(self):
        """Check status of active flow runs / transfers."""
        for run_id, info in list(self._active_flow_runs.items()):
            if info.get("transfer_only"):
                self._check_transfer(run_id, info)
            else:
                self._check_flow(run_id, info)

    def _check_transfer(self, task_id: str, info: dict):
        task = self.tc.get_task(task_id)
        if task['status'] == 'SUCCEEDED':
            logger.info(f'Transfer {task_id} completed for group {info["group_key"]}')
            del self._active_flow_runs[task_id]
            self._submitted_groups.discard(info["group_key"])
        elif task['status'] == 'FAILED':
            logger.error(f'Transfer {task_id} failed: {task.get("nice_status_details", "")}')
            del self._active_flow_runs[task_id]
            self._submitted_groups.discard(info["group_key"])

    def _check_flow(self, run_id: str, info: dict):
        run = self.fc_general.get_run(run_id)
        status = run["status"]

        if status == "SUCCEEDED":
            logger.info(f'Flow run {run_id} completed for group {info["group_key"]}')
            # Results are in the .done.json transferred back by the flow.
            # It lands at the Globus destination path on the DTN filesystem.
            batch_id = self._flow_label(info['group_key'], info.get('batch', []))
            done_path = (Path(self.container_frames_root) /
                         "LivePreprocess" / "job001" / "Manifests" /
                         f"{batch_id}.done.json")
            if done_path.exists():
                done_data = json.loads(done_path.read_text())
                self._update_db_from_done(done_data)
                self._move_thumbnails(done_data)
                logger.info(f'Updated DB from {done_path}')
            else:
                logger.warning(f'Flow completed but .done.json not found at {done_path}')
            del self._active_flow_runs[run_id]
            # Allow resubmission if new images arrived in this group while the flow ran
            self._submitted_groups.discard(info["group_key"])

        elif status in ("FAILED", "CANCELLED"):
            logger.error(f'Flow run {run_id} {status} for group {info["group_key"]}')
            del self._active_flow_runs[run_id]
            self._submitted_groups.discard(info["group_key"])

    def _sync_thumbnails(self):
        """Move any thumbnails sitting on the frames mount to the data mount."""
        import shutil
        grid_rel = str(self.grid.directory)[len(self.container_data_root):].lstrip('/')
        frames_pngs = Path(self.container_frames_root) / grid_rel / 'pngs'
        data_pngs = Path(self.grid.directory) / 'pngs'
        if not frames_pngs.exists():
            return
        data_pngs.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in frames_pngs.glob('*.png'):
            dst = data_pngs / f.name
            if not dst.exists():
                shutil.move(str(f), str(dst))
                count += 1
        # CTF thumbnails
        frames_grid = frames_pngs.parent
        data_grid = Path(self.grid.directory)
        for d in frames_grid.iterdir():
            ctf = d / 'ctf.png'
            if d.is_dir() and ctf.exists():
                dst = data_grid / d.name / 'ctf.png'
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(ctf), str(dst))
                    count += 1
        if count:
            logger.info(f'Synced {count} thumbnails to {data_pngs}')

    def _move_thumbnails(self, done_data: dict):
        """Move thumbnails from Globus landing path (frames mount) to SmartScope data dir."""
        import shutil
        results = done_data.get('results', [])
        # Globus transferred to the frames mount at the same relative path as grid.directory
        # e.g. frames mount: /mnt/arctica/Superluminal/SmartScope/20260316_.../1_Rori_.../pngs/
        #      data mount:   /mnt/data/Superluminal/20260316_.../1_Rori_.../pngs/
        grid_rel = str(self.grid.directory)[len(self.container_data_root):].lstrip('/')
        frames_grid_dir = Path(self.container_frames_root) / grid_rel
        pngs_dir = Path(self.grid.directory) / 'pngs'
        pngs_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for mic in results:
            movie_stem = Path(mic.get('movie_path', mic.get('movie', ''))).stem
            hm_name = self._find_hm_name_for_movie(movie_stem)
            if not hm_name:
                continue
            # Micrograph thumbnail
            src = frames_grid_dir / 'pngs' / f'{hm_name}.png'
            dst = pngs_dir / f'{hm_name}.png'
            if src.exists():
                shutil.move(str(src), str(dst))
                count += 1
            # CTF thumbnail
            src = frames_grid_dir / hm_name / 'ctf.png'
            dst = Path(self.grid.directory) / hm_name / 'ctf.png'
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                count += 1
        if count:
            logger.info(f'Moved {count} thumbnails to {pngs_dir}')

    # ---- Results polling & DB updates ----

    def _find_hm_name_for_movie(self, movie_stem: str) -> str:
        """Find the HighMagModel name that corresponds to a movie filename stem."""
        hm = (HighMagModel.parent_manager
              .filter(grid_id=self.grid.pk, frames__endswith=f'{movie_stem}.tif')
              .values_list('name', flat=True)
              .first())
        if hm:
            return hm
        # Try other extensions
        hm = (HighMagModel.parent_manager
              .filter(grid_id=self.grid.pk, frames__contains=movie_stem)
              .values_list('name', flat=True)
              .first())
        return hm or ''

    def _update_db_from_done(self, done_data: dict):
        """Update HighMagModel + HoleModel from a .done.json file."""
        from django.utils import timezone
        from django.contrib.contenttypes.models import ContentType

        results = done_data.get('results', [])
        pixel_size = self.cmd_data.extra_config.get('pixel_size', 0) or (
            float(self.detector.pixel_size) if hasattr(self.detector, 'pixel_size')
            and self.detector.pixel_size else 1.0
        )

        highmags_to_update = []
        holes_to_update = []
        selectors_to_create = []
        hole_content_type = ContentType.objects.get_for_model(HoleModel)
        selector_hole_pks = set()

        for mic in results:
            movie_stem = Path(mic.get('movie_path', mic.get('movie', ''))).stem
            hm_name = self._find_hm_name_for_movie(movie_stem)
            if not hm_name:
                logger.warning(f'No HighMagModel found for movie {movie_stem}')
                continue

            try:
                hm = HighMagModel.objects.get(name=hm_name)
            except HighMagModel.DoesNotExist:
                logger.warning(f'HighMagModel {hm_name} not in DB')
                continue

            defocus_u = mic.get('defocus_u', 0.0)
            defocus_v = mic.get('defocus_v', 0.0)

            hm.defocus = (defocus_u + defocus_v) / 2.0
            hm.astig = abs(defocus_u - defocus_v)
            hm.angast = mic.get('defocus_angle', 0.0)
            hm.ctffit = mic.get('ctf_max_resolution', 999.0)
            hm.ice_thickness = int(round(mic.get('ice_thickness', 0.0) / 10))
            hm.shape_x = mic.get('shape_x', 0) or 0
            hm.shape_y = mic.get('shape_y', 0) or 0
            hm.pixel_size = pixel_size
            hm.status = 'completed'
            hm.completion_time = timezone.now()
            highmags_to_update.append(hm)

            if hm.hole_id:
                hm.hole_id.status = 'completed'
                hm.hole_id.completion_time = timezone.now()
                holes_to_update.append(hm.hole_id)

            # Compute mean_pick_score from coordinates if available
            coords = mic.get('coordinates', [])
            if coords:
                scores = [c[2] for c in coords if len(c) > 2]
                mic['mean_pick_score'] = sum(scores) / len(scores) if scores else 0.0
            else:
                mic['mean_pick_score'] = 0.0

            # Create Selector records on the parent hole for each mapped result field
            if hm.hole_id:
                hole_pk = hm.hole_id.pk
                selector_hole_pks.add(hole_pk)
                for result_key, method_name in RESULT_SELECTORS.items():
                    value = mic.get(result_key)
                    if value is not None:
                        selectors_to_create.append(Selector(
                            content_type=hole_content_type,
                            object_id=hole_pk,
                            method_name=method_name,
                            value=float(value),
                        ))

        if highmags_to_update or holes_to_update:
            with transaction.atomic():
                if highmags_to_update:
                    HighMagModel.objects.bulk_update(
                        highmags_to_update,
                        fields=['status', 'defocus', 'astig', 'angast', 'ctffit',
                                'ice_thickness', 'shape_x', 'shape_y', 'pixel_size',
                                'completion_time']
                    )
                if holes_to_update:
                    HoleModel.objects.bulk_update(
                        holes_to_update,
                        fields=['status', 'completion_time']
                    )
                if selectors_to_create:
                    # Remove existing selectors for these holes/methods to avoid duplicates
                    Selector.objects.filter(
                        content_type=hole_content_type,
                        object_id__in=list(selector_hole_pks),
                        method_name__in=RESULT_SELECTORS.values(),
                    ).delete()
                    Selector.objects.bulk_create(selectors_to_create)
                    logger.info(f"Created {len(selectors_to_create)} selectors for "
                                f"{len(selector_hole_pks)} holes")

            all_updated = highmags_to_update + holes_to_update
            websocket_update(all_updated, self.grid.grid_id)
            logger.info(f"Updated {len(highmags_to_update)} high-mag images, "
                         f"{len(holes_to_update)} holes from preprocessing results")

    def check_for_update(self, instance):
        pass

    # ---- Shutdown ----

    def stop(self):
        logger.info('Stopping Globus preprocessing pipeline')
        self._stop.set()
