# Supabase setup for Dash multi-tenant groundwork

This runbook covers the **manual operator steps** for issue #26.

> Authoritative schema reference: `docs/multi-tenant-schema.md`.

## 1) Create project

1. In Supabase dashboard, create a new project.
2. Pick region, project name, and DB password.
3. After provisioning, copy:
   - `Project URL` → `SUPABASE_URL`
   - `anon public key` → `SUPABASE_ANON_KEY`
   - `service_role key` → `SUPABASE_SERVICE_ROLE_KEY`
4. From **Project Settings → API**, copy the JWT secret to `SUPABASE_JWT_SECRET`.

## 2) Use Supabase pooler (connection pooling)

1. Go to **Project Settings → Database**.
2. Confirm Supabase Pooler is enabled (default on hosted projects).
3. Keep pool mode at Supabase default unless your org has specific tuning requirements.

For #26, backend traffic goes through Supabase REST/PostgREST endpoints, which already sit behind Supabase-managed pooling.

## 3) Create minimal SQL objects required by #26 smoke test

Run this SQL in **SQL Editor**:

```sql
create extension if not exists pgcrypto;

create schema if not exists app;

create table if not exists public.tenant_memberships (
  tenant_id uuid not null,
  user_id uuid not null,
  role text not null default 'member',
  is_default boolean not null default false,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (tenant_id, user_id)
);

create or replace function app.is_tenant_member(target_tenant uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from tenant_memberships tm
    where tm.tenant_id = target_tenant
      and tm.user_id = auth.uid()
      and tm.deleted_at is null
  );
$$;

create table if not exists public.connection_test (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null,
  note text,
  created_at timestamptz not null default now()
);

alter table public.connection_test enable row level security;

create policy if not exists connection_test_select
on public.connection_test
for select
using (app.is_tenant_member(tenant_id));

create policy if not exists connection_test_insert_service
on public.connection_test
for insert
to service_role
with check (true);
```

## 4) Create a test user + JWT for integration test

1. In **Authentication → Users**, create a user (email/password is enough).
2. Note the user UUID as `SUPABASE_TEST_USER_ID`.
3. Generate a user access token for that user (or sign in and copy the access token).
   - Store as `SUPABASE_TEST_USER_JWT`.
4. Create a tenant UUID and store as `SUPABASE_TEST_TENANT_ID`.
5. Insert membership row (service role SQL):

```sql
insert into public.tenant_memberships (tenant_id, user_id, role, is_default)
values ('<SUPABASE_TEST_TENANT_ID>', '<SUPABASE_TEST_USER_ID>', 'member', true)
on conflict (tenant_id, user_id) do update
set deleted_at = null, updated_at = now();
```

## 5) Configure Dash API env

Set these env vars for the API process:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`

Optional test-only vars:

- `SUPABASE_TEST_USER_ID`
- `SUPABASE_TEST_USER_JWT`
- `SUPABASE_TEST_TENANT_ID`

## 6) Validate

- `GET /api/health/supabase` should return `{ "ok": true, "latency_ms": <number> }`.
- Run `pytest tests/integration/test_supabase_rls_integration.py -m integration`.
