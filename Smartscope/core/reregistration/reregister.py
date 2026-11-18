"""Re-registration of a grid's targets after it was unloaded and reloaded.

Grid level (called from run_grid): reregister_if_reloaded / reregister_grid image a few completed
squares again, pair their pre- and post-reload stage positions, fit an old -> new stage transform
and add a 'Registration' finder with the transformed position to every target.

Square level (the medium mag protocol commands reregisterMediumMagFiducial and
reregisterMediumMagJunkXcorr): reregister_square_at_anchor picks an anchor on the square image,
images it at medium mag and locates the image in the square image, by YOLO junk matching
(register_medium_to_square, v1) or cross-correlation (register_medium_to_square_xcorr, v2).
"""
import logging
from pathlib import Path
from typing import Dict, Union

import numpy as np

from Smartscope.core.interfaces.microscope_interface import MicroscopeInterface
from Smartscope.core.grid.diagnostics import save_reregistration_diagnostics

logger = logging.getLogger(__name__)


# Grid level ------------------------------------------------------------------------------------
# Django models and the protocol command factory are imported inside the functions: the factory
# imports protocol_commands, which uses this module.

def reregister_if_reloaded(scope, grid, protocol, method:str='search_mag') -> None:
    """Re-registers the grid if it was reloaded since it was unloaded, unless that was already done
    since the last load (recorded in <grid directory>/reregistration/last_reregistration.txt)."""
    needs_reregistration = grid.unloading_time is not None and grid.loading_time > grid.unloading_time
    if not needs_reregistration:
        return
    record = Path(grid.directory, 'reregistration', 'last_reregistration.txt')
    reregistered_at = _last_reregistration(record)
    if reregistered_at is not None and reregistered_at > grid.loading_time:
        logger.info(f'Grid already re-registered at {reregistered_at:%Y-%m-%d %H:%M:%S} since it was last loaded, skipping')
        return
    logger.info('Re-registering grid after re-loading')
    if reregister_grid(scope, grid, protocol, method=method):
        _record_reregistration(record)


def _reregister_pairs_search_mag(scope, grid, squares):
    from Smartscope.core.settings.worker import PROTOCOL_COMMANDS_FACTORY
    old_positions, new_positions = [], []
    for square in squares:
        new_pos = PROTOCOL_COMMANDS_FACTORY['reregisterSearchMag'](scope, grid.params_id, square, {})
        if new_pos is not None:
            new_positions.append(new_pos)
            old_positions.append(square.stage_coords)
    return old_positions, new_positions


def _square_stage_xy(square) -> np.ndarray:
    finder = square.finders.first()
    return np.array([finder.stage_x, finder.stage_y], dtype=float)


def _reregister_pairs_medium_mag(scope, grid, selected, others, command:str, content:dict):
    """Runs a medium mag re-registration command (reregisterMediumMagFiducial or
    reregisterMediumMagJunkXcorr) on squares until content['n_anchors'] (default 3) squares agree
    on one stage transform (see Smartscope.core.reregistration.consensus).

    Every match whose peak is not on the search window border is a candidate, including those
    below the per-image thresholds: on weak-contrast grids correct matches often score as low
    as wrong ones, but only correct ones agree with each other. Squares closest to the stage
    origin go first; once a prediction exists, images are acquired at the predicted positions and
    the work proceeds outward in steps, fitting rotation once the agreeing squares are spread.

    Returns the (old, new) positions of the agreeing candidates, or only those of the matches
    above thresholds if no consensus was reached (the caller then falls back to search mag if
    there are fewer than 2)."""
    from Smartscope.core.settings.worker import PROTOCOL_COMMANDS_FACTORY
    from Smartscope.core.reregistration.consensus import ConsensusPlanner
    squares = {sq.pk: sq for sq in list(selected) + list(others)}
    # With few squares every one has to match: spend more images per square (2 anchors even
    # before there is a prediction, and a retry at the predicted position).
    few_squares = len(squares) <= content.get('few_squares', 4)
    if few_squares:
        logger.info(f'Only {len(squares)} squares to re-register with: 2 anchors per square and retries')
        content = {'anchors_per_square_unpredicted': 2, **content}
    planner = ConsensusPlanner(
        {pk: _square_stage_xy(sq) for pk, sq in squares.items()},
        n_squares=content.get('n_anchors', 3),
        tol_um=content.get('consensus_tol_um', 1.25),
        min_step_um=content.get('min_step_um', 150),
        min_rotation_baseline_um=content.get('min_rotation_baseline_um', 200),
        min_spread_um=content.get('min_spread_um', 150),
        max_rotation_deg=content.get('max_rotation_deg', 3.0),
        retry_unpredicted=few_squares,
    )
    while not planner.done():
        pk = planner.next_square()
        if pk is None:
            break
        square = squares[pk]
        T = planner.prediction()
        sink = []
        try:
            PROTOCOL_COMMANDS_FACTORY[command](scope, grid.params_id, square,
                                               {**content, 'predicted_transform': T, 'candidate_sink': sink})
        except Exception as err:
            logger.exception(f'{command} re-registration failed on {square}: {err}')
        planner.add(pk, sink, predicted=T is not None)
        c = planner.consensus()
        if c is not None:
            logger.info(f'Re-registration consensus: {len(c["squares"])} square(s) agree '
                        f'({len(c["inliers"])}/{len(planner.candidates)} candidates, spread {c["spread_um"]:.0f} um, '
                        f'rotation {c["rotation_deg"]:.2f} deg, rms {c["rms_um"]:.2f} um)')
    old_positions, new_positions = planner.result_pairs()
    if planner.done():
        logger.info(f'Re-registration consensus reached with {len(old_positions)} pair(s)')
    else:
        logger.warning(f'No re-registration consensus, using {len(old_positions)} match(es) above thresholds')
    scope.zero_image_shift()
    return old_positions, new_positions


