
from django import forms

class NextPYPPreprocessingPipelineForm(forms.Form):
    frames_directory = forms.CharField(
        label="Frames Directory",
        help_text="Path (from nextPYP perspective) to the frame data"
    )

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
        help_text="Path to the nextPYP token file inside the container, e.g. /root/.nextpyp_token"
    )

    url_base = forms.CharField(
        label="nextPYP Server URL",
        help_text="Base URL of the nextPYP server, e.g. https://nextpyp.example.org"
    )

    group_id = forms.CharField(
        label="nextPYP Group ID",
        help_text="ID of the nextPYP group to create sessions under"
    )

    remote_user = forms.CharField(
        label="Remote SSH Username",
        help_text="Username for SCP file transfer from the HPC cluster"
    )

    remote_host = forms.CharField(
        label="Remote SSH Hostname",
        help_text="Hostname of the HPC cluster for SCP file transfer"
    )

    # gain_reference = forms.CharField(
    #     label="Gain Reference Path",
    #     help_text="Path to the gain reference file (from nextPYP perspective)",
    #     required=False
    # )

    # SLURM settings
    slurm_tasks = forms.IntegerField(
        label="SLURM Tasks",
        initial=7,
        help_text="Number of CPU tasks per SLURM job"
    )

    slurm_memory = forms.IntegerField(
        label="SLURM Memory (GB)",
        initial=14,
        help_text="Memory per SLURM job in GB"
    )

    slurm_daemon_walltime = forms.CharField(
        label="SLURM Walltime",
        initial="0-01:00:00",
        help_text="Walltime for the SLURM daemon job, e.g. 0-01:00:00"
    )

    # Particle picking settings
    detect_rad = forms.FloatField(
        label="Particle Radius (Å)",
        initial=65.0,
        help_text="Expected particle radius in Angstroms"
    )

    detect_method = forms.CharField(
        label="Detection Method",
        initial="all",
        help_text="Particle detection method (e.g. 'all', 'none', 'pyp-train')"
    )

    detect_dist = forms.IntegerField(
        label="Min Particle Distance",
        initial=40,
        help_text="Minimum distance between picked particles (in pixels)"
    )

    # 2D Classification settings
    class2d_num = forms.IntegerField(
        label="Number of 2D Classes",
        initial=50,
        help_text="Number of 2D classes to compute"
    )

    class2d_box = forms.IntegerField(
        label="2D Class Box Size",
        initial=96,
        help_text="Box size in pixels for 2D classification"
    )

    class2d_bin = forms.IntegerField(
        label="2D Class Binning",
        initial=4,
        help_text="Binning factor for 2D classification"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'
            visible.field.required = False
