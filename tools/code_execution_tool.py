#!/usr/bin/env python3
"""
Code Execution Tool -- Programmatic Tool Calling (PTC)

Lets the LLM write a Python script that calls Hermes tools via RPC,
collapsing multi-step tool chains into a single inference turn.

Architecture:
  1. Parent generates a `dash_tools.py` stub module with RPC functions
  2. Parent opens a Unix domain socket and starts an RPC listener thread
  3. Parent spawns a child process that runs the LLM's script
  4. When the script calls a tool function, the call travels over the UDS
     back to the parent, which dispatches through handle_function_call
  5. Only the script's stdout is returned to the LLM; intermediate tool
     results never enter the context window

Platform: Linux / macOS only (Unix domain sockets). Disabled on Windows.

Security layers (defense-in-depth):
  LAYER 1 - OS-level resource limits via rlimit in the child preexec_fn
  LAYER 2 - Pre-execution code safety screening (regex-based blocklist)
  LAYER 3 - Strict tools fallback: empty intersection = error, not all-tools
"""

import json
import logging
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

_IS_WINDOWS = platform.system() == "Windows"
from typing import Any, Dict, List, Optional

from kai_env import kai_home, get_env

# Availability gate: UDS requires a POSIX OS
logger = logging.getLogger(__name__)

SANDBOX_AVAILABLE = sys.platform != "win32"

# The 7 tools allowed inside the sandbox. The intersection of this list
# and the session's enabled tools determines which stubs are generated.
SANDBOX_ALLOWED_TOOLS = frozenset([
    "web_search",
    "web_extract",
    "read_file",
    "write_file",
    "search_files",
    "patch",
    "terminal",
])

# Resource limit defaults (overridable via config.yaml → code_execution.*)
DEFAULT_TIMEOUT = 300        # 5 minutes
DEFAULT_MAX_TOOL_CALLS = 50
MAX_STDOUT_BYTES = 50_000    # 50 KB
MAX_STDERR_BYTES = 10_000    # 10 KB

# ---------------------------------------------------------------------------
# LAYER 1: OS-level resource limits via rlimit
# ---------------------------------------------------------------------------
# These limits are applied in the child process via preexec_fn BEFORE the
# Python interpreter loads the user's script. They are enforced by the kernel
# and cannot be bypassed from userspace.

_RLIMIT_CPU_SECONDS = 30           # Hard CPU time limit
_RLIMIT_AS_BYTES = 512 * 1024 * 1024  # 512 MB virtual memory
_RLIMIT_NOFILE = 64                # Max open file descriptors
_RLIMIT_NPROC = 0                  # No child process forking

try:
    import resource as _resource
    _HAS_RESOURCE = True
except ImportError:
    # Windows does not have the resource module; rlimits are skipped there
    # (the sandbox is already disabled on Windows via SANDBOX_AVAILABLE).
    _HAS_RESOURCE = False


def _make_sandbox_preexec(sock_fd: int):
    """
    Factory that returns a preexec_fn callable for Popen.

    The returned function runs in the child process after fork() but before
    exec(), so it can set up the sandbox environment:
      1. Create a new session (os.setsid) to isolate the process group
      2. Set resource limits (CPU, memory, file descriptors, no-fork)
      3. Close inherited file descriptors except stdin/stdout/stderr and
         the RPC socket fd so the child cannot access parent resources

    Args:
        sock_fd: The file descriptor number of the RPC Unix domain socket
                 that the child needs to keep open for tool calls.
    """
    def _preexec():
        # 1. New session (isolate process group for clean kill)
        os.setsid()

        # 2. Set resource limits (kernel-enforced, cannot be bypassed)
        if _HAS_RESOURCE:
            # CPU time: soft = hard = 30s. After 30s of CPU time the kernel
            # sends SIGKILL (hard limit).
            _resource.setrlimit(
                _resource.RLIMIT_CPU,
                (_RLIMIT_CPU_SECONDS, _RLIMIT_CPU_SECONDS),
            )
            # Virtual address space: 512 MB. Prevents memory bombs.
            _resource.setrlimit(
                _resource.RLIMIT_AS,
                (_RLIMIT_AS_BYTES, _RLIMIT_AS_BYTES),
            )
            # File descriptors: 64. Limits file/socket open abuse.
            _resource.setrlimit(
                _resource.RLIMIT_NOFILE,
                (_RLIMIT_NOFILE, _RLIMIT_NOFILE),
            )
            # No child processes: prevents fork bombs and subprocess spawning.
            _resource.setrlimit(
                _resource.RLIMIT_NPROC,
                (_RLIMIT_NPROC, _RLIMIT_NPROC),
            )

        # 3. Close inherited file descriptors except the ones we need.
        # Keep: 0 (stdin), 1 (stdout), 2 (stderr), and the RPC socket fd.
        keep_fds = {0, 1, 2, sock_fd}
        try:
            # Try /proc/self/fd first (Linux) for accuracy
            if os.path.isdir("/proc/self/fd"):
                open_fds = [int(fd) for fd in os.listdir("/proc/self/fd")]
            else:
                # Fallback: scan a reasonable range
                try:
                    max_fd = _resource.getrlimit(_resource.RLIMIT_NOFILE)[1] if _HAS_RESOURCE else 1024
                except Exception:
                    max_fd = 1024
                max_fd = min(max_fd, 4096)  # Don't scan too many
                open_fds = range(3, max_fd)

            for fd in open_fds:
                if fd not in keep_fds:
                    try:
                        os.close(fd)
                    except OSError:
                        pass  # Already closed or not open
        except Exception:
            # If fd enumeration fails entirely, don't block execution —
            # the other layers (code screening, rlimits) still protect.
            pass

    return _preexec


