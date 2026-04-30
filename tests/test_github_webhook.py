"""Tests for the GitHub webhook endpoint (B3a).

Covers the four real risks:
  1. HMAC verification — bad signatures must produce 401, never trigger work.
  2. Tenant resolution — wrong/missing installation_id must skip cleanly.
  3. Event filtering — only relevant events trigger supervisor; ping returns
     pong; unrelated events 200-ack without dispatching.
  4. Background dispatch — the targeted supervisor runs with the right
     tenant + repo + issue.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server


def _enable_postgres(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://fake/fake")
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", "wh-secret")


def _signed_post(client, body: dict, event: str, secret: str = "wh-secret"):
    raw = json.dumps(body).encode("utf-8")
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/api/integrations/github/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": "test-delivery-1",
        },
    )


def _payload_issue(installation_id: int = 99, repo: str = "acme/api", issue_n: int = 10) -> dict:
    return {
        "installation": {"id": installation_id},
        "repository": {"full_name": repo},
        "issue": {"number": issue_n, "title": "x"},
        "action": "opened",
    }


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def test_returns_503_when_secret_not_configured(monkeypatch):
    _enable_postgres(monkeypatch)
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", "")
    client = TestClient(server.app)
    r = client.post("/api/integrations/github/webhook", json={}, headers={"X-GitHub-Event": "ping"})
    assert r.status_code == 503


def test_bad_signature_returns_401(monkeypatch):
    _enable_postgres(monkeypatch)
    client = TestClient(server.app)
    r = client.post(
        "/api/integrations/github/webhook",
        content=b'{"installation":{"id":1}}',
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "issues",
        },
    )
    assert r.status_code == 401


def test_missing_signature_returns_401(monkeypatch):
    _enable_postgres(monkeypatch)
    client = TestClient(server.app)
    r = client.post(
        "/api/integrations/github/webhook",
        json={},
        headers={"X-GitHub-Event": "issues"},
    )
    assert r.status_code == 401


def test_signature_helper_constant_time_compare():
    """The verify helper should reject mismatched lengths without crashing."""
    from server import _verify_github_webhook_signature
    assert _verify_github_webhook_signature("s", b"body", "sha256=short") is False
    assert _verify_github_webhook_signature("s", b"body", "") is False
    assert _verify_github_webhook_signature("s", b"body", "md5=abc") is False
    assert _verify_github_webhook_signature("", b"body", "sha256=abc") is False


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------

def test_ping_event_returns_pong(monkeypatch):
    _enable_postgres(monkeypatch)
    client = TestClient(server.app)
    r = _signed_post(client, {}, event="ping")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "pong": True}


def test_irrelevant_event_acknowledged(monkeypatch):
    """GitHub retries on non-2xx — unknown events must 200-ack cleanly."""
    _enable_postgres(monkeypatch)
    client = TestClient(server.app)
    r = _signed_post(client, _payload_issue(), event="star")
    assert r.status_code == 200
    assert r.json()["ignored"] == "star"


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------

def test_untracked_installation_acknowledged(monkeypatch):
    """If we don't recognize the installation_id, return 200 + ignored so
    GitHub stops retrying. Don't 4xx — the user might just have installed
    the App into a workspace Dash doesn't track yet."""
    _enable_postgres(monkeypatch)

    fake_repos = type("R", (), {})()
    fake_repos.get_tenant_for_installation = lambda iid: None

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = _signed_post(client, _payload_issue(installation_id=99), event="issues")

    assert r.status_code == 200
    assert r.json()["ignored"] == "untracked installation"


def test_missing_installation_id_returns_400(monkeypatch):
    _enable_postgres(monkeypatch)
    client = TestClient(server.app)
    body = _payload_issue()
    body["installation"] = {}
    r = _signed_post(client, body, event="issues")
    assert r.status_code == 400


def test_invalid_json_returns_400(monkeypatch):
    """Edge case: signature checks out but body is malformed JSON."""
    _enable_postgres(monkeypatch)
    secret = "wh-secret"
    raw = b"not-json"
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    client = TestClient(server.app)
    r = client.post(
        "/api/integrations/github/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "issues",
        },
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Issue number extraction (covers the four event shapes)
# ---------------------------------------------------------------------------

