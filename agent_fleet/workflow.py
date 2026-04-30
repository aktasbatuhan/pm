"""Workflow contract for Dash's issue-lifecycle orchestrator.

A workflow is the declarative source of truth for how Dash delegates and
manages a single GitHub issue from creation to close. It's stored as
Markdown with YAML front matter so a team can keep it in their repo
(`.dash/workflow.md`) and version-control changes alongside their code.

This module defines the data model and the parser. The supervisor
(`agent_fleet.supervisor`, phase 2) reads a Workflow and drives the state
machine by delegating to existing primitives in `agent_fleet/`.

Schema design notes:
  - Markdown body is a Liquid-ish prompt template used when filing the
    delegation issue. Placeholders: {{ problem }}, {{ criteria }},
    {{ context }}, {{ constraints }}, {{ agent.bot_username }}.
  - YAML front matter declares the lifecycle policy.
  - Sections are intentionally small and orthogonal so customers can
    override one without rewriting the rest.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class TriggerConfig:
    """When does Dash adopt an existing GitHub issue into the workflow?"""
    labels: List[str] = field(default_factory=lambda: ["dash:delegate"])
    title_prefix: Optional[str] = "[Dash]"            # also matches our own delegation issues


@dataclass
class RoutingRule:
    """Which agent handles an issue with this label?"""
    label: str
    agent: str


@dataclass
class RoutingConfig:
    default: str = "claude-code"
    rules: List[RoutingRule] = field(default_factory=list)

    def pick_agent(self, labels: List[str]) -> str:
        labelset = {l.lower() for l in labels}
        for rule in self.rules:
            if rule.label.lower() in labelset:
                return rule.agent
        return self.default


@dataclass
class WorkspaceConfig:
    """Per-delegation working dir. Ephemeral by default."""
    ephemeral: bool = True
    root: str = "/tmp/dash-workspaces"


@dataclass
class AcceptanceConfig:
    """Defaults applied when the user (or a brief action) doesn't supply
    explicit acceptance criteria. Empty list means: the criteria are
    user-provided per delegation, no defaults."""
    defaults: List[str] = field(default_factory=list)


@dataclass
class ReviewConfig:
    """What Dash does when a PR is opened and linked to a delegation."""
    auto: bool = True                       # run review_pr_against_criteria automatically
    on_approve: str = "comment"             # comment | auto-merge
    on_request_changes: str = "re-ping"     # re-ping | escalate | manual
    on_needs_human: str = "notify"          # notify | escalate | manual
    max_retries: int = 2                    # max re-pings before escalation


@dataclass
class EscalationConfig:
    """Fallback chain when an agent stalls. Mirrors agent_fleet.escalation."""
    stall_timeout_hours: int = 24
    max_retries_per_agent: int = 2
    fallback_chain: List[str] = field(default_factory=list)
    auto_escalate: bool = False             # re-file to fallback without asking


@dataclass
class HooksConfig:
    """Named-hook lists to run at lifecycle transitions. Each value is a
    handler name resolved by the supervisor (e.g. 'resolve_brief_action').
    The set of recognized handlers is curated in the supervisor; unknown
    handlers are logged and skipped, never crash the loop."""
    on_create: List[str] = field(default_factory=list)
    on_pr_opened: List[str] = field(default_factory=list)
    on_approved: List[str] = field(default_factory=list)
    on_merged: List[str] = field(default_factory=lambda: ["close_dash_issue", "resolve_brief_action"])
    on_failed: List[str] = field(default_factory=list)


@dataclass
class EvolutionAutonomyConfig:
    """What workflow changes Dash can make unilaterally vs. propose to a human.

    Handler names are curated in the evolver; unknown names are ignored.
    Built-in handlers (phase 3):
      tighten_retries          — adjust review.max_retries within ±50%
      rotate_fallback_chain    — reorder escalation.fallback_chain
      adjust_stall_timeout     — bump escalation.stall_timeout_hours
      add_remove_agents        — change routing.default or rules' agent
      change_routing_rules     — add/remove routing.rules entries
      change_triggers          — change which labels Dash adopts
    """
    autonomous: List[str] = field(default_factory=lambda: [
        "tighten_retries",
        "rotate_fallback_chain",
        "adjust_stall_timeout",
    ])
    propose_only: List[str] = field(default_factory=lambda: [
        "add_remove_agents",
        "change_routing_rules",
        "change_triggers",
    ])


@dataclass
class EvolutionConfig:
    """How Dash's observer/evolver can reshape this workflow over time."""
    autonomy: EvolutionAutonomyConfig = field(default_factory=EvolutionAutonomyConfig)
    min_evidence: int = 5                   # don't act on fewer than N data points
    review_frequency: str = "weekly"        # how often the evolver reviews signals


