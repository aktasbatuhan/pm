"""Neon Postgres client + connection pool.

Single global pool, lazily initialized. Use::

    from backend.db.postgres_client import get_pool, is_postgres_enabled

    if is_postgres_enabled():
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

Tenant scoping is enforced in app code (every query filters by ``tenant_id``).
RLS can be layered on later without code changes.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import psycopg
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None
_lock = threading.Lock()


def is_postgres_enabled() -> bool:
    """Return True if DATABASE_URL is set — gates the whole Postgres path."""
    return bool(os.getenv("DATABASE_URL", "").strip())


def get_pool() -> ConnectionPool:
    """Return a process-wide pooled connection to Neon.

    Uses the pooled URL (DATABASE_URL) by default. Prefer DATABASE_URL_DIRECT
    for migrations and long-running operations.
    """
    global _pool
    if _pool is not None:
        return _pool
    with _lock:
        if _pool is not None:
            return _pool
        url = os.getenv("DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError("DATABASE_URL is not set; Postgres is disabled.")
        _pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=10,
            max_idle=300,                          # recycle connections idle > 5min (Neon closes them)
            kwargs={"row_factory": psycopg.rows.dict_row},
            check=ConnectionPool.check_connection, # validate (SELECT 1) before handing out
            open=True,
        )
        logger.info("Initialized Neon connection pool (max=10, check=on)")
        return _pool


def get_direct_connection() -> psycopg.Connection:
    """Open a non-pooled connection (for migrations, backfills, listen/notify)."""
    url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL_DIRECT/DATABASE_URL not set.")
    return psycopg.connect(url, row_factory=psycopg.rows.dict_row)


def close_pool() -> None:
    """Close the global pool (e.g. during graceful shutdown / tests)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
