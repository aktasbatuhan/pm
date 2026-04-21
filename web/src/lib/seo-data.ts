// ── Role pages (/for/[role]) ─────────────────────────────────────────

export const ROLES = {
  "product-managers": {
    slug: "product-managers",
    title: "Dash for Product Managers",
    headline: "Stop managing dashboards. Start managing products.",
    description:
      "Dash reads your GitHub, Linear, PostHog, and Slack so you don't have to. Get daily briefs with action items, track goals with real data, and generate stakeholder updates in one click.",
    painPoints: [
      {
        title: "Context-switching kills your day",
        body: "You check GitHub for PR status, Linear for sprint progress, PostHog for metrics, Slack for decisions. By the time you've synthesized it all, the standup is over.",
      },
      {
        title: "Writing updates takes hours",
        body: "Every week you spend 2-3 hours pulling data from tools and writing the same status update. The data is stale by the time you send it.",
      },
      {
        title: "You react to problems instead of preventing them",
        body: "By the time someone flags a blocked PR or a stale sprint, it's been sitting for days. You're always a step behind.",
      },
    ],
    features: [
      "Daily briefs every 6 hours with action items and charts",
      "One-click stakeholder updates drafted from live data",
      "Goal tracking with automatic progress from GitHub/Linear",
      "Team pulse analysis: who's active, who's blocked, who's quiet",
      "Signal collector for market intelligence and competitor monitoring",
    ],
    cta: "See how Dash replaces your morning dashboard ritual",
  },
  founders: {
    slug: "founders",
    title: "Dash for Founders",
    headline: "You're the PM, the designer, and the tiebreaker. Dash handles the analysis.",
    description:
      "As a founder, you make product decisions with incomplete data because you don't have time to dig. Dash watches your stack 24/7 and tells you what's actually happening.",
    painPoints: [
      {
        title: "You're the bottleneck you can't see",
        body: "Your team ships fast but you can't review every PR, every metric, every sprint item. Things slip through because nobody else connects the dots.",
      },
      {
        title: "Decisions are based on vibes, not data",
        body: "You ask 'how's the sprint going?' in standup and get 'fine.' Meanwhile 3 PRs are stale, a key metric dropped 20%, and the roadmap drifted.",
      },
      {
        title: "You can't scale your judgment",
        body: "Coding agents let your team ship 10x faster. But someone still needs to decide what to build. That someone is you, and you don't scale.",
      },
    ],
    features: [
      "One morning brief replaces checking 5 tools",
      "Action items linked to real PRs, issues, and metrics",
      "Auto-generated changelogs for board updates",
      "Risk assessment that catches problems before they escalate",
      "Custom report templates for investor updates",
    ],
    cta: "See how Dash gives you back your mornings",
  },
  "engineering-leads": {
    slug: "engineering-leads",
    title: "Dash for Engineering Leads",
    headline: "You know the code. Dash tracks the product signals you don't have time to watch.",
    description:
      "As an eng lead wearing a PM hat, you're deep in code but need to make product decisions. Dash brings the PM layer — briefs, priorities, risk flags — without the overhead.",
    painPoints: [
      {
        title: "PM work steals engineering time",
        body: "You spend 30% of your week on sprint planning, status updates, and priority negotiations. That's time you're not shipping or reviewing code.",
      },
      {
        title: "You miss the forest for the trees",
        body: "You know every line of code but miss the product patterns: which features users actually use, which PRs are stale, which team members are overloaded.",
      },
      {
        title: "Reporting feels like busywork",
        body: "Writing the weekly update, updating the board, maintaining the roadmap — it's administrative overhead on top of an already full engineering plate.",
      },
    ],
    features: [
      "Automated team pulse: PRs merged, reviews done, bottlenecks flagged",
      "Sprint tracking that reconciles board state with actual commits",
      "Stale PR detection and review queue management",
      "Automated changelog generation grouped by feature area",
      "Routines that handle the PM busywork on autopilot",
    ],
    cta: "See how Dash handles the PM layer for you",
  },
};

// ── Use case pages (/use-cases/[case]) ──────────────────────────────

