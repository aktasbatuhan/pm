"""Safe runner for user-defined quick commands.

Replaces the unsafe `subprocess.run(cmd, shell=True)` pattern in cli.py
with `shlex.split()` + `shell=False` and an optional binary allowlist.
"""

import logging
import shlex
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Allowlist of safe command binaries. Commands not in this list will be
# blocked. Add entries as needed -- the goal is to prevent arbitrary
# binaries from being spawned via config-sourced quick_commands.
#
# To disable the allowlist entirely (not recommended), set
# QUICK_COMMAND_ALLOW_ALL=1 in the environment.
SAFE_BINARIES = {
    # Common dev tools
    "git", "gh", "docker", "docker-compose",
    "npm", "npx", "yarn", "pnpm", "bun",
    "pip", "pip3", "uv", "poetry", "pipenv",
    "python", "python3", "node",
    # File operations
    "ls", "cat", "head", "tail", "wc", "grep", "find", "tree",
    "cp", "mv", "mkdir",
    # System info
    "echo", "date", "whoami", "hostname", "uname", "env", "printenv",
    "ps", "top", "htop", "df", "du", "free",
    # Network
    "curl", "wget", "ping", "dig", "nslookup",
    # Build tools
    "make", "cmake", "cargo", "go", "rustc", "gcc", "g++",
    # Formatters/linters
    "prettier", "eslint", "black", "ruff", "mypy", "pylint",
    "pytest", "jest", "vitest",
}


def run_quick_command(
    command: str,
    timeout: int = 30,
    allow_all: bool = False,
) -> dict:
    """Run a quick command safely without shell=True.

    Args:
        command: The command string from config (e.g. "git status --short").
        timeout: Max seconds before the command is killed.
        allow_all: If True, skip the binary allowlist check.

    Returns:
        {"output": str, "returncode": int, "error": str or None}
    """
    import os

    if not command or not command.strip():
        return {"output": "", "returncode": 1, "error": "Empty command"}

    try:
        args = shlex.split(command)
    except ValueError as e:
        return {"output": "", "returncode": 1, "error": f"Invalid command syntax: {e}"}

    if not args:
        return {"output": "", "returncode": 1, "error": "Empty command after parsing"}

    binary = args[0]

    # Allow-all escape hatch (not recommended)
    if not allow_all and not os.getenv("QUICK_COMMAND_ALLOW_ALL"):
        # Extract just the binary name (strip path prefixes)
        binary_name = binary.rsplit("/", 1)[-1] if "/" in binary else binary
        if binary_name not in SAFE_BINARIES:
            logger.warning(
                "Quick command blocked: binary '%s' not in allowlist. "
                "Add it to SAFE_BINARIES in tools/quick_command_runner.py "
                "or set QUICK_COMMAND_ALLOW_ALL=1.",
                binary_name,
            )
            return {
                "output": "",
                "returncode": 1,
                "error": (
                    f"Blocked: '{binary_name}' is not in the quick command allowlist. "
                    f"Allowed binaries: {', '.join(sorted(SAFE_BINARIES)[:10])}... "
                    f"Edit tools/quick_command_runner.py to add it."
                ),
            }

    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return {"output": output, "returncode": result.returncode, "error": None}
    except subprocess.TimeoutExpired:
        return {"output": "", "returncode": 1, "error": f"Command timed out ({timeout}s)"}
    except FileNotFoundError:
        return {"output": "", "returncode": 1, "error": f"Command not found: {binary}"}
    except Exception as e:
        return {"output": "", "returncode": 1, "error": f"Execution error: {e}"}
