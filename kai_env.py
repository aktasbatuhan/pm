"""
Kai Agent environment helpers.

Single source of truth for env var resolution and home directory.
Reads KAI_* first, falls back to HERMES_* for backward compatibility
with existing deployments during the naming migration.

Import-safe: no dependencies on other kai-agent modules.
"""

import os
from pathlib import Path

# Mapping: canonical KAI name → legacy HERMES name
_ENV_ALIASES = {
    "KAI_HOME": "HERMES_HOME",
    "KAI_MODEL": "HERMES_MODEL",
    "KAI_TIMEZONE": "HERMES_TIMEZONE",
    "KAI_SESSION_PLATFORM": "HERMES_SESSION_PLATFORM",
    "KAI_SESSION_CHAT_ID": "HERMES_SESSION_CHAT_ID",
    "KAI_SESSION_CHAT_NAME": "HERMES_SESSION_CHAT_NAME",
    "KAI_SESSION_KEY": "HERMES_SESSION_KEY",
    "KAI_REASONING_EFFORT": "HERMES_REASONING_EFFORT",
    "KAI_PREFILL_MESSAGES_FILE": "HERMES_PREFILL_MESSAGES_FILE",
    "KAI_INFERENCE_PROVIDER": "HERMES_INFERENCE_PROVIDER",
    "KAI_MAX_ITERATIONS": "HERMES_MAX_ITERATIONS",
    "KAI_WORKSPACE_ID": "HERMES_WORKSPACE_ID",
    "KAI_EPHEMERAL_SYSTEM_PROMPT": "HERMES_EPHEMERAL_SYSTEM_PROMPT",
    "KAI_BACKGROUND_NOTIFICATIONS": "HERMES_BACKGROUND_NOTIFICATIONS",
    "KAI_TOOL_PROGRESS_MODE": "HERMES_TOOL_PROGRESS_MODE",
    "KAI_DUMP_REQUEST_STDOUT": "HERMES_DUMP_REQUEST_STDOUT",
    "KAI_DUMP_REQUESTS": "HERMES_DUMP_REQUESTS",
    "KAI_NOUS_MIN_KEY_TTL_SECONDS": "HERMES_NOUS_MIN_KEY_TTL_SECONDS",
    "KAI_NOUS_TIMEOUT_SECONDS": "HERMES_NOUS_TIMEOUT_SECONDS",
}


def get_env(kai_name: str, default: str = "") -> str:
    """Read an env var with KAI_ → HERMES_ fallback.

    Args:
        kai_name: The canonical KAI_* variable name (e.g. "KAI_HOME")
        default: Default value if neither KAI_ nor HERMES_ is set

    Returns:
        The value from KAI_* if set, else HERMES_* if set, else default.
    """
    val = os.getenv(kai_name, "")
    if val:
        return val
    hermes_name = _ENV_ALIASES.get(kai_name, "")
    if hermes_name:
        val = os.getenv(hermes_name, "")
        if val:
            return val
    return default


def kai_home() -> Path:
    """Return the Kai agent home directory.

    Resolution order:
      1. KAI_HOME env var
      2. HERMES_HOME env var (backward compat)
      3. ~/.kai-agent/ if it exists
      4. ~/.hermes/ if it exists (backward compat)
      5. ~/.kai-agent/ (default, created on first use)
    """
    # Explicit env var
    env_home = get_env("KAI_HOME")
    if env_home:
        return Path(env_home)

    # Check which directory exists
    kai_dir = Path.home() / ".kai-agent"
    hermes_dir = Path.home() / ".hermes"

    if kai_dir.exists():
        return kai_dir
    if hermes_dir.exists():
        return hermes_dir

    # Neither exists — use new name
    return kai_dir


def ensure_kai_home() -> Path:
    """Return the Kai home directory, creating it if needed."""
    home = kai_home()
    home.mkdir(parents=True, exist_ok=True)
    return home