# ---------------------------------------------------------------------------
# LAYER 2: Pre-execution code safety screening
# ---------------------------------------------------------------------------
# NOTE: This is defense-in-depth, NOT a complete sandbox. A determined
# attacker can bypass regex-based screening (e.g., string concatenation,
# getattr tricks, encoded payloads). The primary sandbox is the rlimit
# layer above, which is kernel-enforced. This screening catches the common
# cases and raises the bar significantly for LLM-generated code.

_DANGEROUS_PATTERNS = [
    # 1. os.system() — shell command execution
    (re.compile(r'os\.system\s*\(', re.IGNORECASE), "os.system() — shell command execution"),
    # 2. os.popen() — shell command execution via pipe
    (re.compile(r'os\.popen\s*\(', re.IGNORECASE), "os.popen() — shell command via pipe"),
    # 3. os.exec* — covers execl, execle, execlp, execv, execve, execvp, etc.
    (re.compile(r'os\.exec', re.IGNORECASE), "os.exec*() — direct process execution"),
    # 4. subprocess.* — any subprocess usage
    (re.compile(r'subprocess\.', re.IGNORECASE), "subprocess module — direct process spawning"),
    # 5. __import__() — dynamic imports bypass static analysis
    (re.compile(r'__import__\s*\('), "__import__() — dynamic import"),
    # 6. importlib — runtime module loading
    (re.compile(r'importlib', re.IGNORECASE), "importlib — dynamic module loading"),
    # 7. ctypes — foreign function interface, raw memory access
    (re.compile(r'ctypes', re.IGNORECASE), "ctypes — foreign function interface"),
    # 8. socket.socket() — raw socket creation (NOT the RPC socket in dash_tools)
    (re.compile(r'socket\.socket\s*\('), "socket.socket() — raw socket creation"),
    # 9. shutil.rmtree — recursive directory deletion
    (re.compile(r'shutil\.rmtree', re.IGNORECASE), "shutil.rmtree() — recursive deletion"),
    # 10. os.remove / os.unlink — file deletion
    (re.compile(r'os\.(?:remove|unlink)\s*\(', re.IGNORECASE), "os.remove/unlink() — file deletion"),
    # 11. eval() — arbitrary code evaluation
    (re.compile(r'(?<!\w)eval\s*\('), "eval() — arbitrary code evaluation"),
    # 12. exec() — arbitrary code execution
    (re.compile(r'(?<!\w)exec\s*\('), "exec() — arbitrary code execution"),
    # 13. compile() — code compilation (often paired with eval/exec)
    (re.compile(r'(?<!\w)compile\s*\('), "compile() — code compilation"),
    # 14. open() accessing sensitive paths
    (re.compile(r'open\s*\(.*(?:/etc|/proc|/sys|\.ssh|\.aws|\.env)', re.IGNORECASE),
     "open() accessing sensitive system paths (/etc, /proc, /sys, .ssh, .aws, .env)"),
]


