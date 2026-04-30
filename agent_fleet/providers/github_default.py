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
from typing import Iterator, Optional

from agent_fleet.providers.base import (
    DelegationEvent,
    DelegationHandle,
    DelegationProvider,
    DelegationState,
    DelegationStatus,
    ProviderUnavailable,
)
from agent_fleet.providers.registry import register

logger = logging.getLogger(__name__)


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
        profile = get_agent_profile(tenant_id, workflow.agent)
        if profile is None:
            raise ProviderUnavailable(
                f"github_default: no AgentProfile for '{workflow.agent}' on this tenant. "
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
        # Defer the heavy lifting to watcher.watch_repo_delegations(); we
        # filter to the single issue this handle points at. Fully wiring
        # this is part of #43 — for now this method exists so the Protocol
        # is satisfied and the supervisor refactor has a target.
        raise NotImplementedError(
            "github_default.status: implemented as part of issue #43 supervisor refactor"
        )

    def stream_events(self, handle: DelegationHandle) -> Iterator[DelegationEvent]:
        """GitHub doesn't stream; the supervisor falls back to polling."""
        raise NotImplementedError("github_default does not support native streaming")

    def cancel(self, handle: DelegationHandle, *, reason: str = "") -> None:
        """Close the issue with an explanatory comment."""
        raise NotImplementedError(
            "github_default.cancel: implemented as part of issue #43 supervisor refactor"
        )

    def supports(self, capability: str) -> bool:
        return capability in {"comment", "rerun"}


# Self-register at import time.
register("github_default", GithubDefaultProvider)
