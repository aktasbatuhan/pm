---
name: pm-analysis/risk-assessment
description: Systematic evaluation of risks across engineering, product, and team dimensions
version: 1.0.0
metadata:
  hermes:
    tags: [pm, risk, analysis]
    requires_toolsets: [memory]
---

# Risk Assessment

Evaluate current risks across all domains. Cross-reference signals to find hidden risks.

## Dimensions

1. **Delivery risk**: Sprint behind? PRs stale? Dependencies blocked?
2. **Quality risk**: CI failing? Error rates up? No tests on recent changes?
3. **Team risk**: Key person absent? Knowledge silos? Overloaded contributors?
4. **Product risk**: Metrics declining? Users hitting bugs? Funnel degrading?
5. **Technical risk**: Security issues open? Dependencies outdated? Infrastructure fragile?

## For each risk found

```markdown
### {Risk Title}
**Severity**: Critical / High / Medium / Low
**Likelihood**: Confirmed / Likely / Possible
**Signal**: {what data shows this}
**Impact**: {what happens if unaddressed}
**Mitigation**: {what to do about it}
```

Rank by severity x likelihood. Top 3 risks get detailed mitigation plans.
