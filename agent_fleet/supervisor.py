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
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from agent_fleet.delegation import parse_dash_metadata
from agent_fleet.watcher import (
    TaskStatus,
    WatchResult,
    post_review_comment,
    review_pr_against_criteria,
    update_issue_checkboxes,
    _gh,
)
from agent_fleet.workflow import Workflow, default_workflow
from agent_fleet.providers import DelegationHandle, DelegationStatus

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


@dataclass
class DelegationSnapshot:
    """Provider status plus the legacy WatchResult shape used by handlers."""
    repo: str
    status: DelegationStatus
    result: WatchResult


def _github_default_provider(*, tenant_id: str, token: str):
    from agent_fleet.providers import registry as provider_registry

    provider = provider_registry.get("github_default", tenant_id=tenant_id)
    if hasattr(provider, "set_token"):
        provider.set_token(token)
    return provider


def _handle_from_dash_issue(repo: str, issue: dict) -> DelegationHandle:
    return DelegationHandle(
        provider="github_default",
        data={
            "repo": repo,
            "issue_number": issue.get("number"),
            "issue_url": issue.get("url") or issue.get("html_url") or "",
            "task_id": issue.get("task_id") or "",
            "agent_id": issue.get("agent_id") or "",
        },
    )


def _watch_result_from_provider_status(status: DelegationStatus) -> WatchResult:
    raw = status.raw or {}
    return WatchResult(
        issue_number=int(raw.get("issue_number") or 0),
        task_id=str(raw.get("task_id") or ""),
        agent_id=str(raw.get("agent_id") or ""),
        status=str(raw.get("task_status") or status.state.value),
        pr_number=raw.get("pr_number"),
        review=raw.get("review"),
        error=raw.get("error"),
    )


def _provider_handle_key(handle: DelegationHandle) -> str:
    if handle.provider == "github_default":
        repo = str(handle.data.get("repo") or "")
        issue_number = str(handle.data.get("issue_number") or "")
        return f"{repo}#{issue_number}"
    for key in ("issue_id", "task_id", "id"):
        value = handle.data.get(key)
        if value:
            return str(value)
    return repr(sorted(handle.data.items()))


def _json_safe(value):
    if dataclasses.is_dataclass(value):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _persist_snapshot(tenant_id: str, status: DelegationStatus) -> None:
    try:
        from backend.db.postgres_client import is_postgres_enabled
        if not is_postgres_enabled():
            return
        from backend import repos as pg_repos
    except Exception:
        return

    try:
        raw = status.raw or {}
        artifacts = [_json_safe(a) for a in (status.artifacts or [])]
        pg_repos.upsert_fleet_delegation(
            tenant_id,
            provider=status.handle.provider,
            provider_handle_key=_provider_handle_key(status.handle),
            handle=status.handle.data,
            state=status.state.value if hasattr(status.state, "value") else str(status.state),
            state_detail=status.state_detail,
            summary=status.summary,
            repo=raw.get("repo") or status.handle.data.get("repo"),
            issue_number=raw.get("issue_number") or status.handle.data.get("issue_number"),
            task_id=raw.get("task_id") or status.handle.data.get("task_id"),
            agent_id=raw.get("agent_id") or status.handle.data.get("agent_id"),
            pr_number=raw.get("pr_number"),
            artifacts=artifacts,
            raw=_json_safe(raw),
            last_activity_at=status.last_activity_at,
        )
    except Exception as e:
        # Never raise: the supervisor must keep iterating even if persistence
        # is broken (Postgres blip, schema drift, etc.). Log enough to
        # diagnose: the handle key + state + tenant_id pinpoint which
        # delegation failed to write without dumping the full raw payload.
        try:
            handle_key = _provider_handle_key(status.handle)
            state_value = status.state.value if hasattr(status.state, "value") else str(status.state)
        except Exception:
            handle_key = "?"
            state_value = "?"
        logger.warning(
            "fleet snapshot persist failed: tenant=%s provider=%s handle=%s state=%s err=%s",
            tenant_id, status.handle.provider, handle_key, state_value, e,
        )


def scan_github_default_delegations(
    *,
    tenant_id: str,
    repos_list: List[str],
    token: str,
) -> List[DelegationSnapshot]:
    """Discover GitHub Dash issues, then get side-effect-free provider status."""
    from agent_fleet.delegation import find_dash_issues

    provider = _github_default_provider(tenant_id=tenant_id, token=token)
    snapshots: List[DelegationSnapshot] = []
    for repo in repos_list:
        for issue in find_dash_issues(repo, token, state="open"):
            handle = _handle_from_dash_issue(repo, issue)
            status = provider.status(handle)
            _persist_snapshot(tenant_id, status)
            snapshots.append(
                DelegationSnapshot(
                    repo=repo,
                    status=status,
                    result=_watch_result_from_provider_status(status),
                )
            )
    return snapshots


