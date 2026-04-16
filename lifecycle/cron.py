"""Lifecycle cron integration — schedule daily check-ins via the skill system.

The lifecycle is now a skill (kai-lifecycle/daily-cycle), not a rigid state machine.
The cron job simply gives the agent a prompt to load the skill and run its daily check-in.
The agent itself decides what to do based on workspace context and available signals.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def register_lifecycle_cron(workspace_id: str, schedule: str = "every 24h") -> Optional[str]:
    """Register a daily lifecycle check-in as a cron job.

    The cron job creates a normal AIAgent with full workspace context and tells
    it to load the daily-cycle skill. The agent then assesses the workspace,
    decides what to work on, and executes.

    Args:
        workspace_id: The workspace to manage.
        schedule: Cron schedule (default: every 24h).

    Returns:
        Job ID if created, None if already exists.
    """
    from cron.jobs import list_jobs, create_job

    # Check if lifecycle job already exists for this workspace
    existing_jobs = list_jobs()
    for job in existing_jobs:
        if job.get("name", "").startswith(f"lifecycle:{workspace_id}"):
            logger.info("Lifecycle cron job already exists: %s", job["id"])
            return None

    prompt = (
        "Time for your daily check-in. "
        "Load the kai-lifecycle/daily-cycle skill with skill_view and follow it. "
        "Assess the workspace, check what happened since last time, decide what to work on, "
        "and execute. Use lifecycle_actions_list to check pending work, and lifecycle_events_list "
        "to see what changed recently. Create new actions with lifecycle_actions_create for any "
        "work you propose. Share findings as you go."
    )

    job = create_job(
        prompt=prompt,
        schedule=schedule,
        name=f"lifecycle:{workspace_id}",
    )
    logger.info("Registered lifecycle cron job: %s (schedule: %s)", job["id"], schedule)
    return job["id"]


def unregister_lifecycle_cron(workspace_id: str) -> bool:
    """Remove the lifecycle cron job for a workspace."""
    from cron.jobs import list_jobs, remove_job

    existing_jobs = list_jobs()
    for job in existing_jobs:
        if job.get("name", "").startswith(f"lifecycle:{workspace_id}"):
            remove_job(job["id"])
            logger.info("Removed lifecycle cron job: %s", job["id"])
            return True
    return False