def test_extract_issue_number_for_each_event_shape():
    from server import _extract_issue_number_for_event
    assert _extract_issue_number_for_event("issues", {"issue": {"number": 7}}) == 7
    assert _extract_issue_number_for_event(
        "issue_comment", {"issue": {"number": 8}}
    ) == 8
    assert _extract_issue_number_for_event(
        "pull_request", {"pull_request": {"number": 9}}
    ) == 9
    assert _extract_issue_number_for_event(
        "pull_request_review", {"pull_request": {"number": 10}}
    ) == 10
    assert _extract_issue_number_for_event("star", {}) is None


# ---------------------------------------------------------------------------
# Dispatch — happy path triggers supervisor in a background thread
# ---------------------------------------------------------------------------

def test_relevant_event_dispatches_supervisor(monkeypatch):
    _enable_postgres(monkeypatch)

    fake_repos = type("R", (), {})()
    fake_repos.get_tenant_for_installation = lambda iid: "tenant-1"
    # The thread also calls get_active_workflow + supervise_one.
    fake_repos.get_active_workflow = lambda tid: None

    captured = {}
    finished = threading.Event()

    def fake_supervise_one(*, tenant_id, repo, issue_number, token, workflow=None,
                           workflow_revision=0):
        captured["tenant_id"] = tenant_id
        captured["repo"] = repo
        captured["issue_number"] = issue_number
        captured["token"] = token
        finished.set()
        from agent_fleet.supervisor import SupervisorReport
        return SupervisorReport(tenant_id=tenant_id, workflow_revision=workflow_revision)

    monkeypatch.setattr("agent_fleet.supervisor.supervise_one", fake_supervise_one)
    monkeypatch.setattr("github_app_auth.refresh_github_token_env",
                        lambda tenant_id=None: True)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = _signed_post(client, _payload_issue(repo="acme/api", issue_n=42),
                         event="issues")

    assert r.status_code == 200, r.text
    assert r.json()["queued"] is True
    finished.wait(timeout=2.0)
    assert captured["tenant_id"] == "tenant-1"
    assert captured["repo"] == "acme/api"
    assert captured["issue_number"] == 42


def test_pull_request_event_dispatches_with_pr_number(monkeypatch):
    """pull_request payloads carry the issue number under .pull_request.number,
    not .issue.number."""
    _enable_postgres(monkeypatch)

    fake_repos = type("R", (), {})()
    fake_repos.get_tenant_for_installation = lambda iid: "tenant-1"
    fake_repos.get_active_workflow = lambda tid: None

    captured = {}
    finished = threading.Event()

    def fake_supervise_one(*, tenant_id, repo, issue_number, token, workflow=None,
                           workflow_revision=0):
        captured["issue_number"] = issue_number
        finished.set()
        from agent_fleet.supervisor import SupervisorReport
        return SupervisorReport(tenant_id=tenant_id, workflow_revision=workflow_revision)

    monkeypatch.setattr("agent_fleet.supervisor.supervise_one", fake_supervise_one)
    monkeypatch.setattr("github_app_auth.refresh_github_token_env",
                        lambda tenant_id=None: True)

    body = {
        "installation": {"id": 99},
        "repository": {"full_name": "acme/api"},
        "pull_request": {"number": 88, "state": "open"},
        "action": "opened",
    }

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = _signed_post(client, body, event="pull_request")

    assert r.status_code == 200
    finished.wait(timeout=2.0)
    assert captured["issue_number"] == 88


def test_dispatch_skipped_when_repo_or_issue_missing(monkeypatch):
    """Webhooks with no repo or no issue (some action types omit them) get
    acknowledged but don't dispatch."""
    _enable_postgres(monkeypatch)

    fake_repos = type("R", (), {})()
    fake_repos.get_tenant_for_installation = lambda iid: "tenant-1"

    called = {"n": 0}

    def fake_supervise_one(**kw):
        called["n"] += 1

    monkeypatch.setattr("agent_fleet.supervisor.supervise_one", fake_supervise_one)

    body = {"installation": {"id": 99}}  # no repository, no issue

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = _signed_post(client, body, event="issues")

    assert r.status_code == 200
    assert "ignored" in r.json()
    # No dispatch happens
    assert called["n"] == 0