def _screen_code(code: str) -> Optional[str]:
    """
    Screen LLM-generated code for dangerous patterns before execution.

    This is a defense-in-depth measure — not a complete sandbox. It catches
    the most common dangerous patterns to prevent accidental or naive
    exploitation. Sophisticated attacks may bypass regex screening, which
    is why LAYER 1 (rlimits) provides the kernel-enforced safety net.

    Args:
        code: The raw Python source code to screen.

    Returns:
        None if the code passes screening, or an error message string
        describing what was blocked.
    """
    blocked = []
    for pattern, description in _DANGEROUS_PATTERNS:
        if pattern.search(code):
            blocked.append(description)

    if blocked:
        violations = "; ".join(blocked)
        return (
            f"Code blocked by safety screening: {violations}. "
            "Use the available dash_tools functions (web_search, terminal, etc.) "
            "instead of direct system access. If you need shell commands, use "
            "terminal() from dash_tools."
        )
    return None


def check_sandbox_requirements() -> bool:
    """Code execution sandbox requires a POSIX OS for Unix domain sockets."""
    return SANDBOX_AVAILABLE


# ---------------------------------------------------------------------------
# dash_tools.py code generator
# ---------------------------------------------------------------------------

# Per-tool stub templates: (function_name, signature, docstring, args_dict_expr)
# The args_dict_expr builds the JSON payload sent over the RPC socket.
_TOOL_STUBS = {
    "web_search": (
        "web_search",
        "query: str, limit: int = 5",
        '"""Search the web. Returns dict with data.web list of {url, title, description}."""',
        '{"query": query, "limit": limit}',
    ),
    "web_extract": (
        "web_extract",
        "urls: list",
        '"""Extract content from URLs. Returns dict with results list of {url, title, content, error}."""',
        '{"urls": urls}',
    ),
    "read_file": (
        "read_file",
        "path: str, offset: int = 1, limit: int = 500",
        '"""Read a file (1-indexed lines). Returns dict with "content" and "total_lines"."""',
        '{"path": path, "offset": offset, "limit": limit}',
    ),
    "write_file": (
        "write_file",
        "path: str, content: str",
        '"""Write content to a file (always overwrites). Returns dict with status."""',
        '{"path": path, "content": content}',
    ),
    "search_files": (
        "search_files",
        'pattern: str, target: str = "content", path: str = ".", file_glob: str = None, limit: int = 50, offset: int = 0, output_mode: str = "content", context: int = 0',
        '"""Search file contents (target="content") or find files by name (target="files"). Returns dict with "matches"."""',
        '{"pattern": pattern, "target": target, "path": path, "file_glob": file_glob, "limit": limit, "offset": offset, "output_mode": output_mode, "context": context}',
    ),
    "patch": (
        "patch",
        'path: str = None, old_string: str = None, new_string: str = None, replace_all: bool = False, mode: str = "replace", patch: str = None',
        '"""Targeted find-and-replace (mode="replace") or V4A multi-file patches (mode="patch"). Returns dict with status."""',
        '{"path": path, "old_string": old_string, "new_string": new_string, "replace_all": replace_all, "mode": mode, "patch": patch}',
    ),
    "terminal": (
        "terminal",
        "command: str, timeout: int = None, workdir: str = None",
        '"""Run a shell command (foreground only). Returns dict with "output" and "exit_code"."""',
        '{"command": command, "timeout": timeout, "workdir": workdir}',
    ),
}


def generate_dash_tools_module(enabled_tools: List[str]) -> str:
    """
    Build the source code for the dash_tools.py stub module.

    Only tools in both SANDBOX_ALLOWED_TOOLS and enabled_tools get stubs.
    """
    tools_to_generate = sorted(SANDBOX_ALLOWED_TOOLS & set(enabled_tools))

    stub_functions = []
    export_names = []
    for tool_name in tools_to_generate:
        if tool_name not in _TOOL_STUBS:
            continue
        func_name, sig, doc, args_expr = _TOOL_STUBS[tool_name]
        stub_functions.append(
            f"def {func_name}({sig}):\n"
            f"    {doc}\n"
            f"    return _call({func_name!r}, {args_expr})\n"
        )
        export_names.append(func_name)

    header = '''\
"""Auto-generated Hermes tools RPC stubs."""
import json, os, socket, shlex, time

_sock = None


# ---------------------------------------------------------------------------
# Convenience helpers (avoid common scripting pitfalls)
# ---------------------------------------------------------------------------

def json_parse(text: str):
    """Parse JSON tolerant of control characters (strict=False).
    Use this instead of json.loads() when parsing output from terminal()
    or web_extract() that may contain raw tabs/newlines in strings."""
    return json.loads(text, strict=False)


def shell_quote(s: str) -> str:
    """Shell-escape a string for safe interpolation into commands.
    Use this when inserting dynamic content into terminal() commands:
        terminal(f"echo {shell_quote(user_input)}")
    """
    return shlex.quote(s)


def retry(fn, max_attempts=3, delay=2):
    """Retry a function up to max_attempts times with exponential backoff.
    Use for transient failures (network errors, API rate limits):
        result = retry(lambda: terminal("gh issue list ..."))
    """
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(delay * (2 ** attempt))
    raise last_err

def _connect():
    global _sock
    if _sock is None:
        _sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        _sock.connect(os.environ["HERMES_RPC_SOCKET"])
        _sock.settimeout(300)
    return _sock

def _call(tool_name, args):
    """Send a tool call to the parent process and return the parsed result."""
    conn = _connect()
    request = json.dumps({"tool": tool_name, "args": args}) + "\\n"
    conn.sendall(request.encode())
    buf = b""
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            raise RuntimeError("Agent process disconnected")
        buf += chunk
        if buf.endswith(b"\\n"):
            break
    raw = buf.decode().strip()
    result = json.loads(raw)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result
    return result

'''

    return header + "\n".join(stub_functions)


