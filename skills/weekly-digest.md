# Weekly Digest

Generate a comprehensive weekly product and engineering digest.

## Workflow

1. **Read memory** — product.md for priorities, metrics.md for week-over-week comparison.

2. **Sprint data** — Fetch current sprint items. Compare against last week's snapshot in metrics.md: items completed this week, velocity trend.

3. **Merged PRs** — List all PRs merged in the last 7 days across all repos. Group by repo and author.

4. **Signal summary** — `signal_query` for the last 7 days. Summarize by source: key metrics, trends, notable events.

5. **Insight review** — `insight_query` for insights created this week. How many were actioned vs. dismissed?

6. **Compose digest**:
   - **Highlights**: Top 3 things that shipped or happened this week
   - **Sprint Progress**: Velocity, completion %, comparison to last week
   - **What Shipped**: Merged PRs grouped by area
   - **Product Signals**: Key metrics from analytics, revenue, user feedback
   - **Open Risks**: Unresolved high-priority insights, stale items
   - **Next Week**: Top priorities and upcoming deadlines

7. **Visualize** — Create dashboard tab "Weekly Digest — [date]" with stat cards and charts.

8. **Update memory** — Update metrics.md with this week's numbers. Write session summary.

9. **Deliver** — Send digest to Slack and present in chat.

## Scheduler Prompt

```
Generate the weekly digest: read memory for context, fetch sprint progress and merged PRs from the last 7 days, summarize signals and insights from the week, compose a comprehensive digest with highlights, sprint progress, what shipped, product signals, and open risks. Create a dashboard tab with visualizations. Update memory with this week's metrics. Send to Slack.
```
