from dataclasses import dataclass
from typing import List
import mrcfile
import numpy as np
import logging

from .image_file import parse_mdoc, save_mrc
from .base_image import BaseImage
from .target import Target


logger = logging.getLogger(__name__)


@dataclass
class Montage(BaseImage):

    def __post_init__(self):
        super().__post_init__()
        self.directory.mkdir(exist_ok=True)

    # TODO deprecated in the future
    def load_or_process(self, check_AWS=False, force_process=False):
        if not force_process and self.check_metadata(check_AWS=check_AWS):
            return
        self.metadata = parse_mdoc(self.mdoc, self.is_movie)
        self.build_montage()
        self.read_image()
        self.save_metadata()

    def build_montage(self):

        def piece_pos(coord):
            coord_end = coord + np.array([self.header.mx, self.header.my])
            return np.array([
                coord, [coord[0], coord_end[1]],
                coord_end, [coord_end[0], coord[1]]
            ])

        def piece_center(piece):
            return np.array([
                np.sum(piece[:, 0]) / piece.shape[0],
                np.sum(piece[:, 1]) / piece.shape[0],
            ])

        with mrcfile.open(self.raw) as mrc:
            self.header = mrc.header
            img = mrc.data
        if int(self.header.mz) == 1:
            self.metadata['PieceCoordinates'] = [[0, 0, 0]]
            self.metadata['piece_limits'] = self.metadata.PieceCoordinates.apply(
                lambda c: piece_pos(np.array(c[0:-1]))
            )
            self.metadata['piece_center'] = self.metadata.piece_limits.apply(piece_center)
            self._image = img
            # self.make_symlink()
            return

        # AlignedPieceCoords (SerialEM's post-alignment tile positions) are not
        # zero-anchored and can be negative, unlike PieceCoordinates. Normalize
        # every tile relative to the tile whose PieceCoordinates == (0,0,0), so
        # that tile stays at the origin of the coordinate frame ImageToStageMatrix
        # is calibrated against, then pad the array to fit any tile that still
        # ends up negative in that frame instead of cropping it.
        coord_field = 'AlignedPieceCoords' if 'AlignedPieceCoords' in self.metadata.columns else 'PieceCoordinates'

        origin_mask = self.metadata.PieceCoordinates.apply(lambda c: c[0] == 0 and c[1] == 0)
        origin_coord = np.array(self.metadata.loc[origin_mask, coord_field].iloc[0][0:-1])

        normalized_coords = self.metadata[coord_field].apply(lambda c: np.array(c[0:-1]) - origin_coord)
        piece_ends = normalized_coords.apply(lambda c: c + np.array([self.header.mx, self.header.my]))

        mins = np.stack(normalized_coords).min(axis=0)
        maxs = np.stack(piece_ends).max(axis=0)
        pad_offset = -mins
        montsize = maxs - mins

        self.metadata['PadOffset'] = [pad_offset.tolist()] * len(self.metadata)
        self.metadata['piece_limits'] = normalized_coords.apply(lambda c: piece_pos(c + pad_offset))
        self.metadata['piece_center'] = self.metadata.piece_limits.apply(piece_center)

        montage = np.zeros(np.flip(montsize), dtype='int16')
        for ind, piece in enumerate(self.metadata.piece_limits):
            montage[piece[0, 1]: piece[-2, 1], piece[0, 0]: piece[-2, 0]] = img[ind, :, :]
        # montage = montage[~np.all(montage == 0, axis=1)]
        # montage = montage[:, ~(montage == 0).all(0)]

        self._image = montage

        save_mrc(self.image_path, self._image, self.pixel_size, [pad_offset[1], pad_offset[0]])


