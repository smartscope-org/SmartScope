from django.db import IntegrityError, transaction

from .base_model import *


class GridCollectionParamsManager(models.Manager):
    def get_by_natural_key(self, microscope_id, name):
        return self.get(microscope_id=microscope_id, name=name)


class GridCollectionParams(BaseModel):
    params_id = models.CharField(max_length=30, primary_key=True, editable=False)
    atlas_x = models.IntegerField(default=3)
    atlas_y = models.IntegerField(default=3)
    square_x = models.IntegerField(default=1)
    square_y = models.IntegerField(default=1)
    squares_num = models.IntegerField(default=3)
    holes_per_square = models.IntegerField(default=3)  # If -1 means all
    max_exposures_for_grid = models.IntegerField(default=-1, verbose_name='Max Exposures For Grid', help_text='Move on to the next grid when this number of exposures were acquired.')  # If -1 means inactive
    bis_max_distance = models.FloatField(default=3)  # 0 means not BIS
    min_bis_group_size = models.IntegerField(default=1)
    afis = models.BooleanField(default=False, verbose_name='AFIS')
    target_defocus_min = models.FloatField(default=-2)
    target_defocus_max = models.FloatField(default=-2)
    step_defocus = models.FloatField(default=0)  # 0 deactivates step defocus
    drift_crit = models.FloatField(default=-1)
    tilt_angle = models.FloatField(default=0)
    save_frames = models.BooleanField(default=True)
    force_process_from_average = models.BooleanField(default=False)
    highmag_aperture_size = models.IntegerField(default=50, verbose_name='High Mag Aperture Size', help_text='Size of the aperture for the View and Record presets. C2 aperture size for Thermo microscopes. CL for JEOL.')
    objective_aperture_size = models.IntegerField(default=0, verbose_name='Objective Aperture Size', help_text='Objective aperture to use for View and Record. 0 means no aperture.')
    offset_targeting = models.BooleanField(default=True)
    offset_distance = models.FloatField(default=-1)
    zeroloss_delay = models.IntegerField(default=-1)
    hardwaredark_delay = models.IntegerField(default=-1,verbose_name='Hardware Dark Delay')
    coldfegflash_delay= models.IntegerField(default=-1,verbose_name='ColdFEG Flash Delay', help_text='Number of hours between cold FEG flashes. Will only work if the microscope has a cold FEG. Values smaller than 0 will disable the procedure.')
    beam_centering_delay = models.IntegerField(default=-1,verbose_name='Beam Centering Delay', help_text='Number of minutes between beam centering procedures. Values smaller than 0 will disable the procedure.')
    multishot_per_hole = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        db_table = 'gridcollectionparams'
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'atlas_x',
                    'atlas_y',
                    'square_x',
                    'square_y',
                    'squares_num',
                    'holes_per_square',
                    'max_exposures_for_grid',
                    'bis_max_distance',
                    'min_bis_group_size',
                    'afis',
                    'target_defocus_min',
                    'target_defocus_max',
                    'step_defocus',
                    'drift_crit',
                    'tilt_angle',
                    'save_frames',
                    'force_process_from_average',
                    'highmag_aperture_size',
                    'objective_aperture_size',
                    'offset_targeting',
                    'offset_distance',
                    'zeroloss_delay',
                    'hardwaredark_delay',
                    'coldfegflash_delay',
                    'beam_centering_delay',
                    'multishot_per_hole',
                ],
                name='unique_gridcollectionparams',
            ),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.params_id:
            self.params_id = generate_unique_id()

    @classmethod
    def atomic_get_or_create(cls, defaults=None, **kwargs):
        """Race-safe alternative to get_or_create.

        get_or_create is not atomic by itself: concurrent requests can pass the
        initial lookup and each insert a row, leaving duplicates in the table and
        eventually raising MultipleObjectsReturned on subsequent lookups.
        Combined with the unique constraint on the params fields, catching the
        IntegrityError and re-fetching makes this safe.
        """
        try:
            with transaction.atomic():
                return cls.objects.get_or_create(defaults=defaults, **kwargs)
        except IntegrityError:
            return cls.objects.get(**kwargs), False

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        return self

    def __str__(self):
        return f'Atlas:{self.atlas_x}X{self.atlas_y} Sq:{self.squares_num} H:{self.holes_per_square} BIS:{self.bis_max_distance} Def:{self.target_defocus_min},{self.target_defocus_max},{self.step_defocus}'
