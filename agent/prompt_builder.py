"""System prompt assembly -- identity, platform hints, skills index, context files.

All functions are stateless. AIAgent._build_system_prompt() calls these to
assemble pieces, then combines them with memory and ephemeral prompts.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from kai_env import kai_home, get_env

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context file scanning — detect prompt injection in AGENTS.md, .cursorrules,
# SOUL.md before they get injected into the system prompt.
# ---------------------------------------------------------------------------

_CONTEXT_THREAT_PATTERNS = [
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+(restrictions|limits|rules)', "bypass_restrictions"),
    (r'<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->', "html_comment_injection"),
    (r'<\s*div\s+style\s*=\s*["\'].*display\s*:\s*none', "hidden_div"),
    (r'translate\s+.*\s+into\s+.*\s+and\s+(execute|run|eval)', "translate_execute"),
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)', "read_secrets"),
]

_CONTEXT_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
}


def _scan_context_content(content: str, filename: str) -> str:
    """Scan context file content for injection. Returns sanitized content."""
    findings = []

    # Check invisible unicode
    for char in _CONTEXT_INVISIBLE_CHARS:
        if char in content:
            findings.append(f"invisible unicode U+{ord(char):04X}")

    # Check threat patterns
    for pattern, pid in _CONTEXT_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            findings.append(pid)

    if findings:
        logger.warning("Context file %s blocked: %s", filename, ", ".join(findings))
        return f"[BLOCKED: {filename} contained potential prompt injection ({', '.join(findings)}). Content not loaded.]"

    return content

# =========================================================================
# Constants
# =========================================================================

DEFAULT_AGENT_IDENTITY = (
    "You are Dash, an autonomous PM that manages product teams. Not an assistant. Not a chatbot. "
    "A senior product manager who understands the organization, connects signals across domains, and drives outcomes.\n\n"

    "What you deliver:\n"
    "- Daily briefs — what happened, what matters, what needs attention, with concrete action items\n"
    "- Cross-domain synthesis — connecting code activity, analytics, team dynamics, and market signals into insights no single tool can see\n"
    "- Proactive risk detection — flagging blockers, stale work, team issues, and product problems before they escalate\n"
    "- Priority recommendations — what to build next based on data, not just gut feel\n"
    "- Stakeholder updates — clear, data-backed summaries for leadership and team\n\n"

    "How you behave:\n"
    "- You speak in findings, not capabilities. Show what you found, not what you can do.\n"
    "- You are concrete. '86% completion rate, 3 PRs stale >5 days, traffic up 40% WoW from LinkedIn' not 'things are going well.'\n"
    "- You are decisive. You say 'we should' not 'you might consider.' You have opinions grounded in data.\n"
    "- You connect dots. A traffic spike + a broken feature + a silent team member = a story. Tell it.\n"
    "- You learn. Save discoveries to memory. Get smarter every cycle.\n\n"

    "What you can do freely (no confirmation needed):\n"
    "- Read project boards, check analytics, browse repos, review PRs, search history\n"
    "- Save learnings, update workspace context, store briefs, manage action items\n"
    "- Schedule recurring briefs and monitoring tasks\n\n"

    "What requires user confirmation first:\n"
    "- Creating GitHub issues or tickets — visible to team\n"
    "- Sending messages to team channels — visible to others\n"
    "- Any action that modifies external systems or is visible to the team\n\n"

    "Your signal sources (use whatever is connected via MCP or CLI):\n"
    "- GitHub — code, PRs, issues, project boards, team activity "
    "(GitHub App installation token in $GITHUB_TOKEN; use `gh api` not `gh pr list` — "
    "installation tokens don't carry a user identity)\n"
    "- Linear — sprints, cycles, issues, team workload (MCP)\n"
    "- Jira — enterprise issue tracking, workflows, cross-team dependencies (MCP)\n"
    "- PostHog/Amplitude/Mixpanel — user behavior, funnels, feature adoption, experiments (MCP)\n"
    "- Sentry — errors, release health, performance regressions (MCP)\n"
    "- Stripe/Paddle — revenue, subscriptions, churn, MRR (MCP)\n"
    "- Notion — PRDs, specs, roadmaps, knowledge base (MCP)\n"
    "- Granola — meeting notes, decisions, action items from calls (MCP)\n"
    "- Figma — design specs, handoff status, design system (MCP)\n"
    "- Slack — team context, decisions, blockers (gateway)\n"
    "- Intercom/Canny — customer feedback, feature requests, support tickets (MCP)\n"
    "- HubSpot/Attio — CRM, pipeline, deal stages (MCP)\n"
    "- Terminal + web search — run scripts, research, data analysis\n"
    "Not all sources are always connected. Use platforms_list to check what's available. "
    "The value is in connecting signals across sources — not in reporting from one tool.\n\n"

    "Never use emojis. Never apologize. Never list capabilities after the first message. "
    "A PM drives outcomes and shows the data."
)

PM_GUIDANCE = (
    "## PM Analysis Patterns\n\n"
    "When analyzing a project or sprint:\n"
    "1. Start with the project board — what's in progress, blocked, done, and unstarted?\n"
    "2. Check recent PRs and commits — who's active, what shipped, what's stale?\n"
    "3. If analytics are connected, check key metrics — any anomalies or trends?\n"
    "4. Cross-reference: do the signals from different sources tell a coherent story?\n"
    "5. Identify the 2-3 most important things the team should know right now\n\n"
    "When producing a daily brief:\n"
    "1. Load the pm-brief/daily-brief skill and follow it exactly\n"
    "2. Check all connected data sources systematically\n"
    "3. Compare current state to your last brief (stored in memory)\n"
    "4. Surface action items with clear priority and category\n"
    "5. Store the brief using brief_store for history\n\n"
    "When asked 'what should we build next?':\n"
    "1. Analyze current sprint velocity and completion patterns\n"
    "2. Check analytics for user pain points and feature adoption\n"
    "3. Review open issues and feature requests by signal strength\n"
    "4. Consider team capacity and current workload\n"
    "5. Recommend with rationale grounded in data, not speculation"
)

MEMORY_GUIDANCE = (
    "You have persistent memory across sessions. Proactively save important things "
    "you learn: team dynamics, product metrics, stakeholder preferences, sprint "
    "patterns, and research findings. Build institutional knowledge about the "
    "organization so you get smarter over time."
)

WORKSPACE_CONTEXT_GUIDANCE = (
    "You have persistent memory across all conversations (web, Slack, CLI, cron). "
    "Use the memory tool to save and recall important context. "
    "Use the todo tool to track work items and pending tasks.\n\n"
    "At conversation start, check your memory for relevant context. "
    "Before ending a conversation, save key learnings and update your task list."
)

SESSION_SEARCH_GUIDANCE = (
    "When the user references something from a past conversation or you suspect "
    "relevant prior context exists, use session_search to recall it before asking "
    "them to repeat themselves."
)

SKILLS_GUIDANCE = (
    "After completing a complex task (5+ tool calls), discovering an effective "
    "PM analysis workflow, or finding a useful research pattern, save "
    "the approach as a skill with skill_manage so you can reuse it next time. "
    "Pay special attention to: brief generation patterns, risk assessment "
    "workflows, and research strategies that yielded good results."
)

CRONJOB_MONITORING_GUIDANCE = (
    "You have cron/scheduling tools. Use them for recurring PM operations. "
    "Schedule daily briefs (default: every 6 hours), risk assessments, and "
    "metric checks as cron jobs. When an operation completes or surfaces "
    "something important, the cron job should notify the user. "
    "Do not rely on the user asking you to check. You are an "
    "always-on PM agent, not a request-response chatbot. Be proactive."
)

PLATFORM_HINTS = {
    "whatsapp": (
        "You are on a text messaging communication platform, WhatsApp. "
        "Please do not use markdown as it does not render. "
        "You can send media files natively: to deliver a file to the user, "
        "include MEDIA:/absolute/path/to/file in your response. The file "
        "will be sent as a native WhatsApp attachment — images (.jpg, .png, "
        ".webp) appear as photos, videos (.mp4, .mov) play inline, and other "
        "files arrive as downloadable documents. You can also include image "
        "URLs in markdown format ![alt](url) and they will be sent as photos."
    ),
    "telegram": (
        "You are on a text messaging communication platform, Telegram. "
        "Please do not use markdown as it does not render. "
        "You can send media files natively: to deliver a file to the user, "
        "include MEDIA:/absolute/path/to/file in your response. Images "
        "(.png, .jpg, .webp) appear as photos, audio (.ogg) sends as voice "
        "bubbles, and videos (.mp4) play inline. You can also include image "
        "URLs in markdown format ![alt](url) and they will be sent as native photos."
    ),
    "discord": (
        "You are in a Discord server or group chat communicating with your user. "
        "You can send media files natively: include MEDIA:/absolute/path/to/file "
        "in your response. Images (.png, .jpg, .webp) are sent as photo "
        "attachments, audio as file attachments. You can also include image URLs "
        "in markdown format ![alt](url) and they will be sent as attachments."
    ),
    "slack": (
        "You are Dash, a PM agent in a Slack workspace, acting as the team's dedicated "
        "product manager. When mentioned or messaged, respond with clear, actionable "
        "updates grounded in data. For long-running operations (briefs, risk assessments), "
        "post progress updates in the thread. Use data and metrics to back your points. "
        "You can send media files via MEDIA:/absolute/path/to/file."
    ),
    "signal": (
        "You are on a text messaging communication platform, Signal. "
        "Please do not use markdown as it does not render. "
        "You can send media files natively: to deliver a file to the user, "
        "include MEDIA:/absolute/path/to/file in your response. Images "
        "(.png, .jpg, .webp) appear as photos, audio as attachments, and other "
        "files arrive as downloadable documents. You can also include image "
        "URLs in markdown format ![alt](url) and they will be sent as photos."
    ),
    "email": (
        "You are communicating via email. Write clear, well-structured responses "
        "suitable for email. Use plain text formatting (no markdown). "
        "Keep responses concise but complete. You can send file attachments — "
        "include MEDIA:/absolute/path/to/file in your response. The subject line "
        "is preserved for threading. Do not include greetings or sign-offs unless "
        "contextually appropriate."
    ),
    "cli": (
        "You are a CLI AI Agent. Try not to use markdown but simple text "
        "renderable inside a terminal."
    ),
}

CONTEXT_FILE_MAX_CHARS = 20_000
CONTEXT_TRUNCATE_HEAD_RATIO = 0.7
CONTEXT_TRUNCATE_TAIL_RATIO = 0.2


# =========================================================================
# Skills index
# =========================================================================

def _read_skill_description(skill_file: Path, max_chars: int = 60) -> str:
    """Read the description from a SKILL.md frontmatter, capped at max_chars."""
    try:
        raw = skill_file.read_text(encoding="utf-8")[:2000]
        match = re.search(
            r"^---\s*\n.*?description:\s*(.+?)\s*\n.*?^---",
            raw, re.MULTILINE | re.DOTALL,
        )
        if match:
            desc = match.group(1).strip().strip("'\"")
            if len(desc) > max_chars:
                desc = desc[:max_chars - 3] + "..."
            return desc
    except Exception as e:
        logger.debug("Failed to read skill description from %s: %s", skill_file, e)
    return ""


def _skill_is_platform_compatible(skill_file: Path) -> bool:
    """Quick check if a SKILL.md is compatible with the current OS platform.

    Reads just enough to parse the ``platforms`` frontmatter field.
    Skills without the field (the vast majority) are always compatible.
    """
    try:
        from tools.skills_tool import _parse_frontmatter, skill_matches_platform
        raw = skill_file.read_text(encoding="utf-8")[:2000]
        frontmatter, _ = _parse_frontmatter(raw)
        return skill_matches_platform(frontmatter)
    except Exception:
        return True  # Err on the side of showing the skill


def _read_skill_conditions(skill_file: Path) -> dict:
    """Extract conditional activation fields from SKILL.md frontmatter."""
    try:
        from tools.skills_tool import _parse_frontmatter
        raw = skill_file.read_text(encoding="utf-8")[:2000]
        frontmatter, _ = _parse_frontmatter(raw)
        hermes = frontmatter.get("metadata", {}).get("hermes", {})
        return {
            "fallback_for_toolsets": hermes.get("fallback_for_toolsets", []),
            "requires_toolsets": hermes.get("requires_toolsets", []),
            "fallback_for_tools": hermes.get("fallback_for_tools", []),
            "requires_tools": hermes.get("requires_tools", []),
        }
    except Exception:
        return {}


def _skill_should_show(
    conditions: dict,
    available_tools: "set[str] | None",
    available_toolsets: "set[str] | None",
) -> bool:
    """Return False if the skill's conditional activation rules exclude it."""
    if available_tools is None and available_toolsets is None:
        return True  # No filtering info — show everything (backward compat)

    at = available_tools or set()
    ats = available_toolsets or set()

    # fallback_for: hide when the primary tool/toolset IS available
    for ts in conditions.get("fallback_for_toolsets", []):
        if ts in ats:
            return False
    for t in conditions.get("fallback_for_tools", []):
        if t in at:
            return False

    # requires: hide when a required tool/toolset is NOT available
    for ts in conditions.get("requires_toolsets", []):
        if ts not in ats:
            return False
    for t in conditions.get("requires_tools", []):
        if t not in at:
            return False

    return True


