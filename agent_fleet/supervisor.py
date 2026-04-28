"""Per-tenant issue-lifecycle orchestrator.

Reads the active workflow contract for a tenant, walks every Dash-tagged
issue across the tenant's connected repos, and drives the state machine
by delegating to the existing primitives in `agent_fleet/`.

Design goals:
  - Idempotent: safe to run on a cron every 10-15 min. No duplicate reviews,
    no double-closes, no spammy re-pings.
  - Defensive: any exception inside an action is logged and absorbed.
    The cron must keep advancing the queue even when a single delegation
    misbehaves.
  - Observable: returns a structured SupervisorReport so the caller can
    surface a summary in the brief or settings UI.

State coverage:
  PR opened + unreviewed         → auto-review (skip if Dash already reviewed)
  Resolved (PR merged)           → run on_merged hooks (close_dash_issue,
                                   resolve_brief_action)
  Delegated + stale (phase 2.5)  → evaluate_task_health → re-ping or mark stalled
  Changes requested (phase 2.5)  → post structured feedback comment to the agent,
                                   tracked toward review.max_retries
  Approved (phase 2.5)           → workflow.review.on_approve dispatch
                                   (comment | auto-merge)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from agent_fleet.delegation import parse_dash_metadata
from agent_fleet.watcher import (
    TaskStatus,
    WatchResult,
    post_review_comment,
    review_pr_against_criteria,
    update_issue_checkboxes,
    watch_repo_delegations,
    _gh,
)
from agent_fleet.workflow import Workflow, default_workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action records (so callers can audit / surface in UI)
# ---------------------------------------------------------------------------


@dataclass
class SupervisorAction:
    repo: str
    issue_number: int
    kind: str               # auto_review | close_on_merge | resolve_brief_action | skip | error
    detail: str = ""        # human-readable summary
    error: Optional[str] = None


@dataclass
class SupervisorReport:
    tenant_id: str
    workflow_revision: int
    repos_scanned: int = 0
    delegations_seen: int = 0
    actions: List[SupervisorAction] = field(default_factory=list)

    def by_kind(self) -> dict:
        counts: dict = {}
        for a in self.actions:
            counts[a.kind] = counts.get(a.kind, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Helpers — markers used to detect prior Dash actions on a PR/issue
# ---------------------------------------------------------------------------

# Canonical headings dropped into comments so we can detect prior Dash
# actions on the next run and avoid double-commenting / spamming.
_DASH_REVIEW_MARKER = "## Dash Review"
_DASH_REPING_MARKER = "## Dash Re-ping"
_DASH_FEEDBACK_MARKER = "## Dash Feedback"
_DASH_STALLED_MARKER = "## Dash Stalled"


def _list_issue_comments(repo: str, issue_number: int, token: str) -> List[dict]:
    status, comments = _gh("GET", f"/repos/{repo}/issues/{issue_number}/comments", token)
    if status != 200 or not isinstance(comments, list):
        return []
    return comments


def _has_existing_dash_review(repo: str, pr_number: int, token: str) -> bool:
    """True if any issue comment on the PR already contains the Dash review marker."""
    return any(
        _DASH_REVIEW_MARKER in (c.get("body") or "")
        for c in _list_issue_comments(repo, pr_number, token)
    )


def _count_marker_comments(repo: str, issue_number: int, marker: str, token: str) -> int:
    """How many comments on this issue carry a given marker (e.g. re-pings, feedback)."""
    return sum(
        1 for c in _list_issue_comments(repo, issue_number, token)
        if marker in (c.get("body") or "")
    )


def _post_comment(repo: str, issue_number: int, body: str, token: str) -> bool:
    status, _ = _gh(
        "POST", f"/repos/{repo}/issues/{issue_number}/comments",
        token, body={"body": body},
    )
    return status in (200, 201)


def _merge_pr(repo: str, pr_number: int, token: str) -> Tuple[bool, str]:
    """Merge a PR via GitHub's merge endpoint. Returns (ok, detail)."""
    status, body = _gh(
        "PUT", f"/repos/{repo}/pulls/{pr_number}/merge",
        token, body={"merge_method": "squash"},
    )
    if status in (200, 201):
        return True, f"merged PR #{pr_number}"
    if status == 405:
        return False, f"PR #{pr_number} not mergeable (likely conflicts or branch protection)"
    return False, f"merge failed: HTTP {status}"


