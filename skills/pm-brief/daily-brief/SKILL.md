---
name: pm-brief/daily-brief
description: Produce a structured daily brief with updates, metrics, charts, goal progress, KPI risks/opportunities, and prioritized action items from all connected data sources
version: 1.3.0
metadata:
  hermes:
    tags: [pm, brief, proactive, daily]
    requires_toolsets: [pm-brief, pm-goals, pm-kpis, memory, cronjob]
---

# Daily Brief

You are producing a daily brief for the team. This is the core PM deliverable: a concise, data-backed summary of what happened, what matters, and what to do next.

## Step 1: Gather Data

Check every connected data source. Skip sources that aren't available.

### GitHub (via GitHub App installation token)
Dash authenticates with GitHub through the installed GitHub App. The short-lived
installation token is exposed as `$GITHUB_TOKEN` and is scoped to **only the repos
the user selected during install**. Use `gh api` for REST calls — installation
tokens don't work with user-oriented commands like `gh pr list` or `gh repo list`.

Useful calls (all via `terminal`):
- **List reachable repos** — always do this first:
  `gh api /installation/repositories --paginate --jq '.repositories[] | {full_name,default_branch,pushed_at}'`
- **PRs merged since a date** (search is fastest):
  `gh api "/search/issues?q=repo:{owner}/{repo}+is:pr+merged:>{YYYY-MM-DD}&per_page=30"`
- **Open PRs, sorted by staleness**:
  `gh api "/repos/{owner}/{repo}/pulls?state=open&sort=updated&direction=asc&per_page=50"`
- **New issues since a date**:
  `gh api "/search/issues?q=repo:{owner}/{repo}+is:issue+created:>{YYYY-MM-DD}&per_page=30"`
- **Commits on default branch**:
  `gh api "/repos/{owner}/{repo}/commits?since={YYYY-MM-DDTHH:MM:SSZ}&per_page=100"`
- **Project board items** (if they use Projects v2):
  `gh api graphql -f query='query { organization(login:"{org}"){ projectV2(number:{n}){ items(first:50){ nodes { content { ... on Issue {title,state,url} ... on PullRequest {title,state,url} } } } } } }'`

If a call returns 404, the repo is outside the installation scope — note it and move on.

### Linear (project boards)
- Current sprint status: items by status (done, in progress, review, blocked, todo)
- PRs merged since last brief
- PRs awaiting review (especially stale ones >2 days)
- New issues created
- Team activity: who committed, who's been silent

### PostHog / Analytics (if connected)
- Key metrics changes (traffic, signups, conversions, errors)
- Any anomalies (>20% deviation from baseline)
- Funnel changes (particularly onboarding/activation funnels)

### Previous Brief
- Load the last brief with `brief_get_latest`
- Compare: what changed since then? What action items are still pending?

### Goals
- Call `goal_list` to get all active goals
- For each goal, note the current `progress`, `trajectory`, and previous `action_items`
- You will re-evaluate each goal in Step 2.5 after gathering new data.

### KPIs
- Call `kpi_list` to get all active KPIs and their recent values
- For each, note the `current_value`, `previous_value`, `target_value`, and the last 3-5 `recent_values`
- You will use this in Step 2.6 to decide whether any KPI deserves a flag in this brief

### Workspace Context
- Read your blueprint and recent learnings
- Check pending work items

## Step 2: Analyze

Cross-reference signals from different sources. The value is in connections:
- A traffic spike + a broken feature = urgent
- A silent team member + stale PRs = potential blocker
- High signup rate + low activation = product problem
- Sprint almost done + many items in review = bottleneck

## Step 2.5: Evaluate Every Active Goal

**This is required for every brief.** For each goal returned by `goal_list`:

1. **Estimate progress (0-100)** based on observable evidence:
   - Merged PRs / closed issues tagged to the goal
   - Metric movement (if the goal is metric-tied and you have analytics)
   - Milestones hit since the last snapshot
   - Be honest — if there's no evidence of movement, don't bump the %.

