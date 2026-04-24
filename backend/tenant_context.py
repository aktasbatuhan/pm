"""Tenant context utilities shared across API, tools, and gateway flows."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class TenantContext:
    user_id: str
    tenant_id: str
    role: str


_current_tenant: ContextVar[Optional[TenantContext]] = ContextVar("current_tenant", default=None)


class TenantContextError(RuntimeError):
    """Raised when tenant context is required but unavailable."""


def set_current_tenant(context: TenantContext) -> Token:
    return _current_tenant.set(context)


def reset_current_tenant(token: Token) -> None:
    _current_tenant.reset(token)


def get_current_tenant() -> Optional[TenantContext]:
    return _current_tenant.get()


def _from_mapping(data: Mapping[str, Any]) -> Optional[TenantContext]:
    tenant_id = str(data.get("tenant_id") or "").strip()
    if not tenant_id:
        return None
    return TenantContext(
        user_id=str(data.get("user_id") or "unknown").strip() or "unknown",
        tenant_id=tenant_id,
        role=str(data.get("role") or "member").strip() or "member",
    )


def resolve_tenant_context(kwargs: Optional[Mapping[str, Any]] = None) -> Optional[TenantContext]:
    if kwargs:
        embedded = kwargs.get("tenant_context")
        if isinstance(embedded, TenantContext):
            return embedded
        if isinstance(embedded, Mapping):
            mapped = _from_mapping(embedded)
            if mapped:
                return mapped

        mapped = _from_mapping(kwargs)
        if mapped:
            return mapped

    from_ctx = get_current_tenant()
    if from_ctx:
        return from_ctx

    tenant_id = (
        os.getenv("KAI_TENANT_ID", "").strip()
        or os.getenv("HERMES_TENANT_ID", "").strip()
    )
    if not tenant_id:
        return None

    return TenantContext(
        user_id=(os.getenv("KAI_USER_ID", "").strip() or "gateway-user"),
        tenant_id=tenant_id,
        role=(os.getenv("KAI_TENANT_ROLE", "").strip() or "member"),
    )


def require_tenant_context(*, kwargs: Optional[Mapping[str, Any]] = None, consumer: str) -> TenantContext:
    context = resolve_tenant_context(kwargs)
    if context:
        return context
    raise TenantContextError(
        f"Tenant context is required for {consumer}. "
        "No tenant_id was resolved from request context, tool arguments, or session environment."
    )
