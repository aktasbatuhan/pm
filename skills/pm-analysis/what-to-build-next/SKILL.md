---
name: pm-analysis/what-to-build-next
description: Analyze all available data to recommend what features or improvements the team should build next
version: 1.0.0
metadata:
  hermes:
    tags: [pm, strategy, prioritization, analysis]
    requires_toolsets: [memory]
---

# What To Build Next

You are performing a strategic analysis to recommend what the team should build next. This is data-driven prioritization, not brainstorming.

## Step 1: Understand Current State

- Read workspace blueprint for context (repos, team, stack)
- Check current sprint: what's in progress? What's the completion rate?
- Review recent briefs for recurring action items or pain points

## Step 2: Gather Signal

### From code (GitHub/Linear):
- Open issues by age and labels: what's been requested but not built?
- PRs and recent commits: what areas are getting the most attention?
- Stale branches or abandoned PRs: what was started but not finished?
- Bug reports: recurring patterns or clusters?

### From analytics (if connected):
- Feature adoption rates: what do users actually use?
- Drop-off points in funnels: where do users get stuck?
- Traffic sources: where are users coming from?
- Error rates by feature: what's breaking?

### From team patterns:
- What areas have the most activity? (momentum)
- What areas have been neglected? (tech debt risk)
- Who has capacity? (realistic about who can build what)

## Step 3: Prioritize

Score each candidate by:
1. **Impact**: How many users affected? Revenue impact? Strategic importance?
2. **Confidence**: How strong is the signal? Data-backed vs speculation?
3. **Effort**: How much work? Who needs to do it? Dependencies?

Present as a ranked list with clear rationale for each.

## Step 4: Recommend

Give 3-5 concrete recommendations:

```markdown
### 1. [Recommendation Title]
**Impact**: High | **Confidence**: High | **Effort**: Medium
**Signal**: {what data supports this}
**Why now**: {why this should be next, not later}
**Who**: {who on the team should own this}
```

## Rules
- Recommendations must be grounded in data you found, not generic advice
- Consider what's realistic given team capacity
- Flag if a recommendation conflicts with current sprint work
- If data is limited, say so and lower the confidence rating
