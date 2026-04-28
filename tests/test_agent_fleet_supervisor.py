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
    def test_skips_unhandled_status(self):
        # IN_PROGRESS / REVIEWED are not currently mapped to handlers.
        result = WatchResult(
            issue_number=1, task_id="t1", agent_id="claude-code",
            status=TaskStatus.REVIEWED,
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


class TestHandleDelegated:
    def _setup(self, *, created_at, ping_count=0):
        """Build the routes a stale-delegation run hits."""
        comments = [
            {"body": "## Dash Re-ping\n\nfirst nudge"} for _ in range(ping_count)
        ]
        # _handle_delegated reads the issue body too (already loaded in run_supervisor)
        return _gh_mock({
            f"/issues/1/comments": (200, comments),
            f"/issues/1": (200, {
                "html_url": "https://github.com/acme/api/issues/1",
                "title": "Fix login",
                "created_at": created_at,
            }),
        })

    def test_re_pings_when_stale_with_no_pings(self):
        # 2 hours ago, expected window is 30 min for claude-code → NUDGE
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = WatchResult(
            issue_number=1, task_id="t1", agent_id="claude-code",
            status=TaskStatus.DELEGATED,
        )
        gh_calls = []

        def gh(method, path, token, body=None, timeout=30):
            gh_calls.append((method, path))
            if "/issues/1/comments" in path and method == "GET":
                return (200, [])
            if "/issues/1/comments" in path and method == "POST":
                return (201, {})
            if "/issues/1" in path:
                return (200, {
                    "html_url": "https://github.com/acme/api/issues/1",
                    "title": "Fix login",
                    "created_at": old,
                })
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )

        kinds = report.by_kind()
        assert "re_ping" in kinds
        # We posted exactly one comment with the marker
        post_calls = [c for c in gh_calls if c[0] == "POST" and "/comments" in c[1]]
        assert len(post_calls) == 1

    def test_marks_stalled_after_max_retries(self):
        # 25 hours ago + 2 prior re-pings → STALLED
        from datetime import datetime, timedelta, timezone
        very_old = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = WatchResult(
            issue_number=1, task_id="t1", agent_id="claude-code",
            status=TaskStatus.DELEGATED,
        )

        def gh(method, path, token, body=None, timeout=30):
            if "/issues/1/comments" in path and method == "GET":
                return (200, [
                    {"body": "## Dash Re-ping\n\n1"},
                    {"body": "## Dash Re-ping\n\n2"},
                ])
            if "/issues/1/comments" in path and method == "POST":
                return (201, {})
            if "/issues/1" in path:
                return (200, {
                    "html_url": "https://github.com/acme/api/issues/1",
                    "title": "Fix login",
                    "created_at": very_old,
                })
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert "mark_stalled" in report.by_kind()

    def test_skips_when_already_marked_stalled(self):
        from datetime import datetime, timedelta, timezone
        very_old = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = WatchResult(
            issue_number=1, task_id="t1", agent_id="claude-code",
            status=TaskStatus.DELEGATED,
        )

        def gh(method, path, token, body=None, timeout=30):
            if "/issues/1/comments" in path and method == "GET":
                return (200, [{"body": "## Dash Stalled\n\nflagged"}])
            if "/issues/1" in path:
                return (200, {
                    "html_url": "https://github.com/acme/api/issues/1",
                    "title": "Fix login",
                    "created_at": very_old,
                })
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert "skip" in report.by_kind()
        assert any("already flagged" in a.detail for a in report.actions)


class TestHandleChangesRequested:
    def test_posts_feedback_with_unmet_criteria(self):
        review = ReviewResult(
            verdict="request_changes",
            criteria=[
                CriterionResult(text="Add tests", status="unmet"),
                CriterionResult(text="Fix race condition", status="unmet"),
                CriterionResult(text="Update docs", status="met"),
            ],
            summary="needs work",
        )
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="codex",
            status=TaskStatus.CHANGES_REQUESTED, pr_number=42,
            review=review,
        )
        posted = []

        def gh(method, path, token, body=None, timeout=30):
            if "/issues/42/comments" in path and method == "GET":
                return (200, [])
            if "/issues/42/comments" in path and method == "POST":
                posted.append(body)
                return (201, {})
            if "/issues/10" in path:
                return (200, {"body": "<!-- dash-delegation -->", "state": "open"})
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert "post_feedback" in report.by_kind()
        assert len(posted) == 1
        assert "Add tests" in posted[0]["body"]
        assert "Fix race condition" in posted[0]["body"]
        assert "Update docs" not in posted[0]["body"]
        assert "@codex" in posted[0]["body"]

    def test_stops_after_max_retries(self):
        review = ReviewResult(
            verdict="request_changes",
            criteria=[CriterionResult(text="x", status="unmet")],
        )
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="codex",
            status=TaskStatus.CHANGES_REQUESTED, pr_number=42,
            review=review,
        )
        prior = [
            {"body": "## Dash Feedback\n\nround 1"},
            {"body": "## Dash Feedback\n\nround 2"},
        ]

        def gh(method, path, token, body=None, timeout=30):
            if "/issues/42/comments" in path and method == "GET":
                return (200, prior)
            if "/issues/10" in path:
                return (200, {"body": ""})
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert "skip" in report.by_kind()
        assert any("max_retries" in a.detail for a in report.actions)