def _close_issue(repo: str, issue_number: int, token: str) -> Tuple[bool, str]:
    """Close a GitHub issue. Idempotent: closing a closed issue is a no-op for us."""
    status, body = _gh(
        "PATCH", f"/repos/{repo}/issues/{issue_number}",
        token, body={"state": "closed", "state_reason": "completed"},
    )
    if status in (200, 201):
        return True, f"closed issue #{issue_number}"
    return False, f"close failed: HTTP {status}"


def _post_completion_comment(repo: str, issue_number: int, pr_number: Optional[int], token: str) -> None:
    """Drop a one-line audit trail comment when Dash auto-closes."""
    body = (
        "Dash closed this issue automatically: PR was merged "
        f"and review verdict was approve."
    )
    if pr_number:
        body = (
            f"Dash closed this issue automatically: PR #{pr_number} merged "
            "and review verdict was approve."
        )
    _gh("POST", f"/repos/{repo}/issues/{issue_number}/comments", token, body={"body": body})


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------

# Each handler signature: handler(ctx) -> SupervisorAction
# `ctx` is a dict the supervisor populates before dispatch.

def _hook_close_dash_issue(ctx: dict) -> SupervisorAction:
    repo = ctx["repo"]
    issue_number = ctx["issue_number"]
    token = ctx["token"]
    ok, detail = _close_issue(repo, issue_number, token)
    if ok:
        _post_completion_comment(repo, issue_number, ctx.get("pr_number"), token)
    return SupervisorAction(
        repo=repo, issue_number=issue_number,
        kind="close_dash_issue",
        detail=detail,
        error=None if ok else detail,
    )


def _hook_resolve_brief_action(ctx: dict) -> SupervisorAction:
    """If this delegation came from a brief action, mark it resolved."""
    repo = ctx["repo"]
    issue_number = ctx["issue_number"]
    brief_action_id = ctx.get("brief_action_id")
    if not brief_action_id:
        return SupervisorAction(
            repo=repo, issue_number=issue_number,
            kind="resolve_brief_action",
            detail="skipped (no brief_action_id in metadata)",
        )
    try:
        from backend.db.postgres_client import is_postgres_enabled
        from backend import repos as pg_repos
        if not is_postgres_enabled():
            return SupervisorAction(
                repo=repo, issue_number=issue_number,
                kind="resolve_brief_action",
                detail="skipped (Postgres disabled)",
            )
        ok = pg_repos.update_brief_action(
            ctx["tenant_id"], brief_action_id, status="resolved",
        )
        return SupervisorAction(
            repo=repo, issue_number=issue_number,
            kind="resolve_brief_action",
            detail=f"resolved brief_action {brief_action_id}" if ok
                   else f"brief_action {brief_action_id} not found",
        )
    except Exception as e:
        return SupervisorAction(
            repo=repo, issue_number=issue_number,
            kind="resolve_brief_action",
            detail="exception", error=str(e),
        )


_HOOK_HANDLERS = {
    "close_dash_issue": _hook_close_dash_issue,
    "resolve_brief_action": _hook_resolve_brief_action,
}


def _run_hooks(names: List[str], ctx: dict, report: SupervisorReport) -> None:
    """Run a list of named hooks, recording each result. Unknown names are
    logged and skipped — never crash the loop."""
    for name in names:
        handler = _HOOK_HANDLERS.get(name)
        if not handler:
            report.actions.append(SupervisorAction(
                repo=ctx["repo"], issue_number=ctx["issue_number"],
                kind="skip", detail=f"unknown hook: {name}",
            ))
            continue
        try:
            report.actions.append(handler(ctx))
        except Exception as e:
            logger.exception("hook %s crashed for %s#%s", name, ctx.get("repo"), ctx.get("issue_number"))
            report.actions.append(SupervisorAction(
                repo=ctx["repo"], issue_number=ctx["issue_number"],
                kind="error", detail=f"hook {name} crashed", error=str(e),
            ))


