
from django import forms

class NextPYPPreprocessingPipelineForm(forms.Form):
    pixel_size = forms.FloatField(label="Pixel Size", 
                                  help_text = "Angstroms per pixel")
    
    frames_directory = forms.CharField(label="Frames Directory",
                                       help_text="Path (from nextPYP perspective) to the frame data")
    
    n_processes = forms.IntegerField(
        initial=1,
        min_value=1,
        max_value=1,
        help_text='Can only use 1 process for preprocessing.'
    )
    
    nextpyp_userid = forms.CharField(
        label="nextPYP User ID",
        help_text="User ID for nextPYP, e.g. netid@duke.edu"
    )
    
    path_to_token = forms.CharField(
        label="Path to nextPYP token",
        help_text="Path to the nextPYP token file (in terms of the filesystem used inside the container) for USERID, e.g. /root/.nextpyp_token"
    )
    
    
    
    def __init__(self, *args,**kwargs):
        super().__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'
            visible.field.required = False