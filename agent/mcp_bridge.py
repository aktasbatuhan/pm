"""
Shared MCP bridge utilities — direct JSON-RPC calls to the MCP server.

These are NOT LLM tool calls. They are direct HTTP requests from Python code
to the MCP server, bypassing the LLM tool-calling loop entirely.

Used by workspace_context_bridge.py and state_reporter.py.
"""

import json
import logging
import os
from typing import Optional

log = logging.getLogger("mcp-bridge")

MCP_TIMEOUT = 5  # seconds


def get_mcp_config() -> tuple[str | None, dict]:
    """Read MCP server URL and headers from config."""
    try:
        from kai_cli.config import load_config

        config = load_config()
        kai_server = (config.get("mcp_servers") or {}).get("kai", {})
        url = kai_server.get("url")
        if isinstance(url, str):
            url = os.path.expandvars(url)
        headers = dict(kai_server.get("headers") or {})

        # Expand env vars in headers (e.g. ${KAI_JWT_TOKEN})
        for k, v in headers.items():
            if isinstance(v, str):
                headers[k] = os.path.expandvars(v)

        return url, headers
    except Exception as e:
        log.debug("Failed to read MCP config: %s", e)
        return None, {}


def mcp_call(tool_name: str, arguments: dict, timeout: int = MCP_TIMEOUT) -> Optional[dict]:
    """Make a direct JSON-RPC tools/call to the MCP server. Returns parsed result or None."""
    url, headers = get_mcp_config()
    if not url:
        log.debug("No MCP URL configured, skipping MCP call for %s", tool_name)
        return None

    import urllib.request
    import urllib.error

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        result = data.get("result", {})
        # MCP tools return {content: [{type: "text", text: "..."}]}
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception) as e:
        log.debug("MCP call %s failed: %s", tool_name, e)
        return None


def get_workspace_id() -> str:
    """Resolve workspace ID from environment."""
    return os.environ.get("KAI_WORKSPACE_ID") or os.environ.get("HERMES_WORKSPACE_ID") or "default"


def get_agent_id() -> str:
    """Resolve agent ID from environment."""
    return os.environ.get("KAI_AGENT_ID") or os.environ.get("HERMES_AGENT_ID") or "default"
