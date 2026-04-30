"""Provider registry — name → factory(tenant_id) -> DelegationProvider.

Lazy-instantiates per-tenant since each provider may need tenant-scoped
config (GitHub install token, Multica API key, etc.).

Registration happens at import time in each provider module; importing
agent_fleet.providers triggers all built-ins to register.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from agent_fleet.providers.base import (
    DelegationProvider,
    ProviderError,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

# name -> factory(tenant_id) -> DelegationProvider
_FACTORIES: Dict[str, Callable[[str], DelegationProvider]] = {}


def register(name: str, factory: Callable[[str], DelegationProvider]) -> None:
    """Register a provider factory by name. Called at module import time."""
    if name in _FACTORIES:
        logger.warning("Re-registering provider %s (was %s)", name, _FACTORIES[name])
    _FACTORIES[name] = factory


def get(name: str, *, tenant_id: str) -> DelegationProvider:
    """Build a provider instance for this tenant. Raises ProviderUnavailable
    if the name is unknown or the tenant hasn't configured it."""
    factory = _FACTORIES.get(name)
    if factory is None:
        raise ProviderUnavailable(
            f"No provider registered as '{name}'. Known: {sorted(_FACTORIES)}"
        )
    return factory(tenant_id)


def list_names() -> list:
    return sorted(_FACTORIES.keys())


def resolve_for_handle(handle, *, tenant_id: str) -> DelegationProvider:
    """Round-trip a persisted DelegationHandle back to its provider so
    status/cancel can be called after a server restart."""
    return get(handle.provider, tenant_id=tenant_id)
