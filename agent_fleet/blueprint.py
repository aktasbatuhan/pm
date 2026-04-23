"""Read/write helpers for external_agents on the workspace blueprint.

The workspace blueprint is a JSON blob — no schema migration is required.
These helpers give typed access to the `external_agents` slice and keep
the rest of the blueprint intact on write.

Usage:
    from agent_fleet.blueprint import get_enabled_agents, upsert_agent_profile
    for p in get_enabled_agents(ctx):
        ...
    upsert_agent_profile(ctx, AgentProfile(id="claude-code", enabled=True, ...))

`ctx` is a WorkspaceContext (see workspace_context.py).
"""

from __future__ import annotations

import logging
from typing import List, Optional, Any

from agent_fleet.profile import AgentProfile

logger = logging.getLogger(__name__)


# Key inside blueprint.data where we persist the list.
BLUEPRINT_KEY = "external_agents"


def _load_data(ctx: Any) -> tuple[dict, str]:
    """Return (blueprint_data, summary). Empty dict/'' if no blueprint yet."""
    bp = ctx.get_blueprint()
    if not bp:
        return {}, ""
    data = bp.get("data") or {}
    if not isinstance(data, dict):
        logger.warning("blueprint.data was %s, expected dict — resetting", type(data).__name__)
        data = {}
    return data, bp.get("summary", "") or ""


def _save_data(ctx: Any, data: dict, summary: str) -> None:
    ctx.update_blueprint(data, summary, updated_by="agent-fleet")


def get_external_agents(ctx: Any) -> List[AgentProfile]:
    """Return every AgentProfile stored in the blueprint (enabled or not)."""
    data, _ = _load_data(ctx)
    raw = data.get(BLUEPRINT_KEY) or []
    profiles: List[AgentProfile] = []
    for entry in raw:
        try:
            profiles.append(AgentProfile.from_dict(entry))
        except Exception as e:  # malformed entries shouldn't crash the caller
            logger.warning("skipping malformed external_agents entry: %s", e)
    return profiles


def get_agent_profile(ctx: Any, agent_id: str) -> Optional[AgentProfile]:
    """Look up a single agent profile by id."""
    for p in get_external_agents(ctx):
        if p.id == agent_id:
            return p
    return None


def get_enabled_agents(ctx: Any) -> List[AgentProfile]:
    """Only agents the tenant has flagged as enabled for delegation."""
    return [p for p in get_external_agents(ctx) if p.enabled]


def upsert_agent_profile(ctx: Any, profile: AgentProfile) -> None:
    """Insert or update a profile by id. Validates before writing."""
    profile.validate()
    data, summary = _load_data(ctx)
    existing = data.get(BLUEPRINT_KEY) or []
    next_list: List[dict] = []
    replaced = False
    for entry in existing:
        if isinstance(entry, dict) and entry.get("id") == profile.id:
            next_list.append(profile.to_dict())
            replaced = True
        else:
            next_list.append(entry)
    if not replaced:
        next_list.append(profile.to_dict())
    data[BLUEPRINT_KEY] = next_list
    _save_data(ctx, data, summary)


def remove_agent_profile(ctx: Any, agent_id: str) -> bool:
    """Remove a profile. Returns True if something was removed."""
    data, summary = _load_data(ctx)
    existing = data.get(BLUEPRINT_KEY) or []
    next_list = [e for e in existing if not (isinstance(e, dict) and e.get("id") == agent_id)]
    if len(next_list) == len(existing):
        return False
    data[BLUEPRINT_KEY] = next_list
    _save_data(ctx, data, summary)
    return True
