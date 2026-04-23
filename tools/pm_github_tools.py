"""
PM GitHub tools — write operations via the GitHub App installation token.

The agent uses these to:
  - List the repos the installation can see (typed, not shell parsing)
  - Create issues on behalf of the team
  - Add comments to existing issues / PRs

All writes require explicit user confirmation per the PM agent identity rules.
`$GITHUB_TOKEN` is injected per agent run by github_app_auth.refresh_github_token_env().
"""

import json
import logging
import os
import urllib.request
import urllib.error

from tools.registry import registry

logger = logging.getLogger(__name__)


def _github_request(method: str, path: str, body: dict = None, timeout: int = 15):
    """POST/GET/PATCH against the GitHub REST API using $GITHUB_TOKEN.

    Returns (status, parsed_json_or_text).
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return 0, {"error": "No $GITHUB_TOKEN in environment. Is the GitHub App installed for this workspace?"}

    url = "https://api.github.com" + (path if path.startswith("/") else "/" + path)
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Dash-PM",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8")
        except Exception:
            pass
        try:
            parsed = json.loads(body_text) if body_text else None
        except Exception:
            parsed = body_text
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)}


# =============================================================================
# Tool: github_list_repos
# =============================================================================

def github_list_repos(**kwargs) -> str:
    """List every repo the installation has access to."""
    status, data = _github_request("GET", "/installation/repositories?per_page=100")
    if status != 200:
        return json.dumps({"error": f"HTTP {status}", "details": data})
    repos = [
        {
            "full_name": r.get("full_name"),
            "description": r.get("description") or "",
            "default_branch": r.get("default_branch"),
            "pushed_at": r.get("pushed_at"),
            "open_issues_count": r.get("open_issues_count"),
            "private": r.get("private"),
        }
        for r in (data or {}).get("repositories", [])
    ]
    return json.dumps({"count": len(repos), "repos": repos})


GITHUB_LIST_REPOS_SCHEMA = {
    "name": "github_list_repos",
    "description": (
        "List every GitHub repository the GitHub App installation can see. "
        "Always call this before attempting to read/write any specific repo — "
        "installation tokens 404 on repos outside the selected set."
    ),
    "parameters": {"type": "object", "properties": {}},
}


# =============================================================================
# Tool: github_create_issue
# =============================================================================

def github_create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list = None,
    assignees: list = None,
    **kwargs,
) -> str:
    """Create a new GitHub issue. Requires `Issues: Read and write` permission."""
    if "/" not in (repo or ""):
        return json.dumps({"error": "repo must be 'owner/name'"})
    if not title.strip():
        return json.dumps({"error": "title required"})

    payload: dict = {"title": title.strip(), "body": body or ""}
    if labels:
        payload["labels"] = list(labels)
    if assignees:
        payload["assignees"] = list(assignees)

    status, data = _github_request("POST", f"/repos/{repo}/issues", body=payload)
    if status == 201 and isinstance(data, dict):
        return json.dumps({
            "ok": True,
            "number": data.get("number"),
            "url": data.get("html_url"),
            "title": data.get("title"),
            "state": data.get("state"),
        })
    # Permission-denied is the most common failure: App needs Issues: write.
    if status == 403:
        return json.dumps({
            "ok": False,
            "error": "permission_denied",
            "hint": (
                "The GitHub App installation doesn't have Issues: Write. "
                "Update permissions at github.com/settings/apps/<slug>/permissions "
                "and accept the new permissions on the installation page."
            ),
            "details": data,
        })
    return json.dumps({"ok": False, "error": f"HTTP {status}", "details": data})


GITHUB_CREATE_ISSUE_SCHEMA = {
    "name": "github_create_issue",
    "description": (
        "Create a new GitHub issue on a repo the installation can see. "
        "This is a user-visible action — confirm with the user before calling, "
        "unless they explicitly asked you to file the issue."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository as 'owner/name' (e.g. 'acme/api'). Use github_list_repos to find valid repos.",
            },
            "title": {"type": "string", "description": "Issue title — concise, action-oriented."},
            "body": {
                "type": "string",
                "description": "Markdown body. Include context, reproduction steps, links to related PRs/metrics, and the expected outcome.",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional labels (must already exist on the repo).",
            },
            "assignees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional GitHub handles to assign.",
            },
        },
        "required": ["repo", "title"],
    },
}


# =============================================================================
# Tool: github_add_comment
# =============================================================================

def github_add_comment(
    repo: str,
    issue_number: int,
    body: str,
    **kwargs,
) -> str:
    """Add a comment to an existing issue or PR."""
    if "/" not in (repo or ""):
        return json.dumps({"error": "repo must be 'owner/name'"})
    if not body.strip():
        return json.dumps({"error": "body required"})
    status, data = _github_request(
        "POST",
        f"/repos/{repo}/issues/{issue_number}/comments",
        body={"body": body},
    )
    if status == 201 and isinstance(data, dict):
        return json.dumps({"ok": True, "url": data.get("html_url"), "id": data.get("id")})
    if status == 403:
        return json.dumps({
            "ok": False,
            "error": "permission_denied",
            "hint": "GitHub App needs Issues: Write for comments on issues, Pull requests: Write for PRs.",
            "details": data,
        })
    return json.dumps({"ok": False, "error": f"HTTP {status}", "details": data})


GITHUB_ADD_COMMENT_SCHEMA = {
    "name": "github_add_comment",
    "description": "Add a comment to an existing GitHub issue or pull request. User-visible — confirm before calling.",
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "'owner/name'"},
            "issue_number": {"type": "integer", "description": "Issue or PR number"},
            "body": {"type": "string", "description": "Markdown body of the comment."},
        },
        "required": ["repo", "issue_number", "body"],
    },
}


# =============================================================================
# Tool: github_discover_agents
# =============================================================================

def github_discover_agents(repos: list = None, lookback_days: int = 90, **kwargs) -> str:
    """Discover coding agents active in connected repos (methods B, C, D from issue #11).

    Runs fingerprint scan + org-installations probe + workflow scan, merges results,
    then writes the merged profiles to the workspace blueprint.

    Always returns a summary of what was found — the caller should present this to
    the user and ask them to enable specific agents before delegation starts.
    """
    import os
    from agent_fleet.discovery import discover_external_agents, merge_with_existing
    from agent_fleet.blueprint import get_external_agents, upsert_agent_profile
    from workspace_context import load_workspace_context

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token — install the GitHub App first."})

    # Resolve repos list
    if not repos:
        status, data = _github_request("GET", "/installation/repositories?per_page=100")
        if status != 200:
            return json.dumps({"error": f"Could not list repos: HTTP {status}"})
        repos = [r["full_name"] for r in (data or {}).get("repositories", [])]

    if not repos:
        return json.dumps({"message": "No repos accessible to the GitHub App."})

    discovered = discover_external_agents(repos, token, lookback_days=lookback_days)

    # Load workspace and merge
    ws_id = (
        os.environ.get("KAI_WORKSPACE_ID")
        or os.environ.get("HERMES_WORKSPACE_ID")
        or "default"
    )
    ctx = load_workspace_context(workspace_id=ws_id)
    existing = get_external_agents(ctx)
    merged, new_ids, updated_ids = merge_with_existing(discovered, existing)

    for profile in merged:
        if profile.id in new_ids or profile.id in updated_ids:
            try:
                upsert_agent_profile(ctx, profile)
            except Exception as e:
                logger.warning("Could not save profile %s: %s", profile.id, e)

    summary = []
    for p in discovered:
        tag = "(new)" if p.id in new_ids else "(updated)"
        summary.append({
            "id": p.id,
            "display_name": p.display_name(),
            "confidence": p.confidence,
            "detected_via": p.detected_via,
            "activity_90d": p.activity_90d,
            "primary_repos": p.primary_repos,
            "enabled": p.enabled,
            "tag": tag,
        })

    return json.dumps({
        "repos_scanned": repos,
        "agents_found": len(discovered),
        "new": new_ids,
        "updated": updated_ids,
        "agents": summary,
        "next_step": (
            "Call github_manage_agent with action='enable' for each agent you want Dash to delegate to. "
            "All agents start disabled until you explicitly enable them."
        ),
    }, indent=2)


GITHUB_DISCOVER_AGENTS_SCHEMA = {
    "name": "github_discover_agents",
    "description": (
        "Discover coding agents (Claude Code, Codex, Devin, Jules, Copilot SWE, Cursor, etc.) "
        "active in connected GitHub repos by scanning PR/comment activity, org app installations, "
        "and workflow YAML files. Run this when the user asks to 'find coding agents', 'set up "
        "agent delegation', or during onboarding. Results are saved to the workspace blueprint. "
        "All discovered agents start DISABLED — use github_manage_agent to enable them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Repos to scan as 'owner/name'. Defaults to all installation repos.",
            },
            "lookback_days": {
                "type": "integer",
                "description": "How many days back to scan for activity (default 90).",
            },
        },
    },
}


# =============================================================================
# Tool: github_manage_agent  (Method A — manual override)
# =============================================================================

def github_manage_agent(
    action: str,
    agent_id: str,
    display_name: str = None,
    notes: str = None,
    **kwargs,
) -> str:
    """Method A: manually add, enable, disable, or rename an agent profile."""
    import os
    from agent_fleet.profile import AgentProfile, AgentProfileError
    from agent_fleet.registry import lookup as registry_lookup
    from agent_fleet.blueprint import (
        get_agent_profile, upsert_agent_profile, remove_agent_profile,
    )
    from workspace_context import load_workspace_context

    ws_id = (
        os.environ.get("KAI_WORKSPACE_ID")
        or os.environ.get("HERMES_WORKSPACE_ID")
        or "default"
    )
    ctx = load_workspace_context(workspace_id=ws_id)
    action = (action or "").strip().lower()

    if action == "add":
        # Allow adding known agents or custom ones (custom:*)
        if not agent_id.startswith("custom:") and registry_lookup(agent_id) is None:
            known_ids = [a.id for a in __import__("agent_fleet.registry", fromlist=["list_known"]).list_known()]
            return json.dumps({
                "error": f"Unknown agent id {agent_id!r}.",
                "hint": f"Known ids: {known_ids}. For unlisted agents use 'custom:<name>'.",
            })
        existing = get_agent_profile(ctx, agent_id)
        if existing:
            return json.dumps({"message": f"{agent_id} already exists. Use action='enable' or 'rename'."})
        profile = AgentProfile(
            id=agent_id,
            enabled=True,   # manual add = intentional, start enabled
            detected_via=["manual"],
            confidence="high",
            display_name_override=display_name,
            notes=notes,
        )
        try:
            upsert_agent_profile(ctx, profile)
        except AgentProfileError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"ok": True, "action": "added", "id": agent_id, "enabled": True})

    if action in ("enable", "disable"):
        profile = get_agent_profile(ctx, agent_id)
        if not profile:
            return json.dumps({"error": f"No profile for {agent_id!r}. Run github_discover_agents first, or use action='add'."})
        profile.enabled = action == "enable"
        upsert_agent_profile(ctx, profile)
        return json.dumps({"ok": True, "action": action, "id": agent_id, "enabled": profile.enabled})

    if action == "rename":
        profile = get_agent_profile(ctx, agent_id)
        if not profile:
            return json.dumps({"error": f"No profile for {agent_id!r}."})
        profile.display_name_override = display_name
        upsert_agent_profile(ctx, profile)
        return json.dumps({"ok": True, "action": "renamed", "id": agent_id, "display_name": display_name})

    if action == "remove":
        removed = remove_agent_profile(ctx, agent_id)
        return json.dumps({"ok": removed, "action": "removed", "id": agent_id})

    if action == "list":
        from agent_fleet.blueprint import get_external_agents
        profiles = get_external_agents(ctx)
        return json.dumps({
            "agents": [
                {
                    "id": p.id,
                    "display_name": p.display_name(),
                    "enabled": p.enabled,
                    "confidence": p.confidence,
                    "detected_via": p.detected_via,
                    "last_active": p.last_active,
                }
                for p in profiles
            ]
        })

    return json.dumps({"error": f"Unknown action {action!r}. Use: add, enable, disable, rename, remove, list."})


GITHUB_MANAGE_AGENT_SCHEMA = {
    "name": "github_manage_agent",
    "description": (
        "Manage external coding agent profiles in the workspace. "
        "Actions: 'list' — show all profiles; 'add' — manually register an agent by id (or 'custom:<name>'); "
        "'enable'/'disable' — control whether Dash delegates to this agent; "
        "'rename' — set a display name override; 'remove' — delete the profile. "
        "Call 'list' first to see what's already registered."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "enable", "disable", "rename", "remove", "list"],
                "description": "What to do.",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent id from the static registry (e.g. 'claude-code', 'codex') or 'custom:<name>'. Required for all actions except 'list'.",
            },
            "display_name": {
                "type": "string",
                "description": "Optional human-readable name override (used with 'add' or 'rename').",
            },
            "notes": {
                "type": "string",
                "description": "Optional free-text note about this agent (stored in profile).",
            },
        },
        "required": ["action"],
    },
}


# =============================================================================
# Registry
# =============================================================================

registry.register(
    name="github_list_repos",
    toolset="pm-github",
    schema=GITHUB_LIST_REPOS_SCHEMA,
    handler=lambda args, **kw: github_list_repos(),
)

registry.register(
    name="github_create_issue",
    toolset="pm-github",
    schema=GITHUB_CREATE_ISSUE_SCHEMA,
    handler=lambda args, **kw: github_create_issue(
        repo=args.get("repo", ""),
        title=args.get("title", ""),
        body=args.get("body", ""),
        labels=args.get("labels") or None,
        assignees=args.get("assignees") or None,
    ),
)

registry.register(
    name="github_add_comment",
    toolset="pm-github",
    schema=GITHUB_ADD_COMMENT_SCHEMA,
    handler=lambda args, **kw: github_add_comment(
        repo=args.get("repo", ""),
        issue_number=int(args.get("issue_number", 0)),
        body=args.get("body", ""),
    ),
)

registry.register(
    name="github_discover_agents",
    toolset="pm-github",
    schema=GITHUB_DISCOVER_AGENTS_SCHEMA,
    handler=lambda args, **kw: github_discover_agents(
        repos=args.get("repos") or None,
        lookback_days=int(args.get("lookback_days") or 90),
    ),
)

registry.register(
    name="github_manage_agent",
    toolset="pm-github",
    schema=GITHUB_MANAGE_AGENT_SCHEMA,
    handler=lambda args, **kw: github_manage_agent(
        action=args.get("action", ""),
        agent_id=args.get("agent_id", ""),
        display_name=args.get("display_name"),
        notes=args.get("notes"),
    ),
)
