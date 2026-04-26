from .base_model import *
from .target import Target


class FocusPosition(Target):

    focus_position_id = models.CharField(max_length=30, primary_key=True, editable=False)

    class Meta(BaseModel.Meta):
        db_table = 'focusposition'

    @property
    def id(self):
        return self.focus_position_id

    @property
    def prefix(self):
        return 'FocusPosition'

    @property
    def targets(self):
        return None  # leaf node, no child targets

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.focus_position_id:
            self.name = f'{self.grid_id.name}_focuspos{self.number}'
            self.focus_position_id = generate_unique_id(extra_inputs=[self.name[:20]])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        return self

    def __str__(self):
        return self.name
