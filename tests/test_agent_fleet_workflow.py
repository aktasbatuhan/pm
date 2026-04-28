"""Tests for the Workflow contract parser + default."""

from __future__ import annotations

import pytest

from agent_fleet.workflow import (
    Workflow,
    WorkflowParseError,
    default_workflow,
    parse_workflow,
)


class TestParse:
    def test_default_parses(self):
        wf = default_workflow()
        assert isinstance(wf, Workflow)
        assert wf.name == "Dash default"
        assert wf.routing.default == "claude-code"
        assert wf.routing.rules[0].label == "bug"
        assert wf.routing.rules[0].agent == "codex"
        assert wf.review.auto is True
        assert wf.review.max_retries == 2
        assert wf.escalation.fallback_chain == ["codex", "claude-code"]
        assert "{{ problem }}" in wf.prompt_template

    def test_minimal_workflow(self):
        text = """---
name: minimal
---

just a prompt
"""
        wf = parse_workflow(text)
        assert wf.name == "minimal"
        assert wf.routing.default == "claude-code"  # falls back to defaults
        assert wf.review.auto is True
        assert wf.prompt_template.strip() == "just a prompt"

    def test_routing_rule_picks_correct_agent(self):
        wf = default_workflow()
        assert wf.routing.pick_agent(["bug"]) == "codex"
        assert wf.routing.pick_agent(["DOCS"]) == "claude-code"  # case-insensitive
        assert wf.routing.pick_agent(["whatever"]) == "claude-code"  # default
        assert wf.routing.pick_agent([]) == "claude-code"

    def test_missing_front_matter_raises(self):
        with pytest.raises(WorkflowParseError):
            parse_workflow("just a prompt with no yaml")

    def test_unclosed_front_matter_raises(self):
        with pytest.raises(WorkflowParseError):
            parse_workflow("---\nname: x\nno trailing delimiter")

    def test_invalid_yaml_raises(self):
        with pytest.raises(WorkflowParseError):
            parse_workflow("---\n: : : not yaml\n---\nbody")

    def test_unknown_escalation_keys_ignored(self):
        # Forwards-compat: future schema additions should not crash old parsers.
        text = """---
name: tolerant
escalation:
  stall_timeout_hours: 6
  unknown_future_key: 42
---
"""
        wf = parse_workflow(text)
        assert wf.escalation.stall_timeout_hours == 6


class TestSerialization:
    def test_to_dict_excludes_prompt_template(self):
        wf = default_workflow()
        d = wf.to_dict()
        assert "prompt_template" not in d
        assert d["name"] == "Dash default"
        assert d["routing"]["rules"][0]["label"] == "bug"
