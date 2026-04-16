#!/usr/bin/env python3
"""
Kai Agent - Slack Socket Mode listener.
Connects via WebSocket (no public URL needed).
Dispatches @Kai mentions to the E2B sandbox agent.

Usage:
    python deploy/slack_socket.py
"""
import os
import re
import logging
import httpx

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("kai")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")
SANDBOX_URL = os.environ.get("SANDBOX_URL", "")
E2B_API_KEY = os.environ.get("E2B_API_KEY", "")
SANDBOX_ID = os.environ.get("SANDBOX_ID", "")

app = App(token=SLACK_BOT_TOKEN)


def resume_sandbox():
    try:
        httpx.post(
            f"https://api.e2b.dev/sandboxes/{SANDBOX_ID}/resume",
            headers={"X-API-Key": E2B_API_KEY, "Content-Type": "application/json"},
            json={"timeout": 3600},
            timeout=10,
        )
    except Exception:
        pass


def dispatch(message, channel, thread_ts):
    long_running = bool(re.search(r"evolve|evolution|scan|overnight|monitor|keep.*posted", message, re.IGNORECASE))
    try:
        r = httpx.post(
            f"{SANDBOX_URL}/dispatch",
            json={"message": message, "channel": channel, "threadTs": thread_ts, "longRunning": long_running},
            timeout=10,
        )
        log.info(f"Dispatched: {r.json()}")
    except Exception as e:
        log.error(f"Dispatch failed: {e}")


@app.event("app_mention")
def handle_mention(event, say):
    text = event.get("text", "")
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts", "")
    user = event.get("user", "")

    # Strip bot mention
    message = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
    if not message:
        return

    log.info(f"@Kai from {user}: {message}")

    resume_sandbox()
    dispatch(message, channel, thread_ts)


@app.event("message")
def handle_message(event, say):
    # Ignore non-mention messages (app_mention handler covers mentions)
    pass


if __name__ == "__main__":
    log.info("Kai Agent Socket Mode starting...")
    log.info(f"Sandbox: {SANDBOX_URL}")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