# ---------------------------------------------------------------------------
# Per-state handlers
# ---------------------------------------------------------------------------

def _handle_pr_opened(result: WatchResult, repo: str, token: str,
                     workflow: Workflow, report: SupervisorReport) -> None:
    """PR opened, never reviewed by Dash → auto-review (idempotent)."""
    if not workflow.review.auto:
        return
    if not result.pr_number:
        return
    if _has_existing_dash_review(repo, result.pr_number, token):
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail=f"PR #{result.pr_number} already has a Dash review",
        ))
        return

    # Pull acceptance criteria from the issue body. The watcher already does
    # this work in watch_repo_delegations but doesn't expose them on
    # WatchResult, so we re-fetch the issue. Cheap.
    status, issue = _gh("GET", f"/repos/{repo}/issues/{result.issue_number}", token)
    if status != 200 or not isinstance(issue, dict):
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="error", detail="couldn't refetch issue body",
            error=f"HTTP {status}",
        ))
        return
    body = issue.get("body") or ""
    criteria = re.findall(r"- \[ ?\]\s*(.+?)\s*$", body, re.MULTILINE)
    if not criteria:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail="no acceptance criteria found in issue body",
        ))
        return

    try:
        review = review_pr_against_criteria(result.pr_number, repo, criteria, token)
    except Exception as e:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="error", detail="review failed", error=str(e),
        ))
        return

    try:
        post_review_comment(repo, result.pr_number, review, result.issue_number, token)
        update_issue_checkboxes(repo, result.issue_number, review, token)
    except Exception as e:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="error", detail="couldn't post review", error=str(e),
        ))
        return

    report.actions.append(SupervisorAction(
        repo=repo, issue_number=result.issue_number,
        kind="auto_review",
        detail=f"PR #{result.pr_number}: verdict={review.verdict} "
               f"({sum(1 for c in review.criteria if c.status == 'met')}/"
               f"{len(review.criteria)} criteria met)",
    ))


def _handle_delegated(result: WatchResult, repo: str, token: str,
                     workflow: Workflow, report: SupervisorReport,
                     issue: dict) -> None:
    """No PR yet. Run the health check; re-ping if stale, mark stalled if we've
    given up. Re-files to a fallback agent are NOT done here — they're a
    separate, riskier action we surface explicitly rather than triggering
    on a 15-min cron."""
    from agent_fleet.escalation import (
        DelegationPolicy, HealthStatus, evaluate_task_health,
    )

    policy = DelegationPolicy(
        default_agent=workflow.routing.default,
        fallback_chain=workflow.escalation.fallback_chain,
        max_retries_per_agent=workflow.review.max_retries,
        stall_timeout_hours=workflow.escalation.stall_timeout_hours,
        auto_escalate=workflow.escalation.auto_escalate,
    )

    issue_url = issue.get("html_url") or ""
    title = issue.get("title") or ""
    created_at = issue.get("created_at") or ""

    # ping_count = number of Dash re-ping comments we've previously left.
    ping_count = _count_marker_comments(repo, result.issue_number, _DASH_REPING_MARKER, token)

    verdict = evaluate_task_health(
        task_status=result.status,
        agent_id=result.agent_id,
        issue_number=result.issue_number,
        issue_url=issue_url,
        task_title=title,
        created_at=created_at,
        last_activity_at=None,
        pr_number=None,
        pr_url=None,
        review_verdict=None,
        ping_count=ping_count,
        policy=policy,
    )

    if verdict.status == HealthStatus.OK:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail=f"on track ({verdict.reason})",
        ))
        return

    if verdict.status == HealthStatus.NUDGE:
        comment = (
            f"{_DASH_REPING_MARKER}\n\n"
            f"Hi @{result.agent_id} — checking in. "
            f"It's been {ping_count + 1} nudge(s); the issue is past the expected window. "
            f"Reason: {verdict.reason}\n\n"
            f"If you're blocked, reply with what you need."
        )
        ok = _post_comment(repo, result.issue_number, comment, token)
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="re_ping",
            detail=f"posted re-ping #{ping_count + 1}; {verdict.reason}",
            error=None if ok else "comment failed",
        ))
        return

    # STALLED: don't auto-refile; just record it once, surface to the user.
    if verdict.status == HealthStatus.STALLED:
        already_marked = _count_marker_comments(repo, result.issue_number, _DASH_STALLED_MARKER, token) > 0
        if already_marked:
            report.actions.append(SupervisorAction(
                repo=repo, issue_number=result.issue_number,
                kind="skip", detail="stalled; already flagged on a previous run",
            ))
            return
        next_agent = verdict.fallback_agent_id or "<no fallback>"
        comment = (
            f"{_DASH_STALLED_MARKER}\n\n"
            f"This delegation is stalled. {verdict.reason}\n\n"
            f"Suggested next step: re-file to **{next_agent}** "
            f"(via `github_delegate_task`) or close manually."
        )
        _post_comment(repo, result.issue_number, comment, token)
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="mark_stalled",
            detail=f"flagged stalled; suggested fallback: {next_agent}",
        ))
        return

    if verdict.status == HealthStatus.NEEDS_HUMAN:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="needs_human", detail=verdict.reason,
        ))
        return


