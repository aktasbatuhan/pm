# Sprint Recommendation

Analyze current sprint state, signals, and memory to generate actionable recommendations for the next sprint or mid-sprint adjustments.

## Workflow

1. **Read context** — `memory_read` product.md for current priorities, team.md for capacity, metrics.md for velocity trends.

2. **Sprint analysis** — Fetch current sprint items. Compute:
   - Completion rate vs. expected pace
   - Items at risk (in progress too long, no PR activity)
   - Unassigned items
   - Workload distribution across team members

3. **Review recent insights** — `insight_query` for all insights from the current sprint period. Which ones have been actioned? Which are still open?

4. **Signal-informed priorities** — Check recent signals for:
   - User feedback or app store reviews mentioning specific features
   - Revenue/churn signals that suggest urgency shifts
   - Analytics showing feature adoption or drop-off

5. **Generate recommendations** — Create 3-5 specific, actionable recommendations:
   - **Scope adjustments**: Items to cut or defer if sprint is at risk
   - **Priority shifts**: Items to elevate based on signal data
   - **New items**: Suggested issues to create based on insights
   - **Team rebalancing**: Workload adjustments if someone is overloaded
   - **Technical debt**: Items that keep causing problems

6. **Create insight** — `insight_create` with category "recommendation" for each suggestion, linking relevant signals.

7. **Update memory** — Write session summary to `sessions/YYYY-MM-DD-sprint-recommendation.md`.

8. **Present** — Show recommendations in chat with supporting data. Optionally send summary to Slack.

## Scheduler Prompt

```
Generate sprint recommendations: read memory for priorities and velocity, analyze current sprint progress, review open insights and recent signals, then produce 3-5 actionable recommendations for scope adjustments, priority shifts, or new items. Create insights for each recommendation. Update memory with the analysis.
```
