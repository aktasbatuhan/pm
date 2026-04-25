"""JWT auth + tenant membership resolution for tenant-scoped API requests.

When DATABASE_URL is set (Postgres mode):
  - JWT is HS256, signed with JWT_SECRET
  - Token payload: { "sub": user_id, "exp": ... }
  - Active tenant is resolved from the X-Tenant-Id header, or the user's
    default tenant if the header is absent
  - Middleware looks up membership in the `tenant_memberships` table

When DATABASE_URL is unset (legacy SQLite mode, e.g. demo):
  - Tenant scoping is bypassed; routes that depend on get_current_tenant
    receive a synthetic 'default' tenant — preserves single-user behavior
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

from backend.db.postgres_client import get_pool, is_postgres_enabled
from backend.tenant_context import TenantContext

logger = logging.getLogger(__name__)


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
    if not is_postgres_enabled():
        return False
    return any(path.startswith(prefix) for prefix in TENANT_SCOPED_PATH_PREFIXES)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET is not set")
    return secret


def issue_jwt(user_id: str, ttl_seconds: int = 60 * 60 * 24 * 30) -> str:
    """Issue a JWT for the given user. Default TTL: 30 days."""
    import time
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc
    sub = str(payload.get("sub") or "").strip()
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing 'sub'")
    return payload


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = auth_header.replace("Bearer ", "", 1).strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty bearer token")
    return token


# ---------------------------------------------------------------------------
# Membership resolution (Postgres)
# ---------------------------------------------------------------------------

def resolve_tenant_membership(user_id: str, requested_tenant_id: Optional[str] = None) -> TenantContext:
    """Pick the active tenant for this request — header value if provided,
    otherwise the user's default membership."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tenant_id, role, is_default
                  FROM tenant_memberships
                 WHERE user_id = %s
                """,
                (user_id,),
            )
            memberships = cur.fetchall()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user has no tenant membership",
        )

    if requested_tenant_id:
        membership = next(
            (m for m in memberships if str(m["tenant_id"]) == requested_tenant_id),
            None,
        )
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not a member of tenant '{requested_tenant_id}'",
            )
    else:
        membership = next(
            (m for m in memberships if m["is_default"]),
            None,
        ) or memberships[0]

    return TenantContext(
        user_id=user_id,
        tenant_id=str(membership["tenant_id"]),
        role=str(membership["role"] or "member"),
    )


def build_tenant_context(request: Request) -> TenantContext:
    token = _extract_bearer_token(request)
    payload = decode_jwt(token)
    user_id = str(payload["sub"])
    requested = request.headers.get("x-tenant-id", "").strip() or None
    return resolve_tenant_membership(user_id, requested)


def get_current_tenant(request: Request) -> TenantContext:
    """FastAPI dependency: returns the active tenant for the current request.

    In Postgres mode, the middleware will have already populated
    ``request.state.tenant_context``. In SQLite mode, returns a synthetic
    'default' context so legacy single-tenant endpoints keep working.
    """
    context = getattr(request.state, "tenant_context", None)
    if context is None:
        if not is_postgres_enabled():
            return TenantContext(user_id="default", tenant_id="default", role="owner")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Tenant context was not resolved for this tenant-scoped endpoint. "
                "This indicates middleware misconfiguration."
            ),
        )
    return context
