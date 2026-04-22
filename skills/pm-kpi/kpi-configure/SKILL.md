---
name: pm-kpi/kpi-configure
description: Configure a newly-created KPI by picking the right measurement approach from connected platforms, recording a first value, and scheduling recurring refreshes
version: 1.0.0
metadata:
  hermes:
    tags: [pm, kpi, configuration, autonomous]
    requires_toolsets: [pm-kpis, pm-platforms, cronjob]
---

# KPI Configure

The user just created a KPI. Your job is to make it actually measure itself —
autonomously, without asking follow-up questions. The user provided a name and
optional description. You figure out the rest.

## Step 1: Load the KPI

Call `kpi_get` with the `kpi_id` given in the prompt. Read `name`, `description`,
`unit`, `direction`, `target_value`.

## Step 2: Survey platforms

Call `platforms_list` to see what data sources are connected. Choose the best
source for this KPI. Common patterns:

- **PostHog** — product analytics: DAU/WAU/MAU, activation/conversion/retention funnels, event counts, session duration
- **Stripe** — revenue: MRR, ARR, churn rate, LTV, new subscriptions, trials-to-paid
- **GitHub / Linear** — engineering throughput: PRs merged/day, cycle time, issue close rate, release cadence
- **Google Analytics / Plausible** — traffic, sessions, bounce, referral sources
- **Sentry** — error rate, crash-free sessions, regression counts
- **Custom SQL / metric endpoint** — anything else, if the user has exposed one

## Step 3: Write the measurement plan

The plan is a short, self-contained description a future run of this skill can
execute without re-inspecting the environment. Include:

1. **Platform + tool** — which MCP tool or CLI command to call
2. **Exact query/endpoint** — the PostHog insight ID, SQL query, GraphQL doc, `gh` command, etc.
3. **Window** — 7d, 30d, instantaneous, week-over-week, etc.
4. **Extraction** — how to turn the response into a single numeric value
5. **Unit** — what the number means (%, $/month, users, ms, etc.)

Example plan (PostHog):
```
Source: PostHog (via mcp-posthog)
Tool: posthog_insights_trend
Query: events=$pageview, breakdown=user_id:uniq, date_range=last_7_days
Extraction: sum over 7d buckets → single number
Unit: Weekly Active Users
```

Example plan (GitHub — via App installation token in `$GITHUB_TOKEN`):
```
Source: GitHub (via `gh api`, installation-scoped)
Command: gh api "/search/issues?q=repo:acme/api+is:pr+merged:>$(date -v-7d +%Y-%m-%d)&per_page=1" --jq '.total_count'
Window: trailing 7 days
Extraction: total_count from the search response
Unit: PRs/week
Note: uses `gh api`, not `gh pr list` — installation tokens can't use user-oriented commands.
```

Call `kpi_set_measurement_plan` with the plan text and `status="configured"`.

### If no platform can measure it

Pick the closest available platform and note the gap in the plan, OR, if truly
unmeasurable right now, call `kpi_set_measurement_plan` with `status="failed"`
and a one-line `error` (e.g. `"Needs Stripe — not connected"`). Do **not** guess
or record a synthetic value.

## Step 4: Record the first value

Execute your plan once now. Call `kpi_record_value` with the real number, a
`source` string matching the plan's source (e.g. `"posthog:weekly_actives"`),
and any caveats in `notes`.

## Step 5: Schedule the refresh

Call `schedule_cronjob` so the KPI refreshes automatically:

- Schedule: `"every 24h"` by default. Use `"every 6h"` for volatile KPIs
  (traffic, error rates); `"every 7d"` for slow-moving ones (MRR, churn).
- Prompt: a self-contained instruction to run the pm-kpi/kpi-refresh skill for this KPI. Include the KPI id and the measurement plan inline.
- Name: `"KPI refresh: <kpi name>"`
- deliver: `"local"`

## Rules

- No follow-up questions to the user. Decide with what you have.
- If you truly can't measure it, say so via `status="failed"` — never fabricate a value.
- Keep the plan concise but executable. Someone reading only the plan should be able to reproduce the measurement.
- Unit matters: set it on the KPI via the UI-set field or infer it — if only the plan has it, put it in the plan header.