def watch_repo_delegations(repo: str, token: str, *, tenant_id: str) -> List[DelegationSnapshot]:
    """Compatibility entry point, now backed by provider status snapshots.

    `tenant_id` is required: every snapshot is persisted to fleet_delegations
    keyed by tenant. Allowing a silent "default" fallback would let stray
    callers write rows under the wrong tenant.
    """
    if not tenant_id:
        raise ValueError("watch_repo_delegations: tenant_id is required")
    return scan_github_default_delegations(
        tenant_id=tenant_id,
        repos_list=[repo],
        token=token,
    )


def scan_persisted_delegations(
    *,
    tenant_id: str,
    token: str,
    include_terminal: bool = False,
) -> List[DelegationSnapshot]:
    """Refresh provider statuses from persisted handles."""
    from agent_fleet.providers import registry as provider_registry
    from agent_fleet.providers.base import DelegationHandle
    from backend import repos as pg_repos

    rows = pg_repos.list_fleet_delegations(
        tenant_id,
        include_terminal=include_terminal,
    )
    snapshots: List[DelegationSnapshot] = []
    for row in rows:
        handle = DelegationHandle(
            provider=row["provider"],
            data=row.get("handle") or {},
        )
        provider = provider_registry.get(handle.provider, tenant_id=tenant_id)
        if handle.provider == "github_default" and hasattr(provider, "set_token"):
            provider.set_token(token)
        status = provider.status(handle)
        _persist_snapshot(tenant_id, status)
        snapshots.append(
            DelegationSnapshot(
                repo=(status.raw or {}).get("repo") or row.get("repo") or "",
                status=status,
                result=_watch_result_from_provider_status(status),
            )
        )
    return snapshots


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


# ---------------------------------------------------------------------------
# Refile: move a stalled delegation to the next agent in the fallback chain
# ---------------------------------------------------------------------------

_DASH_REFILED_MARKER = "## Dash Refiled"


def _next_fallback_agent(current_agent: str, fallback_chain: List[str]) -> Optional[str]:
    """Return the agent immediately after `current_agent` in the chain, or
    the first agent if `current_agent` isn't in the chain at all."""
    if not fallback_chain:
        return None
    if current_agent in fallback_chain:
        idx = fallback_chain.index(current_agent)
        if idx + 1 < len(fallback_chain):
            return fallback_chain[idx + 1]
        return None
    return fallback_chain[0]


def _extract_acceptance_criteria(body: str) -> List[str]:
    """Pull the unchecked acceptance criteria from a Dash issue body."""
    return re.findall(r"- \[[ xX]?\]\s*(.+?)\s*$", body or "", re.MULTILINE)


def _extract_section(body: str, heading: str) -> str:
    """Return the text under a `## <heading>` section (until the next ## or end)."""
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, body or "", re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


@dataclass
class RefileResult:
    ok: bool
    new_issue_number: Optional[int] = None
    new_issue_url: Optional[str] = None
    new_agent_id: Optional[str] = None
    error: Optional[str] = None