# ---------------------------------------------------------------------------
# RPC server (runs in a thread inside the parent process)
# ---------------------------------------------------------------------------

# Terminal parameters that must not be used from ephemeral sandbox scripts
_TERMINAL_BLOCKED_PARAMS = {"background", "check_interval", "pty"}


def _rpc_server_loop(
    server_sock: socket.socket,
    task_id: str,
    tool_call_log: list,
    tool_call_counter: list,   # mutable [int] so the thread can increment
    max_tool_calls: int,
    allowed_tools: frozenset,
):
    """
    Accept one client connection and dispatch tool-call requests until
    the client disconnects or the call limit is reached.
    """
    from model_tools import handle_function_call

    conn = None
    try:
        server_sock.settimeout(5)
        conn, _ = server_sock.accept()
        conn.settimeout(300)

        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk

            # Process all complete newline-delimited messages in the buffer
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue

                call_start = time.monotonic()
                try:
                    request = json.loads(line.decode())
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    resp = json.dumps({"error": f"Invalid RPC request: {exc}"})
                    conn.sendall((resp + "\n").encode())
                    continue

                tool_name = request.get("tool", "")
                tool_args = request.get("args", {})

                # Enforce the allow-list
                if tool_name not in allowed_tools:
                    available = ", ".join(sorted(allowed_tools))
                    resp = json.dumps({
                        "error": (
                            f"Tool '{tool_name}' is not available in execute_code. "
                            f"Available: {available}"
                        )
                    })
                    conn.sendall((resp + "\n").encode())
                    continue

                # Enforce tool call limit
                if tool_call_counter[0] >= max_tool_calls:
                    resp = json.dumps({
                        "error": (
                            f"Tool call limit reached ({max_tool_calls}). "
                            "No more tool calls allowed in this execution."
                        )
                    })
                    conn.sendall((resp + "\n").encode())
                    continue

                # Strip forbidden terminal parameters
                if tool_name == "terminal" and isinstance(tool_args, dict):
                    for param in _TERMINAL_BLOCKED_PARAMS:
                        tool_args.pop(param, None)

                # Dispatch through the standard tool handler.
                # Suppress stdout/stderr from internal tool handlers so
                # their status prints don't leak into the CLI spinner.
                try:
                    _real_stdout, _real_stderr = sys.stdout, sys.stderr
                    sys.stdout = open(os.devnull, "w")
                    sys.stderr = open(os.devnull, "w")
                    try:
                        result = handle_function_call(
                            tool_name, tool_args, task_id=task_id
                        )
                    finally:
                        sys.stdout.close()
                        sys.stderr.close()
                        sys.stdout, sys.stderr = _real_stdout, _real_stderr
                except Exception as exc:
                    logger.error("Tool call failed in sandbox: %s", exc, exc_info=True)
                    result = json.dumps({"error": str(exc)})

                tool_call_counter[0] += 1
                call_duration = time.monotonic() - call_start

                # Log for observability
                args_preview = str(tool_args)[:80]
                tool_call_log.append({
                    "tool": tool_name,
                    "args_preview": args_preview,
                    "duration": round(call_duration, 2),
                })

                conn.sendall((result + "\n").encode())

    except socket.timeout:
        logger.debug("RPC listener socket timeout")
    except OSError as e:
        logger.debug("RPC listener socket error: %s", e, exc_info=True)
    finally:
        if conn:
            try:
                conn.close()
            except OSError as e:
                logger.debug("RPC conn close error: %s", e)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def execute_code(
    code: str,
    task_id: Optional[str] = None,
    enabled_tools: Optional[List[str]] = None,
) -> str:
    """
    Run a Python script in a sandboxed child process with RPC access
    to a subset of Hermes tools.

    Security layers applied:
      1. Code screening (LAYER 2) rejects scripts with dangerous patterns
      2. OS rlimits (LAYER 1) constrain CPU, memory, fds, and forking
      3. Strict tool intersection (LAYER 3) prevents tools fallback

    Args:
        code:          Python source code to execute.
        task_id:       Session task ID for tool isolation (terminal env, etc.).
        enabled_tools: Tool names enabled in the current session. The sandbox
                       gets the intersection with SANDBOX_ALLOWED_TOOLS.

    Returns:
        JSON string with execution results.
    """
    if not SANDBOX_AVAILABLE:
        return json.dumps({
            "error": "execute_code is not available on Windows. Use normal tool calls instead."
        })

    if not code or not code.strip():
        return json.dumps({"error": "No code provided."})

    # -----------------------------------------------------------------------
    # LAYER 2: Pre-execution code safety screening
    # -----------------------------------------------------------------------
    # Screen the code BEFORE writing it to disk or spawning any process.
    # This catches the most common dangerous patterns at zero cost.
    screening_result = _screen_code(code)
    if screening_result is not None:
        return json.dumps({
            "status": "error",
            "error": screening_result,
            "output": "",
            "tool_calls_made": 0,
            "duration_seconds": 0,
        }, ensure_ascii=False)

    # Import interrupt event from terminal_tool (cooperative cancellation)
    from tools.terminal_tool import _interrupt_event

    # Resolve config
    _cfg = _load_config()
    timeout = _cfg.get("timeout", DEFAULT_TIMEOUT)
    max_tool_calls = _cfg.get("max_tool_calls", DEFAULT_MAX_TOOL_CALLS)

    # -----------------------------------------------------------------------
    # LAYER 3: Strict tools intersection (no unsafe fallback)
    # -----------------------------------------------------------------------
    # If enabled_tools is None (not provided), fall back to all sandbox tools.
    # If enabled_tools is explicitly provided but the intersection with
    # SANDBOX_ALLOWED_TOOLS is empty, return an error — do NOT silently
    # grant access to all tools.
    if enabled_tools is None:
        # No tool list provided at all — use the full sandbox set
        sandbox_tools = SANDBOX_ALLOWED_TOOLS
    else:
        session_tools = set(enabled_tools)
        sandbox_tools = frozenset(SANDBOX_ALLOWED_TOOLS & session_tools)
        if not sandbox_tools:
            available = ", ".join(sorted(SANDBOX_ALLOWED_TOOLS))
            requested = ", ".join(sorted(session_tools)) if session_tools else "(empty)"
            return json.dumps({
                "status": "error",
                "error": (
                    f"No sandbox tools available. The enabled tools ({requested}) "
                    f"have no overlap with sandbox-allowed tools ({available}). "
                    "Cannot execute code without at least one available tool."
                ),
                "output": "",
                "tool_calls_made": 0,
                "duration_seconds": 0,
            }, ensure_ascii=False)

    # --- Set up temp directory with dash_tools.py and script.py ---
    tmpdir = tempfile.mkdtemp(prefix="hermes_sandbox_")
    # Use /tmp on macOS to avoid the long /var/folders/... path that pushes
    # Unix domain socket paths past the 104-byte macOS AF_UNIX limit.
    # On Linux, tempfile.gettempdir() already returns /tmp.
    _sock_tmpdir = "/tmp" if sys.platform == "darwin" else tempfile.gettempdir()
    sock_path = os.path.join(_sock_tmpdir, f"hermes_rpc_{uuid.uuid4().hex}.sock")

    tool_call_log: list = []
    tool_call_counter = [0]  # mutable so the RPC thread can increment
    exec_start = time.monotonic()

    try:
        # Write the auto-generated dash_tools module
        # sandbox_tools is already the correct set (intersection with session
        # tools, or SANDBOX_ALLOWED_TOOLS as fallback — see lines above).
        tools_src = generate_dash_tools_module(list(sandbox_tools))
        with open(os.path.join(tmpdir, "dash_tools.py"), "w") as f:
            f.write(tools_src)

        # Write the user's script
        with open(os.path.join(tmpdir, "script.py"), "w") as f:
            f.write(code)

        # --- Start UDS server ---
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(sock_path)
        server_sock.listen(1)

        rpc_thread = threading.Thread(
            target=_rpc_server_loop,
            args=(
                server_sock, task_id, tool_call_log,
                tool_call_counter, max_tool_calls, sandbox_tools,
            ),
            daemon=True,
        )
        rpc_thread.start()

        # --- Spawn child process ---
        # Build a minimal environment for the child. We intentionally exclude
        # API keys and tokens to prevent credential exfiltration from LLM-
        # generated scripts. The child accesses tools via RPC, not direct API.
        _SAFE_ENV_PREFIXES = ("PATH", "HOME", "USER", "LANG", "LC_", "TERM",
                              "TMPDIR", "TMP", "TEMP", "SHELL", "LOGNAME",
                              "XDG_", "PYTHONPATH", "VIRTUAL_ENV", "CONDA")
        _SECRET_SUBSTRINGS = ("KEY", "API", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
                              "PASSWD", "AUTH")
        child_env = {}
        for k, v in os.environ.items():
            if any(s in k.upper() for s in _SECRET_SUBSTRINGS):
                continue
            if any(k.startswith(p) for p in _SAFE_ENV_PREFIXES):
                child_env[k] = v
        child_env["HERMES_RPC_SOCKET"] = sock_path
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        # Inject user's configured timezone so datetime.now() in sandboxed
        # code reflects the correct wall-clock time.
        _tz_name = (get_env("KAI_TIMEZONE") or "").strip()
        if _tz_name:
            child_env["TZ"] = _tz_name

        # -------------------------------------------------------------------
        # LAYER 1: Apply OS-level sandbox via preexec_fn
        # -------------------------------------------------------------------
        # Get the server socket fd so the child can keep it open for RPC.
        # The child connects to the socket via the path in HERMES_RPC_SOCKET,
        # but we pass the server socket fd to _make_sandbox_preexec so it
        # is NOT closed during fd cleanup. Note: the child actually creates
        # its OWN socket in dash_tools._connect(), so we mainly need to
        # ensure the preexec_fn doesn't interfere. We pass -1 as the sock_fd
        # since the child will create its own connection after exec.
        if _IS_WINDOWS:
            preexec = None
        else:
            # Pass server_sock.fileno() through so the preexec_fn knows
            # which fds to preserve. The child process will create its own
            # socket connection via dash_tools._connect().
            preexec = _make_sandbox_preexec(server_sock.fileno())

        proc = subprocess.Popen(
            [sys.executable, "script.py"],
            cwd=tmpdir,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            preexec_fn=preexec,
        )

        # --- Poll loop: watch for exit, timeout, and interrupt ---
        deadline = time.monotonic() + timeout
        stderr_chunks: list = []

        # Background readers to avoid pipe buffer deadlocks.
        # For stdout we use a head+tail strategy: keep the first HEAD_BYTES
        # and a rolling window of the last TAIL_BYTES so the final print()
        # output is never lost.  Stderr keeps head-only (errors appear early).
        _STDOUT_HEAD_BYTES = int(MAX_STDOUT_BYTES * 0.4)   # 40% head
        _STDOUT_TAIL_BYTES = MAX_STDOUT_BYTES - _STDOUT_HEAD_BYTES  # 60% tail

        def _drain(pipe, chunks, max_bytes):
            """Simple head-only drain (used for stderr)."""
            total = 0
            try:
                while True:
                    data = pipe.read(4096)
                    if not data:
                        break
                    if total < max_bytes:
                        keep = max_bytes - total
                        chunks.append(data[:keep])
                    total += len(data)
            except (ValueError, OSError) as e:
                logger.debug("Error reading process output: %s", e, exc_info=True)

        stdout_total_bytes = [0]  # mutable ref for total bytes seen

        def _drain_head_tail(pipe, head_chunks, tail_chunks, head_bytes, tail_bytes, total_ref):
            """Drain stdout keeping both head and tail data."""
            head_collected = 0
            from collections import deque
            tail_buf = deque()
            tail_collected = 0
            try:
                while True:
                    data = pipe.read(4096)
                    if not data:
                        break
                    total_ref[0] += len(data)
                    # Fill head buffer first
                    if head_collected < head_bytes:
                        keep = min(len(data), head_bytes - head_collected)
                        head_chunks.append(data[:keep])
                        head_collected += keep
                        data = data[keep:]  # remaining goes to tail
                        if not data:
                            continue
                    # Everything past head goes into rolling tail buffer
                    tail_buf.append(data)
                    tail_collected += len(data)
                    # Evict old tail data to stay within tail_bytes budget
                    while tail_collected > tail_bytes and tail_buf:
                        oldest = tail_buf.popleft()
                        tail_collected -= len(oldest)
            except (ValueError, OSError):
                pass
            # Transfer final tail to output list
            tail_chunks.extend(tail_buf)

        stdout_head_chunks: list = []
        stdout_tail_chunks: list = []

        stdout_reader = threading.Thread(
            target=_drain_head_tail,
            args=(proc.stdout, stdout_head_chunks, stdout_tail_chunks,
                  _STDOUT_HEAD_BYTES, _STDOUT_TAIL_BYTES, stdout_total_bytes),
            daemon=True
        )
        stderr_reader = threading.Thread(
            target=_drain, args=(proc.stderr, stderr_chunks, MAX_STDERR_BYTES), daemon=True
        )
        stdout_reader.start()
        stderr_reader.start()

        status = "success"
        while proc.poll() is None:
            if _interrupt_event.is_set():
                _kill_process_group(proc)
                status = "interrupted"
                break
            if time.monotonic() > deadline:
                _kill_process_group(proc, escalate=True)
                status = "timeout"
                break
            time.sleep(0.2)

        # Wait for readers to finish draining
        stdout_reader.join(timeout=3)
        stderr_reader.join(timeout=3)

        stdout_head = b"".join(stdout_head_chunks).decode("utf-8", errors="replace")
        stdout_tail = b"".join(stdout_tail_chunks).decode("utf-8", errors="replace")
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        # Assemble stdout with head+tail truncation
        total_stdout = stdout_total_bytes[0]
        if total_stdout > MAX_STDOUT_BYTES and stdout_tail:
            omitted = total_stdout - len(stdout_head) - len(stdout_tail)
            truncated_notice = (
                f"\n\n... [OUTPUT TRUNCATED - {omitted:,} chars omitted "
                f"out of {total_stdout:,} total] ...\n\n"
            )
            stdout_text = stdout_head + truncated_notice + stdout_tail
        else:
            stdout_text = stdout_head + stdout_tail

        exit_code = proc.returncode if proc.returncode is not None else -1
        duration = round(time.monotonic() - exec_start, 2)

        # Wait for RPC thread to finish
        server_sock.close()  # break accept() so thread exits promptly
        rpc_thread.join(timeout=3)

        # Build response
        result: Dict[str, Any] = {
            "status": status,
            "output": stdout_text,
            "tool_calls_made": tool_call_counter[0],
            "duration_seconds": duration,
        }

        if status == "timeout":
            result["error"] = f"Script timed out after {timeout}s and was killed."
        elif status == "interrupted":
            result["output"] = stdout_text + "\n[execution interrupted — user sent a new message]"
        elif exit_code != 0:
            result["status"] = "error"
            result["error"] = stderr_text or f"Script exited with code {exit_code}"
            # Include stderr in output so the LLM sees the traceback
            if stderr_text:
                result["output"] = stdout_text + "\n--- stderr ---\n" + stderr_text

        return json.dumps(result, ensure_ascii=False)

    except Exception as exc:
        duration = round(time.monotonic() - exec_start, 2)
        logging.exception("execute_code failed")
        return json.dumps({
            "status": "error",
            "error": str(exc),
            "tool_calls_made": tool_call_counter[0],
            "duration_seconds": duration,
        }, ensure_ascii=False)

    finally:
        # Cleanup temp dir and socket
        try:
            server_sock.close()
        except Exception as e:
            logger.debug("Server socket close error: %s", e)
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            logger.debug("Could not clean temp dir: %s", e, exc_info=True)
        try:
            os.unlink(sock_path)
        except OSError as e:
            logger.debug("Could not remove socket file: %s", e, exc_info=True)