@dataclass
class Workflow:
    """The full per-tenant (or per-repo) workflow contract."""
    name: str
    description: str = ""
    provider: str = "github_default"          # execution backend for new delegations
    fallback: Optional[str] = None            # provider fallback, e.g. "github_default"
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    acceptance: AcceptanceConfig = field(default_factory=AcceptanceConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    prompt_template: str = ""               # Markdown body, populated with delegation context

    def to_dict(self) -> Dict[str, Any]:
        # dataclasses.asdict() handles nested dataclasses + lists.
        out = dataclasses.asdict(self)
        out.pop("prompt_template", None)
        return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class WorkflowParseError(ValueError):
    pass


_FRONT_MATTER_DELIM = "---\n"


def parse_workflow(text: str) -> Workflow:
    """Parse a Markdown+YAML workflow document into a Workflow.

    Layout:
        ---
        <yaml front matter>
        ---
        <markdown prompt template>
    """
    if not text.startswith("---"):
        raise WorkflowParseError(
            "Workflow document must start with a YAML front-matter block (---)"
        )
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        raise WorkflowParseError("Front-matter block is not closed by a trailing ---")
    yaml_text = rest[:end]
    body = rest[end + 4:].lstrip("\n")

    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise WorkflowParseError(f"Invalid YAML in front matter: {e}") from e

    return _from_dict(data, body)


def _from_dict(data: Dict[str, Any], prompt_template: str) -> Workflow:
    triggers = TriggerConfig(**(data.get("triggers") or {}))

    routing_data = data.get("routing") or {}
    routing = RoutingConfig(
        default=routing_data.get("default", "claude-code"),
        rules=[
            RoutingRule(label=r["label"], agent=r["agent"])
            for r in (routing_data.get("rules") or [])
        ],
    )

    workspace = WorkspaceConfig(**(data.get("workspace") or {}))
    acceptance = AcceptanceConfig(defaults=list((data.get("acceptance") or {}).get("defaults") or []))
    review = ReviewConfig(**(data.get("review") or {}))
    escalation = EscalationConfig(
        **{k: v for k, v in (data.get("escalation") or {}).items() if k in {
            "stall_timeout_hours", "max_retries_per_agent",
            "fallback_chain", "auto_escalate",
        }}
    )
    hooks = HooksConfig(**(data.get("hooks") or {}))

    evo_data = data.get("evolution") or {}
    autonomy_data = evo_data.get("autonomy") or {}
    evolution = EvolutionConfig(
        autonomy=EvolutionAutonomyConfig(
            autonomous=list(autonomy_data.get("autonomous") or EvolutionAutonomyConfig().autonomous),
            propose_only=list(autonomy_data.get("propose_only") or EvolutionAutonomyConfig().propose_only),
        ) if autonomy_data else EvolutionAutonomyConfig(),
        min_evidence=int(evo_data.get("min_evidence") or 5),
        review_frequency=evo_data.get("review_frequency", "weekly"),
    )

    return Workflow(
        name=data.get("name", "default"),
        description=data.get("description", ""),
        provider=str(data.get("provider") or "github_default"),
        fallback=(str(data.get("fallback")) if data.get("fallback") else None),
        triggers=triggers,
        routing=routing,
        workspace=workspace,
        acceptance=acceptance,
        review=review,
        escalation=escalation,
        hooks=hooks,
        evolution=evolution,
        prompt_template=prompt_template,
    )


# ---------------------------------------------------------------------------
# Default workflow (ships with Dash)
# ---------------------------------------------------------------------------


DEFAULT_WORKFLOW_TEXT = """---
name: "Dash default"
description: "Default issue-lifecycle workflow that ships with Dash"
provider: github_default
fallback:

triggers:
  labels:
    - dash:delegate
  title_prefix: "[Dash]"

routing:
  default: claude-code
  rules:
    - label: bug
      agent: codex
    - label: docs
      agent: claude-code
    - label: refactor
      agent: claude-code

workspace:
  ephemeral: true
  root: /tmp/dash-workspaces

acceptance:
  defaults:
    - Implementation passes the criteria stated in this issue
    - Tests added or updated where behaviour changed
    - CI is green

review:
  auto: true
  on_approve: comment
  on_request_changes: re-ping
  on_needs_human: notify
  max_retries: 2

escalation:
  stall_timeout_hours: 24
  max_retries_per_agent: 2
  fallback_chain:
    - codex
    - claude-code
  auto_escalate: false

hooks:
  on_create: []
  on_pr_opened: []
  on_approved: []
  on_merged:
    - close_dash_issue
    - resolve_brief_action
  on_failed: []

evolution:
  autonomy:
    autonomous:
      - tighten_retries
      - rotate_fallback_chain
      - adjust_stall_timeout
    propose_only:
      - add_remove_agents
      - change_routing_rules
      - change_triggers
  min_evidence: 5
  review_frequency: weekly
---
## Problem

{{ problem }}

## Acceptance Criteria

{% for c in criteria %}
- [ ] {{ c }}
{% endfor %}

{% if context %}## Context

{{ context }}
{% endif %}

{% if constraints %}## Constraints

{{ constraints }}
{% endif %}

---
_Filed by Dash. Pick this up via `{{ agent.invocation_hint }}`._
"""


def default_workflow() -> Workflow:
    """The workflow Dash uses when no tenant-specific override exists."""
    return parse_workflow(DEFAULT_WORKFLOW_TEXT)