def _handle_changes_requested(result: WatchResult, repo: str, token: str,
                             workflow: Workflow, report: SupervisorReport) -> None:
    """PR has request_changes from Dash review. Post a structured feedback
    comment mentioning the agent. Tracked toward review.max_retries via
    Dash Feedback markers; escalation past that limit is left to the user."""
    if not result.pr_number:
        return
    if not result.review or not result.review.criteria:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail="changes_requested but no review payload",
        ))
        return

    feedback_count = _count_marker_comments(
        repo, result.pr_number, _DASH_FEEDBACK_MARKER, token,
    )
    if feedback_count >= workflow.review.max_retries:
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip",
            detail=(
                f"feedback already posted {feedback_count}× (max_retries="
                f"{workflow.review.max_retries}); awaiting human"
            ),
        ))
        return

    unmet = [c.text for c in result.review.criteria if c.status != "met"]
    if not unmet:
        # The verdict was request_changes but we can't see which criterion is at
        # fault. Skip rather than spam.
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail="changes_requested but no unmet criteria parsed",
        ))
        return

    bullet_list = "\n".join(f"- {c}" for c in unmet)
    comment = (
        f"{_DASH_FEEDBACK_MARKER}\n\n"
        f"@{result.agent_id} — the review couldn't verify these criteria:\n\n"
        f"{bullet_list}\n\n"
        f"Push commits that address each, then push to the PR. "
        f"This is feedback round {feedback_count + 1} of "
        f"{workflow.review.max_retries}."
    )
    ok = _post_comment(repo, result.pr_number, comment, token)
    report.actions.append(SupervisorAction(
        repo=repo, issue_number=result.issue_number,
        kind="post_feedback",
        detail=(
            f"PR #{result.pr_number}: feedback {feedback_count + 1}/"
            f"{workflow.review.max_retries}, {len(unmet)} unmet criteria"
        ),
        error=None if ok else "comment failed",
    ))


