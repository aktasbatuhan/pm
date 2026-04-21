---
name: pm-kpi/kpi-refresh
description: Execute a KPI's stored measurement plan, record the new value, and raise a risk/opportunity flag only when movement is actually meaningful
version: 1.0.0
metadata:
  hermes:
    tags: [pm, kpi, refresh, autonomous]
    requires_toolsets: [pm-kpis, pm-platforms]
---

# KPI Refresh

Run by a cron job to keep a KPI's value current. The goal is **quiet updates** —
most runs should just record a new value and stop. Flag only when the signal is
worth the user's attention.

## Step 1: Load context

Call `kpi_get(kpi_id, history_limit=30)`. Note:
- `measurement_plan`
- `current_value` / `previous_value`
- `target_value` (if any) + `direction` (higher-is-better vs lower-is-better)
- Recent `history` — for trend sensing

If `measurement_plan` is empty or `measurement_status="failed"`, stop and
re-run the pm-kpi/kpi-configure skill instead.

## Step 2: Execute the plan

Run the plan exactly as written. If the query fails (platform down, credentials
expired, schema changed):

- Retry once.
- Still failing? Call `kpi_set_measurement_plan` with `status="failed"` and a
  short `error`. Do not record a fake value.

## Step 3: Record the value

Call `kpi_record_value` with the new number, a `source` string, and any notes
(e.g. "short window due to API rate limit", "excludes sandbox users").

## Step 4: Decide whether to flag

Compare the new value to recent history. **Most runs raise no flag.** Silence is
the correct default.

Raise a `risk` flag when:
- The value moved against the goal direction by ≥10% vs the prior value
- Or it crossed a natural psychological line (dropped below target, broke a 30-day low, etc.)
- Or a correlated external signal (broken PR, traffic spike, failed deploy) explains the move
- And you can identify a concrete action the user could take

Raise an `opportunity` flag when:
- The value moved with the goal direction by ≥10% and you can identify what caused it (so the user can double down)
- Or you spotted an unused lever (untested segment, new feature adoption, referral source) with clear upside
- And the action is specific, not vague

Do **not** flag when:
- The value is within normal noise
- You can't articulate a specific next step
- You already flagged the same issue in an open flag (check `open_flags`)

## Step 5: (If flagging) Call `kpi_flag`

- `kind`: `"risk"` or `"opportunity"`
- `title`: a single punchy sentence. E.g. "Signup conversion dropped 14% w/w — likely tied to new paywall"
- `description`: 2-3 sentences. What you saw, why it matters for this KPI, what action is implied.
- `references`: array of concrete artifacts. PRs, dashboards, issues, with URLs. Empty array if none.

## Rules

- Record every successful measurement, even unremarkable ones.
- Flag rarely. Users lose trust in noisy systems fast.
- When flagging, be specific: vague flags ("might want to look at traffic") are worse than no flag.
- Measurement plan is authoritative. If you find a better query, update the plan via `kpi_set_measurement_plan` so future runs benefit.
