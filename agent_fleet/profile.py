"""AgentProfile — per-tenant learned state for an external coding agent.

Stored inside the workspace blueprint under `external_agents`.
Schema matches the spec in GitHub issue #10.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Tuple

from agent_fleet.registry import lookup as registry_lookup


Confidence = str         # "high" | "medium" | "low"
DetectionMethod = str    # "manual" | "fingerprint_pr_author" | "fingerprint_comment" | \
                         # "fingerprint_commit" | "fingerprint_signature" | \
                         # "org_installations" | "workflow_scan"

VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_DETECTION = {
    "manual",
    "fingerprint_pr_author",
    "fingerprint_comment",
    "fingerprint_commit",
    "fingerprint_signature",
    "org_installations",
    "workflow_scan",
}
VALID_INVOCATION_TYPES = {
    "comment_mention",
    "issue_assignment",
    "label",
    "workflow_trigger",
}


class AgentProfileError(ValueError):
    """Raised when an AgentProfile fails validation."""


@dataclass
class ObservedInvocationDetail:
    type: str
    count: int = 0
    syntax: Optional[str] = None   # e.g. "@claude"
    label: Optional[str] = None    # e.g. "claude"

    def to_dict(self) -> dict:
        out = {"type": self.type, "count": int(self.count)}
        if self.syntax is not None:
            out["syntax"] = self.syntax
        if self.label is not None:
            out["label"] = self.label
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "ObservedInvocationDetail":
        return cls(
            type=d.get("type", ""),
            count=int(d.get("count", 0) or 0),
            syntax=d.get("syntax"),
            label=d.get("label"),
        )


@dataclass
class ObservedInvocation:
    primary: Optional[ObservedInvocationDetail] = None
    secondary: Optional[ObservedInvocationDetail] = None
    rare: Optional[ObservedInvocationDetail] = None

    def to_dict(self) -> dict:
        out: dict = {}
        if self.primary is not None:
            out["primary"] = self.primary.to_dict()
        if self.secondary is not None:
            out["secondary"] = self.secondary.to_dict()
        if self.rare is not None:
            out["rare"] = self.rare.to_dict()
        return out

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ObservedInvocation":
        if not d:
            return cls()
        return cls(
            primary=ObservedInvocationDetail.from_dict(d["primary"]) if d.get("primary") else None,
            secondary=ObservedInvocationDetail.from_dict(d["secondary"]) if d.get("secondary") else None,
            rare=ObservedInvocationDetail.from_dict(d["rare"]) if d.get("rare") else None,
        )


@dataclass
class AgentProfile:
    id: str                           # must match a KnownAgent.id OR be "custom:*"
    enabled: bool = False
    detected_via: List[DetectionMethod] = field(default_factory=list)
    first_seen: Optional[str] = None  # ISO8601
    last_active: Optional[str] = None
    activity_90d: Dict[str, int] = field(default_factory=dict)  # {"prs": int, "comments": int, ...}
    primary_repos: List[str] = field(default_factory=list)
    observed_invocation: ObservedInvocation = field(default_factory=ObservedInvocation)
    confidence: Confidence = "low"
    display_name_override: Optional[str] = None
    notes: Optional[str] = None

    # ---- (de)serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        out = asdict(self)
        out["observed_invocation"] = self.observed_invocation.to_dict()
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "AgentProfile":
        return cls(
            id=d["id"],
            enabled=bool(d.get("enabled", False)),
            detected_via=list(d.get("detected_via") or []),
            first_seen=d.get("first_seen"),
            last_active=d.get("last_active"),
            activity_90d=dict(d.get("activity_90d") or {}),
            primary_repos=list(d.get("primary_repos") or []),
            observed_invocation=ObservedInvocation.from_dict(d.get("observed_invocation")),
            confidence=d.get("confidence", "low"),
            display_name_override=d.get("display_name_override"),
            notes=d.get("notes"),
        )

    # ---- validation ----------------------------------------------------------

    def validate(self) -> None:
        """Raise AgentProfileError if the profile is malformed."""
        if not self.id or not isinstance(self.id, str):
            raise AgentProfileError("id must be a non-empty string")

        # id must either match a known agent or be explicitly a custom agent
        if not self.id.startswith("custom:") and registry_lookup(self.id) is None:
            raise AgentProfileError(
                f"unknown agent id {self.id!r}; add to registry or use 'custom:<name>'"
            )

        if self.confidence not in VALID_CONFIDENCE:
            raise AgentProfileError(f"confidence must be one of {sorted(VALID_CONFIDENCE)}")

        for m in self.detected_via:
            if m not in VALID_DETECTION:
                raise AgentProfileError(
                    f"invalid detection method {m!r}; must be one of {sorted(VALID_DETECTION)}"
                )

        for slot_name in ("primary", "secondary", "rare"):
            detail = getattr(self.observed_invocation, slot_name)
            if detail is None:
                continue
            if detail.type not in VALID_INVOCATION_TYPES:
                raise AgentProfileError(
                    f"observed_invocation.{slot_name}.type {detail.type!r} invalid; "
                    f"must be one of {sorted(VALID_INVOCATION_TYPES)}"
                )
            if detail.count < 0:
                raise AgentProfileError(
                    f"observed_invocation.{slot_name}.count must be >= 0"
                )

    # ---- convenience ---------------------------------------------------------

    def display_name(self) -> str:
        if self.display_name_override:
            return self.display_name_override
        known = registry_lookup(self.id)
        return known.display_name if known else self.id

    def effective_invocation(self) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (type, syntax, label) Dash should use to invoke this agent.

        Prefers the learned primary invocation if confidence is high/medium,
        otherwise falls back to the registry default.
        Returns ("none", None, None) for custom agents with no learned pattern.
        """
        prim = self.observed_invocation.primary
        if prim and self.confidence in ("high", "medium"):
            return prim.type, prim.syntax, prim.label

        known = registry_lookup(self.id)
        if known is None:
            return "none", None, None

        # Find the documented invocation that matches the default type
        default_type = known.default_invocation
        for inv in known.documented_invocations:
            if inv.type == default_type:
                return inv.type, inv.syntax, inv.label
        return default_type, None, None
