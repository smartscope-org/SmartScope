"""Helpers for talking to a nextPYP server: group-name lookup and app-token requests."""
import logging
from typing import List

from nextpyp.client import Client
from nextpyp.client.gen import AppTokenRequestData, Group

logger = logging.getLogger(__name__)

NEXTPYP_APP_NAME = 'smartscope'

# Every app permission the NextPYP preprocessing pipeline uses. nextPYP doesn't
# publish this list anywhere, so it lives here: when the pipeline starts calling a
# new endpoint, add its ``:Permission Needed:`` (see nextpyp.client.gen) to this list
# and have users request a fresh token.
REQUIRED_APP_PERMISSIONS: List[str] = [
    "project_list",
    "project_listen",
    "session_list",
    "session_read",
    "session_write",
    "session_control",
    "session_create",
    "session_delete",
    "session_export",
    "session_listen",
    "group_list",
]


def resolve_group_id(client: Client, group: str) -> str:
    """Translate a human-readable nextPYP group name into the group ID nextPYP uses.

    Matches on the exact group ID first (so existing configs that store the raw ID
    keep working), then on the display name, case-insensitively.
    """
    group = group.strip()
    if not group:
        raise ValueError("No nextPYP group was given. Set 'nextPYP Group' in the preprocessing settings.")

    groups: List[Group] = client.services.sessions.groups()

    for g in groups:
        if g.id == group:
            return g.id

    matches = [g for g in groups if g.name.strip().lower() == group.lower()]
    if len(matches) == 1:
        logger.info(f"Resolved nextPYP group '{group}' to ID {matches[0].id}")
        return matches[0].id

    available = ', '.join(f"'{g.name}'" for g in groups) or '(none visible to this token)'
    if len(matches) > 1:
        raise ValueError(
            f"nextPYP group name '{group}' is ambiguous ({len(matches)} groups share it). "
            f"Use the group ID instead: {', '.join(str(g.id) for g in matches)}"
        )
    raise ValueError(f"No nextPYP group named '{group}'. Available groups: {available}")


def request_app_token(url_base: str, userid: str) -> AppTokenRequestData:
    """Ask nextPYP for a SmartScope app token carrying REQUIRED_APP_PERMISSIONS.

    The user then approves the request on the nextPYP website and copies the token
    into the file the pipeline's 'Path to nextPYP token' setting points at.
    """
    client = Client(url_base, None)
    return client.services.apps.request_token(
        user_id=userid,
        app_name=NEXTPYP_APP_NAME,
        app_permission_ids=REQUIRED_APP_PERMISSIONS,
    )
