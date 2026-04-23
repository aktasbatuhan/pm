"""Tests for agent_fleet.escalation (#15) and agent_fleet.refresh (#16)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agent_fleet.escalation import (
    DelegationPolicy,
    HealthStatus,
    evaluate_task_health,
    load_delegation_policy,
    _next_fallback,
)
from agent_fleet.profile import AgentProfile
from agent_fleet.refresh import _detect_drift, _is_monday


# ---------------------------------------------------------------------------
# DelegationPolicy
# ---------------------------------------------------------------------------

class TestDelegationPolicy:
    def test_default_values(self):
        p = DelegationPolicy()
        assert p.max_retries_per_agent == 2
        assert p.stall_timeout_hours == 24
        assert p.auto_escalate is False
        assert p.stall_timeout_seconds == 24 * 3600

    def test_from_dict_roundtrip(self):
        d = {"default_agent": "codex", "fallback_chain": ["devin"], "stall_timeout_hours": 12, "auto_escalate": True}
        p = DelegationPolicy.from_dict(d)
        assert p.default_agent == "codex"
        assert p.fallback_chain == ["devin"]
        assert p.stall_timeout_hours == 12
        assert p.auto_escalate is True

    def test_load_delegation_policy_defaults_when_no_blueprint(self):
        p = load_delegation_policy(None)
        assert isinstance(p, DelegationPolicy)

    def test_load_delegation_policy_from_blueprint(self):
        p = load_delegation_policy({"delegation_policy": {"stall_timeout_hours": 6}})
        assert p.stall_timeout_hours == 6


# ---------------------------------------------------------------------------
# _next_fallback
# ---------------------------------------------------------------------------

class TestNextFallback:
    def test_returns_next_in_chain(self):
        policy = DelegationPolicy(fallback_chain=["claude-code", "codex", "devin"])
        assert _next_fallback("claude-code", policy) == "codex"
        assert _next_fallback("codex", policy) == "devin"

    def test_last_in_chain_returns_none(self):
        policy = DelegationPolicy(fallback_chain=["claude-code", "codex"])
        assert _next_fallback("codex", policy) is None

    def test_agent_not_in_chain_returns_first(self):
        policy = DelegationPolicy(fallback_chain=["codex", "devin"])
        assert _next_fallback("jules", policy) == "codex"

    def test_empty_chain_returns_none(self):
        policy = DelegationPolicy(fallback_chain=[])
        assert _next_fallback("claude-code", policy) is None


# ---------------------------------------------------------------------------
# evaluate_task_health — base cases
# ---------------------------------------------------------------------------

_POLICY = DelegationPolicy(fallback_chain=["codex"], max_retries_per_agent=2, stall_timeout_hours=24)
_RECENT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))   # 5 min ago
_STALE = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 90000))  # 25 h ago


def _health(**overrides):
    defaults = dict(
        task_status="delegated",
        agent_id="claude-code",
        issue_number=1,
        issue_url="https://github.com/acme/api/issues/1",
        task_title="Fix login bug",
        created_at=_RECENT,
        last_activity_at=None,
        pr_number=None,
        pr_url=None,
        review_verdict=None,
        ping_count=0,
        policy=_POLICY,
    )
    defaults.update(overrides)
    return evaluate_task_health(**defaults)


class TestEvaluateTaskHealth:
    def test_ok_when_no_pr_within_expected_window(self):
        verdict = _health(created_at=_RECENT)
        assert verdict.status == HealthStatus.OK

    def test_nudge_when_no_pr_past_expected_window(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))  # 2h > 30min expected
        verdict = _health(created_at=old)
        assert verdict.status in (HealthStatus.NUDGE, HealthStatus.STALLED)
        if verdict.status == HealthStatus.NUDGE:
            assert verdict.should_re_ping is True

    def test_stalled_when_exceeded_stall_timeout(self):
        verdict = _health(created_at=_STALE, ping_count=0)
        assert verdict.status == HealthStatus.STALLED
        assert verdict.action_item is not None

    def test_stalled_when_too_many_pings(self):
        verdict = _health(ping_count=3)  # > max_retries=2
        assert verdict.status == HealthStatus.STALLED

    def test_needs_human_on_review_verdict(self):
        verdict = _health(pr_number=99, review_verdict="needs_human")
        assert verdict.status == HealthStatus.NEEDS_HUMAN
        assert verdict.action_item is not None

    def test_ok_when_pr_approved(self):
        verdict = _health(pr_number=99, pr_url="https://github.com/acme/api/pull/99", review_verdict="approve")
        assert verdict.status == HealthStatus.OK

    def test_nudge_when_pr_opened_no_activity(self):
        stale_activity = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5 * 3600))
        verdict = _health(pr_number=99, last_activity_at=stale_activity)
        assert verdict.status == HealthStatus.NUDGE

    def test_nudge_when_changes_requested_no_activity(self):
        stale_activity = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 10 * 3600))
        verdict = _health(pr_number=99, last_activity_at=stale_activity, review_verdict="request_changes")
        assert verdict.status in (HealthStatus.NUDGE, HealthStatus.STALLED)

    def test_stalled_has_fallback_agent_when_chain_available(self):
        verdict = _health(created_at=_STALE)
        assert verdict.fallback_agent_id == "codex"

    def test_auto_escalate_flag_propagated(self):
        policy = DelegationPolicy(fallback_chain=["codex"], auto_escalate=True, stall_timeout_hours=1)
        verdict = _health(created_at=_STALE, policy=policy)
        if verdict.fallback_agent_id:
            assert verdict.should_escalate is True

    def test_action_item_has_required_fields(self):
        verdict = _health(created_at=_STALE)
        ai = verdict.action_item
        assert ai is not None
        assert "category" in ai
        assert "title" in ai
        assert "description" in ai
        assert "priority" in ai
        assert "references" in ai


# ---------------------------------------------------------------------------
# _detect_drift
# ---------------------------------------------------------------------------

class TestDetectDrift:
    def test_new_agent_detected(self):
        discovered = [AgentProfile(id="claude-code", detected_via=["fingerprint_pr_author"])]
        existing = []
        signals = _detect_drift(discovered, existing)
        assert any("New coding agent" in s["title"] for s in signals)

    def test_silent_agent_flagged(self):
        import time
        old_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 20 * 86400),  # 20 days ago
        )
        profile = AgentProfile(id="claude-code", enabled=True, last_active=old_ts)
        signals = _detect_drift([], [profile])
        assert any("inactive" in s["title"].lower() for s in signals)

    def test_active_agent_not_flagged_as_silent(self):
        import time
        recent_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 2 * 86400),  # 2 days ago
        )
        profile = AgentProfile(id="claude-code", enabled=True, last_active=recent_ts)
        signals = _detect_drift([], [profile])
        assert not any("inactive" in s["title"].lower() for s in signals)

    def test_invocation_change_flagged(self):
        from agent_fleet.profile import ObservedInvocation, ObservedInvocationDetail
        old_inv = ObservedInvocation(primary=ObservedInvocationDetail(type="comment_mention", count=5))
        new_inv = ObservedInvocation(primary=ObservedInvocationDetail(type="label", count=5))
        existing = [AgentProfile(id="claude-code", observed_invocation=old_inv)]
        discovered = [AgentProfile(id="claude-code", observed_invocation=new_inv)]
        signals = _detect_drift(discovered, existing)
        assert any("invocation pattern changed" in s["title"].lower() for s in signals)

    def test_no_drift_for_unchanged_profile(self):
        from agent_fleet.profile import ObservedInvocation, ObservedInvocationDetail
        inv = ObservedInvocation(primary=ObservedInvocationDetail(type="comment_mention", count=5))
        profile = AgentProfile(id="claude-code", enabled=True, observed_invocation=inv)
        # Same profile in both
        signals = _detect_drift([profile], [profile])
        assert not any("invocation" in s["title"].lower() for s in signals)

    def test_installed_but_unused_flagged(self):
        profile = AgentProfile(id="claude-code", detected_via=["org_installations"], activity_90d={})
        signals = _detect_drift([], [profile])
        assert any("installed but never" in s["title"].lower() for s in signals)

    def test_empty_inputs_no_signals(self):
        signals = _detect_drift([], [])
        assert signals == []
