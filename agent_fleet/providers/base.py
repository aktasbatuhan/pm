"""DelegationProvider — the abstraction that decouples Dash from any one
agent-execution backend.

Dash always plays the same role: pick what to delegate, judge the result,
record what was learned. The provider plays a narrow role: get the work
to a coding agent, surface lifecycle, cancel on demand.

Four verbs cover every backend we've considered (GitHub issue assignment,
Multica, Codex CLI, Cursor agent webhooks):

    delegate(task, workflow) -> Handle
    status(handle)            -> DelegationStatus
    stream_events(handle)     -> Iterator[DelegationEvent]   (optional)
    cancel(handle)            -> None

The Handle is opaque-to-Dash, provider-defined (e.g. {"issue_url": ...}
for GitHub, {"task_id": uuid} for Multica). Dash persists handles in
the brief_actions / fleet_delegations table and round-trips them back.

Status normalization: every backend reports a different lifecycle. The
provider translates to a fixed DelegationState enum so the supervisor's
state machine doesn't need a per-provider switch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Protocol, runtime_checkable

from agent_fleet.delegation import DelegationTask
from agent_fleet.workflow import Workflow


# ---------------------------------------------------------------------------
# Normalized state
# ---------------------------------------------------------------------------

class DelegationState(str, Enum):
    """Provider-agnostic lifecycle state. Each provider maps its own to this.

    Mapping examples:
      GitHub:    issue open + no PR        -> PENDING
                 issue open + PR open      -> RUNNING
                 PR with review-requested  -> REVIEW
                 PR merged                 -> DONE
                 PR closed without merge   -> FAILED
                 issue closed              -> CANCELLED

      Multica:   task:queued               -> PENDING
                 task:dispatch             -> RUNNING
                 task:progress             -> RUNNING
                 task:completed            -> DONE
                 task:failed               -> FAILED
                 task:cancelled            -> CANCELLED
                 (no native REVIEW state — supervisor decides post-DONE)
    """
    PENDING = "pending"          # accepted by provider, not yet picked up
    RUNNING = "running"          # agent is actively working
    REVIEW = "review"            # work submitted, awaiting human/Dash judgment
    DONE = "done"                # accepted, merged, or otherwise final-positive
    FAILED = "failed"            # agent gave up or errored
    CANCELLED = "cancelled"      # explicit cancel by Dash or user
    UNKNOWN = "unknown"          # provider can't tell (network blip, etc.)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass
class DelegationHandle:
    """Opaque identifier returned by delegate(); persisted by Dash; passed
    back to status/stream/cancel.

    `provider` lets the registry route handles back to the right adapter
    after Dash restarts. `data` is a free-form dict whose shape is the
    provider's business — Dash never inspects it.

    Example shapes:
      github:  {"repo": "org/name", "issue_number": 123, "task_id": "uuid"}
      multica: {"workspace_id": "uuid", "issue_id": "uuid", "task_id": "uuid"}
    """
    provider: str
    data: Dict[str, Any]


@dataclass
class DelegationArtifact:
    """A concrete output a provider can surface — PR, branch, transcript link."""
    kind: str                 # "pr" | "branch" | "transcript" | "log" | "comment"
    url: str = ""
    title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegationStatus:
    """Snapshot of a delegation. Cheap to fetch (single API call typically)."""
    handle: DelegationHandle
    state: DelegationState
    state_detail: str = ""               # human-readable, e.g. "PR open, awaiting review"
    artifacts: List[DelegationArtifact] = field(default_factory=list)
    last_activity_at: Optional[float] = None    # unix ts of last observed activity
    summary: str = ""                    # short one-line for UI / brief
    raw: Dict[str, Any] = field(default_factory=dict)  # provider's native payload, for debugging


@dataclass
class DelegationEvent:
    """Streamed lifecycle event. Providers may translate native events
    (Multica WebSocket frames, GitHub webhooks) into this shape."""
    handle: DelegationHandle
    kind: str                # "queued" | "started" | "progress" | "review_ready" | "done" | "failed" | "cancelled" | "message"
    timestamp: float
    payload: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ProviderError(RuntimeError):
    """Provider-side error that callers should catch and surface."""


class ProviderUnavailable(ProviderError):
    """Provider isn't configured for this tenant (no token, no URL, etc.).
    Dash should pick a fallback or surface a setup hint."""


# ---------------------------------------------------------------------------
# The Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class DelegationProvider(Protocol):
    """A pluggable execution backend for delegated coding tasks.

    Implementations live in agent_fleet/providers/*.py and self-register
    via `agent_fleet.providers.registry.register(name, factory)`. Workflow
    contracts pick a provider via the `provider:` field; the supervisor
    looks up the handle's provider name to route status/cancel.
    """

    name: str

    def delegate(
        self,
        *,
        task: DelegationTask,
        workflow: Workflow,
        tenant_id: str,
    ) -> DelegationHandle:
        """File the task with the backend. Returns a handle Dash persists.

        Must be idempotent if the same task is re-submitted with the same
        task_id — return the existing handle rather than creating a duplicate.

        Raises ProviderUnavailable if the provider isn't configured for
        this tenant.
        """
        ...

    def status(self, handle: DelegationHandle) -> DelegationStatus:
        """Cheap single-call status fetch. Should not raise on transient
        errors — return state=UNKNOWN with state_detail describing the
        problem so the supervisor can retry."""
        ...

    def stream_events(self, handle: DelegationHandle) -> Iterator[DelegationEvent]:
        """Optional: subscribe to native events (WS for Multica, webhook
        replay for GitHub). Default implementation can poll status() and
        synthesize events. Yields until the delegation reaches a terminal
        state (DONE/FAILED/CANCELLED).

        Implementations that don't natively stream may raise NotImplementedError
        and the supervisor will fall back to polling status()."""
        ...

    def cancel(self, handle: DelegationHandle, *, reason: str = "") -> None:
        """Stop the work. May be a no-op if already terminal. Reason is
        passed through to the backend if it accepts one (Multica accepts
        a cancel reason; GitHub takes a closing comment)."""
        ...

    # ----- Optional capabilities (graceful degradation) ----- #

    def supports(self, capability: str) -> bool:
        """Capability gate. Known capabilities:
          - "stream"      — native event streaming (vs polling)
          - "rerun"       — re-run a failed/done task without filing fresh
          - "transcript"  — agent message transcript retrieval
          - "cost"        — token/usage reporting per task
          - "comment"     — Dash can post comments back into the thread
        Defaults to False for any unknown capability.
        """
        return False
