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

Phase 2 scope (this file ships):
  PR opened + unreviewed         → auto-review (skip if Dash already reviewed)
  Resolved (PR merged)           → run on_merged hooks (close_dash_issue,
                                   resolve_brief_action)

Phase 2.5 (next):
  Stale delegations              → escalation policy
  Changes requested + idle       → re-ping with structured feedback
  on_approved / on_failed hooks
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

# A canonical heading we drop into review comments so we can detect on the
# next run that we've already reviewed this PR (and don't double-comment).
_DASH_REVIEW_MARKER = "## Dash Review"


def _has_existing_dash_review(repo: str, pr_number: int, token: str) -> bool:
    """True if any issue comment on the PR already contains the Dash review marker."""
    status, comments = _gh("GET", f"/repos/{repo}/issues/{pr_number}/comments", token)
    if status != 200 or not isinstance(comments, list):
        return False
    return any(_DASH_REVIEW_MARKER in (c.get("body") or "") for c in comments)


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

            if result.status == TaskStatus.PR_OPENED:
                _handle_pr_opened(result, repo, token, workflow, report)
            elif result.status == TaskStatus.RESOLVED:
                _handle_resolved(result, repo, token, tenant_id, workflow, report, metadata)
            else:
                report.actions.append(SupervisorAction(
                    repo=repo, issue_number=result.issue_number,
                    kind="skip", detail=f"status={result.status} not handled in phase 2",
                ))

    return report
