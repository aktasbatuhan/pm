"""Tests for agent_fleet.invocation (GitHub issue #12)."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from agent_fleet.invocation import (
    _classify_trigger,
    _extract_issue_numbers_from_body,
    _find_trigger_for_issue,
    _parse_ts,
    learn_invocation_pattern,
)
from agent_fleet.profile import AgentProfile
from agent_fleet.registry import lookup


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLAUDE = lookup("claude-code")
DEVIN = lookup("devin")


def _make_gh(responses: dict):
    """Mock _gh: longest-matching key wins."""
    def _mock(method, path, token, timeout=20):
        matches = [(k, v) for k, v in responses.items() if k in path]
        if matches:
            return max(matches, key=lambda x: len(x[0]))[1]
        return (200, [])
    return _mock


def _make_paginate(responses: dict):
    def _mock(path, token, max_pages=5):
        for k, v in responses.items():
            if k in path:
                return v
        return []
    return _mock


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_z(self):
        ts = _parse_ts("2026-04-01T12:00:00Z")
        assert ts > 0

    def test_iso_with_offset(self):
        ts = _parse_ts("2026-04-01T12:00:00+00:00")
        assert ts > 0

    def test_none_returns_zero(self):
        assert _parse_ts(None) == 0.0

    def test_garbage_returns_zero(self):
        assert _parse_ts("not-a-date") == 0.0


# ---------------------------------------------------------------------------
# _extract_issue_numbers_from_body
# ---------------------------------------------------------------------------

class TestExtractIssueNumbers:
    def test_closes_hash(self):
        assert 42 in _extract_issue_numbers_from_body("Closes #42")

    def test_fixes(self):
        assert 99 in _extract_issue_numbers_from_body("Fixes #99")

    def test_resolves(self):
        assert 7 in _extract_issue_numbers_from_body("Resolves #7")

    def test_multiple(self):
        nums = _extract_issue_numbers_from_body("Closes #1\nFixes #2\nResolves #3")
        assert sorted(nums) == [1, 2, 3]

    def test_empty_body(self):
        assert _extract_issue_numbers_from_body("") == []

    def test_no_match(self):
        assert _extract_issue_numbers_from_body("Just a plain PR description") == []

    def test_case_insensitive(self):
        assert 5 in _extract_issue_numbers_from_body("CLOSES #5")


# ---------------------------------------------------------------------------
# _classify_trigger
# ---------------------------------------------------------------------------

class TestClassifyTrigger:
    def test_comment_with_at_mention(self):
        event = {"event": "commented", "actor": {"login": "human"}, "body": "Hey @claude please fix this"}
        result = _classify_trigger(event, CLAUDE)
        assert result is not None
        assert result[0] == "comment_mention"

    def test_comment_by_bot_returns_none(self):
        event = {"event": "commented", "actor": {"login": "claude[bot]"}, "body": "@claude go"}
        assert _classify_trigger(event, CLAUDE) is None

    def test_label_trigger(self):
        event = {"event": "labeled", "actor": {"login": "human"}, "label": {"name": "claude"}}
        result = _classify_trigger(event, CLAUDE)
        assert result is not None
        assert result[0] == "label"

    def test_assignment_to_bot(self):
        event = {"event": "assigned", "actor": {"login": "human"}, "assignee": {"login": "devin-ai-integration[bot]"}}
        result = _classify_trigger(event, DEVIN)
        assert result is not None
        assert result[0] == "issue_assignment"

    def test_assignment_to_human_returns_none(self):
        event = {"event": "assigned", "actor": {"login": "pm"}, "assignee": {"login": "alice"}}
        assert _classify_trigger(event, CLAUDE) is None

    def test_unrelated_event_returns_none(self):
        event = {"event": "renamed", "actor": {"login": "human"}}
        assert _classify_trigger(event, CLAUDE) is None


# ---------------------------------------------------------------------------
# _find_trigger_for_issue
# ---------------------------------------------------------------------------

class TestFindTriggerForIssue:
    def test_finds_comment_mention_trigger(self):
        # Bot opened PR at ts=1000, trigger comment at ts=900
        timeline = [
            {"event": "commented", "actor": {"login": "human"}, "body": "Hey @claude please fix this", "created_at": "2026-04-01T00:00:00Z"},
            {"event": "commented", "actor": {"login": "claude[bot]"}, "body": "On it!", "created_at": "2026-04-01T01:00:00Z"},
        ]
        trigger_ts = _parse_ts("2026-04-01T01:30:00Z")  # bot first active

        def mock_gh(method, path, token, timeout=20):
            if "timeline" in path:
                return (200, timeline)
            return (200, [])

        with patch("agent_fleet.invocation._gh", mock_gh):
            result = _find_trigger_for_issue("acme/api", 1, CLAUDE, trigger_ts, "tok")
        assert result is not None
        assert result[0] == "comment_mention"

    def test_ignores_trigger_after_bot_activation(self):
        # Trigger comment came AFTER the bot acted — should be ignored
        trigger_ts = _parse_ts("2026-04-01T01:00:00Z")
        timeline = [
            {"event": "commented", "actor": {"login": "human"}, "body": "@claude fix this", "created_at": "2026-04-01T02:00:00Z"},  # after bot
        ]

        def mock_gh(method, path, token, timeout=20):
            return (200, timeline) if "timeline" in path else (200, [])

        with patch("agent_fleet.invocation._gh", mock_gh):
            result = _find_trigger_for_issue("acme/api", 1, CLAUDE, trigger_ts, "tok")
        assert result is None

    def test_graceful_on_404(self):
        def mock_gh(method, path, token, timeout=20):
            return (404, None)

        with patch("agent_fleet.invocation._gh", mock_gh):
            result = _find_trigger_for_issue("acme/api", 99, CLAUDE, 1000.0, "tok")
        assert result is None

    def test_picks_closest_trigger_before_bot(self):
        """Multiple valid triggers — the most recent one should win."""
        trigger_ts = _parse_ts("2026-04-01T05:00:00Z")
        timeline = [
            {"event": "labeled", "actor": {"login": "pm"}, "label": {"name": "claude"}, "created_at": "2026-04-01T01:00:00Z"},
            {"event": "commented", "actor": {"login": "eng"}, "body": "@claude please look", "created_at": "2026-04-01T04:00:00Z"},
        ]

        def mock_gh(method, path, token, timeout=20):
            return (200, timeline) if "timeline" in path else (200, [])

        with patch("agent_fleet.invocation._gh", mock_gh):
            result = _find_trigger_for_issue("acme/api", 1, CLAUDE, trigger_ts, "tok")
        assert result is not None
        # The comment at 04:00 is more recent than the label at 01:00
        assert result[0] == "comment_mention"


# ---------------------------------------------------------------------------
# learn_invocation_pattern
# ---------------------------------------------------------------------------

class TestLearnInvocationPattern:
    def _pr(self, number: int, bot_login: str, body: str = "", created_at: str = "2026-04-01T00:00:00Z") -> dict:
        return {
            "number": number,
            "user": {"login": bot_login},
            "body": body,
            "created_at": created_at,
        }

    def test_no_token_returns_unchanged_profile(self):
        profile = AgentProfile(id="claude-code", confidence="low")
        result = learn_invocation_pattern(profile, ["acme/api"], token="")
        assert result.confidence == "low"
        assert result.observed_invocation.primary is None

    def test_learns_comment_mention_pattern(self):
        pr = self._pr(42, "claude[bot]", body="Closes #10")
        trigger_ts = _parse_ts("2026-04-01T00:00:00Z")
        timeline = [
            {"event": "commented", "actor": {"login": "human"}, "body": "@claude please fix", "created_at": "2026-03-31T23:00:00Z"},
        ]

        def paginate_mock(path, token, max_pages=5):
            if "/pulls" in path:
                return [pr]
            return []

        def gh_mock(method, path, token, timeout=20):
            if "timeline" in path:
                return (200, timeline)
            if "/search/issues" in path:
                return (200, {"items": []})
            return (200, [])

        profile = AgentProfile(id="claude-code")
        with patch("agent_fleet.invocation._gh_paginate", paginate_mock), \
             patch("agent_fleet.invocation._gh", gh_mock):
            result = learn_invocation_pattern(profile, ["acme/api"], token="tok")

        assert result.observed_invocation.primary is not None
        assert result.observed_invocation.primary.type == "comment_mention"

    def test_high_confidence_requires_5_observations_and_70pct(self):
        # Create 7 PRs all triggered by comment_mention = 100% share, 7 count → high
        prs = [self._pr(i, "claude[bot]", body=f"Closes #{i+100}") for i in range(1, 8)]
        timeline = [
            {"event": "commented", "actor": {"login": "human"}, "body": "@claude please fix", "created_at": "2026-03-31T23:00:00Z"},
        ]

        def paginate_mock(path, token, max_pages=5):
            return prs if "/pulls" in path else []

        def gh_mock(method, path, token, timeout=20):
            if "timeline" in path:
                return (200, timeline)
            if "/search/issues" in path:
                return (200, {"items": []})
            return (200, [])

        profile = AgentProfile(id="claude-code")
        with patch("agent_fleet.invocation._gh_paginate", paginate_mock), \
             patch("agent_fleet.invocation._gh", gh_mock):
            result = learn_invocation_pattern(profile, ["acme/api"], token="tok")

        assert result.confidence == "high"

    def test_medium_confidence_at_3_observations(self):
        prs = [self._pr(i, "claude[bot]", body=f"Closes #{i+100}") for i in range(1, 4)]
        timeline = [
            {"event": "commented", "actor": {"login": "human"}, "body": "@claude fix", "created_at": "2026-03-31T23:00:00Z"},
        ]

        def paginate_mock(path, token, max_pages=5):
            return prs if "/pulls" in path else []

        def gh_mock(method, path, token, timeout=20):
            if "timeline" in path:
                return (200, timeline)
            if "/search/issues" in path:
                return (200, {"items": []})
            return (200, [])

        profile = AgentProfile(id="claude-code")
        with patch("agent_fleet.invocation._gh_paginate", paginate_mock), \
             patch("agent_fleet.invocation._gh", gh_mock):
            result = learn_invocation_pattern(profile, ["acme/api"], token="tok")

        assert result.confidence == "medium"

    def test_no_prs_found_returns_unchanged(self):
        def paginate_mock(path, token, max_pages=5):
            return []

        def gh_mock(method, path, token, timeout=20):
            if "/search/issues" in path:
                return (200, {"items": []})
            return (200, [])

        profile = AgentProfile(id="claude-code", confidence="medium")
        with patch("agent_fleet.invocation._gh_paginate", paginate_mock), \
             patch("agent_fleet.invocation._gh", gh_mock):
            result = learn_invocation_pattern(profile, ["acme/api"], token="tok")

        assert result.confidence == "medium"
        assert result.observed_invocation.primary is None

    def test_custom_agent_skipped(self):
        profile = AgentProfile(id="custom:internal-bot")
        result = learn_invocation_pattern(profile, ["acme/api"], token="tok")
        assert result is profile  # returned unchanged since no registry entry