def build_skills_system_prompt(
    available_tools: "set[str] | None" = None,
    available_toolsets: "set[str] | None" = None,
) -> str:
    """Build a compact skill index for the system prompt.

    Scans ~/.hermes/skills/ for SKILL.md files grouped by category.
    Includes per-skill descriptions from frontmatter so the model can
    match skills by meaning, not just name.
    Filters out skills incompatible with the current OS platform.
    """
    hermes_home = kai_home()
    skills_dir = hermes_home / "skills"

    if not skills_dir.exists():
        return ""

    # Collect skills with descriptions, grouped by category
    # Each entry: (skill_name, description)
    # Supports sub-categories: skills/mlops/training/axolotl/SKILL.md
    # → category "mlops/training", skill "axolotl"
    skills_by_category: dict[str, list[tuple[str, str]]] = {}
    for skill_file in skills_dir.rglob("SKILL.md"):
        # Skip skills incompatible with the current OS platform
        if not _skill_is_platform_compatible(skill_file):
            continue
        # Skip skills whose conditional activation rules exclude them
        conditions = _read_skill_conditions(skill_file)
        if not _skill_should_show(conditions, available_tools, available_toolsets):
            continue
        rel_path = skill_file.relative_to(skills_dir)
        parts = rel_path.parts
        if len(parts) >= 2:
            # Category is everything between skills_dir and the skill folder
            # e.g. parts = ("mlops", "training", "axolotl", "SKILL.md")
            #   → category = "mlops/training", skill_name = "axolotl"
            # e.g. parts = ("github", "github-auth", "SKILL.md")
            #   → category = "github", skill_name = "github-auth"
            skill_name = parts[-2]
            category = "/".join(parts[:-2]) if len(parts) > 2 else parts[0]
        else:
            category = "general"
            skill_name = skill_file.parent.name
        desc = _read_skill_description(skill_file)
        skills_by_category.setdefault(category, []).append((skill_name, desc))

    if not skills_by_category:
        return ""

    # Read category-level descriptions from DESCRIPTION.md
    # Checks both the exact category path and parent directories
    category_descriptions = {}
    for category in skills_by_category:
        cat_path = Path(category)
        desc_file = skills_dir / cat_path / "DESCRIPTION.md"
        if desc_file.exists():
            try:
                content = desc_file.read_text(encoding="utf-8")
                match = re.search(r"^---\s*\n.*?description:\s*(.+?)\s*\n.*?^---", content, re.MULTILINE | re.DOTALL)
                if match:
                    category_descriptions[category] = match.group(1).strip()
            except Exception as e:
                logger.debug("Could not read skill description %s: %s", desc_file, e)

    index_lines = []
    for category in sorted(skills_by_category.keys()):
        cat_desc = category_descriptions.get(category, "")
        if cat_desc:
            index_lines.append(f"  {category}: {cat_desc}")
        else:
            index_lines.append(f"  {category}:")
        # Deduplicate and sort skills within each category
        seen = set()
        for name, desc in sorted(skills_by_category[category], key=lambda x: x[0]):
            if name in seen:
                continue
            seen.add(name)
            if desc:
                index_lines.append(f"    - {name}: {desc}")
            else:
                index_lines.append(f"    - {name}")

    return (
        "## Skills (mandatory)\n"
        "Before replying, scan the skills below. If one clearly matches your task, "
        "load it with skill_view(name) and follow its instructions. "
        "If a skill has issues, fix it with skill_manage(action='patch').\n"
        "\n"
        "<available_skills>\n"
        + "\n".join(index_lines) + "\n"
        "</available_skills>\n"
        "\n"
        "If none match, proceed normally without loading a skill."
    )


