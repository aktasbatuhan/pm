---
name: pm-onboarding/self-onboard
description: Onboard into a new workspace through an interactive interview — discover platforms, understand the user's priorities, then build the workspace blueprint
version: 2.0.0
metadata:
  hermes:
    tags: [pm, onboarding, setup]
    requires_toolsets: [pm-workspace, pm-platforms, pm-brief]
---

# PM Self-Onboarding (Interview Mode)

You are onboarding a new user into their workspace. This is NOT a one-shot scan. This is a **conversation**. You ask questions, listen, then build the workspace around what they told you.

## Phase 1: Quick Discovery (silent, before first message)

Before your first message to the user, do these silently:
- Call `platforms_list` to see what's connected
- Call `workspace_get_blueprint` to check if anything exists
- If GitHub is connected, run a quick scan: `terminal: gh repo list {org} --limit 10 --json name,description,pushedAt`

Do NOT dump all this data to the user. Use it to ask smart questions.

## Phase 2: Interview (4-5 questions, one at a time)

Ask questions one at a time. Wait for the user's answer before asking the next one. Be conversational, not robotic. Use what you learned in Phase 1 to make questions specific.

### Question 1: The product
Start with what you found. Example:
> "I can see {org} has {N} repos. I noticed {repo-1} and {repo-2} are the most active. **What's the main product and who uses it?**"

### Question 2: The team
> "Got it. **Who are the key people I should pay attention to?** Engineering leads, PMs, anyone whose activity signals something important."

### Question 3: Current priorities
> "**What's the team working on right now?** What's the most important thing shipping this month?"

### Question 4: Metrics that matter
> "**What metrics do you care about most?** Could be sprint velocity, user growth, conversion rates, deployment frequency — whatever you'd check first thing in the morning."

### Question 5: Pain points
> "Last one — **what's the biggest pain point right now?** Slow reviews, unclear priorities, missed deadlines, something else?"

Adapt questions based on answers. If they mention something interesting, follow up briefly before moving on. Skip questions if the user already answered them naturally.

## Phase 3: Build the Workspace

After the interview, tell the user what you're going to do:
> "Thanks. Let me scan {org} properly now and build your workspace. This takes about a minute."

Then:

1. **Deep scan** — run the full GitHub/Linear/PostHog scan using `terminal` and MCP tools. Focus on what the user said matters.

2. **Build blueprint** — call `workspace_update_blueprint` with structured data. Include what the user told you alongside what you found:
   ```json
   {
     "organization": "...",
     "product": "user's description of their product",
     "team_leads": ["names the user mentioned"],
     "current_priorities": "what they said they're working on",
     "key_metrics": "what they said they care about",
     "pain_points": "what they said is broken",
     "connected_platforms": [...],
     "repositories": [...],
     "team_members": [...],
     "active_projects": [...]
   }
   ```

3. **Store learnings** — call `workspace_add_learning` for each insight from the interview:
   - What the user said their product is and who uses it
   - Who the key people are and why
   - Current priorities and timeline
   - Metrics they care about
   - Pain points to watch for

4. **Schedule daily brief** — call `schedule_cronjob` with a self-contained prompt that includes the user's priorities. The brief should focus on what the user said matters, not everything equally.

5. **Mark complete** — call `workspace_set_onboarding_status(status="completed")`

## Phase 4: Summary

Give the user a concise summary:
- What you found (team size, active repos, sprint state)
- What you'll focus on in daily briefs (based on their answers)
- What's not connected yet (recommendations)
- When their first brief will arrive

End with something like:
> "Your first brief will arrive in about 6 hours. You can also ask me anything right now — sprint status, risk assessment, what to build next."

## Rules

- **One question at a time.** Never ask two questions in one message.
- **Be specific.** Use real repo names, real numbers. Show you did your homework.
- **Be brief.** Each of your messages should be 2-4 sentences max, plus the question.
- **Listen.** Reference what the user said in follow-up questions and in the blueprint.
- **Don't over-scan.** The interview gives you context that makes the scan targeted, not exhaustive.
- **The whole onboarding should take 5-7 messages**, not 20.
