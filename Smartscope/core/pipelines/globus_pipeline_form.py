
from django import forms
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# Default token file and client ID
DEFAULT_TOKEN_FILE = '/opt/config/smartscope_tokens.json'
DEFAULT_CLIENT_ID = '7df9d534-fb19-4d79-8e83-642f1cdcf081'


def _get_globus_choices():
    """Query Globus APIs for available collections, flows, and compute endpoints.

    Returns a dict of field_name -> [(value, label), ...] choices.
    Falls back to empty lists if tokens are missing or API fails.
    """
    choices = {
        'source_collection_id': [],
        'destination_collection_id': [],
        'globus_flow_id': [],
        'globus_compute_endpoint_id': [],
    }

    try:
        from globus_sdk import (
            NativeAppAuthClient, TransferClient, FlowsClient,
            RefreshTokenAuthorizer,
        )

        token_path = Path(DEFAULT_TOKEN_FILE)
        if not token_path.exists():
            return choices

        tokens = json.loads(token_path.read_text())
        auth_client = NativeAppAuthClient(DEFAULT_CLIENT_ID)

        # Transfer collections
        if 'transfer.api.globus.org' in tokens:
            t = tokens['transfer.api.globus.org']
            authorizer = RefreshTokenAuthorizer(
                t['refresh_token'], auth_client,
                access_token=t['access_token'],
                expires_at=t['expires_at_seconds'],
            )
            tc = TransferClient(authorizer=authorizer)

            collection_choices = []
            for ep in tc.endpoint_search(filter_scope='my-endpoints'):
                label = f"{ep['display_name']}  ({ep['id'][:8]}…)"
                collection_choices.append((ep['id'], label))
            # Also search recently used
            for ep in tc.endpoint_search(filter_scope='recently-used'):
                entry = (ep['id'], f"{ep['display_name']}  ({ep['id'][:8]}…)")
                if entry not in collection_choices:
                    collection_choices.append(entry)

            choices['source_collection_id'] = collection_choices
            choices['destination_collection_id'] = collection_choices

        # Flows
        if 'flows.globus.org' in tokens:
            t = tokens['flows.globus.org']
            authorizer = RefreshTokenAuthorizer(
                t['refresh_token'], auth_client,
                access_token=t['access_token'],
                expires_at=t['expires_at_seconds'],
            )
            fc = FlowsClient(authorizer=authorizer)

            flow_choices = []
            for flow in fc.list_flows():
                label = f"{flow['title']}  ({flow['id'][:8]}…)"
                flow_choices.append((flow['id'], label))
            choices['globus_flow_id'] = flow_choices

        # Compute endpoints
        if 'funcx_service' in tokens:
            try:
                from globus_sdk import ComputeClientV2
                t = tokens['funcx_service']
                authorizer = RefreshTokenAuthorizer(
                    t['refresh_token'], auth_client,
                    access_token=t['access_token'],
                    expires_at=t['expires_at_seconds'],
                )
                cc = ComputeClientV2(authorizer=authorizer)
                endpoint_choices = []
                for ep in cc.get_endpoints().data:
                    name = ep.get('display_name', ep.get('name', ep['uuid'][:8]))
                    label = f"{name}  ({ep['uuid'][:8]}…)"
                    endpoint_choices.append((ep['uuid'], label))
                choices['globus_compute_endpoint_id'] = endpoint_choices
            except Exception as e:
                logger.debug(f'Could not list compute endpoints: {e}')

    except Exception as e:
        logger.warning(f'Could not fetch Globus choices: {e}')

    return choices


