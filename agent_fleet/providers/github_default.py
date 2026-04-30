"""github_default — wraps the existing Dash → GitHub-issue flow as a
DelegationProvider.

Behavior is *unchanged* from agent_fleet.delegation + agent_fleet.watcher;
this adapter is a thin facade so the supervisor stops calling those
modules directly. That keeps issue #43's refactor mechanical: replace
`from agent_fleet.delegation import build_delegation_issue` with
`provider.delegate(...)` at each callsite.

State mapping (GitHub PR-shaped → DelegationState):
    issue open, no PR              -> PENDING
    issue open, PR opened          -> RUNNING
    PR has review_requested label  -> REVIEW
    PR merged                      -> DONE
    PR closed unmerged             -> FAILED
    issue closed without PR        -> CANCELLED

The provider is stateless beyond the GitHub installation token; per-tenant
state lives in the existing fleet_delegations / brief_actions tables.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterator, Optional

from agent_fleet.providers.base import (
    DelegationArtifact,
    DelegationEvent,
    DelegationHandle,
    DelegationProvider,
    DelegationState,
    DelegationStatus,
    ProviderError,
    ProviderUnavailable,
)
from agent_fleet.providers.registry import register

logger = logging.getLogger(__name__)

_DASH_REVIEW_MARKER = "## Dash Review"


class GithubDefaultProvider:
    """Files Dash issues against the user's GitHub via the installed App.
    Polls PR/issue state on each status() call."""

    name = "github_default"

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        # Lazy: resolve the App installation token only when we actually
        # need to make a call — avoids forcing every tenant to have GH
        # configured just to import this module.
        self._token: Optional[str] = None

    def set_token(self, token: str) -> None:
        """Inject a caller-minted tenant token for request-scoped code paths."""
        self._token = token

    def _ensure_token(self) -> str:
        if self._token:
            return self._token
        # Reuse Dash's existing tenant-scoped token resolver.
        from github_app_auth import get_installation_token_for_tenant
        token = get_installation_token_for_tenant(self.tenant_id)
        if not token:
            raise ProviderUnavailable(
                "github_default: no GitHub App installation for this tenant. "
                "Connect GitHub from Settings → Integrations."
            )
        self._token = token
        return token

    def delegate(self, *, task, workflow, tenant_id: str) -> DelegationHandle:
        """File a Dash-shaped issue. Delegates to the existing
        agent_fleet.delegation builder — no behavior change."""
        from agent_fleet.delegation import (
            build_delegation_issue,
            dispatch_post_create_actions,
        )
        # Resolve the agent profile this workflow points to.
        from agent_fleet.blueprint import get_agent_profile
        from workspace_context import load_workspace_context
        agent_id = workflow.routing.default
        ctx = load_workspace_context(workspace_id=tenant_id)
        profile = get_agent_profile(ctx, agent_id)
        if profile is None:
            raise ProviderUnavailable(
                f"github_default: no AgentProfile for '{agent_id}' on this tenant. "
                "Run fleet discovery to populate it."
            )

        token = self._ensure_token()
        title, body, post_create = build_delegation_issue(task, profile)

        # File the issue against the repo named in the task.
        if not task.repo:
            raise ProviderUnavailable(
                "github_default: task has no .repo set; can't pick a target."
            )

        # NOTE: keeping the inline GH POST here is intentional — once #43
        # lands, the existing build_delegation_issue caller in supervisor.py
        # gets refactored to call this method instead, and we can move the
        # POST helper somewhere shared.
        import json
        import urllib.request
        req = urllib.request.Request(
            f"https://api.github.com/repos/{task.repo}/issues",
            data=json.dumps({"title": title, "body": body}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "Dash-PM-Provider",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            issue = json.loads(resp.read())

        issue_number = issue["number"]
        dispatch_post_create_actions(task.repo, issue_number, post_create, token)

        return DelegationHandle(
            provider=self.name,
            data={
                "repo": task.repo,
                "issue_number": issue_number,
                "issue_url": issue["html_url"],
                "task_id": task.task_id,
            },
        )

    def status(self, handle: DelegationHandle) -> DelegationStatus:
        """Fetch issue + linked PR state and translate to DelegationState."""
        from agent_fleet.delegation import parse_dash_metadata
        from agent_fleet.registry import lookup
        from agent_fleet.watcher import TaskStatus, link_pr_to_task, _gh

        repo = str(handle.data.get("repo") or "")
        issue_number = int(handle.data.get("issue_number") or 0)
        if not repo or issue_number < 1:
            raise ProviderError("github_default.status: handle requires repo and issue_number")

        token = self._ensure_token()
        issue_status, issue = _gh("GET", f"/repos/{repo}/issues/{issue_number}", token)
        if issue_status != 200 or not isinstance(issue, dict):
            return DelegationStatus(
                handle=handle,
                state=DelegationState.UNKNOWN,
                state_detail=f"couldn't fetch issue #{issue_number}: HTTP {issue_status}",
                raw={"repo": repo, "issue_number": issue_number, "task_status": DelegationState.UNKNOWN.value},
            )

        issue_body = issue.get("body") or ""
        metadata = parse_dash_metadata(issue_body) or {}
        task_id = metadata.get("task_id") or str(handle.data.get("task_id") or "")
        agent_id = metadata.get("agent_id") or str(handle.data.get("agent_id") or "")
        agent = lookup(agent_id)
        bot_usernames = agent.bot_usernames if agent else ()
        pr_number = link_pr_to_task(
            issue_number=issue_number,
            repo=repo,
            agent_bot_usernames=bot_usernames,
            token=token,
            issue_created_at=issue.get("created_at", ""),
        )

        raw = {
            "repo": repo,
            "issue": issue,
            "issue_number": issue_number,
            "task_id": task_id,
            "agent_id": agent_id,
            "metadata": metadata,
            "pr_number": pr_number,
        }

        last_activity = _ts(issue.get("updated_at") or issue.get("created_at"))

        if pr_number is None:
            if issue.get("state") == "closed":
                raw["task_status"] = TaskStatus.STALLED
                return DelegationStatus(
                    handle=handle,
                    state=DelegationState.CANCELLED,
                    state_detail="issue closed before a PR was linked",
                    last_activity_at=last_activity,
                    summary=f"GitHub issue #{issue_number} is closed with no linked PR",
                    raw=raw,
                )
            raw["task_status"] = TaskStatus.DELEGATED
            return DelegationStatus(
                handle=handle,
                state=DelegationState.PENDING,
                state_detail="issue open, no linked PR yet",
                last_activity_at=last_activity,
                summary=f"GitHub issue #{issue_number} is waiting for agent pickup",
                raw=raw,
            )

        pr_status, pr = _gh("GET", f"/repos/{repo}/pulls/{pr_number}", token)
        if pr_status != 200 or not isinstance(pr, dict):
            raw["task_status"] = DelegationState.UNKNOWN.value
            return DelegationStatus(
                handle=handle,
                state=DelegationState.UNKNOWN,
                state_detail=f"couldn't fetch PR #{pr_number}: HTTP {pr_status}",
                last_activity_at=last_activity,
                raw=raw,
            )

        review = _latest_dash_review(repo, pr_number, token)
        raw["pr"] = pr
        raw["review"] = review
        last_activity = max(last_activity or 0, _ts(pr.get("updated_at") or pr.get("created_at")) or 0) or None
        artifacts = [
            DelegationArtifact(
                kind="pr",
                url=pr.get("html_url") or "",
                title=pr.get("title") or f"PR #{pr_number}",
                metadata={"number": pr_number},
            )
        ]

        if pr.get("merged"):
            if review and review.verdict == "approve":
                raw["task_status"] = TaskStatus.RESOLVED
                return DelegationStatus(
                    handle=handle,
                    state=DelegationState.DONE,
                    state_detail="PR merged after Dash approval",
                    artifacts=artifacts,
                    last_activity_at=last_activity,
                    summary=f"PR #{pr_number} merged",
                    raw=raw,
                )
            raw["task_status"] = TaskStatus.REVIEWED
            return DelegationStatus(
                handle=handle,
                state=DelegationState.DONE,
                state_detail="PR merged without a parsed Dash approval",
                artifacts=artifacts,
                last_activity_at=last_activity,
                summary=f"PR #{pr_number} merged; approval state needs review",
                raw=raw,
            )

        if pr.get("state") == "closed":
            raw["task_status"] = "failed"
            return DelegationStatus(
                handle=handle,
                state=DelegationState.FAILED,
                state_detail="PR closed without merge",
                artifacts=artifacts,
                last_activity_at=last_activity,
                summary=f"PR #{pr_number} closed without merge",
                raw=raw,
            )

        if not review:
            raw["task_status"] = TaskStatus.PR_OPENED
            return DelegationStatus(
                handle=handle,
                state=DelegationState.RUNNING,
                state_detail="PR open, awaiting Dash review",
                artifacts=artifacts,
                last_activity_at=last_activity,
                summary=f"PR #{pr_number} is open and needs review",
                raw=raw,
            )

        if review.verdict == "approve":
            raw["task_status"] = TaskStatus.APPROVED
            detail = "PR open with Dash approval"
        elif review.verdict == "request_changes":
            raw["task_status"] = TaskStatus.CHANGES_REQUESTED
            detail = "PR open with requested changes"
        else:
            raw["task_status"] = TaskStatus.REVIEWED
            detail = "PR open with a Dash review needing human judgment"

        return DelegationStatus(
            handle=handle,
            state=DelegationState.REVIEW,
            state_detail=detail,
            artifacts=artifacts,
            last_activity_at=last_activity,
            summary=f"PR #{pr_number}: {review.verdict}",
            raw=raw,
        )

    def stream_events(self, handle: DelegationHandle) -> Iterator[DelegationEvent]:
        """GitHub doesn't stream; the supervisor falls back to polling."""
        raise NotImplementedError("github_default does not support native streaming")

    def cancel(self, handle: DelegationHandle, *, reason: str = "") -> None:
        """Close the issue with an explanatory comment."""
        from agent_fleet.watcher import _gh

        repo = str(handle.data.get("repo") or "")
        issue_number = int(handle.data.get("issue_number") or 0)
        if not repo or issue_number < 1:
            raise ProviderError("github_default.cancel: handle requires repo and issue_number")

        token = self._ensure_token()
        if reason:
            _gh(
                "POST",
                f"/repos/{repo}/issues/{issue_number}/comments",
                token,
                body={"body": f"## Dash Cancelled\n\n{reason}"},
            )
        status, _ = _gh(
            "PATCH",
            f"/repos/{repo}/issues/{issue_number}",
            token,
            body={"state": "closed", "state_reason": "not_planned"},
        )
        if status not in (200, 201):
            raise ProviderError(f"github_default.cancel failed: HTTP {status}")

    def supports(self, capability: str) -> bool:
        return capability in {"comment", "rerun"}


