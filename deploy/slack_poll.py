#!/usr/bin/env python3
"""
Slack poller for Kai Agent.
Polls for @Kai mentions and dispatches to the E2B sandbox.
Run this locally while testing. No webhooks needed.

Usage:
    python deploy/slack_poll.py
"""
import os
import time
import httpx

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
CHANNEL = os.environ.get("SLACK_CHANNEL", "")
BOT_USER_ID = os.environ.get("SLACK_BOT_USER_ID", "")
SANDBOX_URL = os.environ.get("SANDBOX_URL", "")
E2B_API_KEY = os.environ.get("E2B_API_KEY", "")
SANDBOX_ID = os.environ.get("SANDBOX_ID", "")

POLL_INTERVAL = 3  # seconds
seen = set()


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
    long_running = bool(
        __import__("re").search(r"evolve|evolution|scan|overnight|monitor|keep.*posted", message, __import__("re").IGNORECASE)
    )
    try:
        r = httpx.post(
            f"{SANDBOX_URL}/dispatch",
            json={"message": message, "channel": channel, "threadTs": thread_ts, "longRunning": long_running},
            timeout=10,
        )
        print(f"  Dispatched: {r.json()}")
    except Exception as e:
        print(f"  Dispatch failed: {e}")


def poll():
    """Fetch recent messages and look for @Kai mentions."""
    try:
        r = httpx.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            params={"channel": CHANNEL, "limit": 5},
            timeout=10,
        )
        data = r.json()
        if not data.get("ok"):
            print(f"Slack error: {data.get('error')}")
            return

        for msg in data.get("messages", []):
            ts = msg.get("ts", "")
            text = msg.get("text", "")
            user = msg.get("user", "")

            # Skip if already seen, from bot, or doesn't mention us
            if ts in seen:
                continue
            seen.add(ts)

            if msg.get("bot_id"):
                continue
            if f"<@{BOT_USER_ID}>" not in text:
                continue

            # Strip mention
            clean = text.replace(f"<@{BOT_USER_ID}>", "").strip()
            if not clean:
                continue

            print(f"[{time.strftime('%H:%M:%S')}] @Kai: {clean}")
            resume_sandbox()
            dispatch(clean, CHANNEL, msg.get("thread_ts", ts))

    except Exception as e:
        print(f"Poll error: {e}")


if __name__ == "__main__":
    print(f"Kai Agent Slack Poller")
    print(f"Channel: {CHANNEL}")
    print(f"Sandbox: {SANDBOX_URL}")
    print(f"Polling every {POLL_INTERVAL}s... (Ctrl+C to stop)")
    print()

    # Pre-fill seen messages so we don't replay history
    poll()
    print(f"Loaded {len(seen)} existing messages. Watching for new @Kai mentions...\n")

    while True:
        time.sleep(POLL_INTERVAL)
        poll()
