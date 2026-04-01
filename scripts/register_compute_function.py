#!/usr/bin/env python3
"""Register the SmartScope Globus Compute function using existing tokens.

Usage:
    docker exec smartscope-smartscope-1 python /opt/smartscope/scripts/register_compute_function.py
"""

import json
from pathlib import Path
from globus_sdk import NativeAppAuthClient, ComputeClientV2, RefreshTokenAuthorizer
from globus_compute_sdk.sdk.client import FunctionRegistrationData


def run_preprocessing(manifest_path: str, project_dir: str,
                    source_collection: str = "", destination_collection: str = "",
                    source_base_path: str = "", destination_base_path: str = "",
                    destination_filesystem_root: str = "") -> dict:
    """Run preprocessing for a batch of movies via SLURM.

    Called by Globus Compute on the HPC. Writes a SLURM batch script
    that runs the staged pipeline (motioncor -> CTF -> picking ->
    extraction -> finalize), submits it, waits for completion, reads
    results from the STAR file, and returns transfer items.
    """
    import json as _json
    import os
    import subprocess
    import time
    from pathlib import Path as _Path

    manifest = _json.loads(_Path(manifest_path).read_text())
    batch_id = manifest.get('batch_id', 'unknown')
    config = manifest.get('config', {})

    # Filter to only movie files (not .mdoc etc)
    movies = [m for m in manifest.get('movies', [])
              if m.lower().endswith(('.tif', '.tiff', '.mrc', '.eer'))]

    if not movies:
        return {'status': 'completed', 'batch_id': batch_id,
                'results': [], 'transfer_items': []}

    # --- Set up job directory ---
    job_dir = _Path(config.get('output_dir',
                    str(_Path(project_dir) / 'LivePreprocess' / 'job001')))
    for subdir in ['MotionCorr/Micrographs', 'MotionCorr/Motion',
                   'CtfFind/Micrographs', 'MiFFI', 'AutoPick/Micrographs',
                   'Thumbnails', 'CtfThumbnails', 'batches',
                   'Extract/Particles']:
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Write config
    config_data = {
        'output_dir': str(job_dir),
        'project_dir': project_dir,
        'pixel_size': config.get('pixel_size', 1.0),
        'voltage': config.get('voltage', 300),
        'cs': config.get('cs', 2.7),
        'amplitude_contrast': config.get('amplitude_contrast', 0.07),
        'dose_per_frame': config.get('dose_per_frame', 1.0),
        'gain_reference': config.get('gain_reference', ''),
        'gain_rotation': config.get('gain_rotation', 0),
        'gain_flip': config.get('gain_flip', 0),
        'motioncor_patches': config.get('motioncor_patches', 5),
        'motioncor_binning': config.get('motioncor_binning', 1.0),
        'ctf_backend': config.get('ctf_backend', 'ctffind5'),
        'ctf_box_size': config.get('ctf_box_size', 512),
        'defocus_min': config.get('defocus_min', 5000.0),
        'defocus_max': config.get('defocus_max', 50000.0),
        'do_picking': config.get('do_picking', True),
        'picking_threshold': config.get('picking_threshold', 0.3),
        'picking_model': config.get('picking_model', ''),
        'box_size': config.get('box_size', 200),
        'do_extract': config.get('do_extraction', False),
        'extract_box_size': config.get('extract_box_size', 256),
        'extract_downscale': config.get('extract_downscale', 1),
        'thumbnail_size': config.get('thumbnail_size', 1024),
    }
    config_path = job_dir / 'batches' / f'{batch_id}_config.json'
    config_path.write_text(_json.dumps(config_data, indent=2))

    # Write movies file
    movies_file = job_dir / 'batches' / f'{batch_id}_movies.txt'
    movies_file.write_text('\n'.join(movies) + '\n')

    # --- Build staged SLURM script ---
    batches_dir = job_dir / 'batches'
    mc_results = batches_dir / f'{batch_id}_mc.json'
    ctf_results = batches_dir / f'{batch_id}_ctf.json'
    pick_results = batches_dir / f'{batch_id}_pick.json'
    extract_results = batches_dir / f'{batch_id}_extract.json'

    doppio_bin = config.get('doppio_bin', '/home/group/superluminal/software/moduleapps/ccp/doppio/stable/bin')
    motioncor_module = config.get('motioncor_module', 'motioncor3/1.2.4')
    ctf_module = config.get('ctf_module', 'ctffind/5.0.2')
    picking_module = config.get('picking_module', 'cryolo/stable')
    worker_partition = config.get('worker_partition', 'gpupriority')
    worker_account = config.get('worker_account', 'priority-superluminal')
    worker_time = config.get('worker_time_limit', '24:00:00')
    worker_mem = config.get('worker_mem', '32G')

    stages = []

    # Motion correction
    stages.append(('motioncor', motioncor_module,
        f'doppio-live-stage-motioncor --config {config_path} '
        f'--movies-file {movies_file} --output-file {mc_results}'))

    # CTF
    ctf_backend = config.get('ctf_backend', 'ctffind5')
    if ctf_backend == 'motioncor3':
        stages.append(('ctf', None, f'cp {mc_results} {ctf_results}'))
    else:
        stages.append(('ctf', ctf_module,
            f'doppio-live-stage-ctf --config {config_path} '
            f'--input-file {mc_results} --output-file {ctf_results}'))

    # Picking
    picking_input = ctf_results
    if config.get('do_picking', True):
        stages.append(('picking', picking_module,
            f'doppio-live-stage-picking --config {config_path} '
            f'--input-file {picking_input} --output-file {pick_results}'))
    else:
        stages.append(('picking', None, f'cp {picking_input} {pick_results}'))

    # Extraction
    if config.get('do_extraction', False) and config.get('do_picking', True):
        stages.append(('extraction', None,
            f'doppio-live-stage-extraction --config {config_path} '
            f'--input-file {pick_results} --output-file {extract_results}'))
    else:
        stages.append(('extraction', None, f'cp {pick_results} {extract_results}'))

    # Finalize
    stages.append(('finalize', None,
        f'doppio-live-stage-finalize --config {config_path} '
        f'--input-file {extract_results}'))

    # Build script
    script_file = batches_dir / f'{batch_id}.sh'
    combined_log = batches_dir / f'{batch_id}.log'

    lines = [
        '#!/bin/bash',
        f'#SBATCH --job-name=SmartScope_{batch_id}',
        f'#SBATCH --partition={worker_partition}',
        '#SBATCH --gres=gpu:1',
        '#SBATCH --cpus-per-task=4',
        f'#SBATCH --mem={worker_mem}',
        f'#SBATCH --time={worker_time}',
        f'#SBATCH --output={combined_log}',
        f'#SBATCH --error={combined_log}',
    ]
    if worker_account:
        lines.append(f'#SBATCH --account={worker_account}')
    constraint = config.get('worker_constraint', 'a40|a100')
    if constraint:
        lines.append(f'#SBATCH --constraint="{constraint}"')
    lines.append(f'\ncd {project_dir}')

    for stage_name, tool_module, command in stages:
        stage_log = batches_dir / f'{batch_id}_{stage_name}.log'
        lines.append(f'\n# === Stage: {stage_name} ===')
        if tool_module:
            lines.append('source /etc/profile.d/modules.sh')
            lines.append('module purge')
            lines.append(f'module load {tool_module}')
        lines.append(f'export PATH="{doppio_bin}:$PATH"')
        lines.append(f'{command} >> {stage_log} 2>&1 || exit 1')

    script_file.write_text('\n'.join(lines) + '\n')
    script_file.chmod(0o755)

    # --- Submit and wait ---
    result = subprocess.run(
        ['sbatch', '--parsable', str(script_file)],
        capture_output=True, text=True, cwd=project_dir,
    )
    if result.returncode != 0:
        raise RuntimeError(f'sbatch failed: {result.stderr}')

    slurm_job_id = result.stdout.strip()

    # Poll for SLURM job completion
    state = 'UNKNOWN'
    timeout = 3600
    poll_interval = 10
    elapsed = 0
    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        check = subprocess.run(
            ['sacct', '-j', slurm_job_id, '--format=State', '--noheader', '-P'],
            capture_output=True, text=True,
        )
        states = [s.strip() for s in check.stdout.strip().split('\n') if s.strip()]
        if not states:
            continue
        state = states[0]
        if state in ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL'):
            break

    if state != 'COMPLETED':
        raise RuntimeError(f'SLURM job {slurm_job_id} ended with state: {state}')

    # --- Read results from finalize output ---
    # The finalize stage writes updated results (with shape, thumbnails, etc.)
    # back to the extract_results JSON file.
    extract_results = batches_dir / f'{batch_id}_extract.json'
    results = []
    if extract_results.exists():
        results = _json.loads(extract_results.read_text())

    # Build Globus transfer items using thumbnail_destinations from manifest
    fs_root = destination_filesystem_root.rstrip('/')
    hpc_globus_base = '/' + project_dir.replace(fs_root, '').strip('/')
    # Thumbnail paths from finalize are relative to job_dir, not project_dir
    job_rel = str(job_dir).replace(project_dir, '').strip('/')
    thumb_dests = manifest.get('thumbnail_destinations', {})

    transfer_items = []
    for mic in results:
        movie_name = _Path(mic.get('movie_path', mic.get('movie', ''))).name
        dests = thumb_dests.get(movie_name, {})
        thumb = mic.get('thumbnail', '')
        if thumb and dests.get('png'):
            transfer_items.append({
                'source_path': f'{hpc_globus_base}/{job_rel}/{thumb}',
                'destination_path': dests['png'],
            })
        ctf_thumb = mic.get('ctf_thumbnail', '')
        if ctf_thumb and dests.get('ctf'):
            transfer_items.append({
                'source_path': f'{hpc_globus_base}/{job_rel}/{ctf_thumb}',
                'destination_path': dests['ctf'],
            })

    # Write results to .done.json — keeps metadata out of the flow state
    done_file = job_dir / f'Manifests/{batch_id}.done.json'
    done_file.parent.mkdir(parents=True, exist_ok=True)
    done_file.write_text(_json.dumps({
        'status': 'completed',
        'batch_id': batch_id,
        'results': results,
    }, indent=2))
    done_rel = str(done_file).replace(project_dir, '').strip('/')
    transfer_items.append({
        'source_path': f'{hpc_globus_base}/{done_rel}',
        'destination_path': f'{source_base_path}/{done_rel}',
    })

    # Ensure at least one transfer item (flow requires non-empty DATA)
    if not transfer_items:
        log_rel = str(combined_log).replace(project_dir, '').strip('/')
        transfer_items.append({
            'source_path': f'{hpc_globus_base}/{log_rel}',
            'destination_path': f'{source_base_path}/{log_rel}',
        })

    return {
        'status': 'completed',
        'batch_id': batch_id,
        'transfer_items': transfer_items,
    }


if __name__ == '__main__':
    TOKEN_FILE = '/opt/config/smartscope_tokens.json'
    CLIENT_ID = '7df9d534-fb19-4d79-8e83-642f1cdcf081'

    tokens = json.loads(Path(TOKEN_FILE).read_text())
    t = tokens['funcx_service']
    auth_client = NativeAppAuthClient(CLIENT_ID)
    authorizer = RefreshTokenAuthorizer(
        t['refresh_token'], auth_client,
        access_token=t['access_token'],
        expires_at=t['expires_at_seconds'],
    )
    cc = ComputeClientV2(authorizer=authorizer)

    reg_data = FunctionRegistrationData(function=run_preprocessing)
    result = cc.post('/v3/functions', data=reg_data.to_dict())
    func_id = result.data['function_uuid']
    print(f'Function ID: {func_id}')
    print('Update the SmartScope form "Compute Function ID" field with this value.')
