"""SmartScope Compute Function Template.

Copy this file, implement run_preprocessing(), and register it:

    python setup_globus.py register-func --function my_function.py

Your function will be serialized by Globus Compute and run on the HPC.
It must be self-contained — all imports must happen inside the function
body, since only the function code is sent to the remote endpoint.

Contract:
    Input:  manifest_path (str) — path to manifest JSON on HPC
            project_dir (str) — absolute path to project directory on HPC
            + Globus path kwargs (source_collection, destination_collection, etc.)
    Output: dict with "status", "batch_id", and "transfer_items"

See schemas/ for the full manifest and results JSON schemas.
"""


def run_preprocessing(manifest_path: str, project_dir: str,
                      source_collection: str = "", destination_collection: str = "",
                      source_base_path: str = "", destination_base_path: str = "",
                      destination_filesystem_root: str = "") -> dict:
    """Process a batch of movies on the HPC.

    This function is serialized by Globus Compute. Everything it needs
    must be imported inside the function body.
    """
    import json
    import subprocess
    from pathlib import Path

    # ---- Read manifest ----
    manifest = json.loads(Path(manifest_path).read_text())
    batch_id = manifest.get("batch_id", "unknown")
    config = manifest.get("config", {})
    movies = [m for m in manifest.get("movies", [])
              if m.lower().endswith((".tif", ".tiff", ".mrc", ".eer"))]

    if not movies:
        return {"status": "completed", "batch_id": batch_id,
                "transfer_items": []}

    # ---- Your processing logic here ----
    #
    # config contains:
    #   project_dir, output_dir    — paths on the HPC
    #   pixel_size, voltage, cs    — microscope parameters (auto-populated by SmartScope)
    #   gain_reference             — gain ref filename (in project root)
    #   gain_rotation, gain_flip   — gain ref orientation (RELION convention)
    #   + any extra_config keys from the SmartScope form
    #
    # Example: submit a SLURM job, run a container, call a CLI tool, etc.
    #
    # results = run_my_pipeline(movies, config)

    # ---- Build results ----
    # Each entry corresponds to one processed movie.
    # SmartScope matches on the movie filename stem.
    results = []
    for movie in movies:
        results.append({
            "movie_path": movie,
            # CTF results (Angstroms)
            "defocus_u": 0.0,
            "defocus_v": 0.0,
            "defocus_angle": 0.0,
            "ctf_max_resolution": 999.0,
            # Motion (Angstroms)
            "total_motion": 0.0,
            # Ice thickness (Angstroms — SmartScope converts to nm)
            "ice_thickness": 0.0,
            # Picking
            "particle_count": 0,
            "coordinates": [],  # [[x, y, score], ...]
            # Micrograph dimensions
            "shape_x": 0,
            "shape_y": 0,
            # Thumbnail paths relative to output_dir (optional)
            "thumbnail": "",
            "ctf_thumbnail": "",
        })

    # ---- Write .done.json ----
    # SmartScope reads this file to update its database.
    output_dir = Path(config.get("output_dir",
                      str(Path(project_dir) / "LivePreprocess" / "job001")))
    done_file = output_dir / f"Manifests/{batch_id}.done.json"
    done_file.parent.mkdir(parents=True, exist_ok=True)
    done_file.write_text(json.dumps({
        "status": "completed",
        "batch_id": batch_id,
        "results": results,
    }, indent=2))

    # ---- Build transfer items ----
    # These tell the Globus Flow what to transfer back to SmartScope.
    # At minimum, include the .done.json file.
    fs_root = destination_filesystem_root.rstrip("/")
    hpc_globus_base = "/" + project_dir.replace(fs_root, "").strip("/")
    done_rel = str(done_file).replace(project_dir, "").strip("/")

    transfer_items = [{
        "source_path": f"{hpc_globus_base}/{done_rel}",
        "destination_path": f"{source_base_path}/{done_rel}",
    }]

    # Add thumbnails using destinations from the manifest
    thumb_dests = manifest.get("thumbnail_destinations", {})
    job_rel = str(output_dir).replace(project_dir, "").strip("/")
    for mic in results:
        movie_name = Path(mic.get("movie_path", "")).name
        dests = thumb_dests.get(movie_name, {})
        if mic.get("thumbnail") and dests.get("png"):
            transfer_items.append({
                "source_path": f"{hpc_globus_base}/{job_rel}/{mic['thumbnail']}",
                "destination_path": dests["png"],
            })
        if mic.get("ctf_thumbnail") and dests.get("ctf"):
            transfer_items.append({
                "source_path": f"{hpc_globus_base}/{job_rel}/{mic['ctf_thumbnail']}",
                "destination_path": dests["ctf"],
            })

    return {"status": "completed", "batch_id": batch_id,
            "transfer_items": transfer_items}
