"""Agent fleet — external coding agents Dash can delegate to.

See GitHub issues #10-#16 for the full design. Module layout:

- registry.py — static, ships-with-Dash facts about known coding agents
- profile.py  — AgentProfile dataclass (per-tenant learned state)
- blueprint.py — read/write external_agents into the workspace blueprint
"""

from agent_fleet.registry import (
    KNOWN_AGENTS,
    KnownAgent,
    DocumentedInvocation,
    lookup,
    list_known,
)
from agent_fleet.profile import (
    AgentProfile,
    ObservedInvocation,
    ObservedInvocationDetail,
    Confidence,
    DetectionMethod,
)
from agent_fleet.blueprint import (
    get_external_agents,
    get_agent_profile,
    get_enabled_agents,
    upsert_agent_profile,
    remove_agent_profile,
)

__all__ = [
    "KNOWN_AGENTS",
    "KnownAgent",
    "DocumentedInvocation",
    "lookup",
    "list_known",
    "AgentProfile",
    "ObservedInvocation",
    "ObservedInvocationDetail",
    "Confidence",
    "DetectionMethod",
    "get_external_agents",
    "get_agent_profile",
    "get_enabled_agents",
    "upsert_agent_profile",
    "remove_agent_profile",
]
