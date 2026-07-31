from pathlib import Path

import mrcfile
import numpy as np
import pytest

from ..image.image_file import parse_mdoc
from ..image.montage import Montage
from ..image.process_image import ProcessImage
from ..image.target import Target

TESTFILES_ATLAS = Path(__file__).resolve().parents[4] / 'testfiles' / 'atlas'
SJ27_MRC = TESTFILES_ATLAS / 'SJ27_1_1_collec_atlas.mrc'
SJ27_MDOC = TESTFILES_ATLAS / 'SJ27_1_1_collec_atlas.mrc.mdoc'


def _expected_bounds(mdoc_path, mx, my):
    """Independently reproduce the bounding-box/pad_offset math build_montage()
    is expected to perform, from raw parsed mdoc data."""
    meta = parse_mdoc(str(mdoc_path), False)
    piece = np.stack(meta['PieceCoordinates'].apply(lambda p: np.array(p[:-1])))
    aligned = np.stack(meta['AlignedPieceCoords'].apply(lambda p: np.array(p[:-1])))
    origin_idx = np.where((piece[:, 0] == 0) & (piece[:, 1] == 0))[0][0]
    normalized = aligned - aligned[origin_idx]
    ends = normalized + np.array([mx, my])
    mins = normalized.min(axis=0)
    maxs = ends.max(axis=0)
    pad_offset = -mins
    montsize = maxs - mins
    return meta, normalized, pad_offset, montsize


def _build_montage(tmp_path):
    montage = Montage(name=SJ27_MRC.stem, working_dir=str(tmp_path))
    montage.raw = SJ27_MRC
    montage.load_or_process()
    return montage


def test_build_montage_pads_for_negative_aligned_coords(tmp_path):
    with mrcfile.open(SJ27_MRC) as mrc:
        mx, my, mz = int(mrc.header.mx), int(mrc.header.my), int(mrc.header.mz)
        raw_img = mrc.data.copy()

    _, normalized, expected_pad_offset, expected_montsize = _expected_bounds(SJ27_MDOC, mx, my)
    # sanity: this fixture must actually exercise negative-going aligned coords
    assert (normalized.min(axis=0) < 0).any()

    montage = _build_montage(tmp_path)

    assert montage.image.shape == tuple(np.flip(expected_montsize))
    assert list(montage.metadata.iloc[-1].PadOffset) == list(expected_pad_offset)

    # the origin tile (PieceCoordinates == [0,0,0]) must land exactly at pad_offset,
    # i.e. its corner is the only thing padding shifted, not an arbitrary drift
    origin_piece = montage.metadata.piece_limits.iloc[0]
    assert list(origin_piece[0]) == list(expected_pad_offset)

    # last-drawn tile is never overwritten by a later, overlapping tile, so its
    # placed pixels must match the raw source tile exactly (proves negative/positive
    # aligned coordinates are placed correctly, not clipped, wrapped, or corrupted)
    last_piece = montage.metadata.piece_limits.iloc[mz - 1]
    placed = montage.image[last_piece[0, 1]:last_piece[-2, 1], last_piece[0, 0]:last_piece[-2, 0]]
    assert np.array_equal(placed, raw_img[mz - 1])


def test_build_montage_falls_back_without_aligned_piece_coords(tmp_path):
    montage = Montage(name=SJ27_MRC.stem, working_dir=str(tmp_path))
    montage.raw = SJ27_MRC
    montage.metadata = parse_mdoc(str(SJ27_MDOC), False).drop(columns=['AlignedPieceCoords'])
    montage.build_montage()

    assert list(montage.metadata.iloc[-1].PadOffset) == [0, 0]

    with mrcfile.open(SJ27_MRC) as mrc:
        mx, my = int(mrc.header.mx), int(mrc.header.my)
    piece = np.stack(montage.metadata['PieceCoordinates'].apply(lambda p: np.array(p[:-1])))
    old_montsize = (piece + np.array([mx, my])).max(axis=0)
    assert montage.image.shape == tuple(np.flip(old_montsize))


def test_image_to_stage_matrix_uses_unpadded_origin(tmp_path):
    montage = _build_montage(tmp_path)
    assert 'ImageToStageMatrix' in montage.metadata.iloc[-1].keys()

    pixel = [3000, 3000]
    pad_offset = np.array(montage.metadata.iloc[-1].PadOffset)
    assert (pad_offset > 0).any()  # this fixture must actually need padding

    matrix = montage.metadata.iloc[-1].ImageToStageMatrix
    corrected = np.array(pixel) - pad_offset
    unpadded_height = montage.shape_x - pad_offset[1]
    flipped = Target.flip_y(corrected, unpadded_height)
    expected_stage = ProcessImage.pixel_to_stage_from_vectors(flipped, matrix)

    target = Target(pixel, from_center=True)
    target.convert_image_coords_to_stage(montage)

    assert target.stage_x == pytest.approx(expected_stage[0])
    assert target.stage_y == pytest.approx(expected_stage[1])

    # and the correction must actually matter: ignoring pad_offset entirely
    # (the pre-fix behavior) would give a different, wrong answer
    naive_flipped = Target.flip_y(np.array(pixel), montage.shape_x)
    naive_stage = ProcessImage.pixel_to_stage_from_vectors(naive_flipped, matrix)
    assert not np.allclose(naive_stage, expected_stage)


def test_convert_image_coords_to_stage_relative_path(tmp_path):
    montage = _build_montage(tmp_path)
    target = Target([3000, 3000], from_center=True)
    target.convert_image_coords_to_stage(montage, force_legacy=True)

    assert np.isfinite(target.stage_x)
    assert np.isfinite(target.stage_y)
