"""
reregister_yolo.py
------------------
Re-registers hole coordinates from a high-mag (hole) image back onto the
corresponding low-mag (square) image, using YOLO-detected contaminants
as anchor points.

Pipeline
--------
1. Load metadata JSON (pixel sizes, rotation angles, hole-center-on-square).
2. Build a physics-based initial similarity transform (scale + rotation +
   translation) from the metadata alone.
3. Accept pre-computed contaminant detections (N×2 center arrays) for both
   the hole image and the square image — the caller runs whatever YOLO model
   it already has and passes the results in.
4. Map hole detections through the initial transform into approximate square
   coordinates, then match to nearest square detections.
5. Fit a refined similarity transform from matched pairs via linear least
   squares + RANSAC.
6. Fall back to the initial transform if matching fails.
7. Apply the final transform to the supplied hole coordinates and write output.

Programmatic usage
------------------
    from reregister_yolo import register, load_yolo_txt, boxes_to_centers

    # from YOLO txt files (normalized format)
    det_hole   = load_yolo_txt("det_hole.txt",   img_w=hole_w,   img_h=hole_h)
    det_square = load_yolo_txt("det_square.txt", img_w=square_w, img_h=square_h)

    # or from raw xyxy boxes if running the model directly
    det_hole   = boxes_to_centers(xyxy_hole)    # N×4 → N×2

    result = register(
        hole_img_path   = "hole.png",
        meta            = meta_dict,
        hole_coords     = np.array([[cx, cy]]),
        detections_hole   = det_hole,
        detections_square = det_square,
    )
    # result["hole_coords_sq"]  — registered coords in square space
    # result["warp_matrix"]     — 2×3 similarity matrix

CLI usage
---------
    python reregister_yolo.py \\
        --json            metadata.json \\
        --hole-img        hole.png \\
        --square-img      square.png \\
        --detections-hole   det_hole.txt \\   # YOLO format: class cx cy w h (normalized)
        --detections-square det_square.txt \\ # same
        --hole-coords     holes.csv \\        # columns: x, y  (points to register)
        --output          registered.csv \\
        --visualize

Detection file format (YOLO txt)
---------------------------------
Space-separated, one detection per line, no header:
    class_id  cx_norm  cy_norm  w_norm  h_norm
e.g.
    0 0.420313 0.204492 0.036719 0.037891
Coordinates are normalized to [0, 1] relative to image width/height.
load_yolo_txt() converts them to pixel centers using the image dimensions.
"""

import argparse
import json
from typing import Optional

import cv2
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def load_yolo_txt(path: str, img_w: int, img_h: int) -> np.ndarray:
    """
    Load a YOLO-format detection txt file and return pixel-space centers.

    File format (space-separated, no header):
        class_id  cx_norm  cy_norm  w_norm  h_norm

    Parameters
    ----------
    path  : path to the .txt file
    img_w : image width  in pixels (used to denormalise x)
    img_h : image height in pixels (used to denormalise y)

    Returns
    -------
    centers : (N, 2) float array of (x_px, y_px)
    """
    rows = np.loadtxt(path, dtype=np.float64, ndmin=2)
    if len(rows) == 0:
        return np.empty((0, 2), dtype=np.float64)
    cx_px = rows[:, 1] * img_w
    cy_px = rows[:, 2] * img_h
    return np.column_stack([cx_px, cy_px])


