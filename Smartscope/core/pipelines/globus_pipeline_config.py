
from typing import Any, Dict
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class GlobusPipelineConfig(BaseModel):

    # How to group images into flow runs
    #   per_micrograph: one flow per high-mag image (immediate)
    #   per_group: one flow per BIS group
    #   per_square: one flow per grid square (wait until square is done)
    grouping: str = "per_group"

    # Globus Compute endpoint where jobs run
    globus_compute_endpoint_id: str = ""

    # Globus Compute function to invoke (registered processing function)
    globus_compute_function_id: str = ""

    # Globus Flow ID (deployed flow that chains transfer -> compute -> transfer)
    globus_flow_id: str = ""

    # Globus Transfer collection IDs
    source_collection_id: str = ""
    destination_collection_id: str = ""

    # Path mapping
    source_base_path: str = ""
    destination_base_path: str = ""  # Globus collection path, e.g. "/CryoEM/Projects"
    destination_filesystem_root: str = ""  # HPC filesystem mount, e.g. "/mnt/blackmore/ext-superluminal"

    # ===== Slot-to-project mapping (autoloader positions 1-12) =====
    slot_1: str = ""
    slot_2: str = ""
    slot_3: str = ""
    slot_4: str = ""
    slot_5: str = ""
    slot_6: str = ""
    slot_7: str = ""
    slot_8: str = ""
    slot_9: str = ""
    slot_10: str = ""
    slot_11: str = ""
    slot_12: str = ""

    # ===== Concurrency =====
    max_concurrent_flows: int = 1
    group_settle_seconds: int = 60  # Wait N seconds after newest image before submitting a group

    # ===== Extra config passed through to the compute function =====
    # Key-value pairs merged into the manifest "config" dict.
    # The compute function defines what it expects; SmartScope passes these through.
    extra_config: Dict[str, Any] = {}

    # ===== Globus Auth =====
    globus_client_id: str = "7df9d534-fb19-4d79-8e83-642f1cdcf081"
    token_file: str = "/opt/config/smartscope_tokens.json"

    def get_project_for_slot(self, position: int) -> str:
        """Return the HPC project path for a given autoloader slot (1-12)."""
        return getattr(self, f"slot_{position}", "")
