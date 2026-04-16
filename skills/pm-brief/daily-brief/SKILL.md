---
name: pm-brief/daily-brief
description: Produce a structured daily brief with updates, metrics, charts, and prioritized action items from all connected data sources
version: 1.1.0
metadata:
  hermes:
    tags: [pm, brief, proactive, daily]
    requires_toolsets: [pm-brief, memory, cronjob]
---

# Daily Brief

You are producing a daily brief for the team. This is the core PM deliverable: a concise, data-backed summary of what happened, what matters, and what to do next.

## Step 1: Gather Data

Check every connected data source. Skip sources that aren't available.

### GitHub / Linear (project boards)
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

### Workspace Context
- Read your blueprint and recent learnings
- Check pending work items

## Step 2: Analyze

Cross-reference signals from different sources. The value is in connections:
- A traffic spike + a broken feature = urgent
- A silent team member + stale PRs = potential blocker
- High signup rate + low activation = product problem
- Sprint almost done + many items in review = bottleneck

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

## Step 4: Store and Deliver

1. Store the brief using `brief_store` with the full markdown (including chart blocks), structured action items with references, and suggested_prompts
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
