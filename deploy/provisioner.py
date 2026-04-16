"""
Kai Agent Sandbox Provisioner

Creates and manages E2B sandboxes for Kai Agent instances.
Each workspace gets its own sandbox with the user's JWT injected.

Usage:
    # Provision a new agent for a workspace
    python provisioner.py create --workspace-id <id> --jwt <token>

    # Check agent status
    python provisioner.py status --workspace-id <id>

    # Refresh JWT for an existing agent
    python provisioner.py refresh-jwt --workspace-id <id> --jwt <new_token>

    # Destroy an agent
    python provisioner.py destroy --workspace-id <id>
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from e2b import Sandbox

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

E2B_API_KEY = os.environ.get("E2B_API_KEY", "")
REGISTRY_FILE = Path(__file__).parent / "sandbox_registry.json"

# Agent idle timeout before auto-pause (seconds)
AGENT_IDLE_TIMEOUT = 300  # 5 minutes

# Sandbox max lifetime per wake cycle (seconds)
SANDBOX_TIMEOUT = 3600  # 1 hour, then auto-pauses

# ---------------------------------------------------------------------------
# Registry (workspace_id → sandbox metadata)
# In production, this would be Cloudflare KV or a database.
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text())
    return {}


def _save_registry(registry: dict):
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2))


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def create_agent(workspace_id: str, jwt_token: str, openrouter_key: str = "",
                 firecrawl_key: str = "", slack_bot_token: str = "",
                 slack_app_token: str = "") -> dict:
    """Create a new E2B sandbox for a Kai Agent instance.

    Args:
        workspace_id: Kai workspace ID
        jwt_token: User's JWT for Kai MCP authentication
        openrouter_key: OpenRouter API key for LLM calls
        firecrawl_key: Firecrawl API key for web search
        slack_bot_token: Slack bot token for messaging
        slack_app_token: Slack app token for socket mode

    Returns:
        dict with sandbox_id, status, and metadata
    """
    registry = _load_registry()

    # Check if workspace already has an agent
    if workspace_id in registry:
        existing = registry[workspace_id]
        print(f"Workspace {workspace_id} already has agent: {existing['sandbox_id']}")
        print("Use 'refresh-jwt' to update the token or 'destroy' first.")
        return existing

    print(f"Creating sandbox for workspace {workspace_id}...")
    t0 = time.time()

    # Create sandbox with environment variables
    sbx = Sandbox.create(
        timeout=SANDBOX_TIMEOUT,
        envs={
            "KAI_JWT_TOKEN": jwt_token,
            "KAI_WORKSPACE_ID": workspace_id,
            "OPENROUTER_API_KEY": openrouter_key,
            "FIRECRAWL_API_KEY": firecrawl_key,
            "SLACK_BOT_TOKEN": slack_bot_token,
            "SLACK_APP_TOKEN": slack_app_token,
            "LLM_MODEL": "anthropic/claude-opus-4-6",
        },
    )
    print(f"  Sandbox created in {time.time()-t0:.1f}s: {sbx.sandbox_id}")

    # Install Kai Agent inside the sandbox
    print("  Installing Kai Agent...")
    sbx.commands.run("pip install -q httpx openai pydantic rich prompt_toolkit pyyaml python-dotenv", timeout=60)

    # Upload agent config
    sbx.files.write("/home/user/.kai-agent/config.yaml", f"""
model:
  default: "anthropic/claude-opus-4-6"
  provider: "openrouter"

mcp_servers:
  kai:
    url: "https://production.kai-backend.dria.co/mcp"
    headers:
      Authorization: "Bearer ${{KAI_JWT_TOKEN}}"
    timeout: 300
    connect_timeout: 60
