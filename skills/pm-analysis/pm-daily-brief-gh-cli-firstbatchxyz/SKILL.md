---
name: pm-daily-brief-gh-cli-firstbatchxyz
description: Generate a GitHub-centric daily brief for firstbatchxyz using gh CLI when MCP auth is unreliable
version: 1.0.0
metadata:
  tags: [pm, brief, github, gh-cli, firstbatchxyz]
---

# When to use
Use for daily briefs in the firstbatchxyz workspace when GitHub MCP auth is unreliable and the gh CLI is the authoritative source.

# Workflow
1. Load workspace blueprint, learnings, latest brief, and pending action items.
2. Use `gh project list --owner firstbatchxyz --format json` to identify active project boards.
3. Use `gh project item-list <number> --owner firstbatchxyz --format json` and filter with `jq` rather than Python `json.loads` because long issue bodies can include control characters that break strict JSON parsing.
4. For core repos (`kai-backend`, `kai-frontend`, `kai-agent`, `kai-security`, `kai-evolve-executor`, `kai-executor`), scan:
   - merged PRs since last brief
   - open PRs with reviewDecision and updatedAt
   - new/open issues relevant to current priorities
5. Explicitly re-check known durable risks like `kai-backend#278` and `kai-agent#14` before carrying forward or resolving prior action items.
6. Compare current sprint/project metadata to the prior brief. If board counts collapse or change implausibly, call that out as a process risk rather than trusting the board.
7. Store the brief with structured action items and references.

# Useful commands
- `gh pr list -R firstbatchxyz/<repo> --state merged --search 'merged:>=YYYY-MM-DDTHH:MM:SSZ' --json number,title,author,mergedAt,url`
- `gh pr list -R firstbatchxyz/<repo> --state open --limit 30 --json number,title,author,createdAt,updatedAt,reviewDecision,isDraft,url`
- `gh issue list -R firstbatchxyz/<repo> --state open --search 'created:>=YYYY-MM-DDTHH:MM:SSZ' --json number,title,author,createdAt,assignees,url`
- `gh issue view -R firstbatchxyz/<repo> <num> --json number,title,state,updatedAt,assignees,url`
- `gh project item-list 8 --owner firstbatchxyz --format json | jq -c '[.items[] | select(.sprint==59) | {title,status,priority,assignees,repo:.content.repository,number:.content.number,url:.content.url}]'`

# Pitfalls
- `gh project item-list ... --format json` may output JSON that strict parsers reject because of embedded control characters in issue bodies.
- A merged PR or release does not mean the linked issue is resolved; confirm issue state directly.
- Approved PRs can still represent a merge bottleneck if no one is actually landing them.

# Verification
- Confirm the brief includes: delivery movement, stale review queue, persistent risks, and a judgment on sprint-board reliability.
- Update prior action-item statuses only after re-checking live issue/PR state.
