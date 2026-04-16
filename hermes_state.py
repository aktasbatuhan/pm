"""Backward compatibility shim — use kai_state instead."""
from kai_state import *  # noqa: F401,F403
from kai_state import SessionDB, DEFAULT_DB_PATH  # noqa: F401 — explicit re-exports
