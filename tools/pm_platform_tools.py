"""
PM Platform tools — discover connected platforms and their available tools.

The agent uses these during onboarding to understand what data sources
are available, and during briefs to know which platforms to check.
"""

import json
import os
import logging

from tools.registry import registry

logger = logging.getLogger(__name__)


def platforms_list(**kwargs) -> str:
    """List all connected platforms and their available tools."""
    platforms = []

    # Check MCP-discovered tools by inspecting registry toolsets
    all_toolsets = registry.get_available_toolsets()
    for ts_name, ts_info in all_toolsets.items():
        if ts_name.startswith("mcp-"):
            platform_name = ts_name[4:]  # strip "mcp-"
            tools = ts_info.get("tools", [])
            platforms.append({
                "name": platform_name,
                "source": "mcp",
                "status": "connected",
                "tools_count": len(tools),
                "tools": tools[:10],  # first 10 for brevity
            })

    # Check env-based integrations
    env_checks = [
        ("github", "GITHUB_TOKEN", "GitHub API access via token"),
        ("github", "GITHUB_PERSONAL_ACCESS_TOKEN", "GitHub API access via PAT"),
        ("linear", "LINEAR_API_KEY", "Linear issue tracking"),
        ("posthog", "POSTHOG_API_KEY", "PostHog product analytics"),
        ("slack", "SLACK_BOT_TOKEN", "Slack messaging"),
        ("slack", "SLACK_APP_TOKEN", "Slack app connection"),
    ]

    seen = {p["name"] for p in platforms}
    for name, env_var, desc in env_checks:
        if name not in seen and os.environ.get(env_var):
            platforms.append({
                "name": name,
                "source": "env",
                "status": "configured",
                "description": desc,
            })
            seen.add(name)

    if not platforms:
        return json.dumps({
            "message": "No platforms connected yet. Configure MCP servers in config.yaml or set API keys in .env.",
            "platforms": []
        })

    return json.dumps({
        "count": len(platforms),
        "platforms": platforms
    })


PLATFORMS_LIST_SCHEMA = {
    "name": "platforms_list",
    "description": "List all connected platforms (GitHub, Linear, PostHog, Slack, etc.) and their available tools. Use during onboarding to discover what data sources are available.",
    "parameters": {"type": "object", "properties": {}}
}


def platforms_check(platform: str, **kwargs) -> str:
    """Check if a specific platform is connected and working."""
    all_toolsets = registry.get_available_toolsets()

    # Check MCP toolset
    mcp_key = f"mcp-{platform}"
    if mcp_key in all_toolsets:
        tools = all_toolsets[mcp_key].get("tools", [])
        return json.dumps({
            "platform": platform,
            "connected": True,
            "source": "mcp",
            "tools_count": len(tools),
            "tools": tools,
        })

    # Check env vars
    env_map = {
        "github": ["GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"],
        "linear": ["LINEAR_API_KEY"],
        "posthog": ["POSTHOG_API_KEY"],
        "slack": ["SLACK_BOT_TOKEN"],
    }

    env_vars = env_map.get(platform, [])
    for var in env_vars:
        if os.environ.get(var):
            return json.dumps({
                "platform": platform,
                "connected": True,
                "source": "env",
                "env_var": var,
            })

    return json.dumps({
        "platform": platform,
        "connected": False,
        "message": f"Platform '{platform}' is not connected. Add it to config.yaml as an MCP server or set the appropriate API key."
    })


PLATFORMS_CHECK_SCHEMA = {
    "name": "platforms_check",
    "description": "Check if a specific platform is connected and list its available tools.",
    "parameters": {
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "description": "Platform name to check (e.g. 'github', 'linear', 'posthog', 'slack')"
            }
        },
        "required": ["platform"]
    }
}


# =============================================================================
# Registry
# =============================================================================

registry.register(
    name="platforms_list",
    toolset="pm-platforms",
    schema=PLATFORMS_LIST_SCHEMA,
    handler=lambda args, **kw: platforms_list(),
)

registry.register(
    name="platforms_check",
    toolset="pm-platforms",
    schema=PLATFORMS_CHECK_SCHEMA,
    handler=lambda args, **kw: platforms_check(
        platform=args.get("platform", "")),
)
