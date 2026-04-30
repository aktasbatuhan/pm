"""Endpoint tests for /api/workflow/proposals.

We mock backend.repos at the call sites in server.py so the endpoints can run
under TestClient without a real Postgres. These tests cover the path from
HTTP → repo helper → evolver mutator → resolution, which is the contract the
Settings → Workflow → Proposals panel relies on.
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

import server


def _enable_postgres(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://fake/fake")


def _token() -> str:
    return jwt.encode(
        {"sub": "user-1", "exp": int(time.time()) + 600},
        "test-secret",
        algorithm="HS256",
    )


def _membership_factory():
    from backend.tenant_context import TenantContext
    def _membership(user_id, requested_tenant_id=None):
        return TenantContext(user_id=user_id, tenant_id="tenant-1", role="owner")
    return _membership


def _proposal_action(action_id="p-1", status="pending"):
    """A brief_action row in the shape repos.get_brief_action returns."""
    return {
        "id": action_id,
        "tenant_id": "tenant-1",
        "brief_id": None,
        "category": "workflow-proposal",
        "title": "Workflow proposal: missing_fallback_chain",
        "description": "blah",
        "priority": "medium",
        "status": status,
        "chat_session_id": None,
        "references": [{
            "type": "workflow_proposal",
            "signal_kind": "missing_fallback_chain",
            "severity": "warn",
            "rationale": "5 stalled delegations with no fallback configured",
            "suggested_change": {
                "handler": "add_remove_agents",
                "section": "escalation",
                "field": "fallback_chain",
                "from": [],
                "to": ["codex", "claude-code"],
            },
            "evidence": {"stalled_or_delegated_count": 5},
        }],
        "created_at": 1761800000.0,
        "updated_at": 1761800000.0,
    }


def test_list_proposals_returns_pending_with_structured_payload(monkeypatch):
    _enable_postgres(monkeypatch)
    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership_factory())

    fake_repos = type("R", (), {})()
    fake_repos.list_brief_actions = lambda tenant_id, status=None, category=None, brief_id=None: (
        [_proposal_action()] if category == "workflow-proposal" and status == "pending" else []
    )

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = client.get(
            "/api/workflow/proposals",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["proposals"]) == 1
    p = body["proposals"][0]
    assert p["id"] == "p-1"
    assert p["signal_kind"] == "missing_fallback_chain"
    assert p["suggested_change"]["handler"] == "add_remove_agents"
    assert p["applicable"] is True


def test_accept_applies_mutator_saves_revision_resolves_action(monkeypatch):
    _enable_postgres(monkeypatch)
    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership_factory())

    saved = {}
    resolved = {}

    fake_repos = type("R", (), {})()
    fake_repos.get_brief_action = lambda tenant_id, action_id: _proposal_action(action_id)
    fake_repos.get_active_workflow = lambda tenant_id: None  # use shipped default
    def _save_revision(tenant_id, *, name, body, author, rationale=None, based_on_signals=None):
        saved.update({
            "tenant_id": tenant_id, "name": name, "body": body,
            "author": author, "rationale": rationale, "signals": based_on_signals,
        })
        return 7
    fake_repos.save_workflow_revision = _save_revision
    def _update_action(tenant_id, action_id, *, status=None, chat_session_id=None):
        resolved["action_id"] = action_id
        resolved["status"] = status
        return True
    fake_repos.update_brief_action = _update_action

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = client.post(
            "/api/workflow/proposals/p-1/accept",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 7
    # Mutator ran: the new body must have the proposed fallback_chain.
    assert "codex" in saved["body"] and "claude-code" in saved["body"]
    assert saved["author"] == "user-1"
    assert resolved == {"action_id": "p-1", "status": "resolved"}
    # The accept reason references the proposal so the revision is auditable.
    assert "missing_fallback_chain" in (saved["rationale"] or "")


def test_accept_404_when_proposal_not_found(monkeypatch):
    _enable_postgres(monkeypatch)
    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership_factory())

    fake_repos = type("R", (), {})()
    fake_repos.get_brief_action = lambda tenant_id, action_id: None

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = client.post(
            "/api/workflow/proposals/missing/accept",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert r.status_code == 404


def test_accept_409_when_already_resolved(monkeypatch):
    _enable_postgres(monkeypatch)
    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership_factory())

    fake_repos = type("R", (), {})()
    fake_repos.get_brief_action = lambda tenant_id, action_id: _proposal_action(status="resolved")

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = client.post(
            "/api/workflow/proposals/p-1/accept",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert r.status_code == 409
    assert "resolved" in r.json()["error"]


def test_accept_422_when_payload_has_no_handler(monkeypatch):
    """Legacy proposals filed before references_json carried the suggested_change
    have no handler — the endpoint should refuse rather than guess."""
    _enable_postgres(monkeypatch)
    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership_factory())

    legacy = _proposal_action()
    legacy["references"] = []  # no payload

    fake_repos = type("R", (), {})()
    fake_repos.get_brief_action = lambda tenant_id, action_id: legacy

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = client.post(
            "/api/workflow/proposals/p-1/accept",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert r.status_code == 422


def test_dismiss_resolves_without_saving_revision(monkeypatch):
    _enable_postgres(monkeypatch)
    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership_factory())

    resolved = {}
    save_calls = []

    fake_repos = type("R", (), {})()
    fake_repos.get_brief_action = lambda tenant_id, action_id: _proposal_action(action_id)
    def _update(tenant_id, action_id, *, status=None, chat_session_id=None):
        resolved["status"] = status
        return True
    fake_repos.update_brief_action = _update
    def _save(*a, **k):
        save_calls.append((a, k))
        return 99
    fake_repos.save_workflow_revision = _save

    with patch.dict("sys.modules", {"backend.repos": fake_repos}):
        client = TestClient(server.app)
        r = client.post(
            "/api/workflow/proposals/p-1/dismiss",
            headers={"Authorization": f"Bearer {_token()}"},
        )

    assert r.status_code == 200
    assert resolved == {"status": "dismissed"}
    assert save_calls == []  # dismiss never saves a revision
