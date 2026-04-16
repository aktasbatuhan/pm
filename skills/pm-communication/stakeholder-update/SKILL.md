---
name: pm-communication/stakeholder-update
description: Generate a stakeholder-ready update summarizing progress, risks, and decisions needed
version: 1.0.0
metadata:
  hermes:
    tags: [pm, communication, stakeholder, report]
    requires_toolsets: [memory]
---

# Stakeholder Update

Generate a concise update suitable for leadership, investors, or cross-team stakeholders.

## Gather Context

1. Read recent briefs and action items
2. Check sprint progress and key metrics
3. Review recent decisions and shipped features
4. Identify what stakeholders need to decide or know about

## Output Format

```markdown
# Product Update - {date}

## Progress
- {what shipped or progressed this period}

## Metrics
- {2-3 key numbers with trend direction}

## Risks & Blockers
- {anything stakeholders should know about}

## Decisions Needed
- {if anything requires stakeholder input}

## Next Week Focus
- {what the team will prioritize}
```

## Rules
- Write for a non-technical audience
- Lead with outcomes, not activities
- Keep it under 300 words
- Flag decisions needed prominently
- Use simple language, no jargon