export const USE_CASES = {
  "daily-standups": {
    slug: "daily-standups",
    title: "Automated Daily Standups with Dash",
    headline: "Replace your standup with a brief that's already written",
    description:
      "Dash produces a structured daily brief every 6 hours from your actual tools — GitHub PRs, sprint status, analytics. No more 'what did you do yesterday?' meetings.",
    howItWorks: [
      "Dash scans your GitHub, Linear, and PostHog automatically",
      "Every 6 hours, a structured brief lands in your dashboard",
      "Action items are linked to real PRs and issues with one-click resolve",
      "Charts show sprint progress, team activity, and velocity trends",
    ],
    benefit: "Teams using Dash replace 15-minute daily standups with a 2-minute brief read. That's 5+ hours saved per team per week.",
  },
  "sprint-retrospectives": {
    slug: "sprint-retrospectives",
    title: "AI-Powered Sprint Retrospectives",
    headline: "Retrospectives grounded in data, not memory",
    description:
      "Dash tracks your sprint from start to finish. When retro time comes, it shows what shipped, what slipped, why, and what patterns are emerging — all backed by real data.",
    howItWorks: [
      "Set your sprint cadence and Dash tracks progress continuously",
      "At sprint end, generate a retrospective report with one click",
      "See velocity trends, completion rates, and team contribution patterns",
      "AI surfaces the 'why' behind misses — blocked PRs, review bottlenecks, scope creep",
    ],
    benefit: "No more 'I think we shipped X' guessing. Every retro starts with facts and ends with real patterns to improve.",
  },
  "stakeholder-updates": {
    slug: "stakeholder-updates",
    title: "Automated Stakeholder Updates",
    headline: "Stop spending hours writing the weekly update",
    description:
      "Create a report template, connect your data sources, and Dash generates polished stakeholder updates on your schedule. Copy to email, Slack, or Notion in one click.",
    howItWorks: [
      "Design a report template with markdown and variable placeholders",
      "Connect data sources: briefs, team activity, signals, learnings",
      "Schedule weekly or monthly generation",
      "Copy the rendered report to your stakeholder channel",
    ],
    benefit: "What used to take 2-3 hours of data pulling and writing now takes 2 minutes of review and one click to send.",
  },
  "team-health-monitoring": {
    slug: "team-health-monitoring",
    title: "Team Health Monitoring with Dash",
    headline: "Know who's thriving, who's struggling, and who's invisible",
    description:
      "Dash's Team Pulse analyzes per-person activity from GitHub: PRs merged, reviews done, activity recency. It flags concentration risk, bottlenecks, and quiet contributors before they become problems.",
    howItWorks: [
      "Dash reads your workspace blueprint to know your team",
      "Weekly (or on-demand) analysis of per-person GitHub activity",
      "Flags: quiet contributors, overloaded individuals, review bottlenecks, concentration risk",
      "Visual cards per team member with activity bars and badges",
    ],
    benefit: "Catch burnout signals, concentration risk, and review bottlenecks before they turn into missed deadlines.",
  },
  "signal-collection": {
    slug: "signal-collection",
    title: "Product Signal Collection with Dash",
    headline: "Stop missing what the market is telling you",
    description:
      "Dash's Signal Collector monitors Twitter, web search, and custom sources for signals relevant to your product. Star what matters, dismiss noise, discuss any signal with the agent.",
    howItWorks: [
      "Add sources: Twitter searches, Exa web queries, website scrapes",
      "Set natural language filters for relevance",
      "Dash fetches and deduplicates on your schedule",
      "Star, dismiss, or promote signals to action items",
    ],
    benefit: "Competitive intelligence and market signals flowing into your PM workspace automatically — not from a separate tool you forget to check.",
  },
  "report-automation": {
    slug: "report-automation",
    title: "Report Automation with Dash",
    headline: "Design once, generate forever",
    description:
      "Create markdown report templates with variable placeholders. Dash fills them with real data from your workspace — briefs, team activity, signals, learnings — on a schedule you set.",
    howItWorks: [
      "Design a template with markdown and {{placeholders}}",
      "Pick data sources: learning categories, brief history, signal sources",
      "Set a schedule: daily, weekly, or monthly",
      "Dash generates the report and saves it to your history",
    ],
    benefit: "Board reports, investor updates, team newsletters — all generated from live data without you touching a spreadsheet.",
  },
};

// ── Comparison pages (/vs/[slug]) ───────────────────────────────────