""")

    # Write a marker file for the workspace
    sbx.files.write("/home/user/.kai-agent/workspace.json", json.dumps({
        "workspace_id": workspace_id,
        "provisioned_at": time.time(),
        "version": "0.1.0",
    }))

    print("  Agent configured.")

    # Pause immediately (agent will be woken by webhook)
    print("  Pausing sandbox (ready for wake-on-demand)...")
    sbx.pause()

    # Save to registry
    entry = {
        "sandbox_id": sbx.sandbox_id,
        "workspace_id": workspace_id,
        "status": "paused",
        "created_at": time.time(),
        "jwt_expires_hint": "7 days from creation",
    }
    registry[workspace_id] = entry
    _save_registry(registry)

    print(f"  Done. Agent {sbx.sandbox_id} provisioned and paused.")
    return entry


def get_status(workspace_id: str) -> dict:
    """Check the status of a workspace's agent."""
    registry = _load_registry()
    entry = registry.get(workspace_id)
    if not entry:
        print(f"No agent found for workspace {workspace_id}")
        return {}

    sandbox_id = entry["sandbox_id"]
    try:
        sbx = Sandbox.connect(sandbox_id, timeout=SANDBOX_TIMEOUT)
        info = sbx.get_info()
        entry["status"] = "running"
        entry["info"] = str(info)
        # Don't kill it, let it auto-pause
        print(f"Agent {sandbox_id}: RUNNING")
    except Exception as e:
        entry["status"] = "paused_or_dead"
        entry["error"] = str(e)
        print(f"Agent {sandbox_id}: {entry['status']} ({e})")

    return entry


def refresh_jwt(workspace_id: str, new_jwt: str):
    """Update the JWT token for an existing agent."""
    registry = _load_registry()
    entry = registry.get(workspace_id)
    if not entry:
        print(f"No agent found for workspace {workspace_id}")
        return

    sandbox_id = entry["sandbox_id"]
    print(f"Resuming sandbox {sandbox_id} to update JWT...")

    sbx = Sandbox.connect(sandbox_id, timeout=SANDBOX_TIMEOUT)

    # Update the env file with new JWT
    sbx.files.write("/home/user/.kai-agent/.env_jwt", f"KAI_JWT_TOKEN={new_jwt}\n")

    # Update the config
    config = sbx.files.read("/home/user/.kai-agent/config.yaml")
    # The config uses ${KAI_JWT_TOKEN} which reads from env,
    # but we also write a file the agent can source on startup

    print("  JWT updated. Pausing sandbox...")
    sbx.pause()

    entry["jwt_updated_at"] = time.time()
    registry[workspace_id] = entry
    _save_registry(registry)
    print("  Done.")


def destroy_agent(workspace_id: str):
    """Destroy a workspace's agent sandbox."""
    registry = _load_registry()
    entry = registry.get(workspace_id)
    if not entry:
        print(f"No agent found for workspace {workspace_id}")
        return

    sandbox_id = entry["sandbox_id"]
    print(f"Destroying sandbox {sandbox_id}...")

    try:
        sbx = Sandbox.connect(sandbox_id, timeout=60)
        sbx.kill()
        print("  Sandbox killed.")
    except Exception as e:
        print(f"  Could not connect (may already be dead): {e}")

    del registry[workspace_id]
    _save_registry(registry)
    print("  Removed from registry.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kai Agent Sandbox Provisioner")
    sub = parser.add_subparsers(dest="command")

    create_p = sub.add_parser("create", help="Provision a new agent")
    create_p.add_argument("--workspace-id", required=True)
    create_p.add_argument("--jwt", required=True, help="User's Kai JWT token")
    create_p.add_argument("--openrouter-key", default="")
    create_p.add_argument("--firecrawl-key", default="")
    create_p.add_argument("--slack-bot-token", default="")
    create_p.add_argument("--slack-app-token", default="")

    status_p = sub.add_parser("status", help="Check agent status")
    status_p.add_argument("--workspace-id", required=True)

    refresh_p = sub.add_parser("refresh-jwt", help="Update JWT for existing agent")
    refresh_p.add_argument("--workspace-id", required=True)
    refresh_p.add_argument("--jwt", required=True)

    destroy_p = sub.add_parser("destroy", help="Destroy an agent")
    destroy_p.add_argument("--workspace-id", required=True)

    args = parser.parse_args()

    if not E2B_API_KEY:
        print("Error: E2B_API_KEY environment variable required")
        sys.exit(1)

    if args.command == "create":
        create_agent(
            args.workspace_id, args.jwt,
            openrouter_key=args.openrouter_key,
            firecrawl_key=args.firecrawl_key,
            slack_bot_token=args.slack_bot_token,
            slack_app_token=args.slack_app_token,
        )
    elif args.command == "status":
        get_status(args.workspace_id)
    elif args.command == "refresh-jwt":
        refresh_jwt(args.workspace_id, args.jwt)
    elif args.command == "destroy":
        destroy_agent(args.workspace_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
