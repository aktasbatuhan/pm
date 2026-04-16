"""Backward compatibility shim — use kai_time instead."""
from kai_time import *  # noqa: F401,F403
from kai_time import now, get_timezone, get_timezone_name, reset_cache  # noqa: F401
