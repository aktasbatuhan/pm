"""Supabase JWT + membership resolution for tenant-scoped API requests."""

from __future__ import annotations

from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

from backend.db.supabase_client import get_service_role_client, get_supabase_settings
from backend.tenant_context import TenantContext


TENANT_SCOPED_PATH_PREFIXES = (
    "/api/tenant",
    "/api/brief",
    "/api/briefs",
    "/api/goals",
    "/api/kpis",
    "/api/workspace",
    "/api/chat",
)


def is_tenant_scoped_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in TENANT_SCOPED_PATH_PREFIXES)


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Supabase JWT")
    token = auth_header.replace("Bearer ", "", 1).strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Supabase JWT")
    return token


def decode_supabase_jwt(token: str) -> dict:
    settings = get_supabase_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid Supabase JWT: {exc}") from exc
    sub = str(payload.get("sub") or "").strip()
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Supabase JWT is missing 'sub'")
    return payload


def resolve_tenant_membership(user_id: str, requested_tenant_id: Optional[str] = None) -> TenantContext:
    client = get_service_role_client()
    response = (
        client.table("tenant_memberships")
        .select("tenant_id,role,is_default")
        .eq("user_id", user_id)
        .execute()
    )
    memberships = response.data or []
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user has no tenant membership",
        )

    membership = None
    if requested_tenant_id:
        membership = next((m for m in memberships if m.get("tenant_id") == requested_tenant_id), None)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not a member of tenant '{requested_tenant_id}'",
            )
    else:
        membership = next((m for m in memberships if m.get("is_default") is True), None) or memberships[0]

    return TenantContext(
        user_id=user_id,
        tenant_id=str(membership.get("tenant_id") or "").strip(),
        role=str(membership.get("role") or "member").strip() or "member",
    )


def build_tenant_context(request: Request) -> TenantContext:
    token = _extract_bearer_token(request)
    payload = decode_supabase_jwt(token)
    user_id = str(payload.get("sub"))
    requested_tenant_id = request.headers.get("x-tenant-id", "").strip() or None
    return resolve_tenant_membership(user_id, requested_tenant_id)


def get_current_tenant(request: Request) -> TenantContext:
    context = getattr(request.state, "tenant_context", None)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Tenant context was not resolved for this tenant-scoped endpoint. "
                "This indicates middleware misconfiguration."
            ),
        )
    return context