def refile_delegation(
    *,
    repo: str,
    issue_number: int,
    token: str,
    workflow: Workflow,
    target_agent_id: Optional[str] = None,
) -> RefileResult:
    """Move a stalled delegation to the next agent in the fallback chain.

    Steps:
      1. Fetch and parse the existing Dash issue
      2. Resolve the next fallback agent (or use `target_agent_id` override)
      3. Build a fresh delegation issue with the same task content
      4. POST the new issue + dispatch its post-create actions (labels, assignment)
      5. Comment on the old issue linking the new one
      6. Close the old issue with state_reason='not_planned'
    """
    from agent_fleet.delegation import (
        DelegationTask, build_delegation_issue, dispatch_post_create_actions,
    )
    from agent_fleet.profile import AgentProfile
    from agent_fleet.registry import lookup as registry_lookup

    status, issue = _gh("GET", f"/repos/{repo}/issues/{issue_number}", token)
    if status != 200 or not isinstance(issue, dict):
        return RefileResult(ok=False, error=f"couldn't fetch issue #{issue_number}: HTTP {status}")
    if issue.get("state") == "closed":
        return RefileResult(ok=False, error=f"issue #{issue_number} is already closed")

    body = issue.get("body") or ""
    title = issue.get("title") or ""
    metadata = parse_dash_metadata(body) or {}
    if not metadata:
        return RefileResult(ok=False, error="not a Dash delegation issue (no metadata block)")

    current_agent = metadata.get("agent_id") or "unknown"
    next_agent = target_agent_id or _next_fallback_agent(
        current_agent, workflow.escalation.fallback_chain,
    )
    if not next_agent:
        return RefileResult(ok=False, error="fallback chain exhausted; no further agent to try")
    if next_agent == current_agent:
        return RefileResult(ok=False, error=f"next agent same as current ({current_agent})")
    if registry_lookup(next_agent) is None:
        return RefileResult(ok=False, error=f"unknown agent '{next_agent}' (not in registry)")

    profile = AgentProfile(id=next_agent, enabled=True)
    clean_title = re.sub(r"^\[Dash\]\s*", "", title).strip()
    task = DelegationTask(
        title=clean_title,
        problem=_extract_section(body, "Problem") or clean_title,
        acceptance_criteria=_extract_acceptance_criteria(body) or ["Address the original delegation criteria"],
        context=_extract_section(body, "Context"),
        constraints=_extract_section(body, "Constraints"),
        repo=repo,
        brief_action_id=metadata.get("brief_action_id"),
    )

    new_title, new_body, post_create_actions = build_delegation_issue(task, profile)
    # Annotate the new issue body with a refile breadcrumb so a human (or a
    # future supervisor run) can trace lineage.
    new_body = f"{new_body}\n\n---\n_Refiled from #{issue_number} (was assigned to `{current_agent}`)_"

    create_status, created = _gh("POST", f"/repos/{repo}/issues", token, body={
        "title": new_title,
        "body": new_body,
    })
    if create_status not in (200, 201) or not isinstance(created, dict):
        return RefileResult(ok=False, error=f"create failed: HTTP {create_status}")
    new_issue_number = created.get("number")
    new_issue_url = created.get("html_url")

    # Apply labels / assignments learned for the new agent
    if post_create_actions:
        try:
            dispatch_post_create_actions(repo, new_issue_number, post_create_actions, token)
        except Exception as e:
            logger.warning("dispatch_post_create_actions failed for %s#%s: %s", repo, new_issue_number, e)

    # Link the old issue to the new one + close
    _post_comment(
        repo, issue_number,
        f"{_DASH_REFILED_MARKER}\n\n"
        f"Refiled to #{new_issue_number} (assigned to **{next_agent}**). "
        f"This issue is being closed; the new one carries forward the same criteria.",
        token,
    )
    _gh(
        "PATCH", f"/repos/{repo}/issues/{issue_number}", token,
        body={"state": "closed", "state_reason": "not_planned"},
    )

    return RefileResult(
        ok=True,
        new_issue_number=new_issue_number,
        new_issue_url=new_issue_url,
        new_agent_id=next_agent,
    )


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

    # STALLED: when the workflow opts in (escalation.auto_escalate=true) and
    # we have a fallback agent, refile autonomously. Otherwise just flag
    # once so the user can decide.
    if verdict.status == HealthStatus.STALLED:
        if workflow.escalation.auto_escalate and verdict.fallback_agent_id:
            already_refiled = _count_marker_comments(
                repo, result.issue_number, _DASH_REFILED_MARKER, token,
            ) > 0
            if already_refiled:
                report.actions.append(SupervisorAction(
                    repo=repo, issue_number=result.issue_number,
                    kind="skip", detail="stalled; already auto-refiled on a previous run",
                ))
                return
            try:
                rf = refile_delegation(
                    repo=repo, issue_number=result.issue_number,
                    token=token, workflow=workflow,
                )
                if rf.ok:
                    report.actions.append(SupervisorAction(
                        repo=repo, issue_number=result.issue_number,
                        kind="auto_refile",
                        detail=(
                            f"refiled to #{rf.new_issue_number} "
                            f"(agent: {rf.new_agent_id}); old issue closed"
                        ),
                    ))
                else:
                    report.actions.append(SupervisorAction(
                        repo=repo, issue_number=result.issue_number,
                        kind="error", detail=f"auto-refile failed: {rf.error}",
                        error=rf.error,
                    ))
            except Exception as e:
                logger.exception("auto-refile crashed for %s#%s", repo, result.issue_number)
                report.actions.append(SupervisorAction(
                    repo=repo, issue_number=result.issue_number,
                    kind="error", detail="auto-refile crashed", error=str(e),
                ))
            return

        already_marked = _count_marker_comments(
            repo, result.issue_number, _DASH_STALLED_MARKER, token,
        ) > 0
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
            f"Suggested next step: re-file to **{next_agent}** via the "
            f"`fleet_refile_delegation` tool or `POST /api/fleet/refile` "
            f"(or close manually)."
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
            scanned = watch_repo_delegations(repo, token, tenant_id=tenant_id)
        except Exception as e:
            logger.exception("provider status scan failed for %s", repo)
            report.actions.append(SupervisorAction(
                repo=repo, issue_number=0,
                kind="error", detail="provider status scan failed", error=str(e),
            ))
            continue

        for item in scanned:
            if isinstance(item, DelegationSnapshot):
                snapshot = item
                result = snapshot.result
                issue_dict = (snapshot.status.raw or {}).get("issue") or {}
                metadata = (snapshot.status.raw or {}).get("metadata") or {}
            else:
                snapshot = None
                result = item
                status, issue = _gh("GET", f"/repos/{repo}/issues/{result.issue_number}", token)
                issue_dict = issue if status == 200 and isinstance(issue, dict) else {}
                metadata = parse_dash_metadata(issue_dict.get("body") or "") or {}

            report.delegations_seen += 1

            if not metadata and issue_dict:
                metadata = parse_dash_metadata(issue_dict.get("body") or "") or {}

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
