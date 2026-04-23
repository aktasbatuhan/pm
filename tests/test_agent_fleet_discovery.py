"""Tests for agent_fleet.discovery (GitHub issue #11).

Uses unittest.mock to intercept HTTP calls — no real GitHub traffic.
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from agent_fleet.discovery import (
    _Hits,
    _build_observed_invocation,
    _method_b,
    _method_c,
    _method_d,
    discover_external_agents,
    merge_with_existing,
)
from agent_fleet.profile import AgentProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gh(responses: dict):
    """Return a mock _gh function that dispatches on the URL path.

    responses: {path_substring: (status, body)}
    The longest (most specific) matching key wins.
    """
    def _mock(method, path, token, body=None, timeout=20):
        matches = [(k, v) for k, v in responses.items() if k in path]
        if matches:
            return max(matches, key=lambda x: len(x[0]))[1]
        return (200, [])  # default: empty list
    return _mock


def _make_paginate(responses: dict):
    """Return a mock _gh_paginate that dispatches on path substring."""
    def _mock(path_template, token, max_pages=5):
        for key, val in responses.items():
            if key in path_template:
                return val
        return []
    return _mock


# ---------------------------------------------------------------------------
# _Hits and confidence
# ---------------------------------------------------------------------------

class TestHits:
    def test_single_fingerprint_method_gives_medium(self):
        h = _Hits()
        h.hit("claude-code", "fingerprint_pr_author", repo="acme/api", ts="2026-04-01T00:00:00Z", activity_key="prs")
        p = h.to_profile("claude-code")
        assert p.confidence == "medium"

    def test_two_distinct_method_categories_give_high(self):
        h = _Hits()
        h.hit("claude-code", "fingerprint_pr_author")
        h.hit("claude-code", "workflow_scan")
        assert h.to_profile("claude-code").confidence == "high"

    def test_only_installations_gives_low(self):
        h = _Hits()
        h.hit("devin", "org_installations")
        assert h.to_profile("devin").confidence == "low"

    def test_deduplication_by_id(self):
        h = _Hits()
        h.hit("claude-code", "fingerprint_pr_author", activity_key="prs")
        h.hit("claude-code", "fingerprint_pr_author", activity_key="prs")
        p = h.to_profile("claude-code")
        assert p.activity_90d["prs"] == 2
        assert p.detected_via == ["fingerprint_pr_author"]

    def test_repo_deduplication(self):
        h = _Hits()
        h.hit("claude-code", "fingerprint_pr_author", repo="acme/api")
        h.hit("claude-code", "fingerprint_pr_author", repo="acme/api")
        h.hit("claude-code", "fingerprint_pr_author", repo="acme/web")
        p = h.to_profile("claude-code")
        assert sorted(p.primary_repos) == ["acme/api", "acme/web"]

    def test_first_and_last_active_tracking(self):
        h = _Hits()
        h.hit("codex", "fingerprint_pr_author", ts="2026-01-01T00:00:00Z")
        h.hit("codex", "fingerprint_pr_author", ts="2026-04-20T00:00:00Z")
        h.hit("codex", "fingerprint_pr_author", ts="2026-02-15T00:00:00Z")
        p = h.to_profile("codex")
        assert p.first_seen == "2026-01-01T00:00:00Z"
        assert p.last_active == "2026-04-20T00:00:00Z"


class TestBuildObservedInvocation:
    def test_empty_counts_returns_empty(self):
        obs = _build_observed_invocation({})
        assert obs.primary is None

    def test_orders_by_count(self):
        obs = _build_observed_invocation({
            "label": 3,
            "comment_mention": 19,
            "issue_assignment": 1,
        })
        assert obs.primary.type == "comment_mention"
        assert obs.primary.count == 19
        assert obs.secondary.type == "label"
        assert obs.rare.type == "issue_assignment"

    def test_single_invocation(self):
        obs = _build_observed_invocation({"workflow_trigger": 7})
        assert obs.primary.type == "workflow_trigger"
        assert obs.secondary is None
        assert obs.rare is None


# ---------------------------------------------------------------------------
# Method B
# ---------------------------------------------------------------------------

class TestMethodB:
    def test_detects_bot_pr_author(self):
        prs = [{"user": {"login": "claude[bot]"}, "created_at": "2026-04-01T00:00:00Z", "updated_at": "2026-04-01T00:00:00Z", "body": ""}]
        h = _Hits()
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({"/pulls": prs})):
            _method_b(["acme/api"], token="tok", hits=h, lookback_days=90)
        assert "claude-code" in h.agent_ids()
        assert "fingerprint_pr_author" in h.methods_for("claude-code")
        assert h.to_profile("claude-code").activity_90d.get("prs", 0) >= 1

    def test_detects_output_signature_in_pr_body(self):
        prs = [{"user": {"login": "some-human"}, "created_at": "2026-04-01T00:00:00Z", "updated_at": "2026-04-01T00:00:00Z", "body": "Changes look good.\nGenerated with Claude Code\n"}]
        h = _Hits()
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({"/pulls": prs})):
            _method_b(["acme/api"], token="tok", hits=h, lookback_days=90)
        assert "claude-code" in h.agent_ids()
        assert "fingerprint_signature" in h.methods_for("claude-code")

    def test_detects_comment_by_bot(self):
        comments = [{"user": {"login": "devin-ai-integration[bot]"}, "created_at": "2026-04-10T00:00:00Z", "body": "Done!"}]
        h = _Hits()
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({"/issues/comments": comments})):
            _method_b(["acme/api"], token="tok", hits=h, lookback_days=90)
        assert "devin" in h.agent_ids()
        assert "fingerprint_comment" in h.methods_for("devin")

    def test_detects_at_mention_invocation_in_comments(self):
        comments = [{"user": {"login": "dev-human"}, "created_at": "2026-04-10T00:00:00Z", "body": "Hey @claude please fix this bug"}]
        h = _Hits()
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({"/issues/comments": comments})):
            _method_b(["acme/api"], token="tok", hits=h, lookback_days=90)
        assert "claude-code" in h.agent_ids()
        p = h.to_profile("claude-code")
        assert p.observed_invocation.primary is not None
        assert p.observed_invocation.primary.type == "comment_mention"

    def test_skips_stale_prs(self):
        prs = [{"user": {"login": "claude[bot]"}, "created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-01T00:00:00Z", "body": ""}]
        h = _Hits()
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({"/pulls": prs})):
            _method_b(["acme/api"], token="tok", hits=h, lookback_days=90)
        assert "claude-code" not in h.agent_ids()

    def test_empty_repos_does_nothing(self):
        h = _Hits()
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({})):
            _method_b([], token="tok", hits=h)
        assert len(h.agent_ids()) == 0


# ---------------------------------------------------------------------------
# Method C
# ---------------------------------------------------------------------------

class TestMethodC:
    def test_detects_installed_app(self):
        resp = (200, {"installations": [{"app_slug": "claude", "updated_at": "2026-04-01T00:00:00Z"}]})
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh({"/orgs/acme/installations": resp})):
            _method_c(["acme/api"], token="tok", hits=h)
        assert "claude-code" in h.agent_ids()
        assert "org_installations" in h.methods_for("claude-code")

    def test_graceful_on_403(self):
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh({"/orgs/acme/installations": (403, None)})):
            _method_c(["acme/api"], token="tok", hits=h)  # must not raise
        assert len(h.agent_ids()) == 0

    def test_graceful_on_404(self):
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh({"/orgs/acme/installations": (404, None)})):
            _method_c(["acme/api"], token="tok", hits=h)
        assert len(h.agent_ids()) == 0

    def test_unknown_app_slug_ignored(self):
        resp = (200, {"installations": [{"app_slug": "totally-unknown-app", "updated_at": "2026-04-01T00:00:00Z"}]})
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh({"/orgs/acme/installations": resp})):
            _method_c(["acme/api"], token="tok", hits=h)
        assert len(h.agent_ids()) == 0

    def test_user_repos_skipped(self):
        h = _Hits()
        # personal repos have no org
        with patch("agent_fleet.discovery._gh", _make_gh({})) as mock_gh:
            _method_c(["batuhan/pm"], token="tok", hits=h)
        assert len(h.agent_ids()) == 0


# ---------------------------------------------------------------------------
# Method D
# ---------------------------------------------------------------------------

class TestMethodD:
    def _make_b64(self, content: str) -> str:
        import base64
        return base64.b64encode(content.encode()).decode()

    def test_detects_workflow_action(self):
        listing = [{"name": "ci.yml", "url": "https://api.github.com/repos/acme/api/contents/.github/workflows/ci.yml"}]
        workflow_content = "jobs:\n  build:\n    steps:\n      - uses: anthropics/claude-code-action@v1\n"
        file_resp = {"content": self._make_b64(workflow_content)}
        responses = {
            "/.github/workflows": (200, listing),
            "/contents/.github/workflows/ci.yml": (200, file_resp),
        }
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh(responses)):
            _method_d(["acme/api"], token="tok", hits=h)
        assert "claude-code" in h.agent_ids()
        assert "workflow_scan" in h.methods_for("claude-code")

    def test_ignores_non_yaml_files(self):
        listing = [{"name": "README.md", "url": "https://api.github.com/repos/acme/api/contents/.github/workflows/README.md"}]
        responses = {"/.github/workflows": (200, listing)}
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh(responses)):
            _method_d(["acme/api"], token="tok", hits=h)
        assert len(h.agent_ids()) == 0

    def test_graceful_on_missing_workflows_dir(self):
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh({"/.github/workflows": (404, None)})):
            _method_d(["acme/api"], token="tok", hits=h)
        assert len(h.agent_ids()) == 0

    def test_workflow_uses_version_stripped(self):
        listing = [{"name": "ai.yml", "url": "https://api.github.com/repos/acme/api/contents/.github/workflows/ai.yml"}]
        workflow_content = '    - uses: "anthropics/claude-code-action@v2.1.0"\n'
        file_resp = {"content": self._make_b64(workflow_content)}
        responses = {
            "/.github/workflows": (200, listing),
            "/contents/.github/workflows/ai.yml": (200, file_resp),
        }
        h = _Hits()
        with patch("agent_fleet.discovery._gh", _make_gh(responses)):
            _method_d(["acme/api"], token="tok", hits=h)
        assert "claude-code" in h.agent_ids()


# ---------------------------------------------------------------------------
# discover_external_agents (integration)
# ---------------------------------------------------------------------------

class TestDiscoverExternal:
    def test_no_token_returns_empty(self):
        result = discover_external_agents(["acme/api"], token="")
        assert result == []

    def test_all_methods_run_and_merge(self):
        prs = [{"user": {"login": "claude[bot]"}, "created_at": "2026-04-01T00:00:00Z", "updated_at": "2026-04-01T00:00:00Z", "body": ""}]
        listing = [{"name": "ai.yml", "url": "https://api.github.com/repos/acme/api/contents/.github/workflows/ai.yml"}]
        import base64
        wf = base64.b64encode(b"    - uses: anthropics/claude-code-action@v1\n").decode()
        file_resp = {"content": wf}

        def paginate_mock(path_template, token, max_pages=5):
            if "/pulls" in path_template:
                return prs
            return []

        def gh_mock(method, path, token, body=None, timeout=20):
            if "/.github/workflows" in path and "ai.yml" not in path:
                return (200, listing)
            if "ai.yml" in path:
                return (200, file_resp)
            if "/installations" in path:
                return (403, None)  # no admin:read
            return (200, [])

        with patch("agent_fleet.discovery._gh_paginate", paginate_mock), \
             patch("agent_fleet.discovery._gh", gh_mock):
            result = discover_external_agents(["acme/api"], token="tok")

        ids = [p.id for p in result]
        assert "claude-code" in ids
        profile = next(p for p in result if p.id == "claude-code")
        # B hit (pr_author) + D hit (workflow_scan) → high confidence
        assert profile.confidence == "high"
        assert profile.enabled is False  # always starts disabled

    def test_returns_one_profile_per_agent(self):
        comments = [
            {"user": {"login": "claude[bot]"}, "created_at": "2026-04-01T00:00:00Z", "body": ""},
            {"user": {"login": "claude[bot]"}, "created_at": "2026-04-02T00:00:00Z", "body": ""},
        ]
        with patch("agent_fleet.discovery._gh_paginate", _make_paginate({"/issues/comments": comments})), \
             patch("agent_fleet.discovery._gh", _make_gh({"/.github/workflows": (404, None), "/installations": (403, None)})):
            result = discover_external_agents(["acme/api"], token="tok")
        claude_profiles = [p for p in result if p.id == "claude-code"]
        assert len(claude_profiles) == 1


# ---------------------------------------------------------------------------
# merge_with_existing
# ---------------------------------------------------------------------------

class TestMergeWithExisting:
    def test_new_agent_added(self):
        existing = []
        discovered = [AgentProfile(id="claude-code", confidence="medium")]
        merged, new_ids, updated_ids = merge_with_existing(discovered, existing)
        assert "claude-code" in new_ids
        assert updated_ids == []
        assert len(merged) == 1

    def test_existing_enabled_state_preserved(self):
        existing = [AgentProfile(id="claude-code", enabled=True, confidence="low")]
        discovered = [AgentProfile(id="claude-code", enabled=False, confidence="high")]
        merged, _, updated_ids = merge_with_existing(discovered, existing)
        assert "claude-code" in updated_ids
        result_profile = next(p for p in merged if p.id == "claude-code")
        assert result_profile.enabled is True   # preserved from existing
        assert result_profile.confidence == "high"  # updated from discovery

    def test_manual_only_profile_preserved_if_not_rediscovered(self):
        existing = [AgentProfile(id="custom:internal-bot", enabled=True, detected_via=["manual"])]
        discovered = [AgentProfile(id="claude-code")]
        merged, new_ids, _ = merge_with_existing(discovered, existing)
        ids = [p.id for p in merged]
        assert "custom:internal-bot" in ids
        assert "claude-code" in ids
        assert "claude-code" in new_ids

    def test_display_name_override_preserved(self):
        existing = [AgentProfile(id="devin", display_name_override="Devin (staging)")]
        discovered = [AgentProfile(id="devin", confidence="medium")]
        merged, _, _ = merge_with_existing(discovered, existing)
        result = next(p for p in merged if p.id == "devin")
        assert result.display_name_override == "Devin (staging)"