class TestHandleApproved:
    def test_default_on_approve_skips_with_message(self):
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="claude-code",
            status=TaskStatus.APPROVED, pr_number=42,
        )
        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", _gh_mock({
                 "/pulls/42": (200, {"merged": False, "mergeable": True}),
                 "/issues/10": (200, {"body": ""}),
             })):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert any("awaiting human merge" in a.detail for a in report.actions)

    def test_auto_merge_calls_merge_endpoint(self):
        from agent_fleet.workflow import default_workflow
        wf = default_workflow()
        wf.review.on_approve = "auto-merge"

        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="claude-code",
            status=TaskStatus.APPROVED, pr_number=42,
        )
        merge_called = []

        def gh(method, path, token, body=None, timeout=30):
            if method == "PUT" and "/pulls/42/merge" in path:
                merge_called.append(body)
                return (200, {"merged": True})
            if "/pulls/42" in path:
                return (200, {"merged": False, "mergeable": True})
            if "/issues/10" in path:
                return (200, {"body": ""})
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
                workflow=wf,
            )
        assert "auto_merge" in report.by_kind()
        assert len(merge_called) == 1

    def test_skip_when_pr_already_merged(self):
        result = WatchResult(
            issue_number=10, task_id="t1", agent_id="claude-code",
            status=TaskStatus.APPROVED, pr_number=42,
        )
        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", _gh_mock({
                 "/pulls/42": (200, {"merged": True}),
                 "/issues/10": (200, {"body": ""}),
             })):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok",
            )
        assert any("already merged" in a.detail for a in report.actions)


class TestRefileDelegation:
    def _issue_body(self):
        return (
            "<!-- dash-delegation: v1 -->\n"
            "<!-- dash-task-id: t-123 -->\n"
            "<!-- dash-agent: claude-code -->\n"
            "<!-- dash-created-at: 2026-01-01T00:00:00Z -->\n"
            "\n## Problem\n\nLogin is broken.\n"
            "\n## Acceptance Criteria\n- [ ] Add tests\n- [ ] Fix bug\n"
            "\n## Context\nAffects auth module.\n"
        )

    def test_refile_succeeds(self):
        from agent_fleet.supervisor import refile_delegation
        from agent_fleet.workflow import default_workflow

        wf = default_workflow()
        wf.escalation.fallback_chain = ["claude-code", "codex"]

        recorded = {"posts": [], "patches": [], "comments": []}

        def gh(method, path, token, body=None, timeout=30):
            if method == "GET" and path.endswith("/issues/5"):
                return (200, {
                    "title": "[Dash] Login broken",
                    "body": self._issue_body(),
                    "state": "open",
                    "html_url": "https://github.com/acme/api/issues/5",
                })
            if method == "POST" and "/issues" in path and "/comments" not in path:
                recorded["posts"].append(body)
                return (201, {
                    "number": 99,
                    "html_url": "https://github.com/acme/api/issues/99",
                })
            if method == "POST" and "/comments" in path:
                recorded["comments"].append((path, body))
                return (201, {})
            if method == "PATCH" and path.endswith("/issues/5"):
                recorded["patches"].append(body)
                return (200, {})
            return (200, [])

        with patch("agent_fleet.supervisor._gh", gh):
            rf = refile_delegation(
                repo="acme/api", issue_number=5, token="tok", workflow=wf,
            )

        assert rf.ok is True
        assert rf.new_issue_number == 99
        assert rf.new_agent_id == "codex"  # next after claude-code in chain
        assert recorded["posts"], "should have created a new issue"
        new_body = recorded["posts"][0]["body"]
        assert "Login is broken" in new_body
        assert "Add tests" in new_body
        assert "Refiled from #5" in new_body
        # old issue gets refile comment + close
        assert any("Dash Refiled" in c[1]["body"] for c in recorded["comments"])
        assert any(p.get("state") == "closed" and p.get("state_reason") == "not_planned"
                   for p in recorded["patches"])

    def test_refile_with_explicit_target(self):
        from agent_fleet.supervisor import refile_delegation
        from agent_fleet.workflow import default_workflow

        wf = default_workflow()
        wf.escalation.fallback_chain = []  # no chain — must use override

        def gh(method, path, token, body=None, timeout=30):
            if method == "GET" and path.endswith("/issues/5"):
                return (200, {
                    "title": "[Dash] T",
                    "body": self._issue_body(),
                    "state": "open",
                    "html_url": "x",
                })
            if method == "POST" and "/issues" in path and "/comments" not in path:
                return (201, {"number": 100, "html_url": "x"})
            return (200, {})

        with patch("agent_fleet.supervisor._gh", gh):
            rf = refile_delegation(
                repo="acme/api", issue_number=5, token="tok",
                workflow=wf, target_agent_id="devin",
            )
        assert rf.ok is True
        assert rf.new_agent_id == "devin"

    def test_refile_rejects_closed_issue(self):
        from agent_fleet.supervisor import refile_delegation
        from agent_fleet.workflow import default_workflow

        with patch("agent_fleet.supervisor._gh", _gh_mock({
            "/issues/5": (200, {"state": "closed", "body": self._issue_body()}),
        })):
            rf = refile_delegation(
                repo="acme/api", issue_number=5, token="tok",
                workflow=default_workflow(),
            )
        assert rf.ok is False
        assert "already closed" in (rf.error or "")

    def test_refile_rejects_unknown_agent(self):
        from agent_fleet.supervisor import refile_delegation
        from agent_fleet.workflow import default_workflow

        wf = default_workflow()

        with patch("agent_fleet.supervisor._gh", _gh_mock({
            "/issues/5": (200, {"state": "open", "body": self._issue_body()}),
        })):
            rf = refile_delegation(
                repo="acme/api", issue_number=5, token="tok",
                workflow=wf, target_agent_id="some-fake-agent",
            )
        assert rf.ok is False
        assert "unknown agent" in (rf.error or "")

    def test_refile_exhausted_chain(self):
        from agent_fleet.supervisor import refile_delegation
        from agent_fleet.workflow import default_workflow

        wf = default_workflow()
        # Current agent is last in the chain → no next
        wf.escalation.fallback_chain = ["claude-code"]

        with patch("agent_fleet.supervisor._gh", _gh_mock({
            "/issues/5": (200, {"state": "open", "body": self._issue_body()}),
        })):
            rf = refile_delegation(
                repo="acme/api", issue_number=5, token="tok", workflow=wf,
            )
        assert rf.ok is False
        assert "exhausted" in (rf.error or "")


