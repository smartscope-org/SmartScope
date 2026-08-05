"""
register_holes.py
-----------------
Re-registers hole coordinates detected in a high-magnification (hole) image
back onto the corresponding low-magnification (square) image.

Uses SIFT (preferred) or ORB feature matching, with the JSON metadata
providing an initial transform estimate (scale + rotation + rough translation)
to constrain the search.

Usage
-----
    python register_holes.py \
        --json       metadata.json \
        --hole-img   LK7_3_square182_hole252.png \
        --square-img LK7_3_square182.png \
        --hole-coords holes.csv \
        --output     registered_holes.csv \
        --visualize

Input CSV (--hole-coords)
-------------------------
    x,y
    120,340
    155,340
    ...
    (hole center coordinates in hole-image pixel space)

    If omitted, a single point at the hole image center is used.

Output CSV
----------
    x_hole,y_hole,x_square,y_square
    ...
    (original hole coords + transformed coords in square-image pixel space)
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_image_gray(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Could not load image: {path}")
    return img


def clahe_equalize(img: np.ndarray, clip_limit: float = 2.0,
                   tile_size: int = 8) -> np.ndarray:
    """Apply CLAHE to improve local contrast — important for cryo-EM images."""
    clahe = cv2.createCLAHE(clipLimit=clip_limit,
                             tileGridSize=(tile_size, tile_size))
    return clahe.apply(img)


def build_initial_transform(meta: dict) -> np.ndarray:
    """
    Build a 2x3 affine warp matrix from the JSON metadata.

    The transform maps a point in hole-image coordinates to square-image
    coordinates:   p_square = M @ [x_hole, y_hole, 1]^T

    Components
    ----------
    scale     : pixel_size_hole / pixel_size_square  (hole image is zoomed in,
                so its pixels are smaller — the image covers less physical area)
    rotation  : relative rotation = square_rotation - hole_rotation
    translation: hole_coords_on_square gives where the *center* of the hole
                image lands in square coordinates.
    """
    hole_ps  = meta["hole"]["pixel_size"]
    sq_ps    = meta["square"]["pixel_size"]
    scale    = hole_ps / sq_ps                             # typically ~0.13

    hole_rot = meta["hole"]["rotation_angle"]
    sq_rot   = meta["square"]["rotation_angle"]
    angle    = sq_rot - hole_rot                           # relative rotation (deg)

    tx = meta["hole_coords_on_square"]["x"]
    ty = meta["hole_coords_on_square"]["y"]

    # Rotation + scale matrix
    cos_a = scale * np.cos(np.radians(angle))
    sin_a = scale * np.sin(np.radians(angle))

    # The translation places the hole-image *center* at (tx, ty) in the square.
    # Center of hole image in hole coords:
    # We don't know image size yet at this point, so we return the matrix
    # without centering; centering is applied later once images are loaded.
    # Store raw components for now.
    return {"cos_a": cos_a, "sin_a": sin_a, "tx": tx, "ty": ty,
            "scale": scale, "angle_deg": angle}


def make_warp_matrix(cos_a, sin_a, tx, ty,
                     hole_w, hole_h) -> np.ndarray:
    """
    Construct the final 2x3 matrix, accounting for hole image center.
    Maps hole-image coords -> square-image coords.
    """
    cx, cy = hole_w / 2.0, hole_h / 2.0
    # Translation: (tx,ty) is where hole center lands in square coords
    t_x = tx - cos_a * cx + sin_a * cy
    t_y = ty - sin_a * cx - cos_a * cy
    M = np.array([[cos_a, -sin_a, t_x],
                  [sin_a,  cos_a, t_y]], dtype=np.float64)
    return M


def warp_hole_to_square(hole_img: np.ndarray, M: np.ndarray,
                        square_shape: tuple) -> np.ndarray:
    """Warp hole image into square image coordinate space."""
    h, w = square_shape
    warped = cv2.warpAffine(hole_img, M, (w, h),
                            flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT,
                            borderValue=0)
    return warped


def transform_points(pts: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Apply 2x3 affine matrix M to an Nx2 array of (x,y) points."""
    ones = np.ones((len(pts), 1))
    pts_h = np.hstack([pts, ones])          # Nx3 homogeneous
    return (M @ pts_h.T).T                  # Nx2


# ---------------------------------------------------------------------------
# Feature matching
# ---------------------------------------------------------------------------

