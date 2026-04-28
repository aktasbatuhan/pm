"""Tenant context utilities shared across API, tools, and gateway flows."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


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

    # Previously this fell back to os.environ, which was racy under concurrent
    # requests (the middleware wrote per-request tenant info to process-global
    # env vars). The ContextVar path above is the correct async-safe mechanism.
    # If we reach here, no tenant context was propagated — return None so
    # callers can handle the missing context explicitly.
    logger.warning(
        "resolve_tenant_context: no tenant found via kwargs or ContextVar. "
        "If this is unexpected, ensure the request passes through "
        "tenant_context_middleware or provides tenant_context in kwargs."
    )
    return None


def require_tenant_context(*, kwargs: Optional[Mapping[str, Any]] = None, consumer: str) -> TenantContext:
    context = resolve_tenant_context(kwargs)
    if context:
        return context
    raise TenantContextError(
        f"Tenant context is required for {consumer}. "
        "No tenant_id was resolved from request context, tool arguments, or session environment."
    )