def _last_reregistration(record: Path):
    """When the grid was last re-registered, as written to record, or None."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(record.read_text().strip())
    except (OSError, ValueError):
        return None


def _record_reregistration(record: Path):
    from django.utils import timezone
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(timezone.now().isoformat())


def reregister_grid(scope, grid, protocol, rotation:bool=True, method:str='search_mag', content:Union[dict,None]=None) -> bool:
    """Re-registers all targets of a grid after reloading.

    method:
        'search_mag': re-centers selected squares at Search mag (low mag).
        'yolo' and 'junk_xcorr': find a junk anchor on each square image, acquire a medium mag
                image at its pre-reload stage position and locate it in the square image,
                'yolo' by matching YOLO junk detections on both images (v1) and 'junk_xcorr' by
                hole-suppressed cross-correlation (v2). Squares are tried in order (the 3 most
                spread out first) until content['n_anchors'] (default 3) pairs are found.
        'yolo' and 'junk_xcorr' fall back to 'search_mag' if fewer than 2 reliable pairs are obtained.

    Returns whether the grid is now registered, including when there was nothing to register;
    False means it should be tried again.
    """
    from itertools import combinations
    from scipy.spatial.distance import cdist
    from django.db import transaction
    import matplotlib.pyplot as plt
    from Smartscope.lib.mesh_operations import calculate_transformation_matrix, apply_transform
    from Smartscope.core.models import SquareModel, HoleModel, Finder
    from Smartscope.core.status import status
    logger.info('Re-registering grid')
    completed_squares = list(grid.squaremodel_set.filter(status=status.COMPLETED))
    if len(completed_squares) < 2:
        logger.info('Not enough completed squares to re-register grid')
        return True
    coords = []
    for square in completed_squares:
        finder = square.finders.first()
        coords.append((finder.stage_x, finder.stage_y))

    coords_np = np.asarray(coords, dtype=float)
    D = cdist(coords_np, coords_np, metric='euclidean')

    if len(completed_squares) >= 3:
        best = max(
            combinations(range(len(completed_squares)), 3),
            key=lambda idx: D[idx[0], idx[1]] + D[idx[0], idx[2]] + D[idx[1], idx[2]]
        )
        selected = [completed_squares[k] for k in best]
        logger.info(f'Using 3 squares for re-registration: {selected}')
    else:
        selected = completed_squares


    content = content or {}
    old_positions, new_positions = [], []
    medium_mag_methods = {
        'yolo': ('reregisterMediumMagFiducial', 'square junk anchors and YOLO keypoint matching'),
        'junk_xcorr': ('reregisterMediumMagJunkXcorr', 'square junk anchors and medium mag cross-correlation'),
    }
    if method in medium_mag_methods:
        command, description = medium_mag_methods[method]
        logger.info(f'Re-registering using {description}')
        others = [sq for sq in completed_squares if sq not in selected]
        old_positions, new_positions = _reregister_pairs_medium_mag(scope, grid, selected, others, command, content)
        if len(old_positions) < 2:
            logger.warning(f'{method} re-registration produced {len(old_positions)} reliable pair(s), falling back to search mag re-registration.')
            method = 'search_mag'
    elif method != 'search_mag':
        logger.warning(f'Unknown re-registration method {method}, using search_mag.')
        method = 'search_mag'
    if method == 'search_mag':
        old_positions, new_positions = _reregister_pairs_search_mag(scope, grid, selected)

    if len(old_positions) == 0:
        logger.warning('Cannot re-register grid: no valid positions returned from re-imaging squares')
        return False

    calculated_matrix = calculate_transformation_matrix(old_positions, new_positions, rotation=rotation)
    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111)
    ax.scatter(*zip(*old_positions), color='blue', label='Old Points')
    ax.scatter(*zip(*new_positions), color='red', label='New Points')
    transformed_points=  apply_transform(calculated_matrix, old_positions)
    ax.scatter(*zip(*transformed_points), color='green', label='Transformed Points', marker='x')
    ax.legend()
    fig.savefig(Path(grid.directory, 'reregistration_plot.png'))
    logger.info(f'Re-registration transformation matrix:\n{calculated_matrix}')
    squares = list(SquareModel.display.filter(grid_id=grid))
    holes = list(HoleModel.display.filter(grid_id=grid))
    targets_to_update = squares + holes

    finders_to_create = []
    for target in targets_to_update:
        existing_finder = target.finders.order_by('-created_at').first()
        old_pos = np.array([existing_finder.stage_x, existing_finder.stage_y])
        new_pos = apply_transform(calculated_matrix, old_pos)
        finders_to_create.append(
            Finder(
                content_object=target,
                method_name='Registration',
                x=existing_finder.x,
                y=existing_finder.y,
                stage_x=float(new_pos[0]),
                stage_y=float(new_pos[1]),
                stage_z=existing_finder.stage_z,
            )
        )

    with transaction.atomic():
        Finder.objects.bulk_create(finders_to_create)
        logger.info(f'Created {len(finders_to_create)} new finder entries for re-registered targets')
    return True


# Square level ----------------------------------------------------------------------------------

def register_medium_to_square(square, medium_montage, expected_px, old_stage, content:Dict=None,
                              diagnostics_dir=None, name:str=None, square_montage=None,
                              return_result:bool=False):
    """[v1] Locates a medium mag image (or mini-montage) in the original square image by matching
    YOLO junk/contaminant detections on both images (reregister_yolo.register).
    ``expected_px`` is the full resolution square pixel where the medium image center was
    targeted in the pre-reload frame, and ``old_stage`` the stage position it was acquired at.

    Returns (old_equiv, new): ``new`` is ``old_stage`` and ``old_equiv`` is the pre-reload stage
    position of what was actually imaged. None if the registration was unreliable.
    With return_result, returns (pair_or_None, result) where result also holds ``shift_px``
    (found - expected, full resolution square pixels) and ``accepted``.
    """
    from Smartscope.lib.image.montage import Montage
    from Smartscope.lib.image.target import Target
    from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast, auto_contrast_sigma, to_8bits
    from Smartscope.tasks.base_tasks import send_find_junk
    from Smartscope.core.reregistration.reregister_yolo import register

    content = content or {}
    name = name or medium_montage.name
    final_height = content.get('final_height', 1024)
    junk_kwargs = dict(
        imgsz=content.get('imgsz', final_height),
        conf_thres=content.get('conf_thres', 0.25),
        iou_thres=content.get('iou_thres', 0.45),
    )
    expected_px = np.asarray(expected_px, dtype=float)
    old_stage = np.asarray(old_stage[:2], dtype=float)

    if square_montage is None:
        square_montage = Montage(square.name, working_dir=square.working_dir)
        square_montage.load_or_process()

    scale_hole = final_height / medium_montage.image.shape[0]
    scale_square = final_height / square_montage.image.shape[0]
    normalizations = {'auto_contrast': auto_contrast, 'auto_contrast_sigma': auto_contrast_sigma, 'none': to_8bits}
    hole_img = convert_to_png(medium_montage.image, height=final_height,
                              normalization=normalizations[content.get('hole_normalization', 'auto_contrast_sigma')])
    square_img = convert_to_png(square_montage.image, height=final_height,
                                normalization=normalizations[content.get('square_normalization', 'auto_contrast')])

    meta = {
        'hole': {
            'pixel_size': medium_montage.pixel_size / scale_hole,
            'rotation_angle': medium_montage.rotation_angle,
        },
        'square': {
            'pixel_size': square_montage.pixel_size / scale_square,
            'rotation_angle': square_montage.rotation_angle,
        },
        'hole_coords_on_square': {'x': expected_px[0] * scale_square, 'y': expected_px[1] * scale_square},
    }
    logger.debug(f'Re-registration metadata for {name}: {meta}')

    det_hole = send_find_junk(
        hole_img, weights=content.get('weights_hole', 'junk_detection/junk_medium_mag.pt'),
        classes=content.get('classes_hole', None),
        **{**junk_kwargs, 'conf_thres': content.get('conf_thres_hole', junk_kwargs['conf_thres'])})
    det_square = send_find_junk(
        square_img, weights=content.get('weights_square', 'junk_detection/junk_square_norm.pt'),
        classes=content.get('classes_square', None),
        **{**junk_kwargs, 'conf_thres': content.get('conf_thres_square', junk_kwargs['conf_thres'])})

    hole_h, hole_w = hole_img.shape[:2]
    medium_center = getattr(medium_montage, 'center_px', None)
    if medium_center is None:
        medium_center = medium_montage.center
    hole_center = np.asarray(medium_center, dtype=float) * scale_hole
    result = register(
        hole_img_path=None,
        hole_shape=(hole_h, hole_w),
        meta=meta,
        hole_coords=np.array([hole_center], dtype=float),
        detections_hole=det_hole,
        detections_square=det_square,
        match_dist_px=content.get('match_dist_px', 15.0),
        ransac_thresh=content.get('ransac_thresh', 3.0),
        min_inliers=content.get('min_inliers', 3),
        verbose=False,
    )
    q = result['hole_coords_sq'][0] / scale_square
    result['shift_px'] = q - expected_px
    result['accepted'] = result['quality'] == 'good'
    logger.info(
        f'YOLO re-registration {name} on {square}: quality={result["quality"]}, transform={result["transform_used"]}, '
        f'det={result["n_detections_h"]}/{result["n_detections_sq"]}, '
        f'matches={result["n_matches"]}, inliers={result["n_inliers"]}, shift={np.round(result["shift_px"], 1)} px'
    )

    if diagnostics_dir is not None:
        save_reregistration_diagnostics(diagnostics_dir, name, hole_img, square_img, result,
                                        np.array([hole_center]), det_hole, det_square)

    if not result['accepted']:
        logger.warning(f'YOLO re-registration of {name} unreliable ({result["quality"]}), discarding.')
        return (None, result) if return_result else None

    t_new = Target(q, from_center=True)
    t_new.convert_image_coords_to_stage(square_montage)
    t_exp = Target(expected_px, from_center=True)
    t_exp.convert_image_coords_to_stage(square_montage)
    delta = t_new.stage_coords - t_exp.stage_coords
    old_equiv = old_stage + delta
    logger.info(f'Re-registration pair for {name}: old={np.round(old_equiv, 3)}, new={np.round(old_stage, 3)} '
                f'(stage delta {np.round(delta, 3)} um)')
    if return_result:
        return (old_equiv, old_stage), result
    return old_equiv, old_stage


def _acquire_medium_mag_at(scope:MicroscopeInterface, grid, stage_xyz, name:str, content:Dict):
    """Moves to stage_xyz and acquires a medium mag image, or a mini-montage covering
    ``content['n_pitches']`` (default 4) hole pitches. Returns the processed Montage."""
    from Smartscope.core.grid.run_io import get_file_and_process
    stage_x, stage_y, stage_z = stage_xyz
    scope.moveStage(stage_x, stage_y, stage_z=stage_z)
    num_tiles_x, num_tiles_y = scope.set_medium_mag_size_mini_montage(
        hole_pitch_um=grid.holeType.pitch, n_pitches=content.get('n_pitches', 4))
    im_file = f'raw/{name}.mrc'
    if max(num_tiles_x, num_tiles_y) == 1:
        scope.medium_mag_hole(file=im_file)
    else:
        scope.medium_mag_montage((num_tiles_x, num_tiles_y), file=im_file)
    return get_file_and_process(
        raw=im_file,
        name=name,
        directory=grid.session_id.microscope_id.scope_path,
        force_reprocess=True
    )


def find_square_junk_anchors(square, content:Dict=None, square_montage=None):
    """Finds anchors on the (pre-reload) square image for medium mag re-registration (v1 and v2).

    1. YOLO junk detection. With ``content['crop_to_square']`` (default True) detection runs on a
       crop of the illuminated part of the square, which gives the model more pixels on small or
       partially covered squares. Detections are always mapped back to full resolution,
       uncropped square image pixels before converting to stage coordinates.
       Detections below ``min_anchor_conf`` (default 0.2) are discarded.
    2. If no YOLO anchor is usable and ``content['structure_fallback']`` (default True), up to
       ``n_structure_anchors`` (default 3) model-free candidates are added: places with the
       strongest non-periodic structure after hole suppression (see ``find_structure_anchors``).
    Anchors are ranked by distance from the square edge, most centered first.

    Returns a list of dicts sorted best first, each with:
        square_px  : (x, y) full resolution square image pixel (uncropped)
        stage_xyz  : stage position of the anchor in the pre-reload frame (microns)
        source     : 'yolo' or 'structure'
        confidence : YOLO confidence (None for structure anchors or if the AI worker does not
                     return it)
        score      : structure score (structure anchors only)
        isolation_pitches : distance to the nearest other YOLO detection, in hole pitches
        edge_um    : distance to the square edge, in microns
    """
    from Smartscope.lib.image.montage import Montage
    from Smartscope.lib.image.target import Target
    from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast, auto_contrast_sigma, to_8bits
    from Smartscope.tasks.base_tasks import send_find_junk
    from Smartscope.core.reregistration.xcorr_register import (
        illuminated_mask, square_crop_box, find_structure_anchors)

    content = content or {}
    final_height = content.get('final_height', 1024)
    if square_montage is None:
        square_montage = Montage(square.name, working_dir=square.working_dir)
        square_montage.load_or_process()
    image = square_montage.image
    h, w = image.shape[:2]
    pitch_px = square.grid_id.holeType.pitch * 1e4 / square_montage.pixel_size

    mask = illuminated_mask(image)
    if content.get('crop_to_square', True):
        x0, y0, side = square_crop_box(mask)
    else:
        x0, y0, side = 0, 0, min(h, w)
    crop = image[y0:y0 + side, x0:x0 + side] if content.get('crop_to_square', True) else image
    scale = final_height / crop.shape[0]
    logger.debug(f'Junk detection on {square}: crop origin ({x0}, {y0}), size {crop.shape}, binning scale {scale:.3f}')

    normalizations = {'auto_contrast': auto_contrast, 'auto_contrast_sigma': auto_contrast_sigma, 'none': to_8bits}
    square_img = convert_to_png(crop, height=final_height,
                                normalization=normalizations[content.get('square_normalization', 'auto_contrast')])
    detections, confidences = send_find_junk(
        square_img,
        weights=content.get('weights_square', 'junk_detection/junk_square_norm.pt'),
        imgsz=content.get('imgsz', final_height),
        conf_thres=content.get('conf_thres_square', 0.1),
        iou_thres=content.get('iou_thres', 0.45),
        classes=content.get('classes_square', None),
        return_confidence=True,
    )
    # binned crop pixels -> full resolution, uncropped square pixels
    detections = detections / scale + np.array([x0, y0], dtype=float) if len(detections) else detections

    min_conf = content.get('min_anchor_conf', 0.2)
    if content.get('xcorr_mode', 'full') == 'anchor_patch':
        margin_px = content.get('patch_pitch', 0.75) * pitch_px + 2
    else:
        margin_px = 0.0  # the search window is padded where it extends beyond the square image

    def to_stage(p):
        t = Target(np.asarray(p, dtype=float), from_center=True)
        t.convert_image_coords_to_stage(square_montage)
        return (float(t.stage_x), float(t.stage_y), float(square_montage.stage_z))

    # Near the square edge the medium mag field of view takes in the grid bar, and the straight
    # edge then dominates the correlation: it matches anywhere along its length. Anchors are
    # therefore tried most centered first, measured as in distance_from_center_selector; none are
    # dropped, since a square may have no other.
    from scipy.ndimage import distance_transform_edt
    from Smartscope.lib.Finders.basic_finders import create_square_mask
    edge_distance = distance_transform_edt(create_square_mask(image))
    um_per_px = square_montage.pixel_size / 1e4

    def edge_um(p):
        x = int(np.clip(round(p[0]), 0, w - 1))
        y = int(np.clip(round(p[1]), 0, h - 1))
        return float(edge_distance[y, x]) * um_per_px

    anchors = []
    for i, p in enumerate(detections):
        conf = float(confidences[i]) if confidences is not None else None
        if conf is not None and conf < min_conf:
            logger.debug(f'Junk at {np.round(p, 1)} below minimum anchor confidence ({conf:.2f} < {min_conf}), skipping.')
            continue
        if not (margin_px <= p[0] <= w - margin_px and margin_px <= p[1] <= h - margin_px):
            logger.debug(f'Junk at {np.round(p, 1)} too close to the square image border, skipping.')
            continue
        others = np.delete(detections, i, axis=0)
        isolation = np.min(np.linalg.norm(others - p, axis=1)) / pitch_px if len(others) else np.inf
        anchors.append(dict(square_px=np.asarray(p, dtype=float), source='yolo', confidence=conf,
                            score=None, isolation_pitches=float(isolation), stage_xyz=to_stage(p),
                            edge_um=edge_um(p)))

    if not anchors and content.get('structure_fallback', True):
        candidates = find_structure_anchors(
            image, pitch_px, n=content.get('n_structure_anchors', 3),
            separation_px=content.get('n_pitches', 8) / 2 * pitch_px, mask=mask)
        logger.info(f'No usable YOLO anchor on {square}; using {len(candidates)} structure-based anchor(s).')
        for x, y, sc in candidates:
            anchors.append(dict(square_px=np.array([x, y]), source='structure', confidence=None,
                                score=sc, isolation_pitches=float('inf'), stage_xyz=to_stage((x, y)),
                                edge_um=edge_um((x, y))))
    anchors.sort(key=lambda a: -a['edge_um'])

    def describe(a):
        quality = f"conf={a['confidence']:.2f}" if a['confidence'] is not None else (
            f"score={a['score']:.1f}" if a['score'] is not None else 'conf=n/a')
        return (f"{a['source']} px={np.round(a['square_px'], 1)} {quality} {a['edge_um']:.1f} um from edge "
                f"stage={np.round(a['stage_xyz'][:2], 2)}")
    if anchors:
        logger.info(f'Found {len(anchors)} anchor(s) on {square}, most centered first: '
                    + ', '.join(describe(a) for a in anchors[:5]))
    else:
        logger.info(f'No anchor found on {square}.')
    return anchors


def register_medium_to_square_xcorr(square, medium_montage, expected_px, old_stage, content:Dict=None,
                                    diagnostics_dir=None, name:str=None, square_montage=None, anchor_px=None,
                                    return_result:bool=False):
    """[v2] Locates a medium mag image in the original square image by cross-correlation.
    ``expected_px`` is the full resolution square pixel where the medium image center was
    targeted in the pre-reload frame.

    Modes (``content['xcorr_mode']``):
        'full' (default): the whole medium image, scaled and rotated from the image metadata, is
            the template; it is searched for in a square image window centered on ``expected_px``
            (the junk anchor) and larger than the medium field of view by ``max_shift_pitches``
            on each side.
        'anchor_patch': a small square patch around ``anchor_px`` is searched for inside the
            medium image.

    Returns (old_equiv, new): ``new`` is ``old_stage`` (where the image was acquired) and
    ``old_equiv`` is the pre-reload stage position of what was actually imaged. None if the
    correlation was ambiguous or weak.
    """
    from Smartscope.lib.image.montage import Montage
    from Smartscope.lib.image.target import Target
    from Smartscope.core.reregistration.xcorr_register import register_xcorr, locate_anchor_in_medium, save_diagnostics

    content = content or {}
    if square_montage is None:
        square_montage = Montage(square.name, working_dir=square.working_dir)
        square_montage.load_or_process()
    pitch_um = square.grid_id.holeType.pitch
    max_shift_um = content.get('max_shift_um', content.get('max_shift_pitches', 4) * pitch_um)

    mode = content.get('xcorr_mode', 'full')
    if mode == 'anchor_patch':
        if anchor_px is None:
            anchor_px = expected_px  # the medium image was acquired at the anchor
        result = locate_anchor_in_medium(
            medium_montage.image, medium_montage.pixel_size, medium_montage.rotation_angle,
            square_montage.image, square_montage.pixel_size, square_montage.rotation_angle,
            anchor_px=anchor_px, expected_px=expected_px, pitch_um=pitch_um,
            patch_pitch=content.get('patch_pitch', 0.75), lowpass_pitch=content.get('lowpass_pitch', 0.1),
            max_shift_pitches=content.get('max_shift_pitches', 4.0),
            medium_valid=getattr(medium_montage, 'valid_mask', None),
            medium_center_px=getattr(medium_montage, 'center_px', None),
            min_ncc=content.get('min_ncc', 0.2), min_margin=content.get('min_margin', 0.05),
        )
    else:
        result = register_xcorr(
            medium_montage.image, medium_montage.pixel_size, medium_montage.rotation_angle,
            square_montage.image, square_montage.pixel_size, square_montage.rotation_angle,
            expected_px=expected_px, pitch_um=pitch_um, max_shift_um=max_shift_um,
            # 0.05 let through a slide along a square edge (peak 0.50 vs 0.45); good matches
            # clear 0.18 or more.
            min_ncc=content.get('min_ncc', 0.3), min_margin=content.get('min_margin', 0.1),
            # Holes kept by default, on every foil: they are the strongest signal. Suppressing them
            # was wrong on both reloads tested (BD2_4 carbon: 3-4/17 right vs 16-17/17 kept; 4_2 gold:
            # 0/6 right at any window vs 4/6 kept).
            suppress=content.get('suppress_holes', False), dilate_px=content.get('dilate_px', 1),
            lowpass_pitch=content.get('lowpass_pitch', 0.1),
            medium_center_px=getattr(medium_montage, 'center_px', None),
            refine=content.get('refine', False),
            refine_radius_pitch=content.get('refine_radius_pitch', 0.4),
            refine_lowpass_pitch=content.get('refine_lowpass_pitch', 0.02),
            local_threshold=content.get('local_hole_threshold', False),
            # Subtract the periodic hole lattice before correlating (takes precedence over
            # suppress_holes): what is left is what differs from hole to hole, so a one-hole alias no
            # longer scores almost as high as the right position. 4_2 gold reload: right margins
            # 0.06-0.09 -> 0.12-0.21, all 4 right ones accepted, aliases rejected; BD2_4 carbon
            # unchanged (17/17 right and accepted).
            lattice_subtract=content.get('lattice_subtract', True),
            highpass_pitch=content.get('highpass_pitch', 1.0),
            lattice_notch_px=content.get('lattice_notch_px', 2.0),
        )
    name = name or medium_montage.name
    logger.info(
        f'Cross-correlation ({mode}) re-registration {name} on {square}: shift={np.round(result["shift_px"], 2)} px '
        f'({result["shift_pitches"]:.2f} pitch), peak={result["peak"]:.3f}, second={result["second_peak"]:.3f}, '
        f'margin={result["margin"]:.3f}, accepted={result["accepted"]}'
    )
    if result.get('refinement') is not None:
        ref = result['refinement']
        logger.info(f'Refinement {"used" if ref["used"] else "NOT used (peak on search boundary)"}: '
                    f'correction {np.round(ref["correction_px"], 2)} px, peak {ref["peak"]:.3f}')
    if diagnostics_dir is not None:
        try:
            Path(diagnostics_dir).mkdir(parents=True, exist_ok=True)
            save_diagnostics(result, Path(diagnostics_dir, f'{name}_xcorr.png'))
        except Exception as err:
            logger.warning(f'Could not save cross-correlation diagnostics for {name}: {err}')

    # Pre-reload stage position of what was imaged. Computed for rejected matches too: unless the
    # peak is on the search window border, the pair is kept as a candidate (result['pair']) for
    # the consensus of _reregister_pairs_medium_mag.
    t_found = Target(result['found_px'], from_center=True)
    t_found.convert_image_coords_to_stage(square_montage)
    t_exp = Target(np.asarray(expected_px, dtype=float), from_center=True)
    t_exp.convert_image_coords_to_stage(square_montage)
    delta = t_found.stage_coords - t_exp.stage_coords
    old_stage = np.asarray(old_stage[:2], dtype=float)
    old_equiv = old_stage + delta
    # A near-zero margin is a tie between lattice positions (hole-spacing aliases on a clean foil),
    # not a weak match: such a pair would let the consensus lock onto a hole-shifted transform.
    # 4_2 gold reload: aliases had margins 0.002-0.007, right matches 0.056-0.095; BD2_4 carbon
    # matches all >= 0.33.
    ambiguous = result['margin'] < content.get('min_candidate_margin', 0.03)
    result['pair'] = None if result.get('on_boundary') or ambiguous else (old_equiv, old_stage)

    if not result['accepted']:
        if result.get('on_boundary'):
            logger.warning(f'Cross-correlation re-registration of {name} rejected: peak on the search window border.')
        elif ambiguous:
            logger.warning(f'Cross-correlation re-registration of {name} rejected: ambiguous peak '
                           f'(margin {result["margin"]:.3f}, likely a lattice alias), not used as a consensus candidate.')
        else:
            logger.warning(f'Cross-correlation re-registration of {name} below thresholds (weak or ambiguous peak), '
                           f'kept as a consensus candidate.')
        return (None, result) if return_result else None

    logger.info(f'Re-registration match for {name}: pre-reload position {np.round(old_equiv, 3)} '
                f'(stage delta {np.round(delta, 3)} um from the anchor)')
    if return_result:
        return (old_equiv, old_stage), result
    return old_equiv, old_stage


def _square_frame_offset(square) -> np.ndarray:
    """Stage xy offset (um) from the frame the square image was acquired in to the current frame:
    current (latest) finder minus the latest finder created up to the acquisition. Zero if the
    square was not re-registered since it was imaged. Rotation is neglected over the square size."""
    finders = list(square.finders.order_by('created_at'))
    if not finders or square.completion_time is None:
        return np.zeros(2)
    at_acquisition = [f for f in finders if f.created_at <= square.completion_time]
    frame = at_acquisition[-1] if at_acquisition else finders[0]
    latest = finders[-1]
    return np.array([latest.stage_x - frame.stage_x, latest.stage_y - frame.stage_y], dtype=float)


def reregister_square_at_anchor(scope:MicroscopeInterface, square, content:Dict, prefix:str, register_fn):
    """Shared driver of the medium mag re-registration commands.

    Picks an anchor on the original square image (``content['anchor']`` or the best of
    find_square_junk_anchors), moves to its pre-reload stage position, acquires a medium mag
    image/mini-montage of ``n_pitches`` (default 8) hole pitches and hands it to ``register_fn``
    (register_medium_to_square or register_medium_to_square_xcorr).
    Returns an (old, new) stage coordinate pair or None.
    """
    from Smartscope.lib.image.montage import Montage
    content = content or {}
    grid = square.grid_id
    square_montage = Montage(square.name, working_dir=square.working_dir)
    square_montage.load_or_process()

    if content.get('anchor') is not None:
        anchors = [content['anchor']]
    else:
        anchors = find_square_junk_anchors(square, content, square_montage=square_montage)
        if not anchors:
            return None
    # Anchor stage positions come from the square image, i.e. the stage frame at the time the square
    # was imaged. After an earlier re-registration (grid reloaded more than once) squares imaged
    # before it are in an older frame than those imaged after; move every anchor to the current
    # frame (the square's latest finder), which is what the final transform is applied to.
    offset = _square_frame_offset(square)
    if np.any(offset != 0):
        logger.info(f'{square} was imaged before the last re-registration: moving its anchors by '
                    f'{np.round(offset, 2)} um to the current stage frame')
        anchors = [{**a, 'stage_xyz': (a['stage_xyz'][0] + offset[0], a['stage_xyz'][1] + offset[1],
                                        *a['stage_xyz'][2:])} for a in anchors]
    # A rejected match costs one more medium mag image to try the next anchor here, which keeps
    # the square, rather than moving to another square that may spread the pairs less well.
    tries = anchors[:max(1, content.get('anchors_per_square', 2))]
    # The field of view must cover the expected reload shift around the anchor
    acq_content = {**content, 'n_pitches': content.get('n_pitches', 8)}
    # Old -> new stage transform from the squares already registered (None for the first ones).
    # When given, the image is acquired where the anchor is predicted to be after reload, so only
    # the prediction error has to be found by the correlation instead of the whole reload shift.
    predicted = content.get('predicted_transform')
    if predicted is None and content.get('candidate_sink') is not None:
        # Before any prediction a second anchor cannot be checked against anything, and on the
        # BD2_4 reloads it never rescued a square: move on to the next square instead.
        tries = tries[:max(1, content.get('anchors_per_square_unpredicted', 1))]
    # Every match not on the search window border is appended here as a consensus candidate
    # (dict with square, name, old, new, peak, margin, strong), accepted or not.
    candidate_sink = content.get('candidate_sink')
    tol_um = content.get('consensus_tol_um', 1.25)
    # Without a prediction the whole reload shift must be found: search a larger area of the
    # square image (software only, no image shift; the acquisition is the same). With one, only
    # the prediction error remains and the default range keeps fewer chances of a wrong peak.
    # ±8 pitches (20 um at 2.5 um): reload shifts seen so far were 13-18.5 um. With holes kept ±8 is
    # as right as smaller windows on BD2_4 and needed on the 4_2 gold reload (±5: 0/6, ±8: 4/6).
    reg_content = content
    if predicted is None:
        reg_content = {**content, 'max_shift_pitches': content.get('max_shift_pitches_unpredicted', 8)}
    for i, anchor in enumerate(tries):
        name = f'{prefix}_{square.pk}' + (f'_anchor{i + 1}' if i else '')
        if i:
            logger.info(f'Trying anchor {i + 1} of {len(tries)} on {square}')
        acq_xyz = anchor['stage_xyz']
        if predicted is not None:
            from Smartscope.lib.mesh_operations import apply_transform
            acq_xy = apply_transform(predicted, np.asarray(anchor['stage_xyz'][:2], dtype=float))
            acq_xyz = (float(acq_xy[0]), float(acq_xy[1]), anchor['stage_xyz'][2])
            logger.info(f'Acquiring {name} at predicted position {np.round(acq_xy, 2)} '
                        f'(pre-reload {np.round(anchor["stage_xyz"][:2], 2)})')
        medium_montage = _acquire_medium_mag_at(scope, grid, acq_xyz, name=name, content=acq_content)
        # The match is against the anchor's pre-reload position (old frame); the image was taken at
        # acq_xyz, which is therefore the new-frame coordinate of the pair.
        pair, result = register_fn(
            square, medium_montage, expected_px=anchor['square_px'], old_stage=anchor['stage_xyz'],
            content=reg_content, diagnostics_dir=Path(grid.directory, 'reregistration'), name=name,
            square_montage=square_montage, return_result=True,
        )
        new_xy = np.asarray(acq_xyz[:2], dtype=float)
        if pair is not None:
            pair = (pair[0], new_xy)
        candidate = result.get('pair') if isinstance(result, dict) else None
        if candidate is not None and candidate_sink is not None:
            candidate_sink.append(dict(
                square=square.pk, name=name, old=np.asarray(candidate[0], dtype=float), new=new_xy,
                peak=float(result.get('peak', np.nan)), margin=float(result.get('margin', np.nan)),
                strong=pair is not None,
            ))
        if pair is not None:
            return pair
        if candidate is not None and predicted is not None:
            from Smartscope.lib.mesh_operations import apply_transform
            residual = float(np.linalg.norm(apply_transform(predicted, np.asarray(candidate[0], dtype=float)) - new_xy))
            if residual <= tol_um:
                logger.info(f'{name} agrees with the predicted transform ({residual:.2f} um), '
                            f'not trying more anchors on {square}')
                return None
    return None