def detect_and_match_sift(img1: np.ndarray, img2: np.ndarray,
                           ratio_thresh: float = 0.75):
    """
    SIFT keypoint detection + Lowe's ratio test matching.
    img1 = hole image (warped to square scale as initial guess)
    img2 = square image (or cropped region)
    Returns matched keypoints as (pts1, pts2) each Nx2.
    """
    sift = cv2.SIFT_create(nfeatures=2000)
    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return None, None, 0

    bf = cv2.BFMatcher(cv2.NORM_L2)
    raw_matches = bf.knnMatch(des1, des2, k=2)

    good = []
    for m_n in raw_matches:
        if len(m_n) == 2:
            m, n = m_n
            if m.distance < ratio_thresh * n.distance:
                good.append(m)

    if len(good) < 4:
        return None, None, len(good)

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])
    return pts1, pts2, len(good)


def detect_and_match_orb(img1: np.ndarray, img2: np.ndarray,
                          ratio_thresh: float = 0.75):
    """
    ORB keypoint detection + ratio test matching.
    Faster than SIFT but less robust for low-contrast cryo-EM images.
    """
    orb = cv2.ORB_create(nfeatures=2000)
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return None, None, 0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = bf.knnMatch(des1, des2, k=2)

    good = []
    for m_n in raw_matches:
        if len(m_n) == 2:
            m, n = m_n
            if m.distance < ratio_thresh * n.distance:
                good.append(m)

    if len(good) < 4:
        return None, None, len(good)

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])
    return pts1, pts2, len(good)


def estimate_refined_transform(pts1: np.ndarray, pts2: np.ndarray,
                                ransac_thresh: float = 5.0):
    """
    Estimate affine transform from matched point pairs using RANSAC.
    pts1: points in warped-hole (square-scale) space
    pts2: points in square space (possibly cropped — offset applied later)
    Returns 2x3 affine matrix or None if estimation fails.
    """
    if pts1 is None or len(pts1) < 4:
        return None, 0

    M, inlier_mask = cv2.estimateAffinePartial2D(
        pts1, pts2,
        method=cv2.RANSAC,
        ransacReprojThreshold=ransac_thresh,
        maxIters=5000,
        confidence=0.995
    )

    n_inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    return M, n_inliers


# ---------------------------------------------------------------------------
# Search-region strategy
# ---------------------------------------------------------------------------

