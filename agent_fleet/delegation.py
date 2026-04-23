"""Delegation issue template — GitHub issue #13.

When Dash delegates a coding task to an external agent via GitHub, it files
a structured issue. This module handles:

  - build_delegation_issue(task, profile)  → (title, body, post_create_actions)
  - parse_dash_metadata(body)             → dict of embedded metadata
  - find_dash_issues(repo, token)         → list of open Dash-authored issues
  - dispatch_post_create_actions(repo, issue_number, actions, token) → run label/assign

The issue body carries a machine-parseable HTML comment header so the PR
watcher (#14) can reliably identify and track delegation tasks.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent_fleet.profile import AgentProfile

logger = logging.getLogger(__name__)

# Version of the Dash delegation issue format.  Bump on breaking schema changes.
DELEGATION_FORMAT_VERSION = "v1"

# Regex to extract the metadata comment block from an issue body.
_META_PATTERN = re.compile(
    r"<!--\s*dash-delegation:\s*(?P<version>\S+)\s*-->\s*"
    r"<!--\s*dash-task-id:\s*(?P<task_id>[^\s>]+)\s*-->\s*"
    r"<!--\s*dash-agent:\s*(?P<agent_id>[^\s>]+)\s*-->\s*"
    r"<!--\s*dash-created-at:\s*(?P<created_at>[^\s>]+)\s*-->",
    re.DOTALL,
)

# Regex to scan a listing of issues looking for Dash metadata
_META_PRESENT = re.compile(r"<!--\s*dash-delegation:")


# ---------------------------------------------------------------------------
# Task descriptor (what the agent passes to build_delegation_issue)
# ---------------------------------------------------------------------------

@dataclass
class DelegationTask:
    title: str                        # Short goal statement (becomes issue title suffix)
    problem: str                      # One-paragraph problem statement
    acceptance_criteria: List[str]    # Checklist items (without '- [ ]' prefix)
    context: str = ""                 # Free text: relevant files, links, related issues
    constraints: str = ""             # Style, perf, API-compat constraints
    repo: str = ""                    # "owner/name" — where to file the issue
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "problem": self.problem,
            "acceptance_criteria": self.acceptance_criteria,
            "context": self.context,
            "constraints": self.constraints,
            "repo": self.repo,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Post-create actions
# ---------------------------------------------------------------------------

@dataclass
class PostCreateAction:
    kind: str          # "add_label" | "assign" | "comment"
    payload: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Template builder
# ---------------------------------------------------------------------------

def build_delegation_issue(
    task: DelegationTask,
    profile: AgentProfile,
) -> Tuple[str, str, List[PostCreateAction]]:
    """Build the issue title, body, and post-create actions for a delegation.

    Returns:
        (title, body, post_create_actions)

    The title is formatted as:  [Dash] <task.title>
    The body contains:
      - HTML comment metadata block (machine-parseable)
      - ## Problem
      - ## Acceptance Criteria  (checkboxes)
      - ## Context
      - ## Constraints
      - ## Output expected
      - Invocation line (at bottom, driven by learned/registry pattern)
    """
    inv_type, syntax, label = profile.effective_invocation()
    post_create: List[PostCreateAction] = []

    # Build invocation section
    invocation_line = _build_invocation_line(inv_type, syntax, profile, post_create)

    # Acceptance criteria checkboxes
    criteria_md = "\n".join(f"- [ ] {c.strip()}" for c in task.acceptance_criteria)

    # Metadata comment block
    meta_block = (
        f"<!-- dash-delegation: {DELEGATION_FORMAT_VERSION} -->\n"
        f"<!-- dash-task-id: {task.task_id} -->\n"
        f"<!-- dash-agent: {profile.id} -->\n"
        f"<!-- dash-created-at: {task.created_at} -->"
    )

    body_parts = [meta_block, ""]

    body_parts.append("## Problem")
    body_parts.append(task.problem.strip())
    body_parts.append("")

    body_parts.append("## Acceptance Criteria")
    body_parts.append(criteria_md)
    body_parts.append("")

    if task.context.strip():
        body_parts.append("## Context")
        body_parts.append(task.context.strip())
        body_parts.append("")

    if task.constraints.strip():
        body_parts.append("## Constraints")
        body_parts.append(task.constraints.strip())
        body_parts.append("")

    body_parts.append("## Output expected")
    body_parts.append("- A pull request against the default branch")
    body_parts.append("- Linked back to this issue via \"Closes #<this issue number>\"")

    if invocation_line:
        body_parts.append("")
        body_parts.append("---")
        body_parts.append("<!-- invocation -->")
        body_parts.append(invocation_line)

    title = f"[Dash] {task.title.strip()}"
    body = "\n".join(body_parts)
    return title, body, post_create


def _build_invocation_line(
    inv_type: str,
    syntax: Optional[str],
    profile: AgentProfile,
    post_create: List[PostCreateAction],
) -> str:
    """Return the inline invocation string and populate post_create actions."""

    if inv_type == "comment_mention":
        handle = syntax or f"@{profile.id}"
        return f"{handle} please take this on"

    elif inv_type == "label":
        from agent_fleet.registry import lookup
        agent = lookup(profile.id)
        label_name = None
        if agent:
            for inv in agent.documented_invocations:
                if inv.type == "label" and inv.label:
                    label_name = inv.label
                    break
        # Also check observed invocation
        obs = profile.observed_invocation
        if obs.primary and obs.primary.type == "label" and obs.primary.label:
            label_name = obs.primary.label
        if label_name:
            post_create.append(PostCreateAction(kind="add_label", payload={"label": label_name}))
        return ""  # label is applied post-create, no inline text needed

    elif inv_type == "issue_assignment":
        from agent_fleet.registry import lookup
        agent = lookup(profile.id)
        if agent and agent.bot_usernames:
            bot = agent.bot_usernames[0].replace("[bot]", "")
            post_create.append(PostCreateAction(kind="assign", payload={"assignee": bot}))
        return ""

    elif inv_type == "workflow_trigger":
        return ""  # workflow picks up on issue creation event automatically

    else:
        return ""  # "none" or unknown — no invocation


# ---------------------------------------------------------------------------
# Metadata parsing
# ---------------------------------------------------------------------------

def parse_dash_metadata(body: str) -> Optional[Dict[str, str]]:
    """Extract the machine-readable metadata from a Dash-authored issue body.

    Returns a dict with keys: version, task_id, agent_id, created_at
    or None if the body doesn't contain Dash metadata.
    """
    if not body:
        return None
    m = _META_PATTERN.search(body)
    if not m:
        return None
    return {
        "version": m.group("version"),
        "task_id": m.group("task_id"),
        "agent_id": m.group("agent_id"),
        "created_at": m.group("created_at"),
    }


def is_dash_issue(body: str) -> bool:
    """Quick check — does this issue body contain Dash metadata?"""
    return bool(body and _META_PRESENT.search(body))


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def _gh(method: str, path: str, token: str, body: dict = None, timeout: int = 20):
    url = "https://api.github.com" + (path if path.startswith("/") else "/" + path)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Dash-PM-Delegation",
            **({"Content-Type": "application/json"} if data else {}),
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
        logger.debug("GitHub request failed: %s — %s", path, exc)
        return 0, None


def find_dash_issues(repo: str, token: str, state: str = "open") -> List[Dict[str, Any]]:
    """Return all Dash-authored delegation issues in a repo.

    Uses the GitHub search API to find issues whose body contains the
    metadata marker, then filters client-side.  Returns a list of dicts:
    {number, title, state, task_id, agent_id, created_at, url}.
    """
    status, data = _gh(
        "GET",
        f"/search/issues?q=repo:{repo}+is:issue+state:{state}+%22dash-delegation%22&per_page=100",
        token,
    )
    if status != 200 or not isinstance(data, dict):
        return []

    results = []
    for item in (data.get("items") or []):
        body = item.get("body") or ""
        meta = parse_dash_metadata(body)
        if not meta:
            continue
        results.append({
            "number": item.get("number"),
            "title": item.get("title"),
            "state": item.get("state"),
            "url": item.get("html_url"),
            "task_id": meta["task_id"],
            "agent_id": meta["agent_id"],
            "created_at": meta["created_at"],
        })
    return results


def dispatch_post_create_actions(
    repo: str,
    issue_number: int,
    actions: List[PostCreateAction],
    token: str,
) -> List[Dict[str, Any]]:
    """Run post-create actions (add label, assign) after an issue is filed.

    Returns list of {action, ok, detail} for each action attempted.
    """
    results = []
    for action in actions:
        if action.kind == "add_label":
            label = action.payload.get("label", "")
            status, resp = _gh(
                "POST",
                f"/repos/{repo}/issues/{issue_number}/labels",
                token,
                body={"labels": [label]},
            )
            results.append({"action": f"add_label:{label}", "ok": status in (200, 201), "detail": resp})

        elif action.kind == "assign":
            assignee = action.payload.get("assignee", "")
            status, resp = _gh(
                "POST",
                f"/repos/{repo}/issues/{issue_number}/assignees",
                token,
                body={"assignees": [assignee]},
            )
            results.append({"action": f"assign:{assignee}", "ok": status in (200, 201), "detail": resp})

        elif action.kind == "comment":
            body_text = action.payload.get("body", "")
            status, resp = _gh(
                "POST",
                f"/repos/{repo}/issues/{issue_number}/comments",
                token,
                body={"body": body_text},
            )
            results.append({"action": "comment", "ok": status == 201, "detail": resp})

    return results
