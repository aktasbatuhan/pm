"""Supabase client factories for service-role and user-scoped access."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from supabase import Client, create_client
from supabase.lib.client_options import ClientOptions


@dataclass(frozen=True)
class SupabaseSettings:
    """Runtime Supabase settings loaded from environment variables."""

    url: str
    anon_key: str
    service_role_key: str
    jwt_secret: str


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value


@lru_cache(maxsize=1)
def get_supabase_settings() -> SupabaseSettings:
    """Load and cache Supabase environment configuration."""

    return SupabaseSettings(
        url=_require_env("SUPABASE_URL"),
        anon_key=_require_env("SUPABASE_ANON_KEY"),
        service_role_key=_require_env("SUPABASE_SERVICE_ROLE_KEY"),
        jwt_secret=_require_env("SUPABASE_JWT_SECRET"),
    )


@lru_cache(maxsize=1)
def get_service_role_client() -> Client:
    """Return a service-role Supabase client (bypasses RLS)."""

    settings = get_supabase_settings()
    return create_client(settings.url, settings.service_role_key)


def get_user_client(jwt: str) -> Client:
    """Return a Supabase client bound to an end-user JWT so RLS policies apply."""

    token = jwt.strip()
    if not token:
        raise ValueError("JWT is required to create a user-scoped Supabase client")

    settings = get_supabase_settings()
    options = ClientOptions(headers={"Authorization": f"Bearer {token}"})
    return create_client(settings.url, settings.anon_key, options=options)