def crop_search_region(square_img: np.ndarray, cx: int, cy: int,
                        hole_w_sq: int, hole_h_sq: int,
                        pad_factor: float = 1.5):
    """
    Crop a search region from the square image centred on the JSON estimate,
    padded by pad_factor * hole footprint on each side.

    Returns (crop, offset_x, offset_y) — the crop and its top-left corner
    in square coordinates (needed to convert crop-space matches back to
    square-image coordinates).
    """
    pad_x = int(hole_w_sq * pad_factor)
    pad_y = int(hole_h_sq * pad_factor)

    x0 = max(0, cx - hole_w_sq // 2 - pad_x)
    y0 = max(0, cy - hole_h_sq // 2 - pad_y)
    x1 = min(square_img.shape[1], cx + hole_w_sq // 2 + pad_x)
    y1 = min(square_img.shape[0], cy + hole_h_sq // 2 + pad_y)

    crop = square_img[y0:y1, x0:x1]
    return crop, x0, y0


# ---------------------------------------------------------------------------
# Main registration function
# ---------------------------------------------------------------------------

def register(hole_img_path: str,
             square_img_path: str,
             meta: dict,
             hole_coords: np.ndarray,
             method: str = "sift",
             min_inliers: int = 8,
             fallback: str = "json",
             verbose: bool = True) -> dict:
    """
    Full registration pipeline.

    Parameters
    ----------
    hole_img_path   : path to hole (high-mag) image
    square_img_path : path to square (low-mag) image
    meta            : parsed JSON metadata dict
    hole_coords     : Nx2 array of hole center coords in hole-image space
    method          : "sift" | "orb"
    min_inliers     : minimum RANSAC inliers to accept the refined transform
    fallback        : "json" — use initial estimate if matching fails
    verbose         : print progress

    Returns
    -------
    dict with keys:
        "transform_used"   : "refined" | "initial"
        "warp_matrix"      : 2x3 numpy array
        "n_inliers"        : int
        "n_matches"        : int
        "hole_coords_sq"   : Nx2 array of hole coords in square-image space
        "quality"          : "good" | "low_matches" | "fallback"
    """

    def log(msg):
        if verbose:
            print(f"[register] {msg}")

    # --- Load images --------------------------------------------------------
    hole_img   = load_image_gray(hole_img_path)
    square_img = load_image_gray(square_img_path)
    hole_h, hole_w = hole_img.shape

    # --- Build initial transform from JSON ----------------------------------
    init = build_initial_transform(meta)
    M_init = make_warp_matrix(
        init["cos_a"], init["sin_a"], init["tx"], init["ty"],
        hole_w, hole_h
    )
    log(f"Initial transform — scale: {init['scale']:.4f}, "
        f"angle: {init['angle_deg']:.2f}°, "
        f"translation: ({init['tx']}, {init['ty']})")

    # Compute footprint of hole image in square coords (for search region)
    hole_w_sq = int(hole_w * init["scale"])
    hole_h_sq = int(hole_h * init["scale"])

    # --- Preprocess images --------------------------------------------------
    hole_eq   = clahe_equalize(hole_img)
    square_eq = clahe_equalize(square_img)

    # Warp hole image into square scale as initial estimate
    warped_hole = warp_hole_to_square(hole_eq, M_init, square_img.shape)

    # Crop search region from square image around JSON estimate
    cx = meta["hole_coords_on_square"]["x"]
    cy = meta["hole_coords_on_square"]["y"]
    search_crop, off_x, off_y = crop_search_region(
        square_eq, cx, cy, hole_w_sq, hole_h_sq, pad_factor=1.5
    )
    # Crop the warped hole to match search region footprint (centered)
    # (we match the warped hole against the crop, not the full square)
    wh_y0 = max(0, cy - hole_h_sq // 2 - off_y)
    wh_x0 = max(0, cx - hole_w_sq // 2 - off_x)
    warped_crop = warped_hole[
        off_y : off_y + search_crop.shape[0],
        off_x : off_x + search_crop.shape[1]
    ]

    log(f"Search region: {search_crop.shape}, "
        f"warped hole footprint: {hole_w_sq}×{hole_h_sq} px in square coords")

    # --- Feature matching ---------------------------------------------------
    match_fn = detect_and_match_sift if method == "sift" else detect_and_match_orb
    pts_warped, pts_crop, n_matches = match_fn(warped_crop, search_crop)

    log(f"{method.upper()} matches before RANSAC: {n_matches}")

    if pts_warped is not None and n_matches >= min_inliers:
        # pts_crop are in crop space — convert to square space
        pts_sq = pts_crop + np.array([off_x, off_y])

        # pts_warped are in square space (warped hole already in square coords)
        # so we need them in square space too
        pts_warped_sq = pts_warped + np.array([off_x, off_y])

        # We want a correction to M_init:
        # estimate_refined_transform gives us a transform from
        # warped-hole-crop space -> square space, which we compose with M_init
        M_correction, n_inliers = estimate_refined_transform(
            pts_warped, pts_sq
        )
        log(f"RANSAC inliers: {n_inliers}")

        if M_correction is not None and n_inliers >= min_inliers:
            # Compose: hole -> (M_init) -> approx_square -> (M_correction) -> square
            # M_init is 2x3, M_correction is 2x3; compose as 3x3
            def to_3x3(M_2x3):
                return np.vstack([M_2x3, [0, 0, 1]])

            M_refined_3x3 = to_3x3(M_correction) @ to_3x3(M_init)
            M_refined = M_refined_3x3[:2, :]

            log(f"Registration SUCCESS — {n_inliers} inliers, using refined transform")
            coords_sq = transform_points(hole_coords, M_refined)
            return {
                "transform_used": "refined",
                "warp_matrix": M_refined,
                "n_inliers": n_inliers,
                "n_matches": n_matches,
                "hole_coords_sq": coords_sq,
                "quality": "good"
            }
        else:
            quality = "low_inliers"
            log(f"RANSAC failed or too few inliers ({n_inliers}). "
                f"Falling back to: {fallback}")
    else:
        quality = "low_matches"
        log(f"Too few matches ({n_matches}). Falling back to: {fallback}")

    # --- Fallback -----------------------------------------------------------
    coords_sq = transform_points(hole_coords, M_init)
    return {
        "transform_used": "initial",
        "warp_matrix": M_init,
        "n_inliers": 0,
        "n_matches": n_matches,
        "hole_coords_sq": coords_sq,
        "quality": quality
    }


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def visualize_registration(hole_img_path: str,
                            square_img_path: str,
                            result: dict,
                            hole_coords: np.ndarray,
                            output_path: str):
    """
    Save a side-by-side visualization:
      Left  — hole image with detected holes marked
      Right — square image with registered hole positions overlaid,
              plus the bounding box of the hole image footprint
    """
    hole_img   = cv2.imread(hole_img_path)
    square_img = cv2.imread(square_img_path)

    if hole_img is None or square_img is None:
        print("[visualize] Could not load images for visualization.")
        return

    hole_vis   = hole_img.copy()
    square_vis = square_img.copy()

    # Draw holes on hole image
    for (x, y) in hole_coords.astype(int):
        cv2.circle(hole_vis, (x, y), 8, (0, 255, 0), 2)

    # Draw registered holes on square image
    coords_sq = result["hole_coords_sq"].astype(int)
    for (x, y) in coords_sq:
        if 0 <= x < square_img.shape[1] and 0 <= y < square_img.shape[0]:
            cv2.circle(square_vis, (x, y), 5, (0, 255, 0), -1)
        else:
            # Out of bounds — draw on edge
            x_c = np.clip(x, 0, square_img.shape[1] - 1)
            y_c = np.clip(y, 0, square_img.shape[0] - 1)
            cv2.drawMarker(square_vis, (x_c, y_c), (0, 0, 255),
                           cv2.MARKER_CROSS, 10, 2)

    # Draw footprint bounding box of hole image in square coords
    hole_h, hole_w = cv2.imread(hole_img_path, 0).shape
    corners = np.array([[0, 0], [hole_w, 0],
                         [hole_w, hole_h], [0, hole_h]], dtype=np.float64)
    corners_sq = transform_points(corners, result["warp_matrix"]).astype(int)
    cv2.polylines(square_vis, [corners_sq.reshape(-1, 1, 2)],
                  isClosed=True, color=(255, 100, 0), thickness=2)

    # Quality label
    color_map = {"good": (0, 200, 0), "low_matches": (0, 140, 255),
                 "low_inliers": (0, 140, 255), "fallback": (0, 0, 200)}
    label_color = color_map.get(result["quality"], (200, 200, 200))
    label = (f"Transform: {result['transform_used']} | "
             f"Matches: {result['n_matches']} | "
             f"Inliers: {result['n_inliers']} | "
             f"Quality: {result['quality']}")
    cv2.putText(square_vis, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, label_color, 2)

    # Resize hole image to match square image height for side-by-side display
    sq_h = square_vis.shape[0]
    scale_disp = sq_h / hole_vis.shape[0]
    hole_resized = cv2.resize(hole_vis,
                               (int(hole_vis.shape[1] * scale_disp), sq_h))

    combined = np.hstack([hole_resized, square_vis])
    cv2.imwrite(output_path, combined)
    print(f"[visualize] Saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Register hole coordinates from high-mag to low-mag image."
    )
    p.add_argument("--json",        required=True,
                   help="Path to metadata JSON file")
    p.add_argument("--hole-img",    required=True,
                   help="Path to hole (high-mag) image")
    p.add_argument("--square-img",  required=True,
                   help="Path to square (low-mag) image")
    p.add_argument("--hole-coords", default=None,
                   help="CSV with columns x,y of hole centers in hole-image space. "
                        "If omitted, uses image center.")
    p.add_argument("--output",      default="registered_holes.csv",
                   help="Output CSV path (default: registered_holes.csv)")
    p.add_argument("--method",      default="sift", choices=["sift", "orb"],
                   help="Feature detector to use (default: sift)")
    p.add_argument("--min-inliers", type=int, default=8,
                   help="Minimum RANSAC inliers to accept refined transform "
                        "(default: 8)")
    p.add_argument("--visualize",   action="store_true",
                   help="Save a side-by-side registration visualization")
    p.add_argument("--vis-output",  default="registration_vis.png",
                   help="Path for visualization image (default: registration_vis.png)")
    p.add_argument("--quiet",       action="store_true",
                   help="Suppress progress output")
    return p.parse_args()


def main():
    args = parse_args()

    # Load metadata
    with open(args.json) as f:
        meta = json.load(f)

    # Load hole coordinates
    if args.hole_coords:
        df = pd.read_csv(args.hole_coords)
        if not {"x", "y"}.issubset(df.columns):
            print("ERROR: hole-coords CSV must have columns 'x' and 'y'.")
            sys.exit(1)
        hole_coords = df[["x", "y"]].values.astype(np.float64)
    else:
        # Default: center of hole image
        hole_img_tmp = load_image_gray(args.hole_img)
        h, w = hole_img_tmp.shape
        hole_coords = np.array([[w / 2, h / 2]])
        print("[register] No --hole-coords provided; using image center.")

    # Run registration
    result = register(
        hole_img_path   = args.hole_img,
        square_img_path = args.square_img,
        meta            = meta,
        hole_coords     = hole_coords,
        method          = args.method,
        min_inliers     = args.min_inliers,
        fallback        = "json",
        verbose         = not args.quiet
    )

    # Save output CSV
    out_df = pd.DataFrame({
        "x_hole":   hole_coords[:, 0],
        "y_hole":   hole_coords[:, 1],
        "x_square": result["hole_coords_sq"][:, 0],
        "y_square": result["hole_coords_sq"][:, 1],
    })
    out_df.to_csv(args.output, index=False)
    print(f"[register] Saved registered coordinates to: {args.output}")
    print(f"[register] Summary — quality: {result['quality']}, "
          f"transform: {result['transform_used']}, "
          f"inliers: {result['n_inliers']}")

    # Visualization
    if args.visualize:
        visualize_registration(
            hole_img_path   = args.hole_img,
            square_img_path = args.square_img,
            result          = result,
            hole_coords     = hole_coords,
            output_path     = args.vis_output
        )


if __name__ == "__main__":
    main()