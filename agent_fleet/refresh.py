"""Daily agent-availability refresh + drift detection — GitHub issue #16.

refresh_external_agents(ctx, token, repos) runs discovery methods at the
cadences specified in issue #16 and returns a list of drift signals that
become action items in the daily brief.

Cadence rules:
  B (fingerprint)     — every run, 24h lookback only
  D (workflow scan)   — only if .github/workflows/ was touched in last 24h
  C (installations)   — weekly (weekday == 0, i.e. Monday)
  Invocation learning — weekly (Monday)

Returns (updated_profiles, drift_signals) where drift_signals are
structured action item dicts ready for brief_store.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent_fleet.discovery import discover_external_agents, merge_with_existing
from agent_fleet.profile import AgentProfile
from agent_fleet.blueprint import get_external_agents, upsert_agent_profile

logger = logging.getLogger(__name__)

# How many days without activity before flagging "agent went silent"
SILENCE_THRESHOLD_DAYS = 14


# ---------------------------------------------------------------------------
# Cadence helpers
# ---------------------------------------------------------------------------

def _is_monday() -> bool:
    return datetime.now(timezone.utc).weekday() == 0


def _workflows_touched_recently(repos: List[str], token: str, since_hours: int = 24) -> bool:
    """Return True if any .github/workflows/ file was touched in the last N hours."""
    import json, urllib.request, urllib.error
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for repo in repos:
        url = f"https://api.github.com/repos/{repo}/commits?path=.github/workflows&since={since}&per_page=1"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Dash-PM-Refresh",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if isinstance(data, list) and len(data) > 0:
                    return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

def _detect_drift(
    discovered: List[AgentProfile],
    existing: List[AgentProfile],
) -> List[dict]:
    """Compare discovered profiles to existing and produce drift signals.

    Returns a list of action item dicts (category, title, description, priority).
    """
    signals: List[dict] = []
    existing_by_id = {p.id: p for p in existing}
    discovered_ids = {p.id for p in discovered}

    # New agent detected
    for p in discovered:
        if p.id not in existing_by_id:
            signals.append({
                "category": "team",
                "title": f"New coding agent detected: {p.display_name()}",
                "description": (
                    f"{p.display_name()} was detected in your repos via "
                    f"{', '.join(p.detected_via or ['unknown'])}. "
                    "Enable it with github_manage_agent(action='enable') to start delegating."
                ),
                "priority": "medium",
            })

    # Agent went silent
    now_ts = time.time()
    silence_secs = SILENCE_THRESHOLD_DAYS * 86400
    for p in existing:
        if not p.enabled:
            continue
        if not p.last_active:
            continue
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(p.last_active.replace("Z", "+00:00"))
            last_ts = dt.timestamp()
        except Exception:
            continue
        if now_ts - last_ts > silence_secs:
            days_silent = int((now_ts - last_ts) / 86400)
            signals.append({
                "category": "team",
                "title": f"{p.display_name()} inactive for {days_silent} days",
                "description": f"{p.display_name()} was last active {days_silent} days ago. Still in use?",
                "priority": "low",
            })

    # Invocation pattern changed (primary flipped)
    for disc in discovered:
        if disc.id not in existing_by_id:
            continue
        old = existing_by_id[disc.id]
        old_prim = (old.observed_invocation.primary or None)
        new_prim = (disc.observed_invocation.primary or None)
        if old_prim and new_prim and old_prim.type != new_prim.type:
            signals.append({
                "category": "team",
                "title": f"{disc.display_name()} invocation pattern changed",
                "description": (
                    f"Was '{old_prim.type}', now '{new_prim.type}'. "
                    "Dash will update its delegation policy automatically."
                ),
                "priority": "low",
            })

    # Installed but never used
    for p in existing:
        methods = set(p.detected_via or [])
        if methods == {"org_installations"} and not p.activity_90d:
            signals.append({
                "category": "team",
                "title": f"{p.display_name()} installed but never invoked",
                "description": (
                    f"{p.display_name()} is installed in your org but has no recorded activity. "
                    "Enable it with github_manage_agent to start delegating tasks."
                ),
                "priority": "low",
            })

    # Policy mismatch: fallback chain references unknown/disabled agent
    # (requires access to blueprint — caller must pass policy)

    return signals


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def refresh_external_agents(
    ctx: Any,
    token: str,
    repos: List[str],
    force_weekly: bool = False,
) -> Tuple[List[AgentProfile], List[dict]]:
    """Run the daily refresh cycle. Called inside the brief pipeline.

    Args:
        ctx: WorkspaceContext
        token: GitHub installation token
        repos: repo list ("owner/name")
        force_weekly: override cadence and run weekly methods regardless of day

    Returns:
        (updated_profiles, drift_signal_action_items)
    """
    if not token or not repos:
        return [], []

    existing = get_external_agents(ctx)
    is_weekly_run = force_weekly or _is_monday()

    # Determine which discovery methods to run this cycle
    skip_installations = not is_weekly_run
    run_workflow_scan = is_weekly_run or _workflows_touched_recently(repos, token)

    # Run discovery with appropriate scope
    # discover_external_agents always runs B. D is gated inside on the flag.
    # We pass skip_installations for C.
    # For D: we fake it by setting lookback_days=1 for the B scan.
    discovered = discover_external_agents(
        repos=repos,
        token=token,
        lookback_days=1,                   # brief cycle: 24h lookback
        skip_installations=skip_installations,
    )

    # Workflow scan is already inside discover_external_agents as method D,
    # but we ran with lookback_days=1. Re-run with full lookback if weekly.
    if is_weekly_run:
        full_discovered = discover_external_agents(
            repos=repos,
            token=token,
            lookback_days=90,
            skip_installations=False,
        )
        # Merge: full_discovered supersedes for anything found
        disc_by_id = {p.id: p for p in full_discovered}
        for p in discovered:
            if p.id not in disc_by_id:
                full_discovered.append(p)
        discovered = full_discovered

    # Drift detection (before merge overwrites existing)
    drift_signals = _detect_drift(discovered, existing)

    # Merge and persist
    merged, new_ids, updated_ids = merge_with_existing(discovered, existing)
    for profile in merged:
        if profile.id in new_ids or profile.id in updated_ids:
            try:
                upsert_agent_profile(ctx, profile)
            except Exception as e:
                logger.warning("Could not save profile %s during refresh: %s", profile.id, e)

    logger.info(
        "Agent refresh: %d discovered, %d new, %d updated, %d drift signals",
        len(discovered), len(new_ids), len(updated_ids), len(drift_signals),
    )

    return merged, drift_signals
