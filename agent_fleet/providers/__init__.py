"""Delegation providers — pluggable backends that execute coding tasks.

Dash decides *what* to delegate (brief → action item → DelegationTask) and
*how to judge* the outcome. Providers handle the *execution*: filing the
work, watching it run, surfacing status, and cancelling.

Built-in providers:
  - github_default — files a Dash-shaped GitHub issue, polls PRs (current behavior)
  - multica        — talks to a user-provisioned Multica instance via REST + WS

Adding a new provider is a 4-method adapter: see base.DelegationProvider.
"""

from agent_fleet.providers.base import (
    DelegationProvider,
    DelegationHandle,
    DelegationStatus,
    DelegationState,
    DelegationEvent,
    DelegationArtifact,
    ProviderError,
    ProviderUnavailable,
)

__all__ = [
    "DelegationProvider",
    "DelegationHandle",
    "DelegationStatus",
    "DelegationState",
    "DelegationEvent",
    "DelegationArtifact",
    "ProviderError",
    "ProviderUnavailable",
]
