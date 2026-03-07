# Daily Briefing

Generate a comprehensive morning briefing for the team.

## Workflow

1. **Read memory context** — `memory_read` product.md, team.md, metrics.md for current priorities and baselines.

2. **Check recent signals** — `signal_query` for signals from the last 24 hours. Note any anomalies or notable changes.

3. **Query unresolved insights** — `insight_query` with status "new" to surface anything the team hasn't acknowledged yet.

4. **Sprint snapshot** — Fetch current sprint items via `github_list_project_items`. Compute: total items, done, in progress, todo, blocked. Calculate completion % and projected velocity.

5. **PR activity** — Check for PRs opened, merged, or stuck (open >2 days without review) in the last 24h.

6. **Compose briefing** — Structure as:
   - **Top Priority**: Most urgent item from insights or sprint blockers
   - **Sprint Health**: Completion %, items done yesterday, items in progress today
   - **Signals**: Any new signals or anomalies worth noting
   - **Open Insights**: Unresolved recommendations that need attention
   - **Stuck PRs / Blockers**: Anything that needs unblocking

7. **Update memory** — Write a session summary to `sessions/YYYY-MM-DD-briefing.md`. Update `metrics.md` with latest sprint numbers.

8. **Deliver** — Send to Slack if configured, otherwise present in chat.

## Scheduler Prompt

```
Generate the daily briefing: read memory for context, check signals from the last 24h, query unresolved insights, fetch current sprint status from GitHub, check for stuck PRs, and compile everything into a concise morning briefing. Send to Slack. Update memory with today's metrics.
```