def _kill_process_group(proc, escalate: bool = False):
    """Kill the child and its entire process group."""
    try:
        if _IS_WINDOWS:
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as e:
        logger.debug("Could not kill process group: %s", e, exc_info=True)
        try:
            proc.kill()
        except Exception as e2:
            logger.debug("Could not kill process: %s", e2, exc_info=True)

    if escalate:
        # Give the process 5s to exit after SIGTERM, then SIGKILL
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if _IS_WINDOWS:
                    proc.kill()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError) as e:
                logger.debug("Could not kill process group with SIGKILL: %s", e, exc_info=True)
                try:
                    proc.kill()
                except Exception as e2:
                    logger.debug("Could not kill process: %s", e2, exc_info=True)


def _load_config() -> dict:
    """Load code_execution config from CLI_CONFIG if available."""
    try:
        from cli import CLI_CONFIG
        return CLI_CONFIG.get("code_execution", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# OpenAI Function-Calling Schema
# ---------------------------------------------------------------------------

# Per-tool documentation lines for the execute_code description.
# Ordered to match the canonical display order.
_TOOL_DOC_LINES = [
    ("web_search",
     "  web_search(query: str, limit: int = 5) -> dict\n"
     "    Returns {\"data\": {\"web\": [{\"url\", \"title\", \"description\"}, ...]}}"),
    ("web_extract",
     "  web_extract(urls: list[str]) -> dict\n"
     "    Returns {\"results\": [{\"url\", \"title\", \"content\", \"error\"}, ...]} where content is markdown"),
    ("read_file",
     "  read_file(path: str, offset: int = 1, limit: int = 500) -> dict\n"
     "    Lines are 1-indexed. Returns {\"content\": \"...\", \"total_lines\": N}"),
    ("write_file",
     "  write_file(path: str, content: str) -> dict\n"
     "    Always overwrites the entire file."),
    ("search_files",
     "  search_files(pattern: str, target=\"content\", path=\".\", file_glob=None, limit=50) -> dict\n"
     "    target: \"content\" (search inside files) or \"files\" (find files by name). Returns {\"matches\": [...]}"),
    ("patch",
     "  patch(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict\n"
     "    Replaces old_string with new_string in the file."),
    ("terminal",
     "  terminal(command: str, timeout=None, workdir=None) -> dict\n"
     "    Foreground only (no background/pty). Returns {\"output\": \"...\", \"exit_code\": N}"),
]


def build_execute_code_schema(enabled_sandbox_tools: set = None) -> dict:
    """Build the execute_code schema with description listing only enabled tools.

    When tools are disabled via ``hermes tools`` (e.g. web is turned off),
    the schema description should NOT mention web_search / web_extract —
    otherwise the model thinks they are available and keeps trying to use them.
    """
    if enabled_sandbox_tools is None:
        enabled_sandbox_tools = SANDBOX_ALLOWED_TOOLS

    # Build tool documentation lines for only the enabled tools
    tool_lines = "\n".join(
        doc for name, doc in _TOOL_DOC_LINES if name in enabled_sandbox_tools
    )

    # Build example import list from enabled tools
    import_examples = [n for n in ("web_search", "terminal") if n in enabled_sandbox_tools]
    if not import_examples:
        import_examples = sorted(enabled_sandbox_tools)[:2]
    if import_examples:
        import_str = ", ".join(import_examples) + ", ..."
    else:
        import_str = "..."

    description = (
        "Run a Python script that can call Hermes tools programmatically. "
        "Use this when you need 3+ tool calls with processing logic between them, "
        "need to filter/reduce large tool outputs before they enter your context, "
        "need conditional branching (if X then Y else Z), or need to loop "
        "(fetch N pages, process N files, retry on failure).\n\n"
        "Use normal tool calls instead when: single tool call with no processing, "
        "you need to see the full result and apply complex reasoning, "
        "or the task requires interactive user input.\n\n"
        f"Available via `from dash_tools import ...`:\n\n"
        f"{tool_lines}\n\n"
        "Limits: 5-minute timeout, 50KB stdout cap, max 50 tool calls per script. "
        "terminal() is foreground-only (no background or pty).\n\n"
        "Print your final result to stdout. Use Python stdlib (json, re, math, csv, "
        "datetime, collections, etc.) for processing between tool calls.\n\n"
        "Also available (no import needed — built into dash_tools):\n"
        "  json_parse(text: str) — json.loads with strict=False; use for terminal() output with control chars\n"
        "  shell_quote(s: str) — shlex.quote(); use when interpolating dynamic strings into shell commands\n"
        "  retry(fn, max_attempts=3, delay=2) — retry with exponential backoff for transient failures"
    )

    return {
        "name": "execute_code",
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Python code to execute. Import tools with "
                        f"`from dash_tools import {import_str}` "
                        "and print your final result to stdout."
                    ),
                },
            },
            "required": ["code"],
        },
    }


# Default schema used at registration time (all sandbox tools listed)
EXECUTE_CODE_SCHEMA = build_execute_code_schema()


# --- Registry ---
from tools.registry import registry

registry.register(
    name="execute_code",
    toolset="code_execution",
    schema=EXECUTE_CODE_SCHEMA,
    handler=lambda args, **kw: execute_code(
        code=args.get("code", ""),
        task_id=kw.get("task_id"),
        enabled_tools=kw.get("enabled_tools")),
    check_fn=check_sandbox_requirements,
)
