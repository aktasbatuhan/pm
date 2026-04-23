"""Invocation learning — GitHub issue #12.

Derives how a specific tenant actually invokes each coding agent by walking
GitHub issue/PR timelines and finding the trigger event that preceded each
bot activation.

Public entry point:
    learn_invocation_pattern(profile, repos, token) -> AgentProfile

The function does NOT write to the blueprint; the calling tool does that.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from agent_fleet.registry import lookup as registry_lookup, find_by_bot_username
from agent_fleet.profile import (
    AgentProfile,
    ObservedInvocation,
    ObservedInvocationDetail,
)

logger = logging.getLogger(__name__)

# How many bot-authored PRs to examine per agent per repo
MAX_PRS_PER_REPO = 20
# How far to look back (seconds) before a bot event to find its trigger
TRIGGER_WINDOW_SECONDS = 3600 * 24 * 7  # 7 days


# ---------------------------------------------------------------------------
# HTTP client (mirrors discovery.py — no shared module to avoid coupling)
# ---------------------------------------------------------------------------

def _gh(method: str, path: str, token: str, timeout: int = 20) -> Tuple[int, Optional[object]]:
    url = "https://api.github.com" + (path if path.startswith("/") else "/" + path)
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Dash-PM-Invocation",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode("utf-8")
            return e.code, (json.loads(body_text) if body_text else None)
        except Exception:
            return e.code, None
    except Exception as exc:
        logger.debug("GitHub request failed: %s %s — %s", method, path, exc)
        return 0, None


def _gh_paginate(path: str, token: str, max_pages: int = 5) -> List[dict]:
    results: List[dict] = []
    sep = "&" if "?" in path else "?"
    for page in range(1, max_pages + 1):
        status, data = _gh("GET", f"{path}{sep}per_page=100&page={page}", token)
        if status == 403 or status == 404:
            break
        if status == 422:
            logger.debug("422 on %s — skipping", path)
            break
        # Respect secondary rate limit
        if status == 429:
            logger.warning("Rate-limited on %s — stopping pagination", path)
            break
        if status != 200 or not data:
            break
        items = data if isinstance(data, list) else data.get("items", [])
        results.extend(items)
        if len(items) < 100:
            break
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLOSES_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
    re.IGNORECASE,
)


def _extract_issue_numbers_from_body(body: str) -> List[int]:
    """Parse 'Closes #123', 'Fixes #456', etc. from a PR body."""
    if not body:
        return []
    return [int(m) for m in _CLOSES_RE.findall(body)]


def _is_bot(login: str, bot_usernames: Tuple[str, ...]) -> bool:
    login_lower = (login or "").lower()
    return any(login_lower == b.lower() for b in bot_usernames)


def _parse_ts(ts: Optional[str]) -> float:
    """ISO8601 → unix float. Returns 0 on failure."""
    if not ts:
        return 0.0
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Timeline event classification
# ---------------------------------------------------------------------------

InvocationType = str  # "comment_mention" | "issue_assignment" | "label" | "workflow_trigger"


def _classify_trigger(event: dict, agent: "KnownAgent") -> Optional[Tuple[InvocationType, dict]]:  # type: ignore[name-defined]  # noqa: F821
    """Try to classify a timeline event as a trigger for this agent.

    Returns (invocation_type, metadata_dict) or None if not a trigger.
    """
    etype = event.get("event", "")
    actor = (event.get("actor") or {}).get("login", "")

    # Skip events by the bot itself
    if _is_bot(actor, agent.bot_usernames):
        return None

    if etype == "commented":
        body = (event.get("body") or "").lower()
        for inv in agent.documented_invocations:
            if inv.type == "comment_mention" and inv.syntax:
                if inv.syntax.lower() in body:
                    return "comment_mention", {"syntax": inv.syntax}
        # Generic @mention of any known bot username
        for bot in agent.bot_usernames:
            handle = "@" + bot.replace("[bot]", "").lower()
            if handle in body:
                return "comment_mention", {"syntax": handle}

    elif etype == "labeled":
        label_name = (event.get("label") or {}).get("name", "").lower()
        for inv in agent.documented_invocations:
            if inv.type == "label" and inv.label and inv.label.lower() == label_name:
                return "label", {"label": label_name}
        # Any label matching a bot's documented label
        if label_name in {(inv.label or "").lower() for inv in agent.documented_invocations if inv.type == "label"}:
            return "label", {"label": label_name}

    elif etype == "assigned":
        assignee = (event.get("assignee") or {}).get("login", "").lower()
        if _is_bot(assignee, agent.bot_usernames):
            return "issue_assignment", {}

    elif etype == "cross-referenced":
        # A workflow might cross-reference via automation
        source = event.get("source") or {}
        if source.get("type") == "workflow_run":
            return "workflow_trigger", {}

    return None


# ---------------------------------------------------------------------------
# Core algorithm: find trigger for a single issue/PR
# ---------------------------------------------------------------------------

def _find_trigger_for_issue(
    repo: str,
    issue_number: int,
    agent: "KnownAgent",  # type: ignore[name-defined]  # noqa: F821
    bot_first_active_ts: float,
    token: str,
) -> Optional[Tuple[InvocationType, dict]]:
    """Walk the timeline of issue_number and find the trigger closest before
    the bot's first activity (within TRIGGER_WINDOW_SECONDS).

    Returns (invocation_type, metadata) or None.
    """
    status, timeline = _gh(
        "GET",
        f"/repos/{repo}/issues/{issue_number}/timeline?per_page=100",
        token,
    )
    if status != 200 or not isinstance(timeline, list):
        return None

    best_trigger: Optional[Tuple[InvocationType, dict]] = None
    best_ts: float = 0.0

    for event in timeline:
        ts = _parse_ts(event.get("created_at") or event.get("submitted_at"))
        if ts == 0.0:
            continue
        # Only consider events BEFORE the bot acted and within the window
        if ts >= bot_first_active_ts:
            continue
        if bot_first_active_ts - ts > TRIGGER_WINDOW_SECONDS:
            continue
        result = _classify_trigger(event, agent)
        if result and ts > best_ts:
            best_trigger = result
            best_ts = ts

    return best_trigger


# ---------------------------------------------------------------------------
# Per-agent learning
# ---------------------------------------------------------------------------

def _learn_for_agent(
    profile: AgentProfile,
    repos: List[str],
    token: str,
) -> Dict[str, int]:
    """Scan repos for bot-authored PRs, find their triggers, return counts.

    Returns invocation type → count map.
    """
    agent = registry_lookup(profile.id)
    if agent is None:
        logger.debug("No registry entry for %s — skipping invocation learning", profile.id)
        return {}

    counts: Dict[str, int] = defaultdict(int)

    for repo in repos:
        # Find PRs authored by any of the agent's bot usernames
        prs: List[dict] = []
        for bot_login in agent.bot_usernames:
            clean = bot_login.replace("[bot]", "")
            found = _gh_paginate(
                f"/repos/{repo}/pulls?state=all&sort=created&direction=desc",
                token,
                max_pages=2,
            )
            for pr in found:
                author_login = (pr.get("user") or {}).get("login", "")
                if author_login.lower() == bot_login.lower():
                    prs.append(pr)
            # Also search via the API search endpoint (more efficient for busy repos)
            status, search_data = _gh(
                "GET",
                f"/search/issues?q=repo:{repo}+is:pr+author:app/{clean}&per_page={MAX_PRS_PER_REPO}",
                token,
            )
            if status == 200 and isinstance(search_data, dict):
                for item in (search_data.get("items") or []):
                    prs.append(item)

        seen_prs: set = set()
        for pr in prs[:MAX_PRS_PER_REPO]:
            pr_number = pr.get("number")
            if not pr_number or pr_number in seen_prs:
                continue
            seen_prs.add(pr_number)

            # Get the bot's first activity timestamp on this PR
            bot_first_ts = _parse_ts(pr.get("created_at"))

            # Try to find linked issue(s)
            pr_body = pr.get("body") or ""
            linked_issues = _extract_issue_numbers_from_body(pr_body)

            # Also check PR timeline for cross-references
            if not linked_issues:
                status2, pr_timeline = _gh(
                    "GET",
                    f"/repos/{repo}/issues/{pr_number}/timeline?per_page=50",
                    token,
                )
                if status2 == 200 and isinstance(pr_timeline, list):
                    for ev in pr_timeline:
                        if ev.get("event") == "cross-referenced":
                            src_issue = (ev.get("source") or {}).get("issue") or {}
                            num = src_issue.get("number")
                            if num:
                                linked_issues.append(int(num))

            # Check both the PR itself and any linked issue for trigger
            candidates = [pr_number] + linked_issues
            for issue_num in candidates[:3]:  # cap to avoid excessive API calls
                trigger = _find_trigger_for_issue(
                    repo=repo,
                    issue_number=issue_num,
                    agent=agent,
                    bot_first_active_ts=bot_first_ts,
                    token=token,
                )
                if trigger:
                    inv_type, meta = trigger
                    counts[inv_type] += 1
                    logger.debug(
                        "Agent %s triggered via %s on %s#%s",
                        profile.id, inv_type, repo, issue_num,
                    )
                    break  # found trigger for this PR, move on

        if counts:
            logger.debug("Repo %s: %s → %s", repo, profile.id, dict(counts))

    return dict(counts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def learn_invocation_pattern(
    profile: AgentProfile,
    repos: List[str],
    token: str,
) -> AgentProfile:
    """Learn how this tenant invokes an agent from real PR/issue timeline data.

    Returns a new AgentProfile with updated `observed_invocation` and
    `confidence`. All other fields are preserved.

    Confidence rules (from issue #12 spec):
    - high   if primary has ≥ 5 occurrences AND ≥ 70% share
    - medium if primary has ≥ 3 occurrences
    - low    otherwise — fall back to registry default_invocation
    """
    if not token:
        return profile

    counts = _learn_for_agent(profile, repos, token)
    if not counts:
        logger.info("No invocation data found for %s", profile.id)
        return profile

    total = sum(counts.values())
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    primary_type, primary_count = sorted_items[0]
    primary_share = primary_count / total if total else 0.0

    # Confidence
    if primary_count >= 5 and primary_share >= 0.70:
        confidence = "high"
    elif primary_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    slots: List[Optional[ObservedInvocationDetail]] = [None, None, None]
    for i, (inv_type, count) in enumerate(sorted_items[:3]):
        slots[i] = ObservedInvocationDetail(type=inv_type, count=count)

    observed = ObservedInvocation(primary=slots[0], secondary=slots[1], rare=slots[2])

    import dataclasses
    updated = dataclasses.replace(
        profile,
        observed_invocation=observed,
        confidence=confidence,
    )
    return updated