# Self-register at import time.
register("github_default", GithubDefaultProvider)


_VERDICT_RE = re.compile(r"\*\*Verdict\*\*:\s*(?P<verdict>.+)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"\*\*Summary\*\*:\s*(?P<summary>.+)", re.IGNORECASE)
_CRITERION_RE = re.compile(r"^-\s*(?P<icon>[^\s]+)?\s*\*\*(?P<text>.+?)\*\*", re.MULTILINE)


def _ts(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return None


def _latest_dash_review(repo: str, pr_number: int, token: str):
    from agent_fleet.watcher import CriterionResult, ReviewResult, _gh

    status, comments = _gh("GET", f"/repos/{repo}/issues/{pr_number}/comments", token)
    if status != 200 or not isinstance(comments, list):
        return None

    matching = [c for c in comments if _DASH_REVIEW_MARKER in (c.get("body") or "")]
    if not matching:
        return None
    matching.sort(key=lambda c: c.get("created_at") or "")
    body = matching[-1].get("body") or ""

    verdict_match = _VERDICT_RE.search(body)
    verdict = _normalize_verdict(verdict_match.group("verdict") if verdict_match else "")
    if not verdict:
        return None

    summary_match = _SUMMARY_RE.search(body)
    criteria = []
    for match in _CRITERION_RE.finditer(body):
        icon = match.group("icon") or ""
        status_value = "unclear"
        if "✅" in icon:
            status_value = "met"
        elif "❌" in icon:
            status_value = "unmet"
        elif "❓" in icon:
            status_value = "unclear"
        criteria.append(CriterionResult(text=match.group("text").strip(), status=status_value))

    return ReviewResult(
        verdict=verdict,
        criteria=criteria,
        summary=(summary_match.group("summary").strip() if summary_match else ""),
        pr_number=pr_number,
        pr_url=f"https://github.com/{repo}/pull/{pr_number}",
    )


def _normalize_verdict(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if "request" in normalized and "change" in normalized:
        return "request_changes"
    if "approve" in normalized:
        return "approve"
    if "human" in normalized:
        return "needs_human"
    return ""
