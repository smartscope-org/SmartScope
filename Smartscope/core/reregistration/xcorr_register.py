"""
xcorr_register.py
-----------------
Locates a medium-mag image (or mini-montage) inside the square-mag image it was
originally targeted from, using normalized cross-correlation.

Holey-carbon images are dominated by a periodic hole lattice, which makes any
correlation ambiguous by whole lattice vectors. Only non-periodic features
(contaminants, cracks, square edges) can disambiguate the position, so both
images are "hole-flattened" before correlating: bright hole pixels are replaced
by the carbon level, leaving dark features (including junk sitting inside holes)
and edges. The match is accepted only if the best correlation peak is clearly
above the best peak found at any other (e.g. lattice-aliased) position.

Geometry
--------
The medium-mag image is resampled to the square pixel size. Rather than rotating
the medium image (which would require a masked template), a window of the square
image is rotated into the medium image orientation, so the template stays a full
rectangle. A medium-mag image vector v maps to the square image as R(θ_square − θ_medium) · s · v
(``medium_to_square_rotation``). This was verified on real data: the hole lattices
correlate with this sign and not with the opposite one, which is what
``build_initial_transform`` in ``reregister_yolo.py`` uses.

No Django imports: usable and testable on plain numpy arrays.
"""
from typing import Optional, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------

def _otsu(values: np.ndarray, nbins: int = 256) -> float:
    hist, edges = np.histogram(values, bins=nbins)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    mt = m0[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        mu0 = m0 / w0
        mu1 = (mt - m0) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    between = np.nan_to_num(between)
    return float(centers[int(np.argmax(between))])


def hole_threshold(img: np.ndarray, mask: Optional[np.ndarray] = None) -> float:
    """Intensity above which pixels are considered (empty) hole.

    Otsu separates holes from carbon. If the image also contains dark regions
    (grid bars, outside the square), Otsu may split dark-vs-rest instead; in that
    case the bright class is re-split with a second Otsu pass. ``mask`` restricts
    the statistics to the given pixels (e.g. the illuminated part of a square).
    """
    sel = np.isfinite(img) if mask is None else (np.isfinite(img) & mask.astype(bool))
    values = img[sel].ravel()
    t = _otsu(values)
    bright_fraction = np.mean(values > t)
    if bright_fraction > 0.6:
        t = _otsu(values[values > t])
    return t


def flatten_illumination(img: np.ndarray, pitch_px: float, sigma_pitch: float = 2.0,
                         floor_frac: float = 0.05) -> np.ndarray:
    """Divides out slow illumination variations (e.g. falloff towards a square edge) so that
    holes can be thresholded relative to their local surroundings. The illumination estimate
    is floored at ``floor_frac`` of its 99th percentile so dark areas are not amplified."""
    img = img.astype(np.float32)
    illum = cv2.GaussianBlur(img, (0, 0), max(2.0, sigma_pitch * pitch_px))
    floor = floor_frac * float(np.percentile(illum, 99))
    return img / np.maximum(illum, max(floor, 1e-6))


def suppress_holes(img: np.ndarray, pitch_px: float, dilate_px: int = 1,
                   lowpass_pitch: float = 0.05, threshold_mask: Optional[np.ndarray] = None,
                   local_threshold: bool = False) -> np.ndarray:
    """Flattens the hole lattice and band-passes the image.

    1. Pixels brighter than the hole threshold (dilated by ``dilate_px`` to remove
       edge rings; with ``local_threshold`` the threshold is applied after dividing out the
       slow illumination, so dim holes near square edges are caught) are replaced by the local
       carbon level, estimated by normalized
       convolution over carbon pixels (sigma ~ 1 pitch). This follows illumination
       gradients and square edges. Dark features, including contamination inside
       holes, are preserved.
    2. Difference of Gaussians: low-pass at ``lowpass_pitch`` pitches to average out
       carbon grain (which does not correlate between magnifications), high-pass at
       ~1 pitch to remove slow intensity variations.

    Returns a zero-mean float32 image.
    """
    img = img.astype(np.float32)
    # Holes are detected relative to the local illumination (local_threshold) so that dim holes
    # near a square edge are suppressed as well; the fill and filtering use the original image.
    det = flatten_illumination(img, pitch_px) if local_threshold else img
    t = hole_threshold(det, threshold_mask)
    holes = (det > t).astype(np.uint8)
    if dilate_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
        holes = cv2.dilate(holes, k)
    carbon_mask = (holes == 0).astype(np.float32)
    fill_sigma = max(pitch_px, 2.0)
    num = cv2.GaussianBlur(img * carbon_mask, (0, 0), fill_sigma)
    den = cv2.GaussianBlur(carbon_mask, (0, 0), fill_sigma)
    global_carbon = float(np.median(img[carbon_mask > 0])) if carbon_mask.any() else float(np.median(img))
    local_carbon = np.where(den > 1e-3, num / np.maximum(den, 1e-3), global_carbon)
    flat = np.where(holes > 0, local_carbon, img).astype(np.float32)

    lowpass_sigma = max(lowpass_pitch * pitch_px, 0.5)
    low = cv2.GaussianBlur(flat, (0, 0), lowpass_sigma)
    background = cv2.GaussianBlur(flat, (0, 0), max(pitch_px, 3 * lowpass_sigma))
    out = low - background
    return out - out.mean()


# ---------------------------------------------------------------------------
# Square-level helpers (illuminated area, structure-based anchors)
# ---------------------------------------------------------------------------

def illuminated_mask(img: np.ndarray, work_size: int = 512, smooth_frac: float = 1 / 64) -> np.ndarray:
    """Boolean mask (full resolution) of the illuminated part of a square image, i.e.
    excluding grid bars and dark surroundings. Heavily smoothed Otsu threshold."""
    h, w = img.shape[:2]
    small = cv2.resize(img.astype(np.float32), (work_size, work_size), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(1.0, work_size * smooth_frac))
    t = _otsu(small.ravel())
    m = (small > t).astype(np.uint8)
    # keep the largest connected component
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        m = (labels == largest).astype(np.uint8)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)


