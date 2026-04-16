"""
Workspace context bridge — queries local workspace state (SQLite).

Provides a clean API for entry points (cli.py, gateway, cron) to check
workspace status and build system prompt fragments.

The workspace database lives at ~/.dash-pm/workspace.db.
"""

import os
from typing import Optional

from workspace_context import WorkspaceContext, load_workspace_context


# ── Internals ─────────────────────────────────────────────────────────

def _get_workspace_id() -> str:
    return (
        os.environ.get("KAI_WORKSPACE_ID")
        or os.environ.get("HERMES_WORKSPACE_ID")
        or "default"
    )


def _get_ctx(workspace_id: str = None) -> WorkspaceContext:
    ws_id = workspace_id or _get_workspace_id()
    return load_workspace_context(workspace_id=ws_id)


# ── Public API ─────────────────────────────────────────────────────────


def fetch_workspace_status(workspace_id: str = None) -> Optional[dict]:
    """Fetch workspace status from local SQLite.

    Returns: {onboardingStatus, blueprintUpdatedAt, learningsCount, threadsCount, pendingWorkCount}
    """
    try:
        ctx = _get_ctx(workspace_id)
        bp = ctx.get_blueprint()
        learnings = ctx.get_learnings(limit=100)
        threads = ctx.get_threads(limit=100)
        pending = ctx.get_pending_work()
        onboarding = ctx.get_onboarding_status()

        return {
            "onboardingStatus": onboarding,
            "blueprintUpdatedAt": bp["updated_at"] if bp else None,
            "learningsCount": len(learnings),
            "threadsCount": len(threads),
            "pendingWorkCount": len(pending),
        }
    except Exception:
        return None


def update_workspace_status(workspace_id: str, onboarding_status: str, phase: str = None) -> bool:
    """Update onboarding status. Returns True on success."""
    try:
        ctx = _get_ctx(workspace_id)
        ctx.set_onboarding_status(onboarding_status, phase)
        return True
    except Exception:
        return False


def build_workspace_status_prompt(status: dict) -> str:
    """Render a system prompt fragment from workspace status.

    Guides the agent's first action based on workspace state:
    - Fresh workspace → trigger PM onboarding
    - In-progress → continue onboarding
    - Completed → compact status line
    """
    onb = status.get("onboardingStatus", "not_started")

    if onb == "not_started":
        return (
            "## Workspace Context\n\n"
            "This is a fresh workspace. No blueprint, no history, no learnings.\n\n"
            "**You must onboard.** Load the PM onboarding skill immediately:\n"
            "1. Call `skill_view` with name `pm-onboarding/self-onboard`.\n"
            "2. Follow the skill instructions exactly.\n"
            "3. When done, mark onboarding completed.\n\n"
            "Start now. Do not ask permission."
        )

    if onb == "in_progress":
        return (
            "## Workspace Context\n\n"
            "Onboarding is in progress. Continue where you left off.\n"
            "Load the PM onboarding skill with `skill_view` name `pm-onboarding/self-onboard` if needed.\n"
            "Use workspace tools to see what has been built so far."
        )

    # Completed — compact status
    bp_age = status.get("blueprintUpdatedAt", "unknown")
    learnings = status.get("learningsCount", 0)
    threads = status.get("threadsCount", 0)
    pending = status.get("pendingWorkCount", 0)

    return (
        "## Workspace Context\n\n"
        f"Onboarded. {learnings} learnings, {threads} threads, {pending} pending items. "
        f"Blueprint last updated: {bp_age}.\n"
        "Use workspace tools to read details or write updates as needed."
    )