def _handle_approved(result: WatchResult, repo: str, token: str,
                    workflow: Workflow, report: SupervisorReport) -> None:
    """Review verdict is approve. Apply workflow.review.on_approve and run
    on_approved hooks. Idempotent: skip if PR is already merged or closed."""
    if not result.pr_number:
        return

    # Idempotency: don't try to merge an already-merged PR.
    status, pr = _gh("GET", f"/repos/{repo}/pulls/{result.pr_number}", token)
    if status != 200 or not isinstance(pr, dict):
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="error", detail=f"couldn't refetch PR #{result.pr_number}",
            error=f"HTTP {status}",
        ))
        return
    if pr.get("merged"):
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail=f"PR #{result.pr_number} already merged",
        ))
        return

    on_approve = workflow.review.on_approve
    if on_approve == "auto-merge":
        ok, detail = _merge_pr(repo, result.pr_number, token)
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="auto_merge", detail=detail,
            error=None if ok else detail,
        ))
    else:
        # Default 'comment' branch: the review comment was already posted on
        # PR open; no-op so we don't spam approvals every cron run.
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip",
            detail=f"approved; on_approve='{on_approve}', awaiting human merge",
        ))

    # Run on_approved hooks regardless of merge mode.
    if workflow.hooks.on_approved:
        ctx = {
            "repo": repo,
            "issue_number": result.issue_number,
            "tenant_id": "",  # tenant_id not needed for current handlers
            "token": token,
            "pr_number": result.pr_number,
        }
        _run_hooks(workflow.hooks.on_approved, ctx, report)


def _handle_resolved(result: WatchResult, repo: str, token: str, tenant_id: str,
                    workflow: Workflow, report: SupervisorReport,
                    metadata: dict) -> None:
    """PR merged + review approved → run on_merged hooks."""
    # Idempotency: skip if the issue is already closed.
    status, issue = _gh("GET", f"/repos/{repo}/issues/{result.issue_number}", token)
    if status == 200 and isinstance(issue, dict) and issue.get("state") == "closed":
        report.actions.append(SupervisorAction(
            repo=repo, issue_number=result.issue_number,
            kind="skip", detail="issue already closed; on_merged hooks already ran",
        ))
        return

    ctx = {
        "repo": repo,
        "issue_number": result.issue_number,
        "tenant_id": tenant_id,
        "token": token,
        "pr_number": result.pr_number,
        "brief_action_id": metadata.get("brief_action_id"),
    }
    _run_hooks(workflow.hooks.on_merged, ctx, report)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_supervisor(
    *,
    tenant_id: str,
    repos_list: List[str],
    token: str,
    workflow: Optional[Workflow] = None,
    workflow_revision: int = 0,
) -> SupervisorReport:
    """Walk every Dash issue in `repos_list` and apply the workflow's policy.

    Caller is responsible for resolving the active workflow (or passing the
    default), fetching a tenant-scoped GitHub installation token, and
    handing over the list of repos visible to that installation.
    """
    if workflow is None:
        workflow = default_workflow()

    report = SupervisorReport(tenant_id=tenant_id, workflow_revision=workflow_revision)

    for repo in repos_list:
        report.repos_scanned += 1
        try:
            results = watch_repo_delegations(repo, token)
        except Exception as e:
            logger.exception("watch_repo_delegations failed for %s", repo)
            report.actions.append(SupervisorAction(
                repo=repo, issue_number=0,
                kind="error", detail="watch failed", error=str(e),
            ))
            continue

        for result in results:
            report.delegations_seen += 1

            # Pull metadata once so handlers can use brief_action_id etc.
            status, issue = _gh("GET", f"/repos/{repo}/issues/{result.issue_number}", token)
            metadata = {}
            if status == 200 and isinstance(issue, dict):
                metadata = parse_dash_metadata(issue.get("body") or "") or {}

            issue_dict = issue if isinstance(issue, dict) else {}

            if result.status == TaskStatus.PR_OPENED:
                _handle_pr_opened(result, repo, token, workflow, report)
            elif result.status == TaskStatus.RESOLVED:
                _handle_resolved(result, repo, token, tenant_id, workflow, report, metadata)
            elif result.status == TaskStatus.DELEGATED:
                _handle_delegated(result, repo, token, workflow, report, issue_dict)
            elif result.status == TaskStatus.CHANGES_REQUESTED:
                _handle_changes_requested(result, repo, token, workflow, report)
            elif result.status == TaskStatus.APPROVED:
                _handle_approved(result, repo, token, workflow, report)
            else:
                report.actions.append(SupervisorAction(
                    repo=repo, issue_number=result.issue_number,
                    kind="skip", detail=f"status={result.status} not handled",
                ))

    return report
