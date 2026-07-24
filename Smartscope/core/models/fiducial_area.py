from .base_model import *
from .target import Target


class FiducialArea(Target):

    fiducial_area_id = models.CharField(max_length=30, primary_key=True, editable=False)
    area_type = models.CharField(max_length=100, null=True, blank=True)

    class Meta(BaseModel.Meta):
        db_table = 'fiducialarea'

    @property
    def id(self):
        return self.fiducial_area_id

    @property
    def prefix(self):
        return 'FiducialArea'

    @property
    def targets(self):
        return None  # leaf node, no child targets

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.fiducial_area_id:
            self.name = f'{self.grid_id.name}_fiducial{self.number}'
            self.fiducial_area_id = generate_unique_id(extra_inputs=[self.name[:20]])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        return self

    def __str__(self):
        return self.name
