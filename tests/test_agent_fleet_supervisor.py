"""Tests for agent_fleet.supervisor."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_fleet.supervisor import (
    SupervisorAction,
    SupervisorReport,
    _DASH_REVIEW_MARKER,
    _has_existing_dash_review,
    _hook_close_dash_issue,
    _hook_resolve_brief_action,
    run_supervisor,
)
from agent_fleet.watcher import (
    CriterionResult,
    ReviewResult,
    TaskStatus,
    WatchResult,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _gh_mock(routes: dict):
    """Return a _gh stand-in that resolves by longest matching path prefix."""
    def fn(method, path, token, body=None, timeout=30):
        matches = [(k, v) for k, v in routes.items() if k in path]
        if not matches:
            return (200, [])
        return max(matches, key=lambda x: len(x[0]))[1]
    return fn


# ---------------------------------------------------------------------------
# review-comment idempotency
# ---------------------------------------------------------------------------

class TestExistingDashReview:
    def test_finds_existing_marker(self):
        comments = [{"body": "lgtm"}, {"body": f"{_DASH_REVIEW_MARKER}\n\nverdict: approve"}]
        with patch("agent_fleet.supervisor._gh", _gh_mock({"/comments": (200, comments)})):
            assert _has_existing_dash_review("acme/api", 5, "tok") is True

    def test_returns_false_when_absent(self):
        comments = [{"body": "+1"}, {"body": "we should refactor this"}]
        with patch("agent_fleet.supervisor._gh", _gh_mock({"/comments": (200, comments)})):
            assert _has_existing_dash_review("acme/api", 5, "tok") is False

    def test_returns_false_on_error(self):
        with patch("agent_fleet.supervisor._gh", _gh_mock({"/comments": (500, None)})):
            assert _has_existing_dash_review("acme/api", 5, "tok") is False


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------

class TestCloseDashIssue:
    def test_closes_and_comments(self):
        gh_calls = []

        def gh(method, path, token, body=None, timeout=30):
            gh_calls.append((method, path, body))
            if method == "PATCH":
                return (200, {})
            if method == "POST":
                return (201, {})
            return (200, {})

        with patch("agent_fleet.supervisor._gh", gh):
            action = _hook_close_dash_issue({
                "repo": "acme/api", "issue_number": 7,
                "token": "tok", "pr_number": 12,
            })
        assert action.kind == "close_dash_issue"
        assert action.error is None
        assert any(c[0] == "PATCH" and "/issues/7" in c[1] for c in gh_calls)
        assert any(c[0] == "POST" and "/issues/7/comments" in c[1] for c in gh_calls)


class TestResolveBriefAction:
    def test_skips_when_no_metadata(self):
        action = _hook_resolve_brief_action({
            "repo": "acme/api", "issue_number": 7,
            "tenant_id": "t", "token": "tok",
        })
        assert action.kind == "resolve_brief_action"
        assert "no brief_action_id" in action.detail
        assert action.error is None


# ---------------------------------------------------------------------------
# state machine routing
# ---------------------------------------------------------------------------

class TestRunSupervisor:
    def test_skips_when_status_not_handled(self):
        result = WatchResult(
            issue_number=1, task_id="t1", agent_id="claude-code",
            status=TaskStatus.DELEGATED,
        )
        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", _gh_mock({"/issues/1": (200, {"body": ""})})):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert report.delegations_seen == 1
        assert report.by_kind() == {"skip": 1}
        assert "not handled" in report.actions[0].detail

    def test_pr_opened_triggers_auto_review(self):
        # PR comments live at /issues/<pr_number>/comments — keep the issue's
        # parent body route distinct.
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="claude-code",
            status=TaskStatus.PR_OPENED, pr_number=42,
        )
        body = "## Acceptance Criteria\n- [ ] Add tests\n- [ ] Update docs\n"
        review = ReviewResult(
            verdict="approve",
            criteria=[
                CriterionResult(text="Add tests", status="met"),
                CriterionResult(text="Update docs", status="met"),
            ],
            summary="all good",
        )
        recorded = []
        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", _gh_mock({
                 "/issues/42/comments": (200, []),                  # PR has no Dash review yet
                 "/issues/10": (200, {"body": body, "state": "open"}),  # parent issue body
             })), \
             patch("agent_fleet.supervisor.review_pr_against_criteria", return_value=review), \
             patch("agent_fleet.supervisor.post_review_comment", lambda *a, **kw: recorded.append("post")), \
             patch("agent_fleet.supervisor.update_issue_checkboxes", lambda *a, **kw: recorded.append("update")):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert "auto_review" in report.by_kind()
        assert "post" in recorded and "update" in recorded
        assert "verdict=approve" in report.actions[-1].detail

    def test_pr_opened_idempotent_when_already_reviewed(self):
        """If a Dash review already exists on the PR, don't post another."""
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="claude-code",
            status=TaskStatus.PR_OPENED, pr_number=42,
        )
        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", _gh_mock({
                 "/issues/42/comments": (200, [{"body": _DASH_REVIEW_MARKER + "\n..."}]),
                 "/issues/10": (200, {"body": ""}),
             })), \
             patch("agent_fleet.supervisor.review_pr_against_criteria") as mock_review:
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        mock_review.assert_not_called()
        assert "skip" in report.by_kind()
        assert "already has a Dash review" in report.actions[-1].detail

    def test_resolved_skips_when_issue_already_closed(self):
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="claude-code",
            status=TaskStatus.RESOLVED, pr_number=42,
        )
        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", _gh_mock({
                 "/issues/10": (200, {"body": "<!-- dash-delegation: v1 -->", "state": "closed"}),
             })):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert "already closed" in report.actions[-1].detail


class TestSupervisorReport:
    def test_by_kind_aggregates(self):
        r = SupervisorReport(tenant_id="t", workflow_revision=0)
        r.actions.append(SupervisorAction(repo="r", issue_number=1, kind="auto_review"))
        r.actions.append(SupervisorAction(repo="r", issue_number=2, kind="auto_review"))
        r.actions.append(SupervisorAction(repo="r", issue_number=3, kind="skip"))
        assert r.by_kind() == {"auto_review": 2, "skip": 1}
