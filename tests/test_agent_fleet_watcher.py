"""Tests for agent_fleet.watcher (GitHub issue #14)."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from agent_fleet.watcher import (
    CriterionResult,
    ReviewResult,
    TaskStatus,
    _evaluate_criterion,
    _pr_links_issue,
    _build_review_comment,
    _update_checkbox_line,
    link_pr_to_task,
    post_review_comment,
    review_pr_against_criteria,
    update_issue_checkboxes,
    watch_repo_delegations,
)
from agent_fleet.delegation import DelegationTask, build_delegation_issue
from agent_fleet.profile import AgentProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gh(responses: dict):
    def _mock(method, path, token, body=None, timeout=30):
        matches = [(k, v) for k, v in responses.items() if k in path]
        if matches:
            return max(matches, key=lambda x: len(x[0]))[1]
        return (200, [])
    return _mock


# ---------------------------------------------------------------------------
# _pr_links_issue
# ---------------------------------------------------------------------------

class TestPrLinksIssue:
    def test_closes(self):
        assert _pr_links_issue("Closes #42", 42) is True

    def test_fixes(self):
        assert _pr_links_issue("Fixes #7", 7) is True

    def test_wrong_number(self):
        assert _pr_links_issue("Closes #42", 43) is False

    def test_empty_body(self):
        assert _pr_links_issue("", 1) is False


# ---------------------------------------------------------------------------
# _evaluate_criterion
# ---------------------------------------------------------------------------

class TestEvaluateCriterion:
    def test_met_when_terms_in_diff(self):
        diff = "+ tracking_event('funnel', user_id)\n"
        cr = _evaluate_criterion("Add funnel event tracking", diff, "")
        assert cr.status == "met"

    def test_unclear_when_only_in_pr_body(self):
        cr = _evaluate_criterion("Add funnel tracking", "", "I added funnel tracking in the code.")
        assert cr.status == "unclear"

    def test_unmet_when_nowhere(self):
        cr = _evaluate_criterion("Add funnel event tracking", "def hello(): pass", "Nothing here.")
        assert cr.status == "unmet"

    def test_empty_criterion_is_unclear(self):
        cr = _evaluate_criterion("", "some diff", "")
        assert cr.status == "unclear"


# ---------------------------------------------------------------------------
# _update_checkbox_line
# ---------------------------------------------------------------------------

class TestUpdateCheckboxLine:
    def test_marks_as_checked(self):
        line = "- [ ] Add funnel event tracking"
        result = _update_checkbox_line(line, "Add funnel event tracking", True)
        assert "- [x]" in result

    def test_marks_as_unchecked(self):
        line = "- [x] Add funnel event tracking"
        result = _update_checkbox_line(line, "Add funnel event tracking", False)
        assert "- [ ]" in result

    def test_unrelated_line_unchanged(self):
        line = "- [ ] Unrelated criterion"
        result = _update_checkbox_line(line, "Add funnel event tracking", True)
        assert result == line


# ---------------------------------------------------------------------------
# link_pr_to_task
# ---------------------------------------------------------------------------

class TestLinkPrToTask:
    def test_finds_via_timeline_cross_reference(self):
        timeline = [
            {"event": "cross-referenced", "source": {"issue": {"number": 99, "pull_request": {"url": "..."}}}}
        ]
        def mock_gh(method, path, token, body=None, timeout=30):
            if "timeline" in path:
                return (200, timeline)
            return (200, [])

        with patch("agent_fleet.watcher._gh", mock_gh):
            result = link_pr_to_task(1, "acme/api", (), "tok")
        assert result == 99

    def test_finds_via_pr_body_closes(self):
        prs = [{"number": 55, "body": "Closes #1", "user": {"login": "human"}, "created_at": "2026-04-01T00:00:00Z"}]
        def mock_gh(method, path, token, body=None, timeout=30):
            if "timeline" in path:
                return (200, [])
            if "/pulls" in path:
                return (200, prs)
            return (200, [])

        with patch("agent_fleet.watcher._gh", mock_gh):
            result = link_pr_to_task(1, "acme/api", (), "tok")
        assert result == 55

    def test_finds_via_bot_pr_author(self):
        prs = [{"number": 77, "body": "", "user": {"login": "claude[bot]"}, "created_at": "2026-04-02T00:00:00Z"}]
        def mock_gh(method, path, token, body=None, timeout=30):
            if "timeline" in path:
                return (200, [])
            if "/pulls" in path:
                return (200, prs)
            return (200, [])

        with patch("agent_fleet.watcher._gh", mock_gh):
            result = link_pr_to_task(
                1, "acme/api",
                ("claude[bot]",), "tok",
                issue_created_at="2026-04-01T00:00:00Z",
            )
        assert result == 77

    def test_returns_none_when_no_pr(self):
        def mock_gh(method, path, token, body=None, timeout=30):
            if "timeline" in path:
                return (200, [])
            if "/pulls" in path:
                return (200, [])
            return (200, [])

        with patch("agent_fleet.watcher._gh", mock_gh):
            result = link_pr_to_task(1, "acme/api", (), "tok")
        assert result is None


# ---------------------------------------------------------------------------
# review_pr_against_criteria
# ---------------------------------------------------------------------------

class TestReviewPrAgainstCriteria:
    def _mock_gh_and_diff(self, diff_content: str, pr_body: str = ""):
        def mock_gh(method, path, token, body=None, timeout=30):
            return (200, {"html_url": "https://github.com/acme/api/pull/1", "body": pr_body})

        def mock_diff_fn(repo, pr_number, token):
            return diff_content

        return mock_gh, mock_diff_fn

    def test_all_met_gives_approve(self):
        diff = "+ funnel_tracking(user)\n+ logging.info('drop_off')\n"
        mock_gh, mock_diff = self._mock_gh_and_diff(diff)
        with patch("agent_fleet.watcher._gh", mock_gh), \
             patch("agent_fleet.watcher._gh_diff", mock_diff):
            result = review_pr_against_criteria(1, "acme/api", ["Add funnel tracking", "Add logging"], "tok")
        assert result.verdict == "approve"

    def test_unmet_criterion_gives_request_changes(self):
        diff = "+ some_unrelated_code()\n"
        mock_gh, mock_diff = self._mock_gh_and_diff(diff)
        with patch("agent_fleet.watcher._gh", mock_gh), \
             patch("agent_fleet.watcher._gh_diff", mock_diff):
            result = review_pr_against_criteria(1, "acme/api", ["Add funnel tracking", "Add logging"], "tok")
        assert result.verdict == "request_changes"

    def test_per_criterion_results_present(self):
        diff = "+ funnel_event_tracking()\n"
        mock_gh, mock_diff = self._mock_gh_and_diff(diff)
        with patch("agent_fleet.watcher._gh", mock_gh), \
             patch("agent_fleet.watcher._gh_diff", mock_diff):
            result = review_pr_against_criteria(1, "acme/api", ["Add funnel event tracking", "Add error logging"], "tok")
        assert len(result.criteria) == 2


# ---------------------------------------------------------------------------
# _build_review_comment
# ---------------------------------------------------------------------------

class TestBuildReviewComment:
    def test_contains_verdict_and_criteria(self):
        result = ReviewResult(
            verdict="approve",
            criteria=[CriterionResult(text="Add funnel tracking", status="met", reasoning="Found in diff.")],
            summary="All good.",
        )
        comment = _build_review_comment(result, issue_number=5)
        assert "Dash Review" in comment
        assert "approve" in comment.lower()
        assert "Add funnel tracking" in comment
        assert "#5" in comment

    def test_verdict_emoji_present(self):
        for verdict, emoji in [("approve", "✅"), ("request_changes", "🔄"), ("needs_human", "🧑‍⚖️")]:
            r = ReviewResult(verdict=verdict, criteria=[], summary="")
            assert emoji in _build_review_comment(r, 1)


# ---------------------------------------------------------------------------
# watch_repo_delegations (integration)
# ---------------------------------------------------------------------------

class TestWatchRepoDelegations:
    def test_no_dash_issues_returns_empty(self):
        def mock_gh(method, path, token, body=None, timeout=30):
            if "/search/issues" in path:
                return (200, {"items": []})
            return (200, [])

        with patch("agent_fleet.delegation._gh", mock_gh), \
             patch("agent_fleet.watcher._gh", mock_gh):
            result = watch_repo_delegations("acme/api", "tok")
        assert result == []

    def test_issue_without_pr_returns_delegated_status(self):
        from agent_fleet.delegation import build_delegation_issue, DelegationTask
        from agent_fleet.profile import AgentProfile, ObservedInvocation, ObservedInvocationDetail

        profile = AgentProfile(id="claude-code", enabled=True)
        task = DelegationTask(
            title="Fix bug",
            problem="Bug description",
            acceptance_criteria=["Fix the bug"],
            repo="acme/api",
        )
        _, body, _ = build_delegation_issue(task, profile)
        search_resp = (200, {"items": [{"number": 1, "title": "[Dash] Fix bug", "state": "open", "html_url": "https://github.com/acme/api/issues/1", "body": body}]})

        def mock_delegation_gh(method, path, token, body_data=None, timeout=20):
            if "/search/issues" in path:
                return search_resp
            return (200, [])

        def mock_watcher_gh(method, path, token, body_data=None, timeout=30):
            # No timeline cross-refs, no PRs
            return (200, [])

        with patch("agent_fleet.delegation._gh", mock_delegation_gh), \
             patch("agent_fleet.watcher._gh", mock_watcher_gh), \
             patch("agent_fleet.watcher._gh_diff", lambda *a: ""):
            result = watch_repo_delegations("acme/api", "tok")

        assert len(result) == 1
        assert result[0].status == TaskStatus.DELEGATED
        assert result[0].pr_number is None
