"""Tests for the JWT + Postgres tenant auth middleware."""

from __future__ import annotations

import os
import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server


def _token(user_id: str, secret: str = "test-secret") -> str:
    return jwt.encode(
        {"sub": user_id, "exp": int(time.time()) + 600},
        secret,
        algorithm="HS256",
    )


def _enable_postgres(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://fake/fake")


def test_disabled_when_no_database_url(monkeypatch):
    """Demo path: with DATABASE_URL unset, tenant-scoped endpoints fall back to default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(server.app)
    response = client.get("/api/tenant/context")
    # In legacy mode, get_current_tenant returns synthetic 'default' context
    assert response.status_code == 200
    assert response.json() == {"user_id": "default", "tenant_id": "default", "role": "owner"}


def test_missing_jwt_returns_401(monkeypatch):
    _enable_postgres(monkeypatch)
    client = TestClient(server.app)
    response = client.get("/api/tenant/context")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_invalid_jwt_returns_401(monkeypatch):
    _enable_postgres(monkeypatch)
    bad = jwt.encode({"sub": "u"}, "wrong-secret", algorithm="HS256")
    client = TestClient(server.app)
    response = client.get(
        "/api/tenant/context",
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert response.status_code == 401


def test_valid_jwt_no_membership_returns_403(monkeypatch):
    _enable_postgres(monkeypatch)

    def _no_membership(user_id, requested_tenant_id=None):
        raise HTTPException(status_code=403, detail="Authenticated user has no tenant membership")

    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _no_membership)
    client = TestClient(server.app)
    response = client.get(
        "/api/tenant/context",
        headers={"Authorization": f"Bearer {_token('user-x')}"},
    )
    assert response.status_code == 403


def test_valid_jwt_with_membership_resolves(monkeypatch):
    _enable_postgres(monkeypatch)

    from backend.tenant_context import TenantContext

    def _membership(user_id, requested_tenant_id=None):
        return TenantContext(user_id=user_id, tenant_id="tenant-a", role="owner")

    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership)
    client = TestClient(server.app)
    response = client.get(
        "/api/tenant/context",
        headers={"Authorization": f"Bearer {_token('user-a')}"},
    )
    assert response.status_code == 200
    assert response.json() == {"user_id": "user-a", "tenant_id": "tenant-a", "role": "owner"}


def test_x_tenant_id_header_is_passed_through(monkeypatch):
    _enable_postgres(monkeypatch)

    captured = {}

    from backend.tenant_context import TenantContext

    def _membership(user_id, requested_tenant_id=None):
        captured["requested"] = requested_tenant_id
        return TenantContext(user_id=user_id, tenant_id=requested_tenant_id or "default", role="member")

    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership)
    client = TestClient(server.app)
    client.get(
        "/api/tenant/context",
        headers={
            "Authorization": f"Bearer {_token('user-a')}",
            "X-Tenant-Id": "tenant-b",
        },
    )
    assert captured["requested"] == "tenant-b"
