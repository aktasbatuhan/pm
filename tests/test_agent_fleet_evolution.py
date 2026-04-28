"""Tests for the observer + evolver framework (phase 3)."""

from __future__ import annotations

from unittest.mock import patch

from agent_fleet.evolver import EvolverContext, evolve, _AUTONOMOUS_MUTATORS
from agent_fleet.observer import (
    Signal,
    _signal_excess_stalled_no_fallback,
    _signal_agent_reliability,
    _signal_stall_timeout_too_loose,
    gather_signals,
)
from agent_fleet.watcher import (
    CriterionResult, ReviewResult, TaskStatus, WatchResult,
)
from agent_fleet.workflow import default_workflow, parse_workflow, DEFAULT_WORKFLOW_TEXT


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------


class TestSignalGenerators:
    def test_excess_stalled_emits_when_chain_empty(self):
        wf = default_workflow()
        wf.escalation.fallback_chain = []
        wf.evolution.min_evidence = 3
        dels = [
            WatchResult(issue_number=i, task_id=f"t{i}", agent_id="claude-code",
                        status=TaskStatus.DELEGATED)
            for i in range(5)
        ]
        sig = _signal_excess_stalled_no_fallback(wf, dels)
        assert sig is not None
        assert sig.kind == "missing_fallback_chain"
        assert sig.suggested_change["handler"] == "add_remove_agents"

    def test_excess_stalled_silent_when_chain_present(self):
        wf = default_workflow()
        wf.escalation.fallback_chain = ["codex"]
        dels = [WatchResult(i, f"t{i}", "claude-code", TaskStatus.DELEGATED) for i in range(5)]
        assert _signal_excess_stalled_no_fallback(wf, dels) is None

    def test_excess_stalled_silent_below_min_evidence(self):
        wf = default_workflow()
        wf.escalation.fallback_chain = []
        wf.evolution.min_evidence = 10
        dels = [WatchResult(i, f"t{i}", "claude-code", TaskStatus.DELEGATED) for i in range(3)]
        assert _signal_excess_stalled_no_fallback(wf, dels) is None

    def test_agent_reliability_flags_high_request_changes_rate(self):
        wf = default_workflow()
        wf.evolution.min_evidence = 3
        good = ReviewResult(verdict="approve", criteria=[])
        bad = ReviewResult(verdict="request_changes", criteria=[])
        dels = (
            [WatchResult(i, f"t{i}", "claude-code", TaskStatus.CHANGES_REQUESTED, review=bad) for i in range(4)]
            + [WatchResult(i + 100, f"t{i}", "claude-code", TaskStatus.APPROVED, review=good) for i in range(1)]
        )
        sig = _signal_agent_reliability(wf, dels)
        assert sig is not None
        assert sig.kind == "default_agent_unreliable"
        assert sig.evidence["default_agent"] == "claude-code"

    def test_agent_reliability_silent_when_mostly_approved(self):
        wf = default_workflow()
        wf.evolution.min_evidence = 3
        good = ReviewResult(verdict="approve", criteria=[])
        bad = ReviewResult(verdict="request_changes", criteria=[])
        dels = (
            [WatchResult(i, f"t{i}", "claude-code", TaskStatus.APPROVED, review=good) for i in range(4)]
            + [WatchResult(i + 100, f"t{i}", "claude-code", TaskStatus.CHANGES_REQUESTED, review=bad) for i in range(1)]
        )
        assert _signal_agent_reliability(wf, dels) is None

    def test_stall_timeout_proposes_when_above_12h(self):
        wf = default_workflow()  # default 24h
        wf.evolution.min_evidence = 3
        dels = [WatchResult(i, f"t{i}", "claude-code", TaskStatus.PR_OPENED, pr_number=i + 1) for i in range(5)]
        sig = _signal_stall_timeout_too_loose(wf, dels)
        assert sig is not None
        assert sig.suggested_change["handler"] == "adjust_stall_timeout"
        assert sig.suggested_change["from"] == 24
        assert sig.suggested_change["to"] == 12

    def test_stall_timeout_silent_when_already_tight(self):
        wf = default_workflow()
        wf.escalation.stall_timeout_hours = 6
        wf.evolution.min_evidence = 3
        dels = [WatchResult(i, f"t{i}", "claude-code", TaskStatus.PR_OPENED, pr_number=i + 1) for i in range(5)]
        assert _signal_stall_timeout_too_loose(wf, dels) is None