2. **Set a trajectory**: `on-track`, `at-risk`, `behind`, `ahead`, or `stalled`.
   - Compare days-elapsed-since-created vs days-until-target to sense-check.

3. **Produce 1-3 action items** that would move this goal forward meaningfully this week.
   - Reference real artifacts (PR/issue URLs).
   - Match the action item shape used by `brief_store` (title, description, priority, references[]).

4. **Call `goal_update_progress`** with `goal_id`, `progress`, `trajectory`, `action_items` (JSON string), `brief_id` left empty for now, and a short `notes` line describing what changed since last evaluation.

Do this for every active goal. If there are no goals, skip this step.

You will reference goals in Step 3 under a dedicated `## Goals` section in the brief.

## Step 2.6: KPI Scan

KPIs are the company's continuous metrics. Dash's job is to *protect* and *grow*
them — but without overwhelming the user.

For each KPI from Step 1:

1. **Look at the trend.** Compare `current_value` vs `previous_value` and the
   last few `recent_values`. Is it moving with the goal direction or against it?
   Is it within normal noise (e.g. <5% week-over-week) or genuinely moving?

2. **Cross-reference with the rest of the brief.** A KPI slide often has a
   cause visible elsewhere: a merged PR, a shipping feature, a drop in traffic,
   an outage. If the brief already mentioned the cause, connect them.

3. **Decide whether to flag.** Follow the rule: silence is the correct answer
   when the KPI is moving normally. Flag only when (a) movement is notable and
   (b) you can name a concrete action. See pm-kpi/kpi-refresh for the exact
   criteria.

4. **If flagging,** call `kpi_flag(kpi_id, kind, title, description, references, brief_id)`.
   Use the `brief_id` returned from `brief_store` — you may need to call this
   step AFTER `brief_store` so the flags are linked to the brief.

If **no** KPI deserves a flag this run, omit the KPI section from the brief
entirely. The user will see the steady numbers in the KPIs panel; the brief
should not repeat them.

## Step 3: Produce the Brief

### Format

Write the brief in markdown. Include interactive charts using react-chart code blocks where data supports it. The frontend renders these as live Recharts components.

````markdown
# Daily Brief - {date}

## What Happened
{2-4 bullet points of the most important events since last brief}

## Sprint Progress

```react-chart title="Sprint Status"
const data = [
  { name: 'Done', value: 5, fill: '#10b981' },
  { name: 'In Progress', value: 3, fill: '#3b82f6' },
  { name: 'Review', value: 2, fill: '#f59e0b' },
  { name: 'Todo', value: 4, fill: '#6b7280' },
];

const Component = () => (
  <ResponsiveContainer width="100%" height={200}>
    <BarChart data={data} layout="vertical">
      <XAxis type="number" />
      <YAxis type="category" dataKey="name" width={80} />
      <Tooltip />
      <Bar dataKey="value" radius={[0, 4, 4, 0]}>
        {data.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
      </Bar>
    </BarChart>
  </ResponsiveContainer>
);
```

## Team Activity

```react-chart title="Commits by Author (7 days)"
const data = [
  { name: 'alice', commits: 12 },
  { name: 'bob', commits: 8 },
  { name: 'charlie', commits: 5 },
];

const Component = () => (
  <ResponsiveContainer width="100%" height={200}>
    <BarChart data={data}>
      <XAxis dataKey="name" />
      <YAxis />
      <Tooltip />
      <Bar dataKey="commits" fill="#4f46e5" radius={[4, 4, 0, 0]} />
    </BarChart>
  </ResponsiveContainer>
);
```

## Current State
- Sprint: {completion %}, {in-progress count} active, {blocked count} blocked
- Team: {active members} active, {notable patterns}
- Product: {key metric} {direction} {amount}

## Goals
For each active goal, write one block:
- **{goal title}** — {progress}% ({trajectory})
  - {one-line note on what moved the needle since last brief}
  - Next: {top action item for this goal}

