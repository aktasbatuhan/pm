import os
import uuid

import pytest
from supabase import create_client

from backend.db.supabase_client import get_service_role_client, get_supabase_settings, get_user_client

pytestmark = pytest.mark.integration


def _require(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        pytest.skip(f"{var_name} is required for Supabase integration test")
    return value


def test_supabase_service_write_user_read_and_anonymous_fail_closed():
    user_jwt = _require("SUPABASE_TEST_USER_JWT")
    user_id = _require("SUPABASE_TEST_USER_ID")
    tenant_id = _require("SUPABASE_TEST_TENANT_ID")

    settings = get_supabase_settings()
    service_client = get_service_role_client()
    user_client = get_user_client(user_jwt)
    anonymous_client = create_client(settings.url, settings.anon_key)

    row_id = str(uuid.uuid4())

    service_client.table("tenant_memberships").upsert(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": "member",
            "is_default": True,
            "deleted_at": None,
        },
        on_conflict="tenant_id,user_id",
    ).execute()

    service_client.table("connection_test").insert(
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "note": "issue-26-smoke",
        }
    ).execute()

    user_rows = (
        user_client.table("connection_test")
        .select("id,tenant_id,note")
        .eq("id", row_id)
        .execute()
        .data
    )
    assert len(user_rows) == 1
    assert user_rows[0]["id"] == row_id

    anon_rows = (
        anonymous_client.table("connection_test")
        .select("id")
        .eq("id", row_id)
        .execute()
        .data
    )
    assert anon_rows == []

    anon_helper = (
        anonymous_client.schema("app")
        .rpc("is_tenant_member", {"target_tenant": tenant_id})
        .execute()
        .data
    )
    assert anon_helper is False

    user_helper = (
        user_client.schema("app")
        .rpc("is_tenant_member", {"target_tenant": tenant_id})
        .execute()
        .data
    )
    assert user_helper is True
