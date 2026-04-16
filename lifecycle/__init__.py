"""Kai Agent Lifecycle — autonomous workspace management.

The lifecycle is driven by the kai-lifecycle/daily-cycle skill, triggered
via cron or on-demand. See lifecycle/cron.py for scheduling and
skills/kai-lifecycle/daily-cycle/SKILL.md for the workflow.

Modules:
  cron.py    — Register/unregister the daily cron job
  client.py  — HTTP helpers for kai-backend internal API (integration scan, etc.)
"""
