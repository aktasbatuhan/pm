"""Workflow evolver — applies or proposes changes from observer signals.

Reads `workflow.evolution.autonomy` to decide, per signal, whether Dash can
apply the suggested change unilaterally or must surface it as a proposal for
the human (via a brief action with category='workflow-proposal').

Autonomous changes write a new workflow revision tagged author='dash' with
the signals as `based_on_signals` evidence. Proposals create a brief_action
the user can accept (which then writes the revision) or dismiss.

Handlers are small, pure functions over the workflow text — they parse the
current YAML body, edit one field, and return the new body. Keeping the
prompt-template Markdown intact while we mutate the front matter is the
critical detail; we don't re-serialize via dataclass.to_dict() because
that loses comments and ordering.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import yaml

from agent_fleet.observer import Signal
from agent_fleet.workflow import Workflow, parse_workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision record
# ---------------------------------------------------------------------------


@dataclass
class EvolutionDecision:
    signal: Signal
    outcome: str            # "applied" | "proposed" | "skipped"
    reason: str = ""
    new_revision: Optional[int] = None       # set when outcome == "applied"
    proposal_action_id: Optional[str] = None  # set when outcome == "proposed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal": self.signal.to_dict(),
            "outcome": self.outcome,
            "reason": self.reason,
            "new_revision": self.new_revision,
            "proposal_action_id": self.proposal_action_id,
        }


# ---------------------------------------------------------------------------
# Workflow text mutators (one per handler name from EvolutionAutonomyConfig)
# ---------------------------------------------------------------------------

# Each mutator: (workflow_text, change_dict) -> new_workflow_text
WorkflowMutator = Callable[[str, Dict[str, Any]], str]


def _split_front_matter(text: str) -> tuple[str, str]:
    """Return (yaml_text, body) by splitting the document on the closing ---."""
    if not text.startswith("---"):
        raise ValueError("workflow text must start with '---'")
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        raise ValueError("workflow text has no closing '---'")
    return rest[:end], rest[end + 4:].lstrip("\n")


def _rejoin(yaml_text: str, body: str) -> str:
    return f"---\n{yaml_text.rstrip()}\n---\n\n{body.lstrip()}"


def _mutate_yaml_field(yaml_text: str, path: List[str], new_value: Any) -> str:
    """Round-trip through PyYAML to update a nested field.
    Loses comments — acceptable for Dash-authored revisions, since the
    rationale is captured separately on the revision row."""
    data = yaml.safe_load(yaml_text) or {}
    cursor = data
    for key in path[:-1]:
        if not isinstance(cursor.get(key), dict):
            cursor[key] = {}
        cursor = cursor[key]
    cursor[path[-1]] = new_value
    return yaml.safe_dump(data, sort_keys=False)


def _mutator_adjust_stall_timeout(text: str, change: Dict[str, Any]) -> str:
    yaml_text, body = _split_front_matter(text)
    new_yaml = _mutate_yaml_field(
        yaml_text, ["escalation", "stall_timeout_hours"], int(change["to"]),
    )
    return _rejoin(new_yaml, body)


def _mutator_tighten_retries(text: str, change: Dict[str, Any]) -> str:
    yaml_text, body = _split_front_matter(text)
    new_yaml = _mutate_yaml_field(
        yaml_text, ["review", "max_retries"], int(change["to"]),
    )
    return _rejoin(new_yaml, body)


def _mutator_rotate_fallback_chain(text: str, change: Dict[str, Any]) -> str:
    yaml_text, body = _split_front_matter(text)
    new_yaml = _mutate_yaml_field(
        yaml_text, ["escalation", "fallback_chain"], list(change["to"]),
    )
    return _rejoin(new_yaml, body)


_AUTONOMOUS_MUTATORS: Dict[str, WorkflowMutator] = {
    "adjust_stall_timeout": _mutator_adjust_stall_timeout,
    "tighten_retries": _mutator_tighten_retries,
    "rotate_fallback_chain": _mutator_rotate_fallback_chain,
}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class EvolverContext:
    tenant_id: str
    workflow: Workflow
    workflow_text: str          # the raw markdown+yaml of the active revision

    # Persistence injection points (for testability + so we don't import
    # backend.repos at module load — observer/evolver are agent-runtime code
    # that may run outside the API process).
    save_revision: Callable[..., int]                 # (tenant_id, name, body, author, rationale, signals) -> revision
    file_proposal: Callable[..., Optional[str]]       # (tenant_id, signal) -> brief_action_id or None


def evolve(*, ctx: EvolverContext, signals: List[Signal]) -> List[EvolutionDecision]:
    """Run every signal through the autonomy gate. Returns one decision per
    signal."""
    autonomy = ctx.workflow.evolution.autonomy
    decisions: List[EvolutionDecision] = []
    new_text = ctx.workflow_text  # accumulates autonomous mutations across signals

    autonomous_signals: List[Signal] = []
    for sig in signals:
        handler = (sig.suggested_change or {}).get("handler") or ""
        if not handler:
            decisions.append(EvolutionDecision(
                signal=sig, outcome="skipped",
                reason="signal had no handler in suggested_change",
            ))
            continue

        if handler in autonomy.autonomous and handler in _AUTONOMOUS_MUTATORS:
            try:
                new_text = _AUTONOMOUS_MUTATORS[handler](new_text, sig.suggested_change)
                # Validate the result still parses
                parse_workflow(new_text)
                autonomous_signals.append(sig)
                decisions.append(EvolutionDecision(
                    signal=sig, outcome="applied",
                    reason=f"autonomous handler '{handler}'",
                ))
            except Exception as e:
                logger.exception("autonomous mutator %s failed", handler)
                decisions.append(EvolutionDecision(
                    signal=sig, outcome="skipped",
                    reason=f"mutator crashed: {e}",
                ))
            continue

        if handler in autonomy.propose_only:
            try:
                action_id = ctx.file_proposal(ctx.tenant_id, sig)
                decisions.append(EvolutionDecision(
                    signal=sig, outcome="proposed",
                    reason=f"propose-only handler '{handler}'",
                    proposal_action_id=action_id,
                ))
            except Exception as e:
                logger.exception("filing proposal failed for signal %s", sig.kind)
                decisions.append(EvolutionDecision(
                    signal=sig, outcome="skipped",
                    reason=f"file_proposal raised: {e}",
                ))
            continue

        decisions.append(EvolutionDecision(
            signal=sig, outcome="skipped",
            reason=f"handler '{handler}' not in autonomous or propose_only",
        ))

    # If we mutated the text, persist as a single Dash-authored revision
    # carrying every applied signal as evidence.
    if autonomous_signals and new_text != ctx.workflow_text:
        try:
            wf = parse_workflow(new_text)
            rev = ctx.save_revision(
                tenant_id=ctx.tenant_id,
                name=wf.name,
                body=new_text,
                author="dash",
                rationale=f"Auto-applied {len(autonomous_signals)} signal(s): "
                          + ", ".join(s.kind for s in autonomous_signals),
                based_on_signals=[s.to_dict() for s in autonomous_signals],
            )
            for d in decisions:
                if d.outcome == "applied":
                    d.new_revision = rev
        except Exception as e:
            logger.exception("save_revision failed")
            for d in decisions:
                if d.outcome == "applied":
                    d.outcome = "skipped"
                    d.reason = f"persist failed: {e}"

    return decisions