Omit this section entirely if there are no active goals.

## KPIs
Include this section ONLY if at least one KPI deserved a flag this run
(see Step 2.6). For each flagged KPI:

- **{KPI name}** — {current_value}{unit} (was {previous_value})
  - [risk|opportunity] {flag title}
  - {short description + what to do}

If no KPI was flagged, omit this section entirely.

## Action Items

### Critical
- [{category}] {title}: {one-line description}

### High Priority
- [{category}] {title}: {one-line description}
````

Use real data from your scan. Don't use placeholder numbers. Available chart types:
- `BarChart` (horizontal or vertical) for sprint status, team activity, category breakdowns
- `LineChart` / `AreaChart` for trends over time (PR velocity, metric history)
- `PieChart` for proportional splits (done/todo/blocked)

The react-chart blocks have access to all Recharts components: BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ComposedChart. Use the COLORS array for consistent palette.

### Action Item Categories
- `pain-point`: Something is broken or degrading
- `next-feature`: Data suggests what to build next
- `stakeholder-update`: Something leadership/team needs to know
- `risk`: Emerging risk that needs attention
- `team`: Team dynamics issue (blocked, overloaded, inactive)

### Action Item References
Include references for each action item when you have them:
```json
{
  "category": "risk",
  "title": "Fix JWT exposure",
  "description": "kai-backend issue #278 exposes secrets to sandboxes",
  "priority": "critical",
  "references": [
    {"type": "issue", "url": "https://github.com/org/repo/issues/278", "title": "org/repo#278"}
  ]
}
```

### Suggested Follow-up Prompts
Generate 3-5 specific follow-up questions the user might ask after reading this brief. These appear as clickable buttons in the UI. They must be:
- **Specific** to this brief's content, not generic (bad: "Tell me more", good: "Why did kai-backend have zero merges today?")
- **Actionable** — each should lead to a useful conversation
- **Varied** — mix investigation, planning, and communication prompts

Pass them as `suggested_prompts` in the `brief_store` call.

### Headline
Every brief must have an explicit one-line **headline** passed to `brief_store`
via the `headline` field. This is what appears as the big title on the brief
page — it's separate from the body and NOT auto-extracted from the summary.

Rules:
- 8–14 words, written as a newspaper headline.
- Start with a concrete subject. Use an active verb. Name a number when relevant.
- Summarize the single most important thing in this brief — not a commit,
  not the last infra fix, not meta-work.
- Bad: "Terminal tool unblocked — commit f6f674ba fixed the critical shell access blocker."
- Bad: "Here's today's brief from the Dash repository."
- Good: "Signup conversion drops 14% week-over-week after paywall rollout."
- Good: "Sprint 59 will miss Friday deadline — 3 of 8 items still open, 2 blocked on review."
- Good: "MRR up 6% to $42k; churn spike on the starter plan needs attention."

If nothing notable happened, the headline should say so directly:
"Quiet day: no PRs merged, no KPI movement, sprint on track."

## Step 4: Store and Deliver

1. Store the brief using `brief_store` with:
   - `headline` (required — see Headline section above; do NOT skip)
   - `summary` — the full markdown content (chart blocks, sections, etc.)
   - `action_items` — structured JSON array with references
   - `suggested_prompts` — JSON array of follow-up questions
   - `data_sources` — comma-separated list of what you queried
2. After storing, generate a cover image with `brief_generate_cover`:
   - Write a visual prompt that captures the brief's mood
   - Calm and productive if sprint is on track
   - Urgent/intense if there are critical blockers
   - Celebratory if major milestones were hit
   - Pass the `brief_id` from the `brief_store` response

## Rules
- Be concrete: numbers, names, links. Not "things are going well."
- Be brief: the whole brief should fit on one screen
- Be actionable: every action item should be something someone can do today
- Compare to last brief: highlight what CHANGED, not what stayed the same
- If a data source is unavailable, say so in one line and move on
- Include at least one chart if you have numerical data
- Charts should use real data, not placeholders
