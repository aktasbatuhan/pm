"""
PM Workspace tools — read/write workspace blueprint, learnings, and onboarding state.

These tools give the agent direct access to the shared workspace context
(local SQLite at ~/.dash-pm/workspace.db). The workspace persists across
all sessions (CLI, Slack, cron, gateway).
"""

import json
import os
import time
from typing import Optional

from backend.tenant_context import require_tenant_context
from workspace_context import WorkspaceContext, load_workspace_context
from tools.registry import registry


def _get_ctx(**kwargs) -> WorkspaceContext:
    tenant = require_tenant_context(kwargs=kwargs, consumer="pm_workspace_tools")
    return load_workspace_context(workspace_id=tenant.tenant_id)


# =============================================================================
# Tool: workspace_get_blueprint
# =============================================================================

def workspace_get_blueprint(**kwargs) -> str:
    """Get the current workspace blueprint."""
    ctx = _get_ctx(**kwargs)
    bp = ctx.get_blueprint()
    if not bp:
        return json.dumps({"message": "No blueprint yet. Run onboarding to create one."})
    return json.dumps({
        "summary": bp["summary"],
        "data": bp["data"],
        "updated_at": bp["updated_at"],
    })


WORKSPACE_GET_BLUEPRINT_SCHEMA = {
    "name": "workspace_get_blueprint",
    "description": "Get the workspace blueprint — team structure, repos, stack, metrics, and connected platforms. Returns null if onboarding hasn't run yet.",
    "parameters": {"type": "object", "properties": {}}
}


# =============================================================================
# Tool: workspace_update_blueprint
# =============================================================================

def workspace_update_blueprint(summary: str, data: str, **kwargs) -> str:
    """Update the workspace blueprint."""
    ctx = _get_ctx(**kwargs)
    try:
        parsed_data = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        return json.dumps({"error": "data must be valid JSON"})

    ctx.update_blueprint(parsed_data, summary, updated_by="dash-pm")
    return json.dumps({"success": True, "message": "Blueprint updated."})


WORKSPACE_UPDATE_BLUEPRINT_SCHEMA = {
    "name": "workspace_update_blueprint",
    "description": "Create or update the workspace blueprint. Use during onboarding to store discovered team/repo/metric info, and later to keep it current.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Human-readable summary of the workspace (team, repos, stack, metrics)"
            },
            "data": {
                "type": "string",
                "description": "JSON object with structured blueprint data: {team_members, repos, active_projects, key_metrics, connected_platforms, stack}"
            }
        },
        "required": ["summary", "data"]
    }
}


# =============================================================================
# Tool: workspace_get_learnings
# =============================================================================

def workspace_get_learnings(category: str = "", limit: int = 20, **kwargs) -> str:
    """Get workspace learnings, optionally filtered by category."""
    ctx = _get_ctx(**kwargs)
    learnings = ctx.get_learnings(limit=limit)
    if category:
        learnings = [l for l in learnings if l["category"] == category]
    if not learnings:
        return json.dumps({"message": "No learnings yet.", "items": []})
    return json.dumps({"count": len(learnings), "items": learnings})


WORKSPACE_GET_LEARNINGS_SCHEMA = {
    "name": "workspace_get_learnings",
    "description": "Get workspace learnings — persistent insights discovered across sessions. Optionally filter by category (e.g. 'team', 'product', 'process', 'technical').",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter by category (optional). Common: team, product, process, technical, risk"
            },
            "limit": {
                "type": "integer",
                "description": "Max learnings to return (default: 20)"
            }
        }
    }
}


# =============================================================================
# Tool: workspace_add_learning
# =============================================================================

def workspace_add_learning(category: str, content: str, **kwargs) -> str:
    """Add a learning to the workspace."""
    ctx = _get_ctx(**kwargs)
    ctx.add_learning(category, content)
    return json.dumps({"success": True, "message": f"Learning added [{category}]."})


WORKSPACE_ADD_LEARNING_SCHEMA = {
    "name": "workspace_add_learning",
    "description": "Store a new learning — an insight worth remembering across sessions. Use categories: team, product, process, technical, risk.",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category: team, product, process, technical, risk"
            },
            "content": {
                "type": "string",
                "description": "The insight or learning to store"
            }
        },
        "required": ["category", "content"]
    }
}


# =============================================================================
# Tool: workspace_set_onboarding_status
# =============================================================================

def workspace_set_onboarding_status(status: str, phase: str = "", **kwargs) -> str:
    """Update workspace onboarding status."""
    ctx = _get_ctx(**kwargs)
    ctx.set_onboarding_status(status, phase or None)
    return json.dumps({"success": True, "status": status, "phase": phase})


WORKSPACE_SET_ONBOARDING_STATUS_SCHEMA = {
    "name": "workspace_set_onboarding_status",
    "description": "Update workspace onboarding status. Call with 'completed' when onboarding is done.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["not_started", "in_progress", "completed"],
                "description": "New onboarding status"
            },
            "phase": {
                "type": "string",
                "description": "Current phase name (optional, e.g. 'discovery', 'blueprint', 'cron_setup')"
            }
        },
        "required": ["status"]
    }
}


# =============================================================================
# Registry
# =============================================================================

registry.register(
    name="workspace_get_blueprint",
    toolset="pm-workspace",
    schema=WORKSPACE_GET_BLUEPRINT_SCHEMA,
    handler=lambda args, **kw: workspace_get_blueprint(**kw),
)

registry.register(
    name="workspace_update_blueprint",
    toolset="pm-workspace",
    schema=WORKSPACE_UPDATE_BLUEPRINT_SCHEMA,
    handler=lambda args, **kw: workspace_update_blueprint(
        summary=args.get("summary", ""),
        data=args.get("data", "{}"),
        **kw),
)

registry.register(
    name="workspace_get_learnings",
    toolset="pm-workspace",
    schema=WORKSPACE_GET_LEARNINGS_SCHEMA,
    handler=lambda args, **kw: workspace_get_learnings(
        category=args.get("category", ""),
        limit=int(args.get("limit", 20)),
        **kw),
)

registry.register(
    name="workspace_add_learning",
    toolset="pm-workspace",
    schema=WORKSPACE_ADD_LEARNING_SCHEMA,
    handler=lambda args, **kw: workspace_add_learning(
        category=args.get("category", ""),
        content=args.get("content", ""),
        **kw),
)

registry.register(
    name="workspace_set_onboarding_status",
    toolset="pm-workspace",
    schema=WORKSPACE_SET_ONBOARDING_STATUS_SCHEMA,
    handler=lambda args, **kw: workspace_set_onboarding_status(
        status=args.get("status", ""),
        phase=args.get("phase", ""),
        **kw),
)