export const COMPARISONS = {
  "vs-linear-insights": {
    slug: "vs-linear-insights",
    title: "Dash vs Linear Insights",
    headline: "Linear tracks issues. Dash connects them to everything else.",
    description:
      "Linear is great for issue tracking. But it only sees one tool. Dash connects your Linear data with GitHub, PostHog, Slack, and team dynamics to surface what actually matters.",
    dashAdvantages: [
      "Cross-tool synthesis — Linear + GitHub + PostHog + Slack in one brief",
      "Proactive action items instead of passive board views",
      "Team pulse analysis beyond issue counts",
      "Signal collection from external sources",
      "Custom report templates on any schedule",
    ],
    theirStrength: "Linear excels at issue tracking and sprint management. Dash doesn't replace it — it reads it and adds the analysis layer on top.",
  },
  "vs-notion-pm": {
    slug: "vs-notion-pm",
    title: "Dash vs Notion for PM Workflows",
    headline: "Notion is a blank canvas. Dash is a PM that already knows what to do.",
    description:
      "Notion gives you building blocks. Dash gives you a working PM agent that reads your actual tools and produces real analysis — no template setup, no manual data entry.",
    dashAdvantages: [
      "Automated data collection — no manual entry or pasting",
      "Live analysis from your actual GitHub, Linear, and analytics",
      "Recurring reports and briefs without maintaining a wiki",
      "Action items linked to real PRs and issues, not static text",
      "Agent chat that can answer questions about your actual workspace",
    ],
    theirStrength: "Notion is unmatched for flexible documentation and collaboration. Use Notion for long-form docs and strategy. Use Dash for the automated analysis layer.",
  },
  "vs-manual-standups": {
    slug: "vs-manual-standups",
    title: "Dash vs Manual Standups",
    headline: "Your standup is 15 minutes of status updates that could be a 2-minute read.",
    description:
      "Daily standups were designed for a world without tooling. Dash reads the tools directly and produces a brief with more signal than any round-the-room update.",
    dashAdvantages: [
      "Brief is ready before the meeting (or replaces it)",
      "Data comes from tools, not memory",
      "Action items are trackable and linkable",
      "Charts show patterns humans miss in verbal updates",
      "Works across time zones — no synchronous meeting needed",
    ],
    theirStrength: "Standups still have value for team bonding and quick unblocking. Dash handles the status reporting part so the meeting can focus on decisions.",
  },
  "vs-spreadsheet-reporting": {
    slug: "vs-spreadsheet-reporting",
    title: "Dash vs Spreadsheet Reporting",
    headline: "Stop copying data from 5 tools into a spreadsheet every Friday.",
    description:
      "If your weekly reporting process involves a Google Sheet with manual data entry, Dash automates the entire thing — from data collection to formatted output.",
    dashAdvantages: [
      "Data pulled automatically from GitHub, Linear, PostHog",
      "Report templates render with live data — no manual copy-paste",
      "Scheduled generation means the report writes itself",
      "Charts generated by AI from real metrics, not manual formulas",
      "Copy to clipboard for easy sharing to any channel",
    ],
    theirStrength: "Spreadsheets are flexible and great for custom analysis. Use them for one-off deep dives. Use Dash for the recurring stuff.",
  },
};

// ── Glossary pages (/glossary/[term]) ───────────────────────────────

export const GLOSSARY = {
  "daily-brief": {
    slug: "daily-brief",
    title: "What is a Daily Brief?",
    headline: "A structured snapshot of what happened, what matters, and what to do next",
    definition:
      "A daily brief is an automated report produced by a PM agent that summarizes recent activity across your engineering tools (GitHub, Linear, PostHog, Slack). Unlike a standup or status meeting, a brief is data-driven, proactive, and includes prioritized action items.",
    inDash:
      "Dash produces a daily brief every 6 hours. Each brief includes an executive summary, interactive charts (sprint status, team activity), prioritized action items with reference links, and follow-up prompts for deeper analysis.",
  },
  "product-signals": {
    slug: "product-signals",
    title: "What are Product Signals?",
    headline: "External data points that inform product decisions",
    definition:
      "Product signals are pieces of information from outside your immediate workspace that can influence what you build: competitor moves, market trends, user complaints on social media, industry news, technology shifts. Most teams miss these because they're scattered across Twitter, blogs, forums, and news sites.",
    inDash:
      "Dash's Signal Collector monitors Twitter, web search (via Exa), and custom websites (via Firecrawl). You define sources and natural language filters. Dash fetches, deduplicates, and surfaces relevant signals. Star what matters, dismiss noise, or promote signals to action items.",
  },
  "team-pulse": {
    slug: "team-pulse",
    title: "What is Team Pulse?",
    headline: "A periodic health check of your engineering team's activity and dynamics",
    definition:
      "Team pulse is a structured analysis of per-person engineering activity: PRs merged, reviews completed, days since last activity, and behavioral patterns like concentration risk (one person doing too much) or review bottlenecks (one person blocking too many PRs).",
    inDash:
      "Dash analyzes your team's GitHub activity weekly. It produces per-person cards with activity bars, flags (quiet, overloaded, concentration risk, bottleneck), and a synthesized health summary. Available on-demand or as a scheduled routine.",
  },
  "autonomous-pm": {
    slug: "autonomous-pm",
    title: "What is an Autonomous PM Agent?",
    headline: "An AI that does the analytical work of product management, not just answers questions",
    definition:
      "An autonomous PM agent is different from a chatbot or copilot. Instead of waiting for you to ask, it proactively watches your tools, identifies patterns, produces briefs, flags risks, and recommends actions. It has persistent memory, workspace context, and runs on a schedule.",
    inDash:
      "Dash is an autonomous PM agent built on the Hermes Agent framework. It connects to GitHub, Linear, PostHog, and Slack. It produces daily briefs, tracks goals, monitors signals, generates reports, and runs analysis routines — all automatically. You interact via chat when you need to go deeper.",
  },
  "action-items": {
    slug: "action-items",
    title: "What are Action Items in Dash?",
    headline: "Prioritized, trackable things that need your attention — linked to real data",
    definition:
      "Action items are specific tasks surfaced by the PM agent based on its analysis of your workspace. Unlike generic to-do items, each action item has a priority (critical/high/medium/low), a category (risk/pain-point/team/feature/stakeholder-update), and references to the actual PRs, issues, or metrics that triggered it.",
    inDash:
      "Every daily brief produces 3-5 action items. You can resolve them inline on the dashboard, or click 'Discuss' to open a chat session with full context about that specific item. Resolved items stay visible but dimmed. Action items bridge the brief view and the chat view.",
  },
};