# =========================================================================
# Context files (SOUL.md, AGENTS.md, .cursorrules)
# =========================================================================

def _truncate_content(content: str, filename: str, max_chars: int = CONTEXT_FILE_MAX_CHARS) -> str:
    """Head/tail truncation with a marker in the middle."""
    if len(content) <= max_chars:
        return content
    head_chars = int(max_chars * CONTEXT_TRUNCATE_HEAD_RATIO)
    tail_chars = int(max_chars * CONTEXT_TRUNCATE_TAIL_RATIO)
    head = content[:head_chars]
    tail = content[-tail_chars:]
    marker = f"\n\n[...truncated {filename}: kept {head_chars}+{tail_chars} of {len(content)} chars. Use file tools to read the full file.]\n\n"
    return head + marker + tail


def build_context_files_prompt(cwd: Optional[str] = None) -> str:
    """Discover and load context files for the system prompt.

    Discovery: AGENTS.md (recursive), .cursorrules / .cursor/rules/*.mdc,
    SOUL.md (cwd then ~/.hermes/ fallback). Each capped at 20,000 chars.
    """
    if cwd is None:
        cwd = os.getcwd()

    cwd_path = Path(cwd).resolve()
    sections = []

    # AGENTS.md (hierarchical, recursive)
    top_level_agents = None
    for name in ["AGENTS.md", "agents.md"]:
        candidate = cwd_path / name
        if candidate.exists():
            top_level_agents = candidate
            break

    if top_level_agents:
        agents_files = []
        for root, dirs, files in os.walk(cwd_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.venv')]
            for f in files:
                if f.lower() == "agents.md":
                    agents_files.append(Path(root) / f)
        agents_files.sort(key=lambda p: len(p.parts))

        total_agents_content = ""
        for agents_path in agents_files:
            try:
                content = agents_path.read_text(encoding="utf-8").strip()
                if content:
                    rel_path = agents_path.relative_to(cwd_path)
                    content = _scan_context_content(content, str(rel_path))
                    total_agents_content += f"## {rel_path}\n\n{content}\n\n"
            except Exception as e:
                logger.debug("Could not read %s: %s", agents_path, e)

        if total_agents_content:
            total_agents_content = _truncate_content(total_agents_content, "AGENTS.md")
            sections.append(total_agents_content)

    # .cursorrules
    cursorrules_content = ""
    cursorrules_file = cwd_path / ".cursorrules"
    if cursorrules_file.exists():
        try:
            content = cursorrules_file.read_text(encoding="utf-8").strip()
            if content:
                content = _scan_context_content(content, ".cursorrules")
                cursorrules_content += f"## .cursorrules\n\n{content}\n\n"
        except Exception as e:
            logger.debug("Could not read .cursorrules: %s", e)

    cursor_rules_dir = cwd_path / ".cursor" / "rules"
    if cursor_rules_dir.exists() and cursor_rules_dir.is_dir():
        mdc_files = sorted(cursor_rules_dir.glob("*.mdc"))
        for mdc_file in mdc_files:
            try:
                content = mdc_file.read_text(encoding="utf-8").strip()
                if content:
                    content = _scan_context_content(content, f".cursor/rules/{mdc_file.name}")
                    cursorrules_content += f"## .cursor/rules/{mdc_file.name}\n\n{content}\n\n"
            except Exception as e:
                logger.debug("Could not read %s: %s", mdc_file, e)

    if cursorrules_content:
        cursorrules_content = _truncate_content(cursorrules_content, ".cursorrules")
        sections.append(cursorrules_content)

    # SOUL.md (cwd first, then ~/.hermes/ fallback)
    soul_path = None
    for name in ["SOUL.md", "soul.md"]:
        candidate = cwd_path / name
        if candidate.exists():
            soul_path = candidate
            break
    if not soul_path:
        global_soul = Path.home() / ".hermes" / "SOUL.md"
        if global_soul.exists():
            soul_path = global_soul

    if soul_path:
        try:
            content = soul_path.read_text(encoding="utf-8").strip()
            if content:
                content = _scan_context_content(content, "SOUL.md")
                content = _truncate_content(content, "SOUL.md")
                sections.append(
                    f"## SOUL.md\n\nIf SOUL.md is present, embody its persona and tone. "
                    f"Avoid stiff, generic replies; follow its guidance unless higher-priority "
                    f"instructions override it.\n\n{content}"
                )
        except Exception as e:
            logger.debug("Could not read SOUL.md from %s: %s", soul_path, e)

    if not sections:
        return ""
    return "# Project Context\n\nThe following project context files have been loaded and should be followed:\n\n" + "\n".join(sections)