class TestGatherSignals:
    def test_smoke(self):
        wf = default_workflow()
        wf.escalation.fallback_chain = []
        wf.evolution.min_evidence = 3
        dels = [WatchResult(i, f"t{i}", "claude-code", TaskStatus.DELEGATED) for i in range(5)]
        with patch("agent_fleet.observer.watch_repo_delegations", return_value=dels):
            signals = gather_signals(workflow=wf, repos_list=["acme/api"], token="tok")
        assert any(s.kind == "missing_fallback_chain" for s in signals)


# ---------------------------------------------------------------------------
# Evolver
# ---------------------------------------------------------------------------


class TestEvolver:
    def _ctx(self, **overrides):
        wf = default_workflow()
        saved = {}
        proposals = []

        def save(**kw):
            saved.update(kw)
            return 1

        def propose(tenant_id, signal):
            proposals.append((tenant_id, signal.kind))
            return f"action-{len(proposals)}"

        ctx = EvolverContext(
            tenant_id="t",
            workflow=wf,
            workflow_text=DEFAULT_WORKFLOW_TEXT,
            save_revision=save,
            file_proposal=propose,
        )
        ctx.__dict__.update(overrides)
        # Stash refs so tests can inspect
        ctx._saved = saved   # type: ignore[attr-defined]
        ctx._proposals = proposals   # type: ignore[attr-defined]
        return ctx

    def test_autonomous_handler_applies(self):
        ctx = self._ctx()
        sig = Signal(
            kind="stall_timeout_too_loose",
            severity="info",
            suggested_change={
                "handler": "adjust_stall_timeout",
                "section": "escalation",
                "field": "stall_timeout_hours",
                "from": 24,
                "to": 12,
            },
        )
        decisions = evolve(ctx=ctx, signals=[sig])
        assert decisions[0].outcome == "applied"
        # Saved revision body should reflect the change
        new_wf = parse_workflow(ctx._saved["body"])
        assert new_wf.escalation.stall_timeout_hours == 12
        # Author + signals attached
        assert ctx._saved["author"] == "dash"
        assert ctx._saved["based_on_signals"][0]["kind"] == "stall_timeout_too_loose"

    def test_propose_only_handler_files_proposal(self):
        ctx = self._ctx()
        sig = Signal(
            kind="default_agent_unreliable",
            severity="warn",
            suggested_change={
                "handler": "add_remove_agents",
                "section": "routing",
                "field": "default",
                "from": "claude-code",
                "to": "codex",
            },
        )
        decisions = evolve(ctx=ctx, signals=[sig])
        assert decisions[0].outcome == "proposed"
        assert decisions[0].proposal_action_id is not None
        assert ctx._proposals == [("t", "default_agent_unreliable")]
        # No revision saved
        assert ctx._saved == {}

    def test_unknown_handler_skipped(self):
        ctx = self._ctx()
        sig = Signal(
            kind="weird",
            severity="info",
            suggested_change={"handler": "made_up_handler"},
        )
        decisions = evolve(ctx=ctx, signals=[sig])
        assert decisions[0].outcome == "skipped"
        assert "not in autonomous or propose_only" in decisions[0].reason

    def test_multiple_autonomous_signals_share_revision(self):
        """Two autonomous signals → one new revision with both as evidence."""
        ctx = self._ctx()
        sig_timeout = Signal(
            kind="stall_timeout_too_loose",
            severity="info",
            suggested_change={"handler": "adjust_stall_timeout", "to": 8},
        )
        sig_chain = Signal(
            kind="rotate_chain",
            severity="info",
            suggested_change={"handler": "rotate_fallback_chain", "to": ["devin", "codex"]},
        )
        decisions = evolve(ctx=ctx, signals=[sig_timeout, sig_chain])
        assert all(d.outcome == "applied" for d in decisions)
        new_wf = parse_workflow(ctx._saved["body"])
        assert new_wf.escalation.stall_timeout_hours == 8
        assert new_wf.escalation.fallback_chain == ["devin", "codex"]
        # Both decisions reference the same revision
        revisions = {d.new_revision for d in decisions}
        assert revisions == {1}

    def test_signal_without_handler_skipped(self):
        ctx = self._ctx()
        sig = Signal(kind="naked", severity="info", suggested_change={})
        decisions = evolve(ctx=ctx, signals=[sig])
        assert decisions[0].outcome == "skipped"
        assert "no handler" in decisions[0].reason
