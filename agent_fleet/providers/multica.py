"""multica — adapter for a user-provisioned Multica instance.

STATUS: DEFERRED (issue #43 items A2/A3/A4)
===========================================
This file is a SKELETON. All four DelegationProvider methods raise
NotImplementedError. The Protocol is satisfied so the registry, supervisor,
and workflow `provider:` field all keep working — we just don't ship the
concrete REST / WebSocket / Settings UI until a user actually runs a Multica
instance and asks Dash to point at it.

When that happens, the work is mechanical:
  - A2: REST methods (delegate/status/cancel) — endpoints documented below
  - A3: WebSocket stream_events — wss://<host>/ws subscription
  - A4: Settings → Integrations → Multica UI for URL + PAT entry

The audit comments below are the implementation roadmap; the dispatch state
table at _EVENT_TO_STATE is the contract this adapter has to honor.

LICENSE NOTE
============
Multica is licensed under "modified Apache 2.0" with embedding restrictions:
hosting Multica as part of a commercial SaaS requires a commercial license
from Multica, Inc. (see https://github.com/multica-ai/multica/blob/main/LICENSE).

To stay compliant, **Dash never ships, hosts, or self-hosts Multica.** Tenants
who want to use Multica run their own instance (cloud or self-hosted) and
configure Dash with the URL + Personal Access Token. Dash speaks REST + WS to
that instance the same way a user's browser would.

API SHAPE (audited 2026-04-30 against multica-ai/multica @ v0.2.20)
===================================================================
Authentication: Bearer <PAT> (created via /api/tokens; or short-lived CLI
token via /api/cli-token).

Delegate a task:
    POST /api/issues
        body: {title, description, assignee_type: "agent", assignee_id: <agent_uuid>,
               labels?, project_id?}
    Multica auto-creates a task and enqueues it on the assigned agent's
    runtime (via task:queued event).

Status:
    GET /api/issues/{id}                  -> issue snapshot
    GET /api/issues/{id}/active-task      -> currently-running task (or null)
    GET /api/issues/{id}/task-runs        -> full task history
    GET /api/tasks/{taskId}/messages      -> agent transcript

Cancel:
    POST /api/issues/{id}/tasks/{taskId}/cancel

Rerun (supports our supervisor "refile" flow):
    POST /api/issues/{id}/rerun

Stream events:
    Connect to wss://<host>/ws with ?workspace_id=...
    Filter events by issue_id / task_id. Relevant kinds:
      task:queued, task:dispatch, task:progress, task:completed,
      task:failed, task:cancelled, task:message, comment:created.

State mapping → DelegationState
================================
    task:queued    -> PENDING
    task:dispatch  -> RUNNING
    task:progress  -> RUNNING
    task:completed -> DONE        (supervisor decides if it actually moved the needle)
    task:failed    -> FAILED
    task:cancelled -> CANCELLED

This file is a STUB — concrete REST + WS code lands as part of issue #43's
provider-implementation chunk. The shape of the methods is fixed by the
DelegationProvider Protocol so the supervisor refactor can target it.
"""

from __future__ import annotations

import logging
from typing import Iterator

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


# Maps Multica's native task lifecycle event kinds to our normalized state.
_EVENT_TO_STATE = {
    "task:queued": DelegationState.PENDING,
    "task:dispatch": DelegationState.RUNNING,
    "task:progress": DelegationState.RUNNING,
    "task:completed": DelegationState.DONE,
    "task:failed": DelegationState.FAILED,
    "task:cancelled": DelegationState.CANCELLED,
}


class MulticaProvider:
    """Talks to a user-provisioned Multica instance.

    Per-tenant config (read from integration_connections):
      - base_url:  https://multica.example.com  (or https://multica.ai)
      - pat:       Multica Personal Access Token
      - workspace_id: which Multica workspace to file issues into
    """

    name = "multica"

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._config = None  # lazy-loaded from integration_connections

    def _ensure_config(self) -> dict:
        if self._config is not None:
            return self._config
        # Lookup is part of #43 — checks integration_connections table for
        # platform='multica' under this tenant_id, decodes credentials JSON.
        raise ProviderUnavailable(
            "multica: not configured for this tenant. Connect via "
            "Settings → Integrations → Multica."
        )

    def delegate(self, *, task, workflow, tenant_id: str) -> DelegationHandle:
        """POST /api/issues with assignee_type=agent.

        Implementation outline:
          1. Resolve workflow.agent (e.g. 'codex-via-multica:my-agent') to a
             Multica agent UUID via GET /api/agents.
          2. Compose description from task.problem + acceptance_criteria
             + context + constraints (same content as the GitHub flow,
             different transport).
          3. POST /api/issues. Multica enqueues a task automatically.
          4. Return Handle{provider='multica', data={workspace_id, issue_id, task_id}}.
        """
        raise NotImplementedError(
            "multica.delegate: implemented in #43 provider chunk"
        )

    def status(self, handle: DelegationHandle) -> DelegationStatus:
        """GET /api/issues/{id} + GET /api/issues/{id}/active-task.

        Translates active_task.status to DelegationState via _EVENT_TO_STATE.
        Surfaces task transcript URL as a DelegationArtifact(kind='transcript')
        so the supervisor's review step can pull the full conversation."""
        raise NotImplementedError(
            "multica.status: implemented in #43 provider chunk"
        )

    def stream_events(self, handle: DelegationHandle) -> Iterator[DelegationEvent]:
        """WebSocket subscription on /ws filtered by issue_id.

        Yields DelegationEvent(kind=...) as Multica emits task:* and
        comment:* frames. Closes the iterator once a terminal state is
        observed (DONE/FAILED/CANCELLED)."""
        raise NotImplementedError(
            "multica.stream_events: implemented in #43 provider chunk"
        )

    def cancel(self, handle: DelegationHandle, *, reason: str = "") -> None:
        """POST /api/issues/{id}/tasks/{task_id}/cancel.

        If `reason` is provided, also POST a comment first so the cancel
        is explainable in the Multica timeline."""
        raise NotImplementedError(
            "multica.cancel: implemented in #43 provider chunk"
        )

    def supports(self, capability: str) -> bool:
        return capability in {"stream", "rerun", "transcript", "cost", "comment"}


register("multica", MulticaProvider)
