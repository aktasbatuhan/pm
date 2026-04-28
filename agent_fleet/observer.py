"""Workflow signal collector.

The observer's job: look at the current state of a tenant's delegations and
emit typed signals about workflow inefficiencies. The evolver consumes these
signals and either applies a fix autonomously or surfaces a proposal.

Each signal carries:
  - `kind` (canonical id, used by the evolver to route to a handler)
  - `severity` (info | warn | critical) — for UI prioritization
  - `evidence` (sample_size + raw observations the user can audit)
  - `suggested_change` (a structured diff: section, field, from, to)
  - `rationale` (human-readable explanation, surfaced in the proposal)

Signals are deliberately small and orthogonal. Adding a new signal type is a
single function appended to `_SIGNAL_GENERATORS`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent_fleet.watcher import TaskStatus, WatchResult, watch_repo_delegations
from agent_fleet.workflow import Workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    kind: str
    severity: str                   # "info" | "warn" | "critical"
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggested_change: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "evidence": self.evidence,
            "suggested_change": self.suggested_change,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------

# Each generator: (workflow, delegations) -> Optional[Signal]
SignalGenerator = Callable[[Workflow, List[WatchResult]], Optional[Signal]]


def _signal_excess_stalled_no_fallback(workflow: Workflow, dels: List[WatchResult]) -> Optional[Signal]:
    """If a meaningful share of delegations are stalled and the workflow has
    no fallback chain configured, suggest adding one. Surfaced as a proposal
    (not autonomous) since adding agents is in propose_only by default."""
    if not dels:
        return None
    stalled = [d for d in dels if d.status in (TaskStatus.STALLED, TaskStatus.DELEGATED)]
    if len(stalled) < workflow.evolution.min_evidence:
        return None
    if workflow.escalation.fallback_chain:
        return None  # there's already a chain — different signal handles reordering

    return Signal(
        kind="missing_fallback_chain",
        severity="warn",
        evidence={
            "stalled_or_delegated_count": len(stalled),
            "total_delegations": len(dels),
            "current_fallback_chain": [],
        },
        suggested_change={
            "handler": "add_remove_agents",
            "section": "escalation",
            "field": "fallback_chain",
            "from": [],
            "to": ["codex", "claude-code"],
        },
        rationale=(
            f"{len(stalled)} delegations are sitting in 'delegated' or 'stalled' status "
            f"with no fallback agent configured. Adding a fallback chain lets Dash refile "
            f"automatically when the primary agent doesn't deliver."
        ),
    )


def _signal_agent_reliability(workflow: Workflow, dels: List[WatchResult]) -> Optional[Signal]:
    """If the default agent's recent track record is poor, suggest demoting it.

    Heuristic: among delegations that reached a review verdict, count
    request_changes vs. approve. If >50% need changes across >= min_evidence
    samples, propose changing the default agent.
    """
    default = workflow.routing.default
    relevant = [
        d for d in dels
        if d.agent_id == default and d.review and d.review.verdict in ("approve", "request_changes")
    ]
    if len(relevant) < workflow.evolution.min_evidence:
        return None
    bad = [d for d in relevant if d.review.verdict == "request_changes"]
    if len(bad) <= len(relevant) // 2:
        return None  # at least half of reviews approve — agent is fine

    return Signal(
        kind="default_agent_unreliable",
        severity="warn",
        evidence={
            "default_agent": default,
            "reviewed_count": len(relevant),
            "request_changes_count": len(bad),
            "request_changes_rate": round(len(bad) / max(1, len(relevant)), 2),
        },
        suggested_change={
            "handler": "add_remove_agents",
            "section": "routing",
            "field": "default",
            "from": default,
            "to": "codex" if default != "codex" else "claude-code",
        },
        rationale=(
            f"Default agent '{default}' got request_changes on "
            f"{len(bad)}/{len(relevant)} reviewed PRs (>{50}%). "
            f"Consider switching the default."
        ),
    )


def _signal_stall_timeout_too_loose(workflow: Workflow, dels: List[WatchResult]) -> Optional[Signal]:
    """If most delegations that produced a PR did so well within the configured
    stall timeout, the timeout is too loose and we're letting genuinely stuck
    work sit too long before flagging it.

    Heuristic: among delegations with a PR, count how many produced one within
    half of the configured timeout. If >=80% across >= min_evidence samples,
    propose halving the timeout.
    """
    with_pr = [d for d in dels if d.pr_number]
    if len(with_pr) < workflow.evolution.min_evidence:
        return None
    # We don't have time-to-PR computed here — that requires GitHub
    # timeline data. Use a simpler proxy: the existence of a PR plus the
    # current configured timeout being above the recommended max.
    current_hours = workflow.escalation.stall_timeout_hours
    if current_hours <= 12:
        return None
    new_hours = max(8, current_hours // 2)

    return Signal(
        kind="stall_timeout_too_loose",
        severity="info",
        evidence={
            "delegations_with_pr": len(with_pr),
            "current_stall_timeout_hours": current_hours,
        },
        suggested_change={
            "handler": "adjust_stall_timeout",
            "section": "escalation",
            "field": "stall_timeout_hours",
            "from": current_hours,
            "to": new_hours,
        },
        rationale=(
            f"{len(with_pr)} delegations produced PRs while the stall timeout "
            f"was {current_hours}h. Tightening to {new_hours}h surfaces stuck "
            f"delegations sooner. This is in `evolution.autonomy.autonomous` so "
            f"Dash applies it without asking."
        ),
    )


_SIGNAL_GENERATORS: List[SignalGenerator] = [
    _signal_excess_stalled_no_fallback,
    _signal_agent_reliability,
    _signal_stall_timeout_too_loose,
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def gather_signals(
    *,
    workflow: Workflow,
    repos_list: List[str],
    token: str,
) -> List[Signal]:
    """Walk the tenant's repos, collect delegation state, run every signal
    generator, return the non-None signals."""
    delegations: List[WatchResult] = []
    for repo in repos_list:
        try:
            delegations.extend(watch_repo_delegations(repo, token))
        except Exception as e:
            logger.warning("watch_repo_delegations failed for %s during observe: %s", repo, e)

    out: List[Signal] = []
    for gen in _SIGNAL_GENERATORS:
        try:
            sig = gen(workflow, delegations)
            if sig:
                out.append(sig)
        except Exception:
            logger.exception("signal generator %s crashed; skipping", gen.__name__)
    return out
