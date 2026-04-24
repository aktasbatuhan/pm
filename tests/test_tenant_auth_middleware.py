import os
import sys
import types

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient

if "supabase" not in sys.modules:
    fake_supabase = types.ModuleType("supabase")
    fake_supabase.Client = object
    fake_supabase.create_client = lambda *args, **kwargs: object()
    sys.modules["supabase"] = fake_supabase

if "supabase.lib.client_options" not in sys.modules:
    sys.modules.setdefault("supabase.lib", types.ModuleType("supabase.lib"))
    fake_client_options = types.ModuleType("supabase.lib.client_options")

    class _ClientOptions:
        def __init__(self, headers=None):
            self.headers = headers or {}

    fake_client_options.ClientOptions = _ClientOptions
    sys.modules["supabase.lib.client_options"] = fake_client_options

import server


def _token(user_id: str) -> str:
    secret = os.environ["SUPABASE_JWT_SECRET"]
    return jwt.encode({"sub": user_id}, secret, algorithm="HS256")


def test_tenant_middleware_missing_jwt_returns_401(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")

    client = TestClient(server.app)
    response = client.get("/api/tenant/context")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Supabase JWT"


def test_tenant_middleware_valid_jwt_without_membership_returns_403(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")

    def _no_membership(user_id: str, requested_tenant_id=None):
        raise HTTPException(status_code=403, detail="Authenticated user has no tenant membership")

    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _no_membership)

    client = TestClient(server.app)
    response = client.get(
        "/api/tenant/context",
        headers={"Authorization": f"Bearer {_token('user-no-membership')}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Authenticated user has no tenant membership"


def test_tenant_middleware_resolves_membership_and_isolates_by_user(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")

    tenant_map = {
        "user-a": ("tenant-a", "owner"),
        "user-b": ("tenant-b", "member"),
    }

    def _membership(user_id: str, requested_tenant_id=None):
        if user_id not in tenant_map:
            raise HTTPException(status_code=403, detail="Authenticated user has no tenant membership")
        tenant_id, role = tenant_map[user_id]
        from backend.tenant_context import TenantContext

        if requested_tenant_id and requested_tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=f"User is not a member of tenant '{requested_tenant_id}'")
        return TenantContext(user_id=user_id, tenant_id=tenant_id, role=role)

    monkeypatch.setattr("backend.tenant_auth.resolve_tenant_membership", _membership)

    client = TestClient(server.app)

    response_a = client.get(
        "/api/tenant/context",
        headers={"Authorization": f"Bearer {_token('user-a')}"},
    )
    response_b = client.get(
        "/api/tenant/context",
        headers={"Authorization": f"Bearer {_token('user-b')}"},
    )

    assert response_a.status_code == 200
    assert response_a.json() == {"user_id": "user-a", "tenant_id": "tenant-a", "role": "owner"}

    assert response_b.status_code == 200
    assert response_b.json() == {"user_id": "user-b", "tenant_id": "tenant-b", "role": "member"}
