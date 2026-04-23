"""Delegation fallback and escalation policy — GitHub issue #15.

evaluate_task_health(task_status, agent_profile, context) assesses a delegation
task and returns a HealthVerdict with the recommended action.

The escalation policy is stored in the workspace blueprint under
`delegation_policy`. Default policy ships here.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How long (seconds) to wait per expected_pr_back_seconds range before stalling
STALL_MULTIPLIER = 2.0
# How many re-pings before giving up
DEFAULT_MAX_RETRIES = 2
# Default stall timeout (seconds) before marking a task stalled regardless
DEFAULT_STALL_TIMEOUT = 24 * 3600  # 24 h


class HealthStatus:
    OK = "ok"
    NUDGE = "nudge"       # re-ping the agent
    STALLED = "stalled"   # no activity, declare stalled
    FAILED = "failed"     # agent returned error
    NEEDS_HUMAN = "needs_human"  # review says unclear, escalate


@dataclass
class DelegationPolicy:
    default_agent: str = "claude-code"
    fallback_chain: List[str] = field(default_factory=list)
    max_retries_per_agent: int = DEFAULT_MAX_RETRIES
    stall_timeout_hours: int = 24
    auto_escalate: bool = False  # if True, re-file to fallback without asking

    @property
    def stall_timeout_seconds(self) -> int:
        return self.stall_timeout_hours * 3600

    @classmethod
    def from_dict(cls, d: dict) -> "DelegationPolicy":
        return cls(
            default_agent=d.get("default_agent", "claude-code"),
            fallback_chain=list(d.get("fallback_chain") or []),
            max_retries_per_agent=int(d.get("max_retries_per_agent") or DEFAULT_MAX_RETRIES),
            stall_timeout_hours=int(d.get("stall_timeout_hours") or 24),
            auto_escalate=bool(d.get("auto_escalate", False)),
        )

    def to_dict(self) -> dict:
        return {
            "default_agent": self.default_agent,
            "fallback_chain": self.fallback_chain,
            "max_retries_per_agent": self.max_retries_per_agent,
            "stall_timeout_hours": self.stall_timeout_hours,
            "auto_escalate": self.auto_escalate,
        }


@dataclass
class HealthVerdict:
    status: str                       # HealthStatus.*
    reason: str
    recommended_action: str           # human-readable next step
    action_item: Optional[dict] = None  # brief action item if escalating
    should_re_ping: bool = False
    should_escalate: bool = False
    fallback_agent_id: Optional[str] = None


def _now() -> float:
    return time.time()


def _parse_ts(ts: Optional[str]) -> float:
    if not ts:
        return 0.0
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def evaluate_task_health(
    task_status: str,
    agent_id: str,
    issue_number: int,
    issue_url: str,
    task_title: str,
    created_at: str,
    last_activity_at: Optional[str],
    pr_number: Optional[int],
    pr_url: Optional[str],
    review_verdict: Optional[str],   # "approve"|"request_changes"|"needs_human"|None
    ping_count: int,
    policy: DelegationPolicy,
) -> HealthVerdict:
    """Evaluate the health of a single delegation task.

    Returns a HealthVerdict the orchestrator uses to decide what to do next.

    Follows the state table from issue #15:
    | Condition | Action |
    |---|---|
    | No PR after expected * 2 | Re-ping. Log attempt. |
    | No PR after 3 re-pings or 24h | Stalled |
    | PR opened but no commits 4h | Nudge once, then stalled |
    | review: request_changes no new commits 8h | Re-ping, then stalled |
    | review: needs_human | Immediate escalation action item |
    | Agent error in PR description | Classify: retry or re-delegate |
    """
    from agent_fleet.registry import lookup
    now = _now()
    created_ts = _parse_ts(created_at)
    last_activity_ts = _parse_ts(last_activity_at) if last_activity_at else created_ts
    elapsed_since_creation = now - created_ts
    elapsed_since_activity = now - last_activity_ts

    agent = lookup(agent_id)
    expected_min, expected_max = agent.expected_pr_back_seconds if agent else (300, 1800)

    stall_timeout = policy.stall_timeout_seconds

    # -- Immediate escalation: review said needs_human --
    if review_verdict == "needs_human":
        return HealthVerdict(
            status=HealthStatus.NEEDS_HUMAN,
            reason="Review verdict is 'needs_human' — criteria unclear from diff alone.",
            recommended_action="Human review required before merging.",
            action_item=_make_action_item(
                task_title, agent_id, issue_number, issue_url, pr_number, pr_url,
                "Review verdict unclear — human needed to assess PR against criteria.",
                priority="high",
            ),
            should_escalate=False,
        )

    # -- No PR yet --
    if not pr_number:
        # Hard stall: exceeded stall_timeout or too many re-pings
        if elapsed_since_creation >= stall_timeout or ping_count >= policy.max_retries_per_agent:
            _status = HealthStatus.STALLED
            fallback = _next_fallback(agent_id, policy)
            return HealthVerdict(
                status=_status,
                reason=f"No PR after {int(elapsed_since_creation/3600):.0f}h / {ping_count} pings.",
                recommended_action=f"Re-delegate to {fallback}" if fallback else "Manual intervention required.",
                action_item=_make_action_item(
                    task_title, agent_id, issue_number, issue_url, None, None,
                    f"No PR filed after {int(elapsed_since_creation/3600):.0f}h.",
                    priority="high",
                ),
                should_escalate=policy.auto_escalate and bool(fallback),
                fallback_agent_id=fallback,
            )
        # Soft nudge: exceeded expected_max * STALL_MULTIPLIER
        if elapsed_since_creation >= expected_max * STALL_MULTIPLIER:
            return HealthVerdict(
                status=HealthStatus.NUDGE,
                reason=f"No PR after {elapsed_since_creation/3600:.1f}h (expected ≤{expected_max/60:.0f}m).",
                recommended_action="Re-ping the agent.",
                should_re_ping=True,
            )
        # Still within expected window
        return HealthVerdict(
            status=HealthStatus.OK,
            reason=f"PR not yet filed; within expected window ({expected_max/60:.0f}m).",
            recommended_action="Wait.",
        )

    # -- PR exists: check review state --
    if review_verdict == "request_changes":
        if elapsed_since_activity >= 8 * 3600:
            if ping_count >= policy.max_retries_per_agent:
                fallback = _next_fallback(agent_id, policy)
                return HealthVerdict(
                    status=HealthStatus.STALLED,
                    reason=f"Changes requested but no activity for {elapsed_since_activity/3600:.0f}h after {ping_count} pings.",
                    recommended_action=f"Re-delegate to {fallback}" if fallback else "Manual fix required.",
                    action_item=_make_action_item(
                        task_title, agent_id, issue_number, issue_url, pr_number, pr_url,
                        "Agent stalled after change requests.",
                        priority="high",
                    ),
                    should_escalate=policy.auto_escalate and bool(fallback),
                    fallback_agent_id=fallback,
                )
            return HealthVerdict(
                status=HealthStatus.NUDGE,
                reason=f"Changes requested; no activity for {elapsed_since_activity/3600:.0f}h.",
                recommended_action="Re-ping agent to address review comments.",
                should_re_ping=True,
            )

    if review_verdict == "approve":
        return HealthVerdict(
            status=HealthStatus.OK,
            reason="PR approved — waiting for human to merge.",
            recommended_action="Merge the PR.",
        )

    # PR opened but no review yet
    if elapsed_since_activity >= 4 * 3600:
        return HealthVerdict(
            status=HealthStatus.NUDGE,
            reason=f"PR opened but no commits / activity for {elapsed_since_activity/3600:.0f}h.",
            recommended_action="Nudge the agent to continue.",
            should_re_ping=True,
        )

    return HealthVerdict(
        status=HealthStatus.OK,
        reason="PR in progress.",
        recommended_action="Wait for the agent to complete.",
    )


def _next_fallback(agent_id: str, policy: DelegationPolicy) -> Optional[str]:
    chain = policy.fallback_chain
    if not chain:
        return None
    try:
        idx = chain.index(agent_id)
        return chain[idx + 1] if idx + 1 < len(chain) else None
    except ValueError:
        return chain[0] if chain else None


def _make_action_item(
    task_title: str,
    agent_id: str,
    issue_number: int,
    issue_url: str,
    pr_number: Optional[int],
    pr_url: Optional[str],
    description: str,
    priority: str = "high",
) -> dict:
    refs = [{"type": "issue", "url": issue_url, "title": f"#{issue_number}"}]
    if pr_url and pr_number:
        refs.append({"type": "pr", "url": pr_url, "title": f"PR #{pr_number}"})
    return {
        "category": "risk",
        "title": f"Delegated task stalled: {task_title}",
        "description": f"Agent: {agent_id}. {description}",
        "priority": priority,
        "references": refs,
    }


def load_delegation_policy(blueprint_data: Optional[dict]) -> DelegationPolicy:
    """Read delegation_policy from blueprint data, or return defaults."""
    if not blueprint_data:
        return DelegationPolicy()
    raw = blueprint_data.get("delegation_policy")
    if not raw or not isinstance(raw, dict):
        return DelegationPolicy()
    return DelegationPolicy.from_dict(raw)