def square_crop_box(mask: np.ndarray, pad_frac: float = 0.03) -> Tuple[int, int, int]:
    """Square box (x0, y0, side) around a mask, padded and clipped to the image."""
    h, w = mask.shape[:2]
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0, 0, min(h, w)
    pad = int(pad_frac * max(h, w))
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
    side = int(min(max(x1 - x0, y1 - y0), h, w))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    x0 = int(np.clip(cx - side // 2, 0, w - side))
    y0 = int(np.clip(cy - side // 2, 0, h - side))
    return x0, y0, side


def find_structure_anchors(square_img: np.ndarray, pitch_px: float, n: int = 3,
                           separation_px: Optional[float] = None, mask: Optional[np.ndarray] = None,
                           edge_pitches: float = 1.5, work_height: int = 1024,
                           feature_sigma_pitch: float = 0.5) -> list:
    """Model-free anchor candidates: locations with the strongest non-periodic structure.

    The hole lattice is suppressed (as for the correlation) and the remaining local energy is
    measured at ~half a pitch scale. Candidates are restricted to the illuminated area shrunk by
    ``edge_pitches`` pitches, and picked by non-maximum suppression with ``separation_px``.

    Returns a list of (x, y, score) in full resolution square pixels, best first. The score is the
    local energy relative to the median over the area (dimensionless).
    """
    h, w = square_img.shape[:2]
    f = work_height / h
    size = (max(1, int(round(w * f))), work_height)
    img_b = cv2.resize(square_img.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    pitch_b = pitch_px * f
    if mask is None:
        mask = illuminated_mask(square_img)
    mask_b = cv2.resize(mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)

    sup = suppress_holes(img_b, pitch_b, dilate_px=1, lowpass_pitch=0.1, threshold_mask=mask_b)
    sup = np.where(mask_b, sup, 0.0).astype(np.float32)
    energy = cv2.GaussianBlur(sup ** 2, (0, 0), max(1.0, feature_sigma_pitch * pitch_b))

    er = max(1, int(round(edge_pitches * pitch_b)))
    allowed = cv2.erode(mask_b.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * er + 1, 2 * er + 1))) > 0
    if not allowed.any():
        return []
    ref = float(np.median(energy[allowed])) or 1e-12
    score = np.where(allowed, energy / ref, 0.0)

    sep_b = (separation_px if separation_px is not None else 4 * pitch_px) * f
    yy, xx = np.mgrid[0:score.shape[0], 0:score.shape[1]]
    out = []
    for _ in range(n):
        iy, ix = np.unravel_index(int(np.argmax(score)), score.shape)
        if score[iy, ix] <= 0:
            break
        out.append(((ix + 0.5) / f - 0.5, (iy + 0.5) / f - 0.5, float(score[iy, ix])))
        score = np.where((xx - ix) ** 2 + (yy - iy) ** 2 <= sep_b ** 2, 0.0, score)
    return out


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def medium_to_square_rotation(medium_rot: float, square_rot: float) -> float:
    """Rotation (degrees, image coordinates) taking medium-mag image vectors to the square image."""
    return square_rot - medium_rot


def rotation_matrix(delta_deg: float) -> np.ndarray:
    d = np.radians(delta_deg)
    return np.array([[np.cos(d), -np.sin(d)],
                     [np.sin(d), np.cos(d)]], dtype=np.float64)


def scale_medium_to_square(medium_img: np.ndarray, medium_px: float, square_px: float) -> np.ndarray:
    """Resamples the medium-mag image to the square pixel size (area averaging)."""
    s = medium_px / square_px
    h, w = medium_img.shape[:2]
    new_w, new_h = max(1, int(round(w * s))), max(1, int(round(h * s)))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    return cv2.resize(medium_img.astype(np.float32), (new_w, new_h), interpolation=interp)


def extract_rotated_window(square_img: np.ndarray, center_px: np.ndarray, size_wh: Tuple[int, int],
                           delta_deg: float, fill: Optional[float] = None,
                           center_uv=None) -> Tuple[np.ndarray, np.ndarray]:
    """Extracts a window of ``size_wh`` from the square image, centered at ``center_px``
    and rotated into the medium-mag orientation.

    ``center_uv`` is the window pixel that maps onto ``center_px`` (default: window center).
    Returns (window, M) where M is the 2x3 affine mapping window (u, v) -> square (x, y).
    """
    w, h = size_wh
    R = rotation_matrix(delta_deg)
    c_win = np.array([w / 2.0, h / 2.0]) if center_uv is None else np.asarray(center_uv, dtype=np.float64)
    t = np.asarray(center_px, dtype=np.float64) - R @ c_win
    M = np.hstack([R, t[:, None]])
    if fill is None:
        fill = float(np.median(square_img))
    window = cv2.warpAffine(square_img.astype(np.float32), M, (w, h),
                            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=fill)
    return window, M


def window_to_square(M: np.ndarray, uv: np.ndarray) -> np.ndarray:
    uv = np.asarray(uv, dtype=np.float64)
    return M[:, :2] @ uv + M[:, 2]


def overlay_medium_on_square(medium_scaled: np.ndarray, center_t, found_px, square_img: np.ndarray,
                             delta_deg: float, margin_px: float = 0.0, expected_px=None) -> dict:
    """Places the (already scaled) medium image onto the square image at the found position,
    rotated by ``delta_deg`` into the square orientation.

    Returns a dict with an axis-aligned square crop around the medium footprint, the medium image
    warped into that crop, its validity mask, the footprint corners and the found/expected
    stage-position pixels, all in crop coordinates.
    """
    R = rotation_matrix(delta_deg)
    center_t = np.asarray(center_t, dtype=np.float64)
    found_px = np.asarray(found_px, dtype=np.float64)
    th, tw = medium_scaled.shape[:2]
    corners_t = np.array([[0, 0], [tw, 0], [tw, th], [0, th]], dtype=np.float64)
    corners_sq = (corners_t - center_t) @ R.T + found_px
    pts = [corners_sq, found_px[None]]
    if expected_px is not None:
        pts.append(np.asarray(expected_px, dtype=np.float64)[None])
    allp = np.vstack(pts)
    sh, sw = square_img.shape[:2]
    x0 = int(max(0, np.floor(allp[:, 0].min() - margin_px)))
    y0 = int(max(0, np.floor(allp[:, 1].min() - margin_px)))
    x1 = int(min(sw, np.ceil(allp[:, 0].max() + margin_px)))
    y1 = int(min(sh, np.ceil(allp[:, 1].max() + margin_px)))
    origin = np.array([x0, y0], dtype=np.float64)
    crop = square_img[y0:y1, x0:x1].astype(np.float32)
    # template pixel u -> crop pixel: R (u - center_t) + found_px - origin
    A = np.hstack([R, (found_px - origin - R @ center_t)[:, None]])
    size = (x1 - x0, y1 - y0)
    warped = cv2.warpAffine(medium_scaled.astype(np.float32), A, size, flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    mask = cv2.warpAffine(np.ones((th, tw), np.uint8), A, size, flags=cv2.INTER_NEAREST, borderValue=0)
    return {
        'square': crop,
        'medium': warped,
        'mask': mask.astype(bool),
        'corners': corners_sq - origin,
        'found': found_px - origin,
        'expected': None if expected_px is None else np.asarray(expected_px, dtype=np.float64) - origin,
    }


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _subpixel_peak(ncc: np.ndarray, iy: int, ix: int) -> Tuple[float, float]:
    def parabolic(m1, c, p1):
        denom = m1 - 2 * c + p1
        return 0.0 if denom == 0 else 0.5 * (m1 - p1) / denom
    dx = parabolic(ncc[iy, ix - 1], ncc[iy, ix], ncc[iy, ix + 1]) if 0 < ix < ncc.shape[1] - 1 else 0.0
    dy = parabolic(ncc[iy - 1, ix], ncc[iy, ix], ncc[iy + 1, ix]) if 0 < iy < ncc.shape[0] - 1 else 0.0
    return ix + dx, iy + dy


def register_xcorr(medium_img: np.ndarray, medium_px: float, medium_rot: float,
                   square_img: np.ndarray, square_px: float, square_rot: float,
                   expected_px, pitch_um: float,
                   max_shift_um: Optional[float] = None,
                   min_ncc: float = 0.3, min_margin: float = 0.05,
                   exclusion_pitch: float = 0.5,
                   suppress: bool = True, dilate_px: int = 1,
                   lowpass_pitch: float = 0.1, medium_center_px=None,
                   refine: bool = False, refine_radius_pitch: float = 0.4,
                   refine_lowpass_pitch: float = 0.02, local_threshold: bool = False) -> dict:
    """Finds where the center of ``medium_img`` lies in ``square_img``.

    Parameters
    ----------
    medium_px, square_px : pixel sizes, same units (e.g. Angstrom).
    medium_rot, square_rot : image rotation angles in degrees (mdoc RotationAngle).
    expected_px : (x, y) expected location of the medium image center in square pixels.
    pitch_um : hole pitch in microns; sets the band-pass, the default search range
        (4 pitches) and the exclusion radius for the ambiguity check.
    max_shift_um : search radius in microns around ``expected_px``.
    medium_center_px : (x, y) pixel of the medium image that corresponds to the stage
        position it was acquired at. Defaults to the image center (w/2, h/2).
    min_ncc, min_margin : acceptance thresholds on the best peak and on
        (best − second best peak outside ``exclusion_pitch`` pitches).
    local_threshold : detect holes after dividing out slow illumination (experimental; did not
        improve matches near square edges in testing, off by default).
    refine : after the coarse (hole-suppressed) match has selected the lattice position, run a
        second correlation keeping the holes, lightly band-passed (``refine_lowpass_pitch``),
        restricted to ``refine_radius_pitch`` pitches around the coarse peak. The sharp hole
        edges give a more precise translation; restricting the radius below half a pitch avoids
        lattice ambiguity. Acceptance is still decided by the coarse match.

    Returns
    -------
    dict with found_px, shift_px, peak, second_peak, margin, accepted, plus the
    processed template/window, NCC map and geometry for diagnostics.
    """
    expected_px = np.asarray(expected_px, dtype=np.float64)
    pitch_px = pitch_um * 1e4 / square_px
    if max_shift_um is None:
        max_shift_um = 4 * pitch_um
    max_shift_px = int(np.ceil(max_shift_um * 1e4 / square_px))
    delta = medium_to_square_rotation(medium_rot, square_rot)

    template = scale_medium_to_square(medium_img, medium_px, square_px)
    th, tw = template.shape[:2]
    mh, mw = medium_img.shape[:2]
    if medium_center_px is None:
        medium_center_px = (mw / 2.0, mh / 2.0)
    # Medium pixel -> template pixel (pixel-center convention of cv2.resize)
    center_t = np.array([(medium_center_px[0] + 0.5) * tw / mw - 0.5,
                         (medium_center_px[1] + 0.5) * th / mh - 0.5])
    win_w, win_h = tw + 2 * max_shift_px, th + 2 * max_shift_px
    window, M = extract_rotated_window(square_img, expected_px, (win_w, win_h), delta,
                                       center_uv=center_t + max_shift_px)

    if suppress:
        template_p = suppress_holes(template, pitch_px, dilate_px=dilate_px, lowpass_pitch=lowpass_pitch,
                                    local_threshold=local_threshold)
        window_p = suppress_holes(window, pitch_px, dilate_px=dilate_px, lowpass_pitch=lowpass_pitch,
                                  local_threshold=local_threshold)
    else:
        template_p = bandpass(template, pitch_px, lowpass_pitch)
        window_p = bandpass(window, pitch_px, lowpass_pitch)

    ncc = cv2.matchTemplate(window_p.astype(np.float32), template_p.astype(np.float32), cv2.TM_CCOEFF_NORMED)
    ncc = np.nan_to_num(ncc)
    iy, ix = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    peak = float(ncc[iy, ix])

    yy, xx = np.mgrid[0:ncc.shape[0], 0:ncc.shape[1]]
    excl = (xx - ix) ** 2 + (yy - iy) ** 2 <= (exclusion_pitch * pitch_px) ** 2
    rest = np.where(excl, -np.inf, ncc)
    if np.isfinite(rest).any():
        jy, jx = np.unravel_index(int(np.argmax(rest)), rest.shape)
        second = float(rest[jy, jx])
        second_loc = (int(jx), int(jy))
    else:
        second, second_loc = -1.0, None

    sx, sy = _subpixel_peak(ncc, iy, ix)
    # Template center in window coords -> square coords
    center_uv = np.array([sx, sy]) + center_t
    found_px = window_to_square(M, center_uv)
    margin = peak - second
    accepted = bool(peak >= min_ncc and margin >= min_margin)

    refinement = None
    if refine:
        t_r = bandpass(template, pitch_px, refine_lowpass_pitch)
        w_r = bandpass(window, pitch_px, refine_lowpass_pitch)
        ncc_r = np.nan_to_num(cv2.matchTemplate(w_r.astype(np.float32), t_r.astype(np.float32),
                                                cv2.TM_CCOEFF_NORMED))
        rr = refine_radius_pitch * pitch_px
        yy_r, xx_r = np.mgrid[0:ncc_r.shape[0], 0:ncc_r.shape[1]]
        near = (xx_r - sx) ** 2 + (yy_r - sy) ** 2 <= rr ** 2
        ncc_r = np.where(near, ncc_r, -1.0).astype(np.float32)
        ry, rx = np.unravel_index(int(np.argmax(ncc_r)), ncc_r.shape)
        rsx, rsy = _subpixel_peak(ncc_r, ry, rx)
        refined_px = window_to_square(M, np.array([rsx, rsy]) + center_t)
        on_edge = np.hypot(rx - sx, ry - sy) >= rr - 1.5
        refinement = {
            'coarse_found_px': found_px,
            'refined_px': refined_px,
            'correction_px': refined_px - found_px,
            'peak': float(ncc_r[ry, rx]),
            'on_edge': bool(on_edge),
        }
        if on_edge:
            # The maximum sits on the search boundary: the refinement did not converge, keep coarse.
            refinement['used'] = False
        else:
            refinement['used'] = True
            found_px = refined_px
            sx, sy = rsx, rsy
    overlay = overlay_medium_on_square(template, center_t, found_px, square_img, delta,
                                       margin_px=0.5 * pitch_px, expected_px=expected_px)

    return {
        'overlay': overlay,
        'refinement': refinement,
        'found_px': found_px,
        'expected_px': expected_px,
        'shift_px': found_px - expected_px,
        'shift_pitches': np.linalg.norm(found_px - expected_px) / pitch_px,
        'peak': peak,
        'second_peak': second,
        'margin': margin,
        'accepted': accepted,
        'peak_loc': (int(ix), int(iy)),
        'second_loc': second_loc,
        'pitch_px': pitch_px,
        'max_shift_px': max_shift_px,
        'delta_deg': delta,
        'template': template_p,
        'window': window_p,
        'window_raw': window,
        'ncc': ncc,
        'M': M,
        'center_t': center_t,
        'mode': 'full',
    }


def bandpass(img: np.ndarray, pitch_px: float, lowpass_pitch: float = 0.1, highpass_pitch: float = 1.0) -> np.ndarray:
    """Difference of Gaussians band-pass with sigmas expressed in hole pitches."""
    img = img.astype(np.float32)
    low = cv2.GaussianBlur(img, (0, 0), max(lowpass_pitch * pitch_px, 0.5))
    high = cv2.GaussianBlur(img, (0, 0), max(highpass_pitch * pitch_px, 1.0))
    return low - high


def locate_anchor_in_medium(medium_img: np.ndarray, medium_px: float, medium_rot: float,
                            square_img: np.ndarray, square_px: float, square_rot: float,
                            anchor_px, expected_px, pitch_um: float,
                            patch_pitch: float = 0.75, lowpass_pitch: float = 0.1,
                            max_shift_pitches: Optional[float] = 4.0,
                            min_ncc: float = 0.2, min_margin: float = 0.05,
                            exclusion_pitch: float = 0.5, medium_center_px=None,
                            medium_valid: Optional[np.ndarray] = None) -> dict:
    """Finds a square-image feature (e.g. a contaminant) inside a medium-mag image.

    A small patch of the square image (radius ``patch_pitch`` pitches) centered on
    ``anchor_px`` is used as template. The medium image is resampled to the square pixel
    size and rotated into the square orientation, and the patch is searched for in it by
    normalized cross-correlation. Keeping the template small and centered on the
    contaminant keeps the non-periodic feature dominant over the hole lattice and over
    carbon texture that does not correlate between magnifications.

    ``medium_valid`` optionally flags the medium pixels holding real data (e.g. missing tiles
    or padding); invalid pixels are filled with the valid median before filtering and patch
    positions overlapping them are excluded.

    The search is limited to ``max_shift_pitches`` around where the anchor is expected in the
    medium image (None searches the whole image).

    Returns the same keys as ``register_xcorr``: ``found_px`` is where the medium image
    center lies in square pixels and ``shift_px = found_px - expected_px``, where
    ``expected_px`` is where the medium image was targeted (the anchor itself when the
    image was acquired at the anchor's stage position).
    """
    anchor_px = np.asarray(anchor_px, dtype=np.float64)
    expected_px = np.asarray(expected_px, dtype=np.float64)
    pitch_px = pitch_um * 1e4 / square_px
    delta = medium_to_square_rotation(medium_rot, square_rot)

    if medium_valid is not None:
        medium_valid = medium_valid.astype(bool)
        medium_img = np.where(medium_valid, medium_img, np.median(medium_img[medium_valid]))
    med = scale_medium_to_square(medium_img, medium_px, square_px)
    mh, mw = med.shape[:2]
    oh, ow = medium_img.shape[:2]
    if medium_valid is not None:
        med_valid = cv2.resize(medium_valid.astype(np.uint8), (mw, mh), interpolation=cv2.INTER_NEAREST)
    else:
        med_valid = np.ones((mh, mw), dtype=np.uint8)
    if medium_center_px is None:
        medium_center_px = (ow / 2.0, oh / 2.0)
    c_med = np.array([(medium_center_px[0] + 0.5) * mw / ow - 0.5,
                      (medium_center_px[1] + 0.5) * mh / oh - 0.5])

    # Medium -> square orientation on a canvas large enough for any rotation
    R = rotation_matrix(delta)
    side = int(np.ceil(np.hypot(mw, mh))) + 2
    c_canvas = np.array([side / 2.0, side / 2.0])
    A = np.hstack([R, (c_canvas - R @ c_med)[:, None]])
    fill = float(np.median(med))
    med_rot = cv2.warpAffine(med, A, (side, side), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=fill)
    valid = cv2.warpAffine(med_valid, A, (side, side),
                           flags=cv2.INTER_NEAREST, borderValue=0)

    r = max(2, int(round(patch_pitch * pitch_px)))
    ax, ay = int(round(anchor_px[0])), int(round(anchor_px[1]))
    sh, sw = square_img.shape[:2]
    if ax - r < 0 or ay - r < 0 or ax + r > sw or ay + r > sh:
        raise ValueError(f'Anchor {anchor_px} too close to the square image border for a {2 * r} px patch.')
    patch = square_img[ay - r:ay + r, ax - r:ax + r]

    T = bandpass(patch, pitch_px, lowpass_pitch)
    W = bandpass(med_rot, pitch_px, lowpass_pitch)
    ncc = np.nan_to_num(cv2.matchTemplate(W, T, cv2.TM_CCOEFF_NORMED))
    # Only positions where the whole patch lies inside the acquired image
    inside = cv2.erode(valid, np.ones((2 * r, 2 * r), np.uint8), anchor=(0, 0),
                       borderType=cv2.BORDER_CONSTANT, borderValue=0)[:ncc.shape[0], :ncc.shape[1]]
    ncc = np.where(inside > 0, ncc, -1.0).astype(np.float32)
    # Expected anchor position in the canvas -> expected top-left of the patch in the NCC map
    expected_tl = c_canvas + (anchor_px - expected_px) - r
    yy, xx = np.mgrid[0:ncc.shape[0], 0:ncc.shape[1]]
    max_shift_px = None
    if max_shift_pitches is not None:
        max_shift_px = max_shift_pitches * pitch_px
        outside = (xx - expected_tl[0]) ** 2 + (yy - expected_tl[1]) ** 2 > max_shift_px ** 2
        ncc = np.where(outside, -1.0, ncc).astype(np.float32)
    if ncc.max() <= -1.0:
        raise ValueError('No valid search position: the anchor patch does not fit in the medium image '
                         'within the search radius.')

    iy, ix = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    peak = float(ncc[iy, ix])
    excl = (xx - ix) ** 2 + (yy - iy) ** 2 <= (exclusion_pitch * pitch_px) ** 2
    rest = np.where(excl | (ncc <= -1.0), -np.inf, ncc)
    if np.isfinite(rest).any():
        jy, jx = np.unravel_index(int(np.argmax(rest)), rest.shape)
        second, second_loc = float(rest[jy, jx]), (int(jx), int(jy))
    else:
        second, second_loc = -1.0, None

    sx, sy = _subpixel_peak(ncc, iy, ix)
    anchor_in_canvas = np.array([sx + r, sy + r])
    found_px = anchor_px - (anchor_in_canvas - c_canvas)
    margin = peak - second
    accepted = bool(peak >= min_ncc and margin >= min_margin)

    return {
        'mode': 'anchor_patch',
        'found_px': found_px,
        'expected_px': expected_px,
        'anchor_px': anchor_px,
        'shift_px': found_px - expected_px,
        'shift_pitches': np.linalg.norm(found_px - expected_px) / pitch_px,
        'peak': peak,
        'second_peak': second,
        'margin': margin,
        'accepted': accepted,
        'peak_loc': (int(ix), int(iy)),
        'second_loc': second_loc,
        'pitch_px': pitch_px,
        'patch_r': r,
        'max_shift_px': max_shift_px,
        'expected_tl': expected_tl,
        'delta_deg': delta,
        'template': T,
        'patch_raw': patch,
        'window': W,
        'window_raw': med_rot,
        'ncc': ncc,
        'canvas_center': c_canvas,
    }


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _to_u8(img: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(img, [1, 99])
    if hi <= lo:
        hi = lo + 1
    return np.clip((img - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)


def _to_u8_masked(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    vals = img[mask] if mask.any() else img.ravel()
    lo, hi = np.percentile(vals, [1, 99])
    if hi <= lo:
        hi = lo + 1
    return np.clip((img - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)


def _overlay_panel(ov: dict, pitch_px: float) -> np.ndarray:
    """Square crop in gray; inside the medium footprint a two-color composite
    (medium = magenta, square = green): aligned structure appears gray/white,
    misalignment shows as magenta/green fringes."""
    sq = _to_u8(ov['square'])
    md = _to_u8_masked(ov['medium'], ov['mask'])
    out = cv2.cvtColor(sq, cv2.COLOR_GRAY2BGR)
    comp = np.dstack([md, sq, md])  # B, G, R
    out[ov['mask']] = comp[ov['mask']]
    lw = max(1, int(round(out.shape[0] / 300)))
    cv2.polylines(out, [np.round(ov['corners']).astype(np.int32).reshape(-1, 1, 2)], True, (0, 0, 255), lw)
    r = max(2, int(pitch_px * 0.3))
    if ov['expected'] is not None:
        cv2.circle(out, tuple(np.round(ov['expected']).astype(int)), r, (0, 255, 0), lw)
    cv2.circle(out, tuple(np.round(ov['found']).astype(int)), r, (0, 0, 255), lw)
    return out


def save_diagnostics(result: dict, output_path: str, panel_height: int = 512) -> None:
    """Writes a 4-panel diagnostics PNG.

    anchor_patch mode: square patch around the anchor | medium image (square orientation)
    with the found anchor (red box) and where it was expected (green) | NCC map with best
    (red) and second (blue) peaks | band-passed medium image.
    full mode: processed template | processed search window with expected (green) and found
    (red) positions | NCC map | raw window with template outline at the found position |
    overlay of the raw medium image on the square image (square orientation) at the found
    position: medium = magenta, square = green, aligned = gray/white.
    """
    lw_ref = result['window'].shape[0]
    lw = max(1, int(round(lw_ref / 300)))
    ncc = cv2.applyColorMap(_to_u8(result['ncc'].clip(min=float(np.percentile(result['ncc'], 5)))), cv2.COLORMAP_VIRIDIS)
    ix, iy = result['peak_loc']

    if result.get('mode') == 'anchor_patch':
        r = result['patch_r']
        patch = cv2.cvtColor(_to_u8(result['patch_raw']), cv2.COLOR_GRAY2BGR)
        cv2.circle(patch, (r, r), max(2, r // 6), (0, 0, 255), max(1, r // 60))
        raw = cv2.cvtColor(_to_u8(result['window_raw']), cv2.COLOR_GRAY2BGR)
        win = cv2.cvtColor(_to_u8(result['window']), cv2.COLOR_GRAY2BGR)
        c = result['canvas_center']
        exp_anchor = result['anchor_px'] - result['expected_px'] + c
        for im in (raw, win):
            cv2.rectangle(im, (ix, iy), (ix + 2 * r, iy + 2 * r), (0, 0, 255), lw)
            cv2.circle(im, (int(exp_anchor[0]), int(exp_anchor[1])), max(3, r // 4), (0, 255, 0), lw)
            cv2.drawMarker(im, (int(c[0]), int(c[1])), (0, 255, 255), cv2.MARKER_CROSS, 4 * lw, lw)
        if result.get('max_shift_px'):
            for im in (raw, win):
                cv2.circle(im, (int(exp_anchor[0]), int(exp_anchor[1])), int(result['max_shift_px']), (0, 255, 0), max(1, lw // 2))
        cv2.circle(ncc, (ix, iy), 2 * lw, (0, 0, 255), -1)
        if result['second_loc'] is not None:
            cv2.circle(ncc, result['second_loc'], 2 * lw, (255, 0, 0), -1)
        ex = (int(exp_anchor[0] - r), int(exp_anchor[1] - r))
        if 0 <= ex[0] < ncc.shape[1] and 0 <= ex[1] < ncc.shape[0]:
            cv2.circle(ncc, ex, 2 * lw, (0, 255, 0), -1)
        images = (patch, raw, ncc, win)
    else:
        tmpl = cv2.cvtColor(_to_u8(result['template']), cv2.COLOR_GRAY2BGR)
        win = cv2.cvtColor(_to_u8(result['window']), cv2.COLOR_GRAY2BGR)
        raw = cv2.cvtColor(_to_u8(result['window_raw']), cv2.COLOR_GRAY2BGR)
        th, tw = result['template'].shape[:2]
        m = result['max_shift_px']
        ct = result['center_t']
        exp_c = (int(round(m + ct[0])), int(round(m + ct[1])))
        found_c = (int(round(ix + ct[0])), int(round(iy + ct[1])))
        rr = max(2, int(result['pitch_px'] * 0.3))
        for im in (win, raw):
            cv2.circle(im, exp_c, rr, (0, 255, 0), lw)
            cv2.circle(im, found_c, rr, (0, 0, 255), lw)
        cv2.rectangle(raw, (ix, iy), (ix + tw, iy + th), (0, 0, 255), lw)
        cv2.rectangle(raw, (m, m), (m + tw, m + th), (0, 255, 0), lw)
        cv2.circle(ncc, (ix, iy), 2 * lw, (0, 0, 255), -1)
        if result['second_loc'] is not None:
            cv2.circle(ncc, result['second_loc'], 2 * lw, (255, 0, 0), -1)
        cv2.circle(ncc, (m, m), 2 * lw, (0, 255, 0), -1)
        images = (tmpl, win, ncc, raw)

    if result.get('overlay') is not None:
        images = images + (_overlay_panel(result['overlay'], result['pitch_px']),)

    panels = []
    for im in images:
        scale = panel_height / im.shape[0]
        panels.append(cv2.resize(im, (max(1, int(im.shape[1] * scale)), panel_height),
                                 interpolation=cv2.INTER_AREA))
    out = np.hstack(panels)
    label = (f"peak={result['peak']:.3f} second={result['second_peak']:.3f} "
             f"margin={result['margin']:.3f} shift={np.round(result['shift_px'], 1)}px "
             f"({result['shift_pitches']:.2f} pitch) accepted={result['accepted']}")
    ref = result.get('refinement')
    if ref is not None:
        label += (f" | refine {'used' if ref['used'] else 'NOT used (edge)'}: "
                  f"corr={np.round(ref['correction_px'], 1)}px peak={ref['peak']:.3f}")
    color = (0, 200, 0) if result['accepted'] else (0, 0, 230)
    cv2.putText(out, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.imwrite(str(output_path), out)