def boxes_to_centers(xyxy: np.ndarray) -> np.ndarray:
    """
    Convert pixel-space bounding boxes to center points.

    Parameters
    ----------
    xyxy : array-like, shape (N, 4) — columns [x1, y1, x2, y2]
           or (N, 2) if centers were already extracted.

    Returns
    -------
    centers : (N, 2) float array of (cx, cy)
    """
    arr = np.asarray(xyxy, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[None]
    if arr.shape[1] == 4:
        return np.column_stack([(arr[:, 0] + arr[:, 2]) / 2.0,
                                 (arr[:, 1] + arr[:, 3]) / 2.0])
    if arr.shape[1] == 2:
        return arr.copy()
    raise ValueError(f"Expected N×2 or N×4 array, got shape {arr.shape}")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def build_initial_transform(meta: dict, hole_w: int, hole_h: int) -> np.ndarray:
    """
    Return a 2×3 affine matrix M such that:
        p_square ≈ M @ [x_hole, y_hole, 1]^T

    Scale:       s = pixel_size_hole / pixel_size_square
    Rotation:    Δθ = θ_hole − θ_square
    Translation: hole image center maps to hole_coords_on_square.
    """
    hole_ps = meta["hole"]["pixel_size"]
    sq_ps   = meta["square"]["pixel_size"]
    s       = hole_ps / sq_ps

    delta = np.radians(meta["hole"]["rotation_angle"] -
                       meta["square"]["rotation_angle"])

    a = s * np.cos(delta)
    b = s * np.sin(delta)

    cx, cy = hole_w / 2.0, hole_h / 2.0
    tx_raw = meta["hole_coords_on_square"]["x"]
    ty_raw = meta["hole_coords_on_square"]["y"]

    tx = tx_raw - a * cx + b * cy
    ty = ty_raw - b * cx - a * cy

    return np.array([[a, -b, tx],
                     [b,  a, ty]], dtype=np.float64)


def transform_points(pts: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Apply 2×3 affine matrix M to an N×2 array of (x, y) points."""
    ones  = np.ones((len(pts), 1))
    pts_h = np.hstack([pts, ones])
    return (M @ pts_h.T).T


def fit_similarity(src: np.ndarray, dst: np.ndarray) -> Optional[np.ndarray]:
    """
    Fit similarity transform  dst = M @ [src | 1]^T  by linear least squares.

    Parameterisation:
        x_dst = a·x_src − b·y_src + tx
        y_dst = b·x_src + a·y_src + ty

    Returns 2×3 matrix, or None if underdetermined / singular.
    """
    n = len(src)
    if n < 2:
        return None

    A = np.zeros((2 * n, 4), dtype=np.float64)
    b_vec = np.zeros(2 * n, dtype=np.float64)

    for i, ((xs, ys), (xd, yd)) in enumerate(zip(src, dst)):
        A[2 * i]     = [ xs, -ys, 1, 0]
        A[2 * i + 1] = [ ys,  xs, 0, 1]
        b_vec[2 * i]     = xd
        b_vec[2 * i + 1] = yd

    result, *_ = np.linalg.lstsq(A, b_vec, rcond=None)
    a, b, tx, ty = result
    return np.array([[a, -b, tx],
                     [b,  a, ty]], dtype=np.float64)


def ransac_similarity(src: np.ndarray, dst: np.ndarray,
                      thresh: float = 5.0,
                      max_iter: int = 1000,
                      min_inliers: int = 3,
                      rng: Optional[np.random.Generator] = None):
    """
    RANSAC over fit_similarity.

    Returns (M_refined, inlier_mask) or (None, None).
    """
    if rng is None:
        rng = np.random.default_rng(42)

    n = len(src)
    if n < 2:
        return None, None

    best_count, best_mask = 0, None

    for _ in range(max_iter):
        idx = rng.choice(n, size=2, replace=False)
        M   = fit_similarity(src[idx], dst[idx])
        if M is None:
            continue

        err   = np.linalg.norm(transform_points(src, M) - dst, axis=1)
        mask  = err < thresh
        count = mask.sum()
        if count > best_count:
            best_count, best_mask = count, mask

    if best_count < min_inliers:
        return None, None

    return fit_similarity(src[best_mask], dst[best_mask]), best_mask


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def nearest_neighbor_match(pts_hole_in_sq: np.ndarray,
                             pts_sq: np.ndarray,
                             max_dist: float) -> tuple:
    """
    Greedy nearest-neighbor match: for each hole detection (mapped to square
    space via the initial transform), find the closest unmatched square
    detection within max_dist pixels.

    Returns (idx_hole, idx_sq) index arrays.
    """
    if len(pts_hole_in_sq) == 0 or len(pts_sq) == 0:
        return np.array([], dtype=int), np.array([], dtype=int)

    dists = np.linalg.norm(
        pts_hole_in_sq[:, None, :] - pts_sq[None, :, :], axis=2)  # Nh×Ns

    matched_h, matched_s, used_s = [], [], set()

    for ih in range(len(pts_hole_in_sq)):
        row = dists[ih].copy()
        row[list(used_s)] = np.inf
        is_ = int(np.argmin(row))
        if row[is_] <= max_dist:
            matched_h.append(ih)
            matched_s.append(is_)
            used_s.add(is_)

    return np.array(matched_h, dtype=int), np.array(matched_s, dtype=int)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(hole_img_path: str,
             meta: dict,
             hole_coords: np.ndarray,
             detections_hole: Optional[np.ndarray] = None,
             detections_square: Optional[np.ndarray] = None,
             match_dist_px: float = 15.0,
             ransac_thresh: float = 3.0,
             min_inliers: int = 3,
             verbose: bool = True) -> dict:
    """
    Re-register hole-image coordinates onto the square image.

    Parameters
    ----------
    hole_img_path
        Path to the hole image (used to read image dimensions).
    meta
        Parsed metadata dict with pixel_size, rotation_angle, and
        hole_coords_on_square.
    hole_coords
        N×2 array of (x, y) points in hole-image space to re-register.
    detections_hole, detections_square
        N×2 arrays of contaminant center coordinates (pixel space) for the
        hole and square images respectively.  Pass None to use the
        physics-based initial transform only.
        Use load_yolo_txt() or boxes_to_centers() to build these arrays.
    match_dist_px
        Maximum nearest-neighbor distance (in square pixels) for matching
        hole detections to square detections.
    ransac_thresh
        Reprojection threshold (square pixels) for RANSAC inlier scoring.
    min_inliers
        Minimum RANSAC inliers required to accept the refined transform.

    Returns
    -------
    dict with keys:
        transform_used   : "refined" | "initial"
        warp_matrix      : 2×3 numpy array (hole → square)
        n_detections_h   : number of hole detections supplied
        n_detections_sq  : number of square detections supplied
        n_matches        : matched anchor pairs before RANSAC
        n_inliers        : RANSAC inliers
        hole_coords_sq   : N×2 registered coords in square space
        quality          : "good" | "few_anchors" | "initial_only"
    """
    def log(msg):
        if verbose:
            print(f"[reregister] {msg}")

    hole_img = cv2.imread(hole_img_path, cv2.IMREAD_GRAYSCALE)
    if hole_img is None:
        raise FileNotFoundError(hole_img_path)
    hole_h, hole_w = hole_img.shape

    # --- Physics-based initial transform ------------------------------------
    M_init = build_initial_transform(meta, hole_w, hole_h)
    s      = meta["hole"]["pixel_size"] / meta["square"]["pixel_size"]
    dtheta = meta["hole"]["rotation_angle"] - meta["square"]["rotation_angle"]
    log(f"Initial transform — scale: {s:.4f}, Δangle: {dtheta:.2f}°, "
        f"hole-center-on-square: ({meta['hole_coords_on_square']['x']}, "
        f"{meta['hole_coords_on_square']['y']})")

    def _fallback(quality, n_matches=0, n_inliers=0):
        return {
            "transform_used":  "initial",
            "warp_matrix":     M_init,
            "n_detections_h":  len(detections_hole)   if detections_hole   is not None else 0,
            "n_detections_sq": len(detections_square) if detections_square is not None else 0,
            "n_matches":       n_matches,
            "n_inliers":       n_inliers,
            "hole_coords_sq":  transform_points(hole_coords, M_init),
            "quality":         quality,
        }

    # --- Check detections ---------------------------------------------------
    if detections_hole is None or detections_square is None:
        log("No detections provided — using initial transform only.")
        return _fallback("initial_only")

    pts_h  = np.asarray(detections_hole,   dtype=np.float64)
    pts_sq = np.asarray(detections_square, dtype=np.float64)
    log(f"Detections — hole: {len(pts_h)}, square: {len(pts_sq)}")

    if len(pts_h) < 2 or len(pts_sq) < 2:
        log("Too few detections — falling back to initial transform.")
        return _fallback("few_anchors")

    # --- Map hole detections into approximate square space ------------------
    pts_h_in_sq = transform_points(pts_h, M_init)

    # --- Nearest-neighbor matching -----------------------------------------
    idx_h, idx_s = nearest_neighbor_match(pts_h_in_sq, pts_sq,
                                           max_dist=match_dist_px)
    log(f"Matched pairs (before RANSAC): {len(idx_h)}")

    if len(idx_h) < min_inliers:
        log(f"Too few matched pairs ({len(idx_h)} < {min_inliers}) — "
            "falling back to initial transform.")
        return _fallback("few_anchors", n_matches=len(idx_h))

    src = pts_h[idx_h]
    dst = pts_sq[idx_s]

    # --- RANSAC similarity fit ----------------------------------------------
    M_refined, inlier_mask = ransac_similarity(src, dst,
                                               thresh=ransac_thresh,
                                               min_inliers=min_inliers)
    n_inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    log(f"RANSAC inliers: {n_inliers} / {len(idx_h)}")

    if M_refined is not None and n_inliers >= min_inliers:
        log("Registration SUCCESS — using refined transform.")
        return {
            "transform_used":  "refined",
            "warp_matrix":     M_refined,
            "n_detections_h":  len(pts_h),
            "n_detections_sq": len(pts_sq),
            "n_matches":       len(idx_h),
            "n_inliers":       n_inliers,
            "hole_coords_sq":  transform_points(hole_coords, M_refined),
            "quality":         "good",
        }

    log("RANSAC failed — falling back to initial transform.")
    return _fallback("few_anchors", n_matches=len(idx_h), n_inliers=n_inliers)


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def visualize(hole_img_path: str, square_img_path: str,
              result: dict, hole_coords: np.ndarray,
              output_path: str,
              detections_hole: Optional[np.ndarray] = None,
              detections_square: Optional[np.ndarray] = None):
    hole_img   = cv2.imread(hole_img_path)
    square_img = cv2.imread(square_img_path)
    if hole_img is None or square_img is None:
        print("[visualize] Could not load images.")
        return

    hole_vis   = hole_img.copy()
    square_vis = square_img.copy()

    if detections_hole is not None:
        for (x, y) in np.asarray(detections_hole, dtype=int):
            cv2.circle(hole_vis, (x, y), 6, (0, 100, 255), 2)
    if detections_square is not None:
        for (x, y) in np.asarray(detections_square, dtype=int):
            cv2.circle(square_vis, (x, y), 4, (0, 100, 255), 2)

    for (x, y) in hole_coords.astype(int):
        cv2.circle(hole_vis, (x, y), 10, (0, 255, 0), 2)

    for (x, y) in result["hole_coords_sq"].astype(int):
        x_c = int(np.clip(x, 0, square_img.shape[1] - 1))
        y_c = int(np.clip(y, 0, square_img.shape[0] - 1))
        color = (0, 255, 0) if (0 <= x < square_img.shape[1] and
                                0 <= y < square_img.shape[0]) else (0, 0, 255)
        cv2.circle(square_vis, (x_c, y_c), 6, color, -1)

    # Hole footprint outline in square image
    hole_gray = cv2.imread(hole_img_path, cv2.IMREAD_GRAYSCALE)
    if hole_gray is not None:
        h, w = hole_gray.shape
        corners    = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float64)
        corners_sq = transform_points(corners, result["warp_matrix"]).astype(int)
        cv2.polylines(square_vis, [corners_sq.reshape(-1, 1, 2)],
                      isClosed=True, color=(255, 100, 0), thickness=2)

    label = (f"  {result['transform_used']} | "
             f"det h/sq: {result['n_detections_h']}/{result['n_detections_sq']} | "
             f"matches: {result['n_matches']} | inliers: {result['n_inliers']} | "
             f"quality: {result['quality']}")
    color_map = {"good": (0, 200, 0), "few_anchors": (0, 140, 255),
                 "initial_only": (0, 0, 200)}
    cv2.putText(square_vis, label, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                color_map.get(result["quality"], (200, 200, 200)), 2)

    sq_h = square_vis.shape[0]
    scale_disp = sq_h / hole_vis.shape[0]
    hole_resized = cv2.resize(hole_vis,
                              (int(hole_vis.shape[1] * scale_disp), sq_h))
    cv2.imwrite(output_path, np.hstack([hole_resized, square_vis]))
    print(f"[visualize] Saved → {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="YOLO-anchor re-registration: hole image → square image."
    )
    p.add_argument("--json",        required=True,  help="Metadata JSON")
    p.add_argument("--hole-img",    required=True,  help="Hole (high-mag) image")
    p.add_argument("--square-img",  required=True,  help="Square (low-mag) image")
    p.add_argument("--detections-hole",   default=None,
                   help="YOLO txt file of contaminant detections in the hole image "
                        "(format: class cx cy w h, normalized)")
    p.add_argument("--detections-square", default=None,
                   help="YOLO txt file of contaminant detections in the square image "
                        "(format: class cx cy w h, normalized)")
    p.add_argument("--hole-coords", default=None,
                   help="CSV of points to re-register in hole-image space (columns: x, y). "
                        "Defaults to hole image center.")
    p.add_argument("--output",      default="registered_holes.csv")
    p.add_argument("--match-dist",  type=float, default=15.0,
                   help="Max nearest-neighbor distance in square px (default: 15)")
    p.add_argument("--ransac-thresh", type=float, default=3.0,
                   help="RANSAC reprojection threshold in square px (default: 3)")
    p.add_argument("--min-inliers", type=int, default=3)
    p.add_argument("--visualize",   action="store_true")
    p.add_argument("--vis-output",  default="reregistration_vis.png")
    p.add_argument("--quiet",       action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    with open(args.json) as f:
        meta = json.load(f)

    # Load images to get dimensions for YOLO txt denormalisation
    hole_img_gray   = cv2.imread(args.hole_img,   cv2.IMREAD_GRAYSCALE)
    square_img_gray = cv2.imread(args.square_img, cv2.IMREAD_GRAYSCALE)
    if hole_img_gray is None:
        raise FileNotFoundError(args.hole_img)
    if square_img_gray is None:
        raise FileNotFoundError(args.square_img)
    hole_h,   hole_w   = hole_img_gray.shape
    square_h, square_w = square_img_gray.shape

    detections_hole   = (load_yolo_txt(args.detections_hole,   hole_w,   hole_h)
                         if args.detections_hole   else None)
    detections_square = (load_yolo_txt(args.detections_square, square_w, square_h)
                         if args.detections_square else None)

    if args.hole_coords:
        df = pd.read_csv(args.hole_coords)
        if not {"x", "y"}.issubset(df.columns):
            raise ValueError("--hole-coords CSV must have columns 'x' and 'y'.")
        hole_coords = df[["x", "y"]].values.astype(np.float64)
    else:
        hole_coords = np.array([[hole_w / 2.0, hole_h / 2.0]])
        print("[reregister] No --hole-coords; using image center.")

    result = register(
        hole_img_path     = args.hole_img,
        meta              = meta,
        hole_coords       = hole_coords,
        detections_hole   = detections_hole,
        detections_square = detections_square,
        match_dist_px     = args.match_dist,
        ransac_thresh     = args.ransac_thresh,
        min_inliers       = args.min_inliers,
        verbose           = not args.quiet,
    )

    out_df = pd.DataFrame({
        "x_hole":   hole_coords[:, 0],
        "y_hole":   hole_coords[:, 1],
        "x_square": result["hole_coords_sq"][:, 0],
        "y_square": result["hole_coords_sq"][:, 1],
    })
    out_df.to_csv(args.output, index=False)
    print(f"[reregister] Saved → {args.output}")
    print(f"[reregister] quality={result['quality']}, "
          f"transform={result['transform_used']}, "
          f"det={result['n_detections_h']}/{result['n_detections_sq']}, "
          f"matches={result['n_matches']}, inliers={result['n_inliers']}")

    if args.visualize:
        visualize(
            hole_img_path     = args.hole_img,
            square_img_path   = args.square_img,
            result            = result,
            hole_coords       = hole_coords,
            output_path       = args.vis_output,
            detections_hole   = detections_hole,
            detections_square = detections_square,
        )


if __name__ == "__main__":
    main()
