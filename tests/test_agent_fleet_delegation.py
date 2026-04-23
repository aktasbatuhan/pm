"""Tests for agent_fleet.delegation (GitHub issue #13)."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from agent_fleet.delegation import (
    DelegationTask,
    PostCreateAction,
    build_delegation_issue,
    dispatch_post_create_actions,
    find_dash_issues,
    is_dash_issue,
    parse_dash_metadata,
    DELEGATION_FORMAT_VERSION,
)
from agent_fleet.profile import AgentProfile, ObservedInvocation, ObservedInvocationDetail


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _comment_mention_profile() -> AgentProfile:
    """Profile with high-confidence comment_mention invocation."""
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="comment_mention", syntax="@claude", count=10),
    )
    return AgentProfile(id="claude-code", enabled=True, confidence="high", observed_invocation=inv)


def _label_profile() -> AgentProfile:
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="label", label="claude", count=5),
    )
    return AgentProfile(id="claude-code", enabled=True, confidence="high", observed_invocation=inv)


def _assignment_profile() -> AgentProfile:
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="issue_assignment", count=4),
    )
    return AgentProfile(id="copilot-swe", enabled=True, confidence="medium", observed_invocation=inv)


def _workflow_profile() -> AgentProfile:
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="workflow_trigger", count=3),
    )
    return AgentProfile(id="claude-code", enabled=True, confidence="medium", observed_invocation=inv)


def _low_confidence_profile() -> AgentProfile:
    return AgentProfile(id="claude-code", enabled=True, confidence="low")


def _make_task(**overrides) -> DelegationTask:
    defaults = dict(
        title="Fix login conversion drop",
        problem="Authenticated users drop off at the login→onboarding step at 43%.",
        acceptance_criteria=["Add funnel event tracking", "Identify drop-off source in logs"],
        context="Relevant file: `auth/login.py`",
        constraints="Must not break existing tests.",
        repo="acme/api",
    )
    defaults.update(overrides)
    return DelegationTask(**defaults)


# ---------------------------------------------------------------------------
# build_delegation_issue — structure
# ---------------------------------------------------------------------------

class TestBuildDelegationIssue:
    def test_title_prefixed_with_dash(self):
        title, _, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert title.startswith("[Dash]")
        assert "Fix login conversion drop" in title

    def test_body_contains_metadata_block(self):
        _, body, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert f"<!-- dash-delegation: {DELEGATION_FORMAT_VERSION} -->" in body
        assert "<!-- dash-task-id:" in body
        assert "<!-- dash-agent: claude-code -->" in body
        assert "<!-- dash-created-at:" in body

    def test_body_contains_required_sections(self):
        _, body, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert "## Problem" in body
        assert "## Acceptance Criteria" in body
        assert "## Output expected" in body

    def test_acceptance_criteria_are_checkboxes(self):
        _, body, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert "- [ ] Add funnel event tracking" in body
        assert "- [ ] Identify drop-off source in logs" in body

    def test_context_included_when_provided(self):
        _, body, _ = build_delegation_issue(_make_task(context="See `auth/login.py`"), _comment_mention_profile())
        assert "## Context" in body
        assert "auth/login.py" in body

    def test_constraints_included_when_provided(self):
        _, body, _ = build_delegation_issue(_make_task(constraints="No breaking changes."), _comment_mention_profile())
        assert "## Constraints" in body
        assert "No breaking changes." in body

    def test_empty_context_omitted(self):
        _, body, _ = build_delegation_issue(_make_task(context=""), _comment_mention_profile())
        assert "## Context" not in body

    def test_output_expected_section_present(self):
        _, body, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert "A pull request against the default branch" in body

    def test_task_id_is_uuid_like(self):
        import re
        _, body, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        meta = parse_dash_metadata(body)
        assert re.match(r"[0-9a-f-]{36}", meta["task_id"])


# ---------------------------------------------------------------------------
# build_delegation_issue — invocation dispatch
# ---------------------------------------------------------------------------

class TestInvocationDispatch:
    def test_comment_mention_appended_to_body(self):
        _, body, actions = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert "@claude" in body
        assert not any(a.kind == "add_label" for a in actions)
        assert not any(a.kind == "assign" for a in actions)

    def test_label_invocation_adds_post_create_action(self):
        _, body, actions = build_delegation_issue(_make_task(), _label_profile())
        label_actions = [a for a in actions if a.kind == "add_label"]
        assert len(label_actions) == 1
        assert label_actions[0].payload["label"] == "claude"
        assert "@claude" not in body  # no inline mention for label

    def test_assignment_invocation_adds_post_create_action(self):
        _, body, actions = build_delegation_issue(_make_task(), _assignment_profile())
        assign_actions = [a for a in actions if a.kind == "assign"]
        assert len(assign_actions) == 1

    def test_workflow_trigger_no_inline_text_no_actions(self):
        _, body, actions = build_delegation_issue(_make_task(), _workflow_profile())
        assert "<!-- invocation -->" not in body or "@" not in body.split("<!-- invocation -->")[-1].strip()
        assert len(actions) == 0

    def test_low_confidence_falls_back_to_registry_default(self):
        """claude-code registry default is comment_mention → @claude should appear."""
        _, body, actions = build_delegation_issue(_make_task(), _low_confidence_profile())
        assert "@claude" in body


# ---------------------------------------------------------------------------
# parse_dash_metadata
# ---------------------------------------------------------------------------

class TestParseDashMetadata:
    def test_roundtrip(self):
        task = _make_task()
        profile = _comment_mention_profile()
        _, body, _ = build_delegation_issue(task, profile)
        meta = parse_dash_metadata(body)
        assert meta is not None
        assert meta["version"] == DELEGATION_FORMAT_VERSION
        assert meta["task_id"] == task.task_id
        assert meta["agent_id"] == "claude-code"
        assert meta["created_at"] == task.created_at

    def test_returns_none_for_plain_body(self):
        assert parse_dash_metadata("This is a normal issue.") is None

    def test_returns_none_for_empty(self):
        assert parse_dash_metadata("") is None
        assert parse_dash_metadata(None) is None

    def test_is_dash_issue_true(self):
        _, body, _ = build_delegation_issue(_make_task(), _comment_mention_profile())
        assert is_dash_issue(body) is True

    def test_is_dash_issue_false(self):
        assert is_dash_issue("Just a regular PR description.") is False


# ---------------------------------------------------------------------------
# find_dash_issues
# ---------------------------------------------------------------------------

class TestFindDashIssues:
    def _make_search_response(self, issues_with_meta: int, plain_issues: int):
        items = []
        for i in range(issues_with_meta):
            task = _make_task(title=f"Task {i}")
            _, body, _ = build_delegation_issue(task, _comment_mention_profile())
            items.append({"number": i + 1, "title": f"[Dash] Task {i}", "state": "open", "html_url": f"https://github.com/acme/api/issues/{i+1}", "body": body})
        for j in range(plain_issues):
            items.append({"number": 100 + j, "title": "Regular issue", "state": "open", "html_url": f"https://github.com/acme/api/issues/{100+j}", "body": "Just a normal issue."})
        return (200, {"items": items})

    def test_returns_only_dash_issues(self):
        search_resp = self._make_search_response(issues_with_meta=3, plain_issues=2)

        def mock_gh(method, path, token, body=None, timeout=20):
            return search_resp

        with patch("agent_fleet.delegation._gh", mock_gh):
            result = find_dash_issues("acme/api", "tok")

        assert len(result) == 3
        for issue in result:
            assert "task_id" in issue
            assert "agent_id" in issue

    def test_graceful_on_api_error(self):
        def mock_gh(method, path, token, body=None, timeout=20):
            return (403, None)

        with patch("agent_fleet.delegation._gh", mock_gh):
            result = find_dash_issues("acme/api", "tok")

        assert result == []

    def test_empty_repo_returns_empty(self):
        def mock_gh(method, path, token, body=None, timeout=20):
            return (200, {"items": []})

        with patch("agent_fleet.delegation._gh", mock_gh):
            result = find_dash_issues("acme/api", "tok")

        assert result == []


# ---------------------------------------------------------------------------
# dispatch_post_create_actions
# ---------------------------------------------------------------------------

class TestDispatchPostCreateActions:
    def test_add_label(self):
        def mock_gh(method, path, token, body=None, timeout=20):
            if "labels" in path:
                return (200, [{"name": "claude"}])
            return (200, None)

        actions = [PostCreateAction(kind="add_label", payload={"label": "claude"})]
        with patch("agent_fleet.delegation._gh", mock_gh):
            results = dispatch_post_create_actions("acme/api", 1, actions, "tok")

        assert len(results) == 1
        assert results[0]["ok"] is True
        assert "add_label:claude" in results[0]["action"]

    def test_assign(self):
        def mock_gh(method, path, token, body=None, timeout=20):
            if "assignees" in path:
                return (201, {"assignees": [{"login": "claude"}]})
            return (200, None)

        actions = [PostCreateAction(kind="assign", payload={"assignee": "claude"})]
        with patch("agent_fleet.delegation._gh", mock_gh):
            results = dispatch_post_create_actions("acme/api", 1, actions, "tok")

        assert results[0]["ok"] is True

    def test_empty_actions_returns_empty(self):
        with patch("agent_fleet.delegation._gh", lambda *a, **kw: (200, None)):
            results = dispatch_post_create_actions("acme/api", 1, [], "tok")
        assert results == []
