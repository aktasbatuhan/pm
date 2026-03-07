# Anomaly Detection

Analyze recent signals against historical baselines to detect anomalies and generate insights.

## Workflow

1. **Load baselines** — `memory_read` metrics.md for known metric baselines and thresholds.

2. **Fetch recent signals** — `signal_query` for signals from the last 24-48 hours, grouped by source.

3. **Compare against baselines** — For each signal source:
   - Compare current values against stored baselines in metrics.md
   - Flag anything that deviates >20% from baseline (or uses source-specific thresholds)
   - Note trends: is the metric trending up/down over the last 3+ data points?

4. **Check for pattern breaks** — Look for:
   - Sudden drops in usage/revenue (risk)
   - Unexpected spikes in errors or churn (risk)
   - Accelerating growth in a metric (opportunity)
   - Correlation between signals from different sources

5. **Generate insights** — For each detected anomaly, call `insight_create` with:
   - `category`: anomaly, trend, risk, or opportunity
   - `priority`: based on severity and business impact
   - `signal_ids`: link to the triggering signals

6. **Update baselines** — If metrics have naturally shifted, update `metrics.md` with new baselines.

7. **Alert if critical** — If any insight is `priority: critical`, send an immediate Slack alert.

## Scheduler Prompt

```
Run anomaly detection: read metric baselines from memory, fetch signals from the last 48 hours, compare against baselines, detect anomalies and pattern breaks, create insights for anything notable, and update baselines. Alert on Slack if anything critical is found.
```
