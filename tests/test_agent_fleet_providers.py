"""Tests for agent_fleet DelegationProvider adapters."""

from __future__ import annotations

from unittest.mock import patch

import agent_fleet.providers  # noqa: F401 - imports built-ins for registration
from agent_fleet.providers import registry
from agent_fleet.providers.base import DelegationHandle, DelegationState
from agent_fleet.providers.github_default import GithubDefaultProvider
from agent_fleet.watcher import TaskStatus


def _handle() -> DelegationHandle:
    return DelegationHandle(
        provider="github_default",
        data={"repo": "acme/api", "issue_number": 10, "task_id": "t1", "agent_id": "claude-code"},
    )


def _issue_body() -> str:
    return (
        "<!-- dash-delegation: v1 -->\n"
        "<!-- dash-task-id: t1 -->\n"
        "<!-- dash-agent: claude-code -->\n"
        "<!-- dash-created-at: 2026-04-30T10:00:00Z -->\n"
        "## Problem\nFix it.\n"
    )


def test_builtin_providers_register_on_package_import():
    assert "github_default" in registry.list_names()
    assert "multica" in registry.list_names()


def test_github_status_open_issue_without_pr_maps_to_pending():
    provider = GithubDefaultProvider("tenant")
    provider.set_token("tok")

    def gh(method, path, token, body=None, timeout=30):
        if path.endswith("/issues/10"):
            return (200, {
                "number": 10,
                "state": "open",
                "body": _issue_body(),
                "created_at": "2026-04-30T10:00:00Z",
                "updated_at": "2026-04-30T10:10:00Z",
            })
        if "timeline" in path:
            return (200, [])
        if "/pulls?" in path:
            return (200, [])
        return (200, [])

    with patch("agent_fleet.watcher._gh", gh):
        status = provider.status(_handle())

    assert status.state == DelegationState.PENDING
    assert status.raw["task_status"] == TaskStatus.DELEGATED
    assert status.raw["task_id"] == "t1"


def test_github_status_open_pr_without_review_maps_to_pr_opened():
    provider = GithubDefaultProvider("tenant")
    provider.set_token("tok")

    def gh(method, path, token, body=None, timeout=30):
        if path.endswith("/issues/10"):
            return (200, {
                "number": 10,
                "state": "open",
                "body": _issue_body(),
                "created_at": "2026-04-30T10:00:00Z",
                "updated_at": "2026-04-30T10:10:00Z",
            })
        if "timeline" in path:
            return (200, [])
        if "/pulls?" in path:
            return (200, [{
                "number": 42,
                "body": "Closes #10",
                "user": {"login": "codex"},
                "created_at": "2026-04-30T10:20:00Z",
            }])
        if path.endswith("/pulls/42"):
            return (200, {
                "number": 42,
                "state": "open",
                "merged": False,
                "title": "Fix it",
                "html_url": "https://github.com/acme/api/pull/42",
                "created_at": "2026-04-30T10:20:00Z",
                "updated_at": "2026-04-30T10:25:00Z",
            })
        if path.endswith("/issues/42/comments"):
            return (200, [])
        return (200, [])

    with patch("agent_fleet.watcher._gh", gh):
        status = provider.status(_handle())

    assert status.state == DelegationState.RUNNING
    assert status.raw["task_status"] == TaskStatus.PR_OPENED
    assert status.raw["pr_number"] == 42


def test_github_status_dash_approved_pr_maps_to_review_approved():
    provider = GithubDefaultProvider("tenant")
    provider.set_token("tok")

    def gh(method, path, token, body=None, timeout=30):
        if path.endswith("/issues/10"):
            return (200, {
                "number": 10,
                "state": "open",
                "body": _issue_body(),
                "created_at": "2026-04-30T10:00:00Z",
                "updated_at": "2026-04-30T10:10:00Z",
            })
        if "timeline" in path:
            return (200, [])
        if "/pulls?" in path:
            return (200, [{
                "number": 42,
                "body": "Closes #10",
                "user": {"login": "codex"},
                "created_at": "2026-04-30T10:20:00Z",
            }])
        if path.endswith("/pulls/42"):
            return (200, {
                "number": 42,
                "state": "open",
                "merged": False,
                "title": "Fix it",
                "html_url": "https://github.com/acme/api/pull/42",
                "created_at": "2026-04-30T10:20:00Z",
                "updated_at": "2026-04-30T10:25:00Z",
            })
        if path.endswith("/issues/42/comments"):
            return (200, [{
                "created_at": "2026-04-30T10:30:00Z",
                "body": (
                    "## Dash Review\n\n"
                    "**Verdict**: Approve\n"
                    "**Summary**: all good\n\n"
                    "### Acceptance Criteria\n"
                    "- ✅ **Add tests**\n"
                ),
            }])
        return (200, [])

    with patch("agent_fleet.watcher._gh", gh):
        status = provider.status(_handle())

    assert status.state == DelegationState.REVIEW
    assert status.raw["task_status"] == TaskStatus.APPROVED
    assert status.raw["review"].verdict == "approve"


def test_github_cancel_posts_comment_and_closes_issue():
    """cancel() with a reason posts a Dash Cancelled comment, then PATCHes
    the issue closed with state_reason='not_planned'."""
    provider = GithubDefaultProvider("tenant")
    provider.set_token("tok")

    calls = []

    def gh(method, path, token, body=None, timeout=30):
        calls.append({"method": method, "path": path, "body": body})
        if method == "POST" and "/comments" in path:
            return (201, {"id": 1})
        if method == "PATCH" and path.endswith("/issues/10"):
            return (200, {"number": 10, "state": "closed"})
        return (200, {})

    with patch("agent_fleet.watcher._gh", gh):
        provider.cancel(_handle(), reason="superseded by issue #99")

    # Comment posted first with the reason in the body
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].endswith("/issues/10/comments")
    assert "Dash Cancelled" in calls[0]["body"]["body"]
    assert "superseded" in calls[0]["body"]["body"]
    # Then issue closed with the right state_reason
    assert calls[1]["method"] == "PATCH"
    assert calls[1]["path"].endswith("/issues/10")
    assert calls[1]["body"] == {"state": "closed", "state_reason": "not_planned"}


def test_github_cancel_without_reason_skips_comment():
    """No reason => no comment, just close. Avoids cluttering the timeline
    when the cancel is e.g. a deduplication and a comment would be noise."""
    provider = GithubDefaultProvider("tenant")
    provider.set_token("tok")

    calls = []

    def gh(method, path, token, body=None, timeout=30):
        calls.append({"method": method, "path": path})
        if method == "PATCH":
            return (200, {})
        return (200, {})

    with patch("agent_fleet.watcher._gh", gh):
        provider.cancel(_handle())

    methods = [c["method"] for c in calls]
    assert "POST" not in methods
    assert methods.count("PATCH") == 1


def test_github_cancel_raises_provider_error_on_close_failure():
    """If GH refuses the close, surface a ProviderError so the supervisor's
    refile/retry logic can react instead of silently believing it succeeded."""
    from agent_fleet.providers.base import ProviderError

    provider = GithubDefaultProvider("tenant")
    provider.set_token("tok")

    def gh(method, path, token, body=None, timeout=30):
        if method == "PATCH":
            return (403, {"message": "forbidden"})
        return (201, {})

    with patch("agent_fleet.watcher._gh", gh):
        try:
            provider.cancel(_handle(), reason="x")
        except ProviderError as e:
            assert "403" in str(e)
        else:
            raise AssertionError("expected ProviderError")
