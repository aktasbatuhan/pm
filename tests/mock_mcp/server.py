#!/usr/bin/env python3
"""
Mock MCP Server for Kai Agent testing.

Implements MCP Streamable HTTP protocol directly with starlette + uvicorn.
No FastMCP dependency = no DNS rebinding middleware = works behind any proxy.

Usage:
    python tests/mock_mcp/server.py                          # default scenario
    python tests/mock_mcp/server.py --scenario fresh_onboard # specific scenario
    python tests/mock_mcp/server.py --port 4000              # custom port

Then point the agent at it:
    mcp_servers:
      kai:
        url: "http://localhost:4000/mcp"
        timeout: 300
"""

import argparse
import importlib.util
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("mock-mcp")

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "kai"
SERVER_VERSION = "1.0.0"


def load_scenario(name: str) -> dict:
    """Load a scenario fixture module and return its RESPONSES dict."""
    scenario_dir = Path(__file__).parent / "scenarios"
    module_path = scenario_dir / f"{name}.py"
    if not module_path.exists():
        available = [f.stem for f in scenario_dir.glob("*.py") if f.stem != "__init__"]
        log.error("Scenario '%s' not found. Available: %s", name, available)
        sys.exit(1)

    spec = importlib.util.spec_from_file_location(f"scenarios.{name}", str(module_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "RESPONSES"):
        log.error("Scenario '%s' missing RESPONSES dict", name)
        sys.exit(1)

    return mod.RESPONSES


def build_tool_list(responses: dict, tool_schemas: dict = None) -> list[dict]:
    """Build MCP tools/list response from scenario responses."""
    schemas = tool_schemas or {}
    tools = []
    for name in responses:
        schema = schemas.get(name, {})
        tools.append({
            "name": name,
            "description": schema.get("description", name),
            "inputSchema": schema.get("inputSchema", {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            }),
        })
    return tools


def handle_tool_call(responses: dict, tool_name: str, arguments: dict) -> dict:
    """Execute a tool call against scenario data."""
    handler_or_data = responses.get(tool_name)
    if handler_or_data is None:
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}]}

    if callable(handler_or_data):
        result = handler_or_data(**arguments)
    else:
        result = handler_or_data

    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


def create_app(scenario_name: str) -> Starlette:
    """Create the starlette app that speaks MCP protocol."""
    responses = load_scenario(scenario_name)
    # Load optional tool schemas from the scenario module
    scenario_dir = Path(__file__).parent / "scenarios"
    module_path = scenario_dir / f"{scenario_name}.py"
    tool_schemas = None
    try:
        spec = importlib.util.spec_from_file_location(f"scenarios.{scenario_name}.schemas", str(module_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tool_schemas = getattr(mod, "TOOL_SCHEMAS", None)
    except Exception:
        pass
    tool_list = build_tool_list(responses, tool_schemas)
    sessions = {}

    log.info("Loaded scenario '%s' with %d tools", scenario_name, len(responses))

    async def handle_mcp(request: Request):
        # Handle GET — SSE endpoint for server-initiated notifications (not needed for mock)
        if request.method == "GET":
            return JSONResponse({"error": "SSE not supported by mock server"}, status_code=405)

        # Handle DELETE — session termination
        if request.method == "DELETE":
            return JSONResponse({}, status_code=200)

        # Handle POST — main JSON-RPC endpoint
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
                status_code=400,
            )

        # Handle batch requests
        if isinstance(body, list):
            results = []
            for item in body:
                result = process_jsonrpc(item, responses, tool_list, sessions)
                if result is not None:  # notifications return None
                    results.append(result)
            if not results:
                return JSONResponse({}, status_code=202)
            response = JSONResponse(results if len(results) > 1 else results[0])
        else:
            result = process_jsonrpc(body, responses, tool_list, sessions)
            if result is None:
                return JSONResponse({}, status_code=202)
            response = JSONResponse(result)

        # Set session header
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            session_id = uuid.uuid4().hex
        sessions[session_id] = True
        response.headers["mcp-session-id"] = session_id
        return response

    app = Starlette(routes=[
        Route("/mcp", handle_mcp, methods=["GET", "POST", "DELETE"]),
    ])
    return app


def process_jsonrpc(body: dict, responses: dict, tool_list: list, sessions: dict) -> dict | None:
    """Process a single JSON-RPC request and return the response."""
    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    # Notifications (no id) — just acknowledge
    if req_id is None:
        log.info("Notification: %s", method)
        return None

    log.info("Request: %s (id=%s)", method, req_id)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tool_list},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        log.info("Tool call: %s(%s)", tool_name, json.dumps(arguments, default=str)[:200])
        result = handle_tool_call(responses, tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    parser = argparse.ArgumentParser(description="Mock MCP server for Kai Agent testing")
    parser.add_argument("--scenario", default="fresh_onboard", help="Scenario name (default: fresh_onboard)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: $PORT or 8000)")
    args = parser.parse_args()

    port = args.port or int(os.environ.get("PORT", "8000"))
    app = create_app(args.scenario)

    log.info("Starting mock MCP server on port %d (scenario: %s)", port, args.scenario)
    log.info("Agent MCP URL: http://localhost:%d/mcp", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
