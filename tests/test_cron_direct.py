"""Tests for the direct-call cron path (B1/B2 dispatch).

Covers:
  - Direct dispatch in scheduler.run_job: handler runs, success/error are
    recorded correctly, output doc is rendered.
  - jobs.upsert_direct_job: idempotent on (tenant_id, name).
  - direct_handlers.register/get/list_handlers behavior.

We don't cover the actual fleet_supervise / fleet_observe handlers here —
they hit Postgres + GitHub and are exercised end-to-end on Railway. The
test focus is on the dispatch + registration plumbing.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_jobs_dir(monkeypatch):
    """Run each test with a fresh jobs.json in a temp directory.

    cron.jobs reads JOBS_FILE at module-import time, so we patch the path
    constants directly rather than relying on env vars."""
    tmp = tempfile.mkdtemp()
    cron_dir = Path(tmp) / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cron.jobs.CRON_DIR", cron_dir)
    monkeypatch.setattr("cron.jobs.JOBS_FILE", cron_dir / "jobs.json")
    yield cron_dir


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

def test_register_and_lookup_handler():
    from cron import direct_handlers

    @direct_handlers.register("test_echo")
    def _echo(tenant_id, msg="hi"):
        return f"{tenant_id}:{msg}"

    assert "test_echo" in direct_handlers.list_handlers()
    fn = direct_handlers.get("test_echo")
    assert fn("t1", msg="hello") == "t1:hello"


def test_get_unknown_handler_raises():
    from cron import direct_handlers
    with pytest.raises(KeyError) as exc:
        direct_handlers.get("doesnt_exist")
    assert "doesnt_exist" in str(exc.value)


# ---------------------------------------------------------------------------
# Scheduler dispatch
# ---------------------------------------------------------------------------

def test_run_job_dispatches_direct_handler_on_success():
    from cron.scheduler import run_job
    from cron import direct_handlers

    captured = {}

    @direct_handlers.register("dispatch_test_ok")
    def _ok(tenant_id, **kw):
        captured["tenant_id"] = tenant_id
        captured["kw"] = kw
        return "all good"

    job = {
        "id": "j1",
        "name": "test job",
        "kind": "direct",
        "handler": "dispatch_test_ok",
        "tenant_id": "tenant-X",
        "handler_args": {"foo": "bar"},
        "schedule_display": "every 12m",
    }
    success, doc, response, error = run_job(job)

    assert success is True
    assert response == "all good"
    assert error is None
    assert captured == {"tenant_id": "tenant-X", "kw": {"foo": "bar"}}
    assert "all good" in doc and "test job" in doc


def test_run_job_records_error_when_direct_handler_raises():
    from cron.scheduler import run_job
    from cron import direct_handlers

    @direct_handlers.register("dispatch_test_boom")
    def _boom(tenant_id, **kw):
        raise RuntimeError("nope")

    job = {
        "id": "j2",
        "name": "boom",
        "kind": "direct",
        "handler": "dispatch_test_boom",
        "tenant_id": "tenant-Y",
        "handler_args": {},
        "schedule_display": "every 12m",
    }
    success, doc, response, error = run_job(job)

    assert success is False
    assert response == ""
    assert error and "nope" in error
    assert "FAILED" in doc


def test_run_job_rejects_direct_job_without_handler():
    """A direct job with no handler is malformed — surface the error rather
    than silently fall through to the agent path."""
    from cron.scheduler import run_job

    job = {
        "id": "j3",
        "name": "broken",
        "kind": "direct",
        "tenant_id": "tenant-Z",
        "schedule_display": "every 12m",
    }
    success, doc, response, error = run_job(job)
    assert success is False
    assert "missing handler" in error


# ---------------------------------------------------------------------------
# Idempotent registration
# ---------------------------------------------------------------------------

def test_upsert_direct_job_inserts_new(tmp_jobs_dir):
    from cron import direct_handlers
    from cron.jobs import upsert_direct_job, list_jobs

    direct_handlers._HANDLERS["fleet_supervise"] = lambda *a, **k: "ok"

    job = upsert_direct_job(
        tenant_id="tenant-1",
        handler="fleet_supervise",
        schedule="every 12 minutes",
        name="fleet-supervise:tenant-1",
    )
    assert job["kind"] == "direct"
    assert job["handler"] == "fleet_supervise"
    assert job["tenant_id"] == "tenant-1"
    assert len(list_jobs(include_disabled=True)) == 1


def test_upsert_direct_job_is_idempotent(tmp_jobs_dir):
    """Re-registering the same (tenant_id, name) updates the existing row
    rather than creating a duplicate. Critical: prevents double-running the
    fleet supervisor when GitHub gets reinstalled."""
    from cron import direct_handlers
    from cron.jobs import upsert_direct_job, list_jobs

    direct_handlers._HANDLERS["fleet_supervise"] = lambda *a, **k: "ok"

    upsert_direct_job(
        tenant_id="tenant-1",
        handler="fleet_supervise",
        schedule="every 12 minutes",
        name="fleet-supervise:tenant-1",
    )
    upsert_direct_job(
        tenant_id="tenant-1",
        handler="fleet_supervise",
        schedule="every 6 minutes",  # changed cadence
        name="fleet-supervise:tenant-1",
    )

    jobs = list_jobs(include_disabled=True)
    assert len(jobs) == 1, f"expected one job after idempotent upsert, got {len(jobs)}"
    assert jobs[0]["schedule"]["minutes"] == 6


def test_upsert_direct_job_separate_tenants(tmp_jobs_dir):
    """Different tenants get their own jobs even with the same handler."""
    from cron import direct_handlers
    from cron.jobs import upsert_direct_job, list_jobs

    direct_handlers._HANDLERS["fleet_supervise"] = lambda *a, **k: "ok"

    upsert_direct_job(
        tenant_id="tenant-A",
        handler="fleet_supervise",
        schedule="every 12 minutes",
        name="fleet-supervise:tenant-A",
    )
    upsert_direct_job(
        tenant_id="tenant-B",
        handler="fleet_supervise",
        schedule="every 12 minutes",
        name="fleet-supervise:tenant-B",
    )
    jobs = list_jobs(include_disabled=True)
    assert len(jobs) == 2
    tenants = sorted(j["tenant_id"] for j in jobs)
    assert tenants == ["tenant-A", "tenant-B"]


def test_create_job_requires_tenant_for_direct_kind():
    """create_job's contract: kind='direct' without tenant_id is a coding bug,
    raise immediately rather than persist a malformed row."""
    from cron.jobs import create_job
    with pytest.raises(ValueError) as exc:
        create_job(
            prompt="x",
            schedule="every 12 minutes",
            kind="direct",
            handler="fleet_supervise",
            tenant_id=None,
        )
    assert "tenant_id" in str(exc.value)


def test_create_job_requires_handler_for_direct_kind():
    from cron.jobs import create_job
    with pytest.raises(ValueError) as exc:
        create_job(
            prompt="x",
            schedule="every 12 minutes",
            kind="direct",
            handler=None,
            tenant_id="t1",
        )
    assert "handler" in str(exc.value)
