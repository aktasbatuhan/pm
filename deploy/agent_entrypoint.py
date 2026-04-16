"""
Kai Agent Entrypoint for E2B Sandbox

Called by the Cloudflare Worker when a message arrives.
Runs a single query through the Kai Agent CLI and posts the response to Slack.

Usage (from E2B commands.run):
    python3 /home/user/kai-agent/deploy/agent_entrypoint.py \
        --message "scan my repos for vulnerabilities" \
        --channel "C0123456789" \
        --user "U0123456789" \
        --thread-ts "1234567890.123456"

Environment variables (injected during provisioning):
    KAI_JWT_TOKEN       - Kai MCP authentication
    OPENROUTER_API_KEY  - LLM provider
    FIRECRAWL_API_KEY   - Web search
    SLACK_BOT_TOKEN     - Post responses to Slack
    KAI_WORKSPACE_ID    - Workspace context
"""

import argparse
import json
import os
import sys
import time
import traceback

# Add agent to path
sys.path.insert(0, "/home/user/kai-agent")


def post_to_slack(channel: str, text: str, thread_ts: str = None):
    """Post a message to Slack."""
    import httpx

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        print(f"[SLACK] No token, would post: {text[:100]}")
        return

    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        r = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=10,
        )
        if not r.json().get("ok"):
            print(f"[SLACK] Error: {r.json().get('error', 'unknown')}")
    except Exception as e:
        print(f"[SLACK] Failed to post: {e}")


def run_agent_query(message: str) -> str:
    """Run a single query through the Kai Agent and return the response."""
    # All config comes from env vars injected by backend at sandbox creation

    # Import after path setup
    from kai_cli.config import load_config
    from model_tools import get_tool_definitions, handle_function_call, ensure_mcp_discovered
    from run_agent import AIAgent

    # Ensure MCP tools are discovered
    ensure_mcp_discovered()

    # Get tool definitions for kai-cli toolset
    tools = get_tool_definitions(enabled_toolsets=["kai-cli"], quiet_mode=True)

    # Create agent instance
    config = load_config()
    model = config.get("model", {}).get("default", "anthropic/claude-opus-4-6")

    agent = AIAgent(
        model=model,
        tools=tools,
        quiet_mode=True,
    )

    # Run the conversation
    result = agent.run_conversation(message)

    # Extract the final response
    if isinstance(result, dict):
        return result.get("final_response", str(result))
    return str(result)


def main():
    parser = argparse.ArgumentParser(description="Kai Agent Entrypoint")
    parser.add_argument("--message", required=True, help="User message")
    parser.add_argument("--channel", required=True, help="Slack channel ID")
    parser.add_argument("--user", default="", help="Slack user ID")
    parser.add_argument("--thread-ts", default="", help="Slack thread timestamp")
    args = parser.parse_args()

    channel = args.channel
    thread_ts = args.thread_ts or None

    # Post "working on it" indicator
    post_to_slack(channel, "Analyzing your request...", thread_ts)

    try:
        t0 = time.time()
        response = run_agent_query(args.message)
        elapsed = time.time() - t0

        # Post the response
        post_to_slack(channel, response, thread_ts)

        # Post timing info as a small footer
        post_to_slack(
            channel,
            f"_Completed in {elapsed:.0f}s_",
            thread_ts,
        )

    except Exception as e:
        traceback.print_exc()
        post_to_slack(
            channel,
            f"Error processing your request: {str(e)[:200]}",
            thread_ts,
        )


if __name__ == "__main__":
    main()
