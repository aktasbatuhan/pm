---
name: pm-analysis/sprint-review
description: Deep analysis of the current or most recent sprint with metrics, blockers, and recommendations
version: 1.0.0
metadata:
  hermes:
    tags: [pm, sprint, analysis, review]
    requires_toolsets: [memory]
---

# Sprint Review

Perform a comprehensive sprint review covering velocity, blockers, team performance, and recommendations for the next sprint.

## Analysis Steps

1. **Get sprint data**: Fetch all items from the current sprint on the project board. Group by status.
2. **Calculate velocity**: Done items vs total. Compare to previous sprints if data available in memory.
3. **Identify blockers**: Items in "blocked" or "in review" for >2 days. Stale PRs. Unassigned high-priority items.
4. **Team workload**: Who delivered what? Is work evenly distributed? Anyone overloaded or idle?
5. **Carryover risk**: Items not yet started with the sprint deadline approaching.
6. **Quality signals**: If analytics available, check if shipped features had issues (error spikes, user complaints).

## Output Format

```markdown
# Sprint {number} Review

## Metrics
- Completion: {done}/{total} ({percent}%)
- Velocity: {points or items done}
- Carryover: {items} items likely to spill

## Highlights
- {what went well}

## Concerns
- {blockers, risks, patterns}

## Team
| Member | Done | In Progress | Blocked |
|--------|------|-------------|---------|

## Recommendations for Next Sprint
1. {concrete recommendation}
```
