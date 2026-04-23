"""PR watcher — GitHub issue #14.

After Dash files a delegation issue, the target agent produces a PR. This
module detects the PR, evaluates acceptance criteria against the diff, posts
a structured review comment, and updates the originating issue's checkboxes.

Key functions:
  link_pr_to_task(task_info, repo, token)        → pr_number or None
  review_pr_against_criteria(pr_info, criteria, token) → ReviewResult
  post_review_comment(repo, pr_number, result, token)  → comment_url or None
  update_issue_checkboxes(repo, issue_number, result, token) → ok
  watch_repo_delegations(repo, token)            → List[WatchResult]
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent_fleet.delegation import parse_dash_metadata, is_dash_issue

logger = logging.getLogger(__name__)

# Number of PR candidates to check per delegation issue
MAX_PR_CANDIDATES = 10
# Max diff bytes we'll load (keep context windows sane)
MAX_DIFF_BYTES = 100_000


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class TaskStatus:
    DELEGATED = "delegated"
    IN_PROGRESS = "in_progress"
    PR_OPENED = "pr_opened"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    STALLED = "stalled"
    RESOLVED = "resolved"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CriterionResult:
    text: str
    status: str   # "met" | "unmet" | "unclear"
    reasoning: str = ""


@dataclass
class ReviewResult:
    verdict: str                                        # "approve" | "request_changes" | "needs_human"
    criteria: List[CriterionResult] = field(default_factory=list)
    summary: str = ""
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None


@dataclass
class WatchResult:
    issue_number: int
    task_id: str
    agent_id: str
    status: str
    pr_number: Optional[int] = None
    review: Optional[ReviewResult] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def _gh(method: str, path: str, token: str, body: dict = None, timeout: int = 30):
    url = "https://api.github.com" + (path if path.startswith("/") else "/" + path)
    data = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Dash-PM-Watcher",
    }
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            bt = e.read().decode("utf-8")
            return e.code, (json.loads(bt) if bt else None)
        except Exception:
            return e.code, None
    except Exception as exc:
        logger.debug("GitHub request failed: %s — %s", path, exc)
        return 0, None


def _gh_diff(repo: str, pr_number: int, token: str) -> str:
    """Fetch the unified diff for a PR (raw text)."""
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3.diff",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Dash-PM-Watcher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read(MAX_DIFF_BYTES).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Diff fetch failed for PR %s#%s: %s", repo, pr_number, exc)
        return ""


# ---------------------------------------------------------------------------
# PR linking
# ---------------------------------------------------------------------------

_CLOSES_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
    re.IGNORECASE,
)


def _pr_links_issue(pr_body: str, issue_number: int) -> bool:
    """True if the PR body links (Closes/Fixes/Resolves #N) to the issue."""
    for m in _CLOSES_RE.finditer(pr_body or ""):
        if int(m.group(1)) == issue_number:
            return True
    return False


def link_pr_to_task(
    issue_number: int,
    repo: str,
    agent_bot_usernames: Tuple[str, ...],
    token: str,
    issue_created_at: str = "",
) -> Optional[int]:
    """Find the PR that was created in response to a delegation issue.

    Three detection paths (per issue #14 spec):
    1. Issue timeline cross-referenced events where source is a PR
    2. PRs whose body contains 'Closes #<issue_number>'
    3. PRs opened by the agent's known bot username after the issue was created
    """
    # Path 1: timeline cross-references
    status, timeline = _gh("GET", f"/repos/{repo}/issues/{issue_number}/timeline?per_page=100", token)
    if status == 200 and isinstance(timeline, list):
        for event in timeline:
            if event.get("event") != "cross-referenced":
                continue
            source = event.get("source") or {}
            issue_data = source.get("issue") or {}
            if issue_data.get("pull_request"):
                return issue_data.get("number")

    # Path 2: PRs whose body links this issue
    status, prs_data = _gh("GET", f"/repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page={MAX_PR_CANDIDATES}", token)
    if status == 200 and isinstance(prs_data, list):
        for pr in prs_data:
            if _pr_links_issue(pr.get("body") or "", issue_number):
                return pr.get("number")

    # Path 3: PRs by bot user after issue creation
    if status == 200 and isinstance(prs_data, list) and agent_bot_usernames:
        for pr in prs_data:
            author_login = (pr.get("user") or {}).get("login", "").lower()
            if any(author_login == b.lower() for b in agent_bot_usernames):
                if not issue_created_at or (pr.get("created_at", "") >= issue_created_at):
                    return pr.get("number")

    return None


# ---------------------------------------------------------------------------
# Criteria evaluation (heuristic — no LLM dependency)
# ---------------------------------------------------------------------------

def _evaluate_criterion(criterion: str, diff: str, pr_body: str) -> CriterionResult:
    """Heuristic evaluation of a single acceptance criterion against a diff.

    Uses keyword matching as a lightweight proxy for semantic evaluation.
    Callers can swap this for an LLM call if desired.

    Verdict heuristic:
    - "met" if key nouns from the criterion appear in the diff or PR body
    - "unclear" if only found in PR body (mentioned but can't confirm in code)
    - "unmet" if not found at all
    """
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", criterion.lower())
    if not words:
        return CriterionResult(text=criterion, status="unclear", reasoning="Empty criterion.")

    in_diff = sum(1 for w in words if w in diff.lower())
    in_body = sum(1 for w in words if w in pr_body.lower())
    coverage = in_diff / len(words) if words else 0.0

    if coverage >= 0.5:
        return CriterionResult(
            text=criterion,
            status="met",
            reasoning=f"{in_diff}/{len(words)} key terms found in diff.",
        )
    elif in_body > 0:
        return CriterionResult(
            text=criterion,
            status="unclear",
            reasoning="Terms referenced in PR description but not clearly visible in diff.",
        )
    else:
        return CriterionResult(
            text=criterion,
            status="unmet",
            reasoning=f"Only {in_diff}/{len(words)} key terms found in diff.",
        )


def review_pr_against_criteria(
    pr_number: int,
    repo: str,
    criteria: List[str],
    token: str,
    pr_body: str = "",
) -> ReviewResult:
    """Evaluate each acceptance criterion against the PR diff.

    Returns a ReviewResult with per-criterion status and overall verdict:
    - approve           → all criteria met
    - request_changes   → ≥1 criterion unmet
    - needs_human       → ≥1 criterion unclear AND no unmet ones (ambiguous)
    """
    diff = _gh_diff(repo, pr_number, token)
    status, pr_data = _gh("GET", f"/repos/{repo}/pulls/{pr_number}", token)
    pr_url = (pr_data or {}).get("html_url") if status == 200 else None

    if not pr_body and status == 200 and pr_data:
        pr_body = pr_data.get("body") or ""

    results: List[CriterionResult] = []
    for c in criteria:
        results.append(_evaluate_criterion(c, diff, pr_body))

    met = sum(1 for r in results if r.status == "met")
    unmet = sum(1 for r in results if r.status == "unmet")
    unclear = sum(1 for r in results if r.status == "unclear")

    if unmet > 0:
        verdict = "request_changes"
        summary = f"{met} of {len(criteria)} criteria met; {unmet} unmet, {unclear} unclear."
    elif unclear > 0:
        verdict = "needs_human"
        summary = f"All {met} verifiable criteria appear met, but {unclear} could not be confirmed from diff alone."
    else:
        verdict = "approve"
        summary = f"All {len(criteria)} criteria appear met."

    return ReviewResult(
        verdict=verdict,
        criteria=results,
        summary=summary,
        pr_number=pr_number,
        pr_url=pr_url,
    )


# ---------------------------------------------------------------------------
# Review comment + checkbox update
# ---------------------------------------------------------------------------

def _build_review_comment(result: ReviewResult, issue_number: int) -> str:
    """Format a structured review comment (single comment per review round)."""
    verdict_emoji = {"approve": "✅", "request_changes": "🔄", "needs_human": "🧑‍⚖️"}.get(result.verdict, "")
    lines = [
        f"## Dash Review {verdict_emoji}",
        "",
        f"**Verdict**: {result.verdict.replace('_', ' ').title()}",
        f"**Summary**: {result.summary}",
        "",
        "### Acceptance Criteria",
    ]
    for cr in result.criteria:
        icon = {"met": "✅", "unmet": "❌", "unclear": "❓"}.get(cr.status, "•")
        lines.append(f"- {icon} **{cr.text}**")
        if cr.reasoning:
            lines.append(f"  _{cr.reasoning}_")
    lines.append("")
    lines.append(f"_Originating task: #{issue_number}_")
    return "\n".join(lines)


def _update_checkbox_line(line: str, criterion_text: str, checked: bool) -> str:
    """Replace '- [ ]' with '- [x]' (or back) for a matching criterion line."""
    norm_line = line.strip().lstrip("- ").lstrip("[x]").lstrip("[ ]").strip().lower()
    norm_crit = criterion_text.strip().lower()
    if norm_crit in norm_line or norm_line in norm_crit:
        if checked:
            return re.sub(r"\[ \]", "[x]", line)
        else:
            return re.sub(r"\[x\]", "[ ]", line, flags=re.IGNORECASE)
    return line


def post_review_comment(
    repo: str,
    pr_number: int,
    result: ReviewResult,
    issue_number: int,
    token: str,
) -> Optional[str]:
    """Post the review comment on the PR. Returns comment URL or None."""
    body = _build_review_comment(result, issue_number)
    status, data = _gh(
        "POST",
        f"/repos/{repo}/issues/{pr_number}/comments",
        token,
        body={"body": body},
    )
    if status == 201 and isinstance(data, dict):
        return data.get("html_url")
    logger.warning("Failed to post review comment: HTTP %s", status)
    return None


def update_issue_checkboxes(
    repo: str,
    issue_number: int,
    result: ReviewResult,
    token: str,
) -> bool:
    """Tick or un-tick acceptance criteria checkboxes in the original issue body."""
    status, issue_data = _gh("GET", f"/repos/{repo}/issues/{issue_number}", token)
    if status != 200 or not isinstance(issue_data, dict):
        return False

    body = issue_data.get("body") or ""
    if not body:
        return False

    new_lines = []
    for line in body.splitlines():
        if "- [ ]" not in line and "- [x]" not in line.lower():
            new_lines.append(line)
            continue
        updated = line
        for cr in result.criteria:
            updated = _update_checkbox_line(updated, cr.text, cr.status == "met")
        new_lines.append(updated)

    new_body = "\n".join(new_lines)
    if new_body == body:
        return True  # nothing changed, still OK

    status2, _ = _gh("PATCH", f"/repos/{repo}/issues/{issue_number}", token, body={"body": new_body})
    return status2 == 200


# ---------------------------------------------------------------------------
# Full watch loop for a repo
# ---------------------------------------------------------------------------

def watch_repo_delegations(repo: str, token: str) -> List[WatchResult]:
    """Scan a repo for open Dash delegation issues, link PRs, post reviews.

    Returns one WatchResult per delegation issue found.
    """
    from agent_fleet.delegation import find_dash_issues
    from agent_fleet.registry import lookup

    issues = find_dash_issues(repo, token, state="open")
    results: List[WatchResult] = []

    for issue in issues:
        issue_number = issue["number"]
        task_id = issue["task_id"]
        agent_id = issue["agent_id"]

        agent = lookup(agent_id)
        bot_usernames = agent.bot_usernames if agent else ()

        pr_number = link_pr_to_task(
            issue_number=issue_number,
            repo=repo,
            agent_bot_usernames=bot_usernames,
            token=token,
            issue_created_at=issue.get("created_at", ""),
        )

        if pr_number is None:
            results.append(WatchResult(
                issue_number=issue_number,
                task_id=task_id,
                agent_id=agent_id,
                status=TaskStatus.DELEGATED,
            ))
            continue

        # Get acceptance criteria from the issue body
        status, issue_data = _gh("GET", f"/repos/{repo}/issues/{issue_number}", token)
        criteria: List[str] = []
        if status == 200 and isinstance(issue_data, dict):
            body = issue_data.get("body") or ""
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
                    text = re.sub(r"^- \[[ x]\]\s*", "", stripped)
                    criteria.append(text)

        if not criteria:
            results.append(WatchResult(
                issue_number=issue_number,
                task_id=task_id,
                agent_id=agent_id,
                status=TaskStatus.PR_OPENED,
                pr_number=pr_number,
                error="No acceptance criteria found in issue body.",
            ))
            continue

        review = review_pr_against_criteria(
            pr_number=pr_number,
            repo=repo,
            criteria=criteria,
            token=token,
        )

        # Post review comment (idempotent: could check for existing comment, simplified here)
        comment_url = post_review_comment(repo, pr_number, review, issue_number, token)

        # Update checkboxes in originating issue
        update_issue_checkboxes(repo, issue_number, review, token)

        status_map = {
            "approve": TaskStatus.APPROVED,
            "request_changes": TaskStatus.CHANGES_REQUESTED,
            "needs_human": TaskStatus.REVIEWED,
        }
        task_status = status_map.get(review.verdict, TaskStatus.REVIEWED)

        results.append(WatchResult(
            issue_number=issue_number,
            task_id=task_id,
            agent_id=agent_id,
            status=task_status,
            pr_number=pr_number,
            review=review,
        ))

    return results
