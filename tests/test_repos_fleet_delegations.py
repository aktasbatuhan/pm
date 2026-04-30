"""Round-trip tests for the fleet_delegations repo layer.

The supervisor calls upsert_fleet_delegation on every status() snapshot.
These tests cover the two real risks in that path:

  1. JSON columns (handle_json, artifacts_json, raw_json) get serialized
     correctly going in.
  2. The terminal_at semantics (set when state ∈ {done,failed,cancelled},
     cleared otherwise) are issued via the right SQL.

We mock get_pool() rather than hit a real Postgres so these stay
hermetic and fast.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class _FakeCursor:
    def __init__(self, fetch_row=None):
        self.executed: list = []
        self._fetch_row = fetch_row

    def execute(self, sql, args=None):
        self.executed.append({"sql": sql, "args": args})

    def fetchone(self):
        return self._fetch_row

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    @contextmanager
    def cursor(self):
        yield self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, cursor):
        self._cursor = cursor

    @contextmanager
    def connection(self):
        yield _FakeConn(self._cursor)


def _row(state="running", terminal_at=None) -> dict:
    """A representative fleet_delegations row as Postgres would return it."""
    return {
        "id": "abc123",
        "tenant_id": "tenant-1",
        "provider": "github_default",
        "provider_handle_key": "acme/api#10",
        "handle_json": {"repo": "acme/api", "issue_number": 10},
        "state": state,
        "state_detail": "PR open",
        "summary": "PR #42 awaiting review",
        "repo": "acme/api",
        "issue_number": 10,
        "task_id": "t1",
        "agent_id": "claude-code",
        "pr_number": 42,
        "artifacts_json": [{"kind": "pr", "url": "https://github.com/acme/api/pull/42"}],
        "raw_json": {"task_status": "pr_opened"},
        "last_activity_at": datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
        "terminal_at": terminal_at,
        "created_at": datetime(2026, 4, 30, 11, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
    }


def test_upsert_fleet_delegation_serializes_json_columns():
    """handle/artifacts/raw must hit the SQL as JSON strings, not raw dicts —
    psycopg with our schema needs json.dumps() before INSERT."""
    from backend import repos

    cur = _FakeCursor(fetch_row=_row())
    with patch("backend.repos.get_pool", return_value=_FakePool(cur)):
        result = repos.upsert_fleet_delegation(
            "tenant-1",
            provider="github_default",
            provider_handle_key="acme/api#10",
            handle={"repo": "acme/api", "issue_number": 10},
            state="running",
            state_detail="PR open",
            summary="PR #42 awaiting review",
            repo="acme/api",
            issue_number=10,
            task_id="t1",
            agent_id="claude-code",
            pr_number=42,
            artifacts=[{"kind": "pr", "url": "x"}],
            raw={"task_status": "pr_opened"},
            last_activity_at=1761830400.0,
        )

    assert len(cur.executed) == 1
    args = cur.executed[0]["args"]
    # Args index for JSON columns: handle_json=4, artifacts_json=13, raw_json=14
    assert json.loads(args[4]) == {"repo": "acme/api", "issue_number": 10}
    assert json.loads(args[13]) == [{"kind": "pr", "url": "x"}]
    assert json.loads(args[14]) == {"task_status": "pr_opened"}
    # Result is the shaped row, not the SQL row
    assert result["state"] == "running"
    assert result["handle"] == {"repo": "acme/api", "issue_number": 10}
    assert result["artifacts"] == [{"kind": "pr", "url": "https://github.com/acme/api/pull/42"}]


@pytest.mark.parametrize("state,is_terminal", [
    ("pending", False),
    ("running", False),
    ("review", False),
    ("done", True),
    ("failed", True),
    ("cancelled", True),
])
def test_upsert_fleet_delegation_terminal_flag(state, is_terminal):
    """The boolean passed to the CASE expression must reflect terminal-ness
    so first-write rows get terminal_at populated correctly."""
    from backend import repos

    cur = _FakeCursor(fetch_row=_row(state=state))
    with patch("backend.repos.get_pool", return_value=_FakePool(cur)):
        repos.upsert_fleet_delegation(
            "tenant-1",
            provider="github_default",
            provider_handle_key="k",
            handle={},
            state=state,
        )

    args = cur.executed[0]["args"]
    # The CASE WHEN %s flag is the 17th positional arg (index 16):
    # (id, tenant, provider, key, handle, state, detail, summary, repo,
    #  issue_number, task_id, agent_id, pr_number, artifacts, raw,
    #  last_activity, terminal_flag) -> 17 placeholders
    assert args[16] is is_terminal


def test_list_fleet_delegations_excludes_terminal_by_default():
    """list_fleet_delegations should hide done/failed/cancelled by default
    so the supervisor's open-work scan doesn't churn over closed stuff."""
    from backend import repos

    cur = _FakeCursor()
    with patch("backend.repos.get_pool", return_value=_FakePool(cur)):
        repos.list_fleet_delegations("tenant-1")

    sql = cur.executed[0]["sql"]
    assert "state NOT IN ('done', 'failed', 'cancelled')" in sql


def test_list_fleet_delegations_include_terminal_lifts_filter():
    from backend import repos

    cur = _FakeCursor()
    with patch("backend.repos.get_pool", return_value=_FakePool(cur)):
        repos.list_fleet_delegations("tenant-1", include_terminal=True)

    sql = cur.executed[0]["sql"]
    assert "state NOT IN" not in sql


def test_fleet_activity_summary_buckets_open_and_terminal():
    """Open states populate by_state; terminal rows fan out into
    completions/failures/cancellations based on their state."""
    from backend import repos

    # Three executes happen in order: open-state counts, new-since count,
    # terminal events. We return different fetchall rows per call.
    open_rows = [
        {"state": "pending", "c": 2},
        {"state": "running", "c": 3},
        {"state": "review", "c": 1},
    ]
    new_since_row = {"c": 4}
    terminal_rows = [
        {"state": "done", "repo": "acme/api", "issue_number": 10, "summary": "shipped", "terminal_at": datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc), "pr_number": 42},
        {"state": "failed", "repo": "acme/api", "issue_number": 11, "summary": "agent gave up", "terminal_at": datetime(2026, 4, 30, 11, 0, 0, tzinfo=timezone.utc), "pr_number": None},
        {"state": "cancelled", "repo": "acme/api", "issue_number": 12, "summary": "superseded", "terminal_at": datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc), "pr_number": None},
    ]

    cur = MagicMock()
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda *a: False
    cur.fetchall.side_effect = [open_rows, terminal_rows]
    cur.fetchone.side_effect = [new_since_row]

    @contextmanager
    def fake_cursor():
        yield cur

    conn = MagicMock()
    conn.cursor = fake_cursor

    @contextmanager
    def fake_conn():
        yield conn

    pool = MagicMock()
    pool.connection = fake_conn

    with patch("backend.repos.get_pool", return_value=pool):
        out = repos.fleet_activity_summary("tenant-1", since_ts=1761800000.0)

    assert out["by_state"] == {"pending": 2, "running": 3, "review": 1}
    assert out["open_total"] == 6
    assert out["new_since"] == 4
    assert len(out["completions"]) == 1 and out["completions"][0]["issue_number"] == 10
    assert len(out["failures"]) == 1 and out["failures"][0]["summary"] == "agent gave up"
    assert len(out["cancellations"]) == 1


def test_fleet_activity_summary_empty_buckets():
    """No rows at all → zero-valued shape, never raises."""
    from backend import repos

    cur = MagicMock()
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda *a: False
    cur.fetchall.side_effect = [[], []]
    cur.fetchone.side_effect = [{"c": 0}]

    @contextmanager
    def fake_cursor():
        yield cur

    conn = MagicMock()
    conn.cursor = fake_cursor

    @contextmanager
    def fake_conn():
        yield conn

    pool = MagicMock()
    pool.connection = fake_conn

    with patch("backend.repos.get_pool", return_value=pool):
        out = repos.fleet_activity_summary("tenant-1", since_ts=1761800000.0)

    assert out["open_total"] == 0
    assert out["new_since"] == 0
    assert out["completions"] == []
    assert out["failures"] == []
    assert out["cancellations"] == []


def test_shape_fleet_delegation_parses_json_strings():
    """If Postgres returns JSON columns as strings (depends on psycopg adapter
    config), _shape_fleet_delegation must json.loads them rather than leaving
    them as opaque strings."""
    from backend.repos import _shape_fleet_delegation

    row = _row()
    # Simulate a driver that returned JSONB as text
    row["handle_json"] = '{"k": "v"}'
    row["artifacts_json"] = '[{"a": 1}]'
    row["raw_json"] = '{}'

    out = _shape_fleet_delegation(row)
    assert out["handle"] == {"k": "v"}
    assert out["artifacts"] == [{"a": 1}]
    assert out["raw"] == {}
