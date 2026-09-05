from django.db import IntegrityError, transaction
from django.test import TestCase

from Smartscope.core.models.grid_collection_params import GridCollectionParams


class GridCollectionParamsTests(TestCase):

    def test_atomic_get_or_create_creates_and_reuses(self):
        obj, created = GridCollectionParams.atomic_get_or_create(atlas_x=5, atlas_y=8)
        self.assertTrue(created)
        obj2, created2 = GridCollectionParams.atomic_get_or_create(atlas_x=5, atlas_y=8)
        self.assertFalse(created2)
        self.assertEqual(obj.params_id, obj2.params_id)
        self.assertEqual(GridCollectionParams.objects.count(), 1)

    def test_unique_constraint_blocks_duplicates(self):
        GridCollectionParams.objects.create(atlas_x=5, atlas_y=8)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GridCollectionParams.objects.create(atlas_x=5, atlas_y=8)