class TestAutoEscalate:
    """Wire auto_escalate=True in the workflow → handle_delegated triggers refile."""

    def test_auto_escalate_calls_refile(self):
        from datetime import datetime, timedelta, timezone
        from agent_fleet.workflow import default_workflow

        wf = default_workflow()
        wf.escalation.auto_escalate = True
        wf.escalation.fallback_chain = ["claude-code", "codex"]

        very_old = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = WatchResult(
            issue_number=5, task_id="t-123", agent_id="claude-code",
            status=TaskStatus.DELEGATED,
        )

        issue_body = (
            "<!-- dash-delegation: v1 -->\n"
            "<!-- dash-task-id: t-123 -->\n"
            "<!-- dash-agent: claude-code -->\n"
            "<!-- dash-created-at: 2026-01-01T00:00:00Z -->\n"
            "## Problem\nA bug.\n## Acceptance Criteria\n- [ ] Fix it\n"
        )

        def gh(method, path, token, body=None, timeout=30):
            if method == "GET" and path.endswith("/issues/5/comments"):
                return (200, [])
            if method == "GET" and path.endswith("/issues/5"):
                return (200, {
                    "title": "[Dash] T",
                    "body": issue_body,
                    "state": "open",
                    "created_at": very_old,
                    "html_url": "x",
                })
            if method == "POST" and "/issues" in path and "/comments" not in path:
                return (201, {"number": 88, "html_url": "x"})
            if method == "PATCH" and path.endswith("/issues/5"):
                return (200, {})
            if method == "POST" and "/comments" in path:
                return (201, {})
            return (200, [])

        with patch("agent_fleet.supervisor.watch_repo_delegations", return_value=[result]), \
             patch("agent_fleet.supervisor._gh", gh):
            report = run_supervisor(
                tenant_id="t", repos_list=["acme/api"], token="tok", workflow=wf,
            )
        assert "auto_refile" in report.by_kind()
        action = next(a for a in report.actions if a.kind == "auto_refile")
        assert "#88" in action.detail
        assert "codex" in action.detail


class TestSupervisorReport:
    def test_by_kind_aggregates(self):
        r = SupervisorReport(tenant_id="t", workflow_revision=0)
        r.actions.append(SupervisorAction(repo="r", issue_number=1, kind="auto_review"))
        r.actions.append(SupervisorAction(repo="r", issue_number=2, kind="auto_review"))
        r.actions.append(SupervisorAction(repo="r", issue_number=3, kind="skip"))
        assert r.by_kind() == {"auto_review": 2, "skip": 1}