class GlobusPipelineForm(forms.Form):

    grouping = forms.ChoiceField(
        choices=[
            ('per_micrograph', 'Per Micrograph — one flow per image (immediate)'),
            ('per_group', 'Per Group — one flow per BIS group'),
            ('per_square', 'Per Square — one flow per grid square'),
        ],
        widget=forms.RadioSelect(attrs={'class': ''}),
        initial='per_group',
        help_text='How to batch images into Globus Flow runs.',
    )

    max_concurrent_flows = forms.IntegerField(
        label='Max concurrent flows',
        initial=1,
        min_value=1,
        max_value=20,
        help_text='Maximum number of Globus Flow runs to have active simultaneously.',
    )

    # ===== Globus — these become dropdowns populated from the API =====

    globus_compute_endpoint_id = forms.ChoiceField(
        label='Globus Compute Endpoint',
        choices=[],
        help_text='HPC endpoint where compute functions run. Leave blank for transfer-only mode.',
    )

    globus_compute_function_id = forms.CharField(
        label='Compute Function ID',
        widget=forms.TextInput(attrs={'placeholder': 'UUID from setup_globus.py register-func'}),
        help_text='Function UUID from registration. Leave blank for transfer-only mode.',
    )

    globus_flow_id = forms.ChoiceField(
        label='Globus Flow',
        choices=[],
        help_text='Select a deployed Globus Flow. Leave blank for transfer-only mode (files transferred, no processing).',
    )

    source_collection_id = forms.ChoiceField(
        label='Source Collection',
        choices=[],
        help_text='Globus collection on the microscope side.',
    )

    destination_collection_id = forms.ChoiceField(
        label='Destination Collection',
        choices=[],
        help_text='Globus collection on the HPC side.',
    )

    source_base_path = forms.CharField(
        label='Source Base Path',
        help_text='Globus path prefix mapping to the container data root. '
                  'e.g. "/SmartScope" if that maps to /mnt/data inside the container.',
    )

    destination_base_path = forms.CharField(
        label='Destination Base Path (Globus)',
        help_text='Globus collection path for HPC projects, e.g. "/CryoEM/Projects".',
    )

    destination_filesystem_root = forms.CharField(
        label='Destination Filesystem Root (HPC)',
        help_text='HPC filesystem mount point for the Globus collection root, e.g. "/mnt/blackmore/ext-superluminal".',
    )

    # ===== Slot-to-Project Mapping =====

    slot_1 = forms.CharField(
        label='Slot 1',
        help_text='HPC project path. e.g. "Lodos/Apoferritin". Same value = same project. Empty = skip.',
    )
    slot_2 = forms.CharField(label='Slot 2')
    slot_3 = forms.CharField(label='Slot 3')
    slot_4 = forms.CharField(label='Slot 4')
    slot_5 = forms.CharField(label='Slot 5')
    slot_6 = forms.CharField(label='Slot 6')
    slot_7 = forms.CharField(label='Slot 7')
    slot_8 = forms.CharField(label='Slot 8')
    slot_9 = forms.CharField(label='Slot 9')
    slot_10 = forms.CharField(label='Slot 10')
    slot_11 = forms.CharField(label='Slot 11')
    slot_12 = forms.CharField(label='Slot 12')

    # ===== Extra Config (passed through to compute function) =====

    extra_config = forms.CharField(
        label='Compute Function Parameters',
        widget=forms.Textarea(attrs={'rows': 10, 'placeholder':
            '{\n'
            '  "do_motioncor": true,\n'
            '  "do_ctf": true,\n'
            '  "do_picking": true,\n'
            '  "dose_per_frame": 1.0,\n'
            '  "picking_threshold": 0.3\n'
            '}'}),
        help_text='JSON key-value pairs passed to the compute function. '
                  'Parameters depend on the selected function.',
    )

    # ===== Auth =====

    globus_client_id = forms.CharField(
        label='Globus Client ID',
        initial='7df9d534-fb19-4d79-8e83-642f1cdcf081',
        help_text='Globus app client ID (pre-filled with SmartScope app).',
    )

    token_file = forms.CharField(
        label='Token File',
        initial='/opt/config/smartscope_tokens.json',
        help_text='Path to cached Globus auth tokens.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate dynamic dropdown choices from Globus APIs
        globus_choices = _get_globus_choices()
        for field_name, field_choices in globus_choices.items():
            if field_name in self.fields and field_choices:
                self.fields[field_name].choices = [('', '— Select —')] + field_choices

        for visible in self.visible_fields():
            widget = visible.field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-check-input'
            elif not isinstance(widget, forms.RadioSelect):
                widget.attrs['class'] = 'form-control'
            visible.field.required = False

    def clean_extra_config(self):
        value = self.cleaned_data.get('extra_config', '').strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise forms.ValidationError('Must be a JSON object (key-value pairs).')
            return parsed
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {e}')
