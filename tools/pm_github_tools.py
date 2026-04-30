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
from typing import Optional

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


# =============================================================================
# Tool: github_learn_invocations
# =============================================================================

def github_learn_invocations(agent_ids: list = None, **kwargs) -> str:
    """Run invocation learning for enabled agents and update their profiles."""
    import os
    from agent_fleet.invocation import learn_invocation_pattern
    from agent_fleet.blueprint import get_external_agents, get_enabled_agents, upsert_agent_profile
    from workspace_context import load_workspace_context

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token."})

    ws_id = (
        os.environ.get("KAI_WORKSPACE_ID")
        or os.environ.get("HERMES_WORKSPACE_ID")
        or "default"
    )
    ctx = load_workspace_context(workspace_id=ws_id)

    # Resolve repos
    status, data = _github_request("GET", "/installation/repositories?per_page=100")
    if status != 200:
        return json.dumps({"error": f"Could not list repos: HTTP {status}"})
    repos = [r["full_name"] for r in (data or {}).get("repositories", [])]

    # Determine which agents to learn for
    all_profiles = get_external_agents(ctx)
    if agent_ids:
        targets = [p for p in all_profiles if p.id in agent_ids]
    else:
        targets = [p for p in all_profiles if p.enabled]

    if not targets:
        return json.dumps({"message": "No enabled agents to learn for. Run github_discover_agents first, then enable agents with github_manage_agent."})

    results = []
    for profile in targets:
        updated = learn_invocation_pattern(profile, repos, token)
        upsert_agent_profile(ctx, updated)
        inv = updated.observed_invocation
        results.append({
            "id": updated.id,
            "confidence": updated.confidence,
            "primary": inv.primary.to_dict() if inv.primary else None,
            "secondary": inv.secondary.to_dict() if inv.secondary else None,
        })

    return json.dumps({"agents_updated": len(results), "results": results}, indent=2)


GITHUB_LEARN_INVOCATIONS_SCHEMA = {
    "name": "github_learn_invocations",
    "description": (
        "Learn how this tenant actually invokes each enabled coding agent by scanning "
        "recent PR/issue timelines. Updates the observed_invocation and confidence fields "
        "on each agent's profile in the workspace blueprint. Run this after discovery "
        "(github_discover_agents) to sharpen delegation accuracy. "
        "Can be scoped to specific agent ids or defaults to all enabled agents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of agent ids to learn for. Defaults to all enabled agents.",
            },
        },
    },
}

registry.register(
    name="github_learn_invocations",
    toolset="pm-github",
    schema=GITHUB_LEARN_INVOCATIONS_SCHEMA,
    handler=lambda args, **kw: github_learn_invocations(
        agent_ids=args.get("agent_ids") or None,
    ),
)


# =============================================================================
# Tool: github_delegate_task
# =============================================================================

def github_delegate_task(
    repo: str,
    title: str,
    problem: str,
    acceptance_criteria: list,
    agent_id: str,
    context: str = "",
    constraints: str = "",
    **kwargs,
) -> str:
    """File a structured Dash delegation issue and invoke the coding agent."""
    import os
    from agent_fleet.delegation import DelegationTask, build_delegation_issue, dispatch_post_create_actions
    from agent_fleet.blueprint import get_agent_profile
    from workspace_context import load_workspace_context

    if "/" not in (repo or ""):
        return json.dumps({"error": "repo must be 'owner/name'"})
    if not title.strip() or not problem.strip() or not acceptance_criteria:
        return json.dumps({"error": "title, problem, and acceptance_criteria are required"})

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token."})

    ws_id = (
        os.environ.get("KAI_WORKSPACE_ID")
        or os.environ.get("HERMES_WORKSPACE_ID")
        or "default"
    )
    ctx = load_workspace_context(workspace_id=ws_id)
    profile = get_agent_profile(ctx, agent_id)
    if not profile:
        return json.dumps({"error": f"No profile for agent '{agent_id}'. Run github_discover_agents or add it with github_manage_agent."})
    if not profile.enabled:
        return json.dumps({"error": f"Agent '{agent_id}' is disabled. Enable it first with github_manage_agent(action='enable', agent_id='{agent_id}')."})

    task = DelegationTask(
        title=title,
        problem=problem,
        acceptance_criteria=list(acceptance_criteria),
        context=context,
        constraints=constraints,
        repo=repo,
    )
    issue_title, issue_body, post_create_actions = build_delegation_issue(task, profile)

    # Create the issue
    status, data = _github_request("POST", f"/repos/{repo}/issues", body={
        "title": issue_title,
        "body": issue_body,
    })
    if status != 201 or not isinstance(data, dict):
        return json.dumps({"ok": False, "error": f"HTTP {status}", "details": data})

    issue_number = data.get("number")
    issue_url = data.get("html_url")

    # Dispatch post-create actions (labels, assignments)
    actions_log = []
    if post_create_actions:
        actions_log = dispatch_post_create_actions(repo, issue_number, post_create_actions, token)

    inv_type, syntax, _ = profile.effective_invocation()
    return json.dumps({
        "ok": True,
        "issue_number": issue_number,
        "url": issue_url,
        "title": issue_title,
        "agent": profile.display_name(),
        "invocation_type": inv_type,
        "task_id": task.task_id,
        "post_create_actions": actions_log,
    }, indent=2)


GITHUB_DELEGATE_TASK_SCHEMA = {
    "name": "github_delegate_task",
    "description": (
        "Delegate a coding task to an external agent (Claude Code, Codex, Devin, etc.) "
        "by filing a structured GitHub issue with acceptance criteria. "
        "Automatically invokes the agent using the tenant's learned invocation pattern "
        "(mention, label, assignment, or workflow trigger). "
        "Requires the agent to be discovered (github_discover_agents) and enabled "
        "(github_manage_agent). Always confirm with the user before calling — "
        "this creates a visible GitHub issue."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "'owner/name' of the repo to file the issue in."},
            "agent_id": {"type": "string", "description": "Agent id to delegate to (e.g. 'claude-code'). Must be enabled."},
            "title": {"type": "string", "description": "Short goal statement — becomes the issue title (prefixed with '[Dash]')."},
            "problem": {"type": "string", "description": "One-paragraph problem statement."},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of verifiable acceptance criteria (each becomes a checkbox).",
            },
            "context": {"type": "string", "description": "Optional: relevant files, related issue URLs, links to docs."},
            "constraints": {"type": "string", "description": "Optional: style, performance, API-compat constraints."},
        },
        "required": ["repo", "agent_id", "title", "problem", "acceptance_criteria"],
    },
}

registry.register(
    name="github_delegate_task",
    toolset="pm-github",
    schema=GITHUB_DELEGATE_TASK_SCHEMA,
    handler=lambda args, **kw: github_delegate_task(
        repo=args.get("repo", ""),
        title=args.get("title", ""),
        problem=args.get("problem", ""),
        acceptance_criteria=args.get("acceptance_criteria") or [],
        agent_id=args.get("agent_id", ""),
        context=args.get("context", ""),
        constraints=args.get("constraints", ""),
    ),
)


# =============================================================================
# Tool: fleet_refile_delegation
# =============================================================================

def fleet_refile_delegation(repo: str, issue_number: int, agent_id: str = "", **kwargs) -> str:
    """Move a stalled Dash delegation to the next agent in the fallback chain.

    Closes the original issue, creates a new one with the same task content
    routed to the fallback agent (or `agent_id` if explicitly supplied).
    """
    import os
    from agent_fleet.supervisor import refile_delegation
    from agent_fleet.workflow import default_workflow, parse_workflow

    if "/" not in (repo or ""):
        return json.dumps({"error": "repo must be 'owner/name'"})
    try:
        issue_number_int = int(issue_number)
    except (TypeError, ValueError):
        return json.dumps({"error": "issue_number must be an integer"})

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token. The supervisor's token refresh should have set one."})

    # Resolve active workflow for this tenant if Postgres is on; else default.
    workflow = default_workflow()
    try:
        from backend.db.postgres_client import is_postgres_enabled
        from backend import repos as pg_repos
        from backend.tenant_context import get_current_tenant as _ctx
        if is_postgres_enabled():
            ctx = _ctx()
            tenant_id = ctx.tenant_id if ctx and ctx.tenant_id and ctx.tenant_id != "default" else None
            if tenant_id:
                active = pg_repos.get_active_workflow(tenant_id)
                if active:
                    try:
                        workflow = parse_workflow(active["body"])
                    except Exception:
                        pass
    except Exception:
        pass

    rf = refile_delegation(
        repo=repo, issue_number=issue_number_int, token=token,
        workflow=workflow, target_agent_id=(agent_id.strip() or None),
    )
    if not rf.ok:
        return json.dumps({"ok": False, "error": rf.error})
    return json.dumps({
        "ok": True,
        "new_issue_number": rf.new_issue_number,
        "new_issue_url": rf.new_issue_url,
        "new_agent_id": rf.new_agent_id,
        "closed_issue_number": issue_number_int,
    })


FLEET_REFILE_SCHEMA = {
    "name": "fleet_refile_delegation",
    "description": (
        "Refile a stalled Dash delegation issue to the next agent in the "
        "workflow's fallback chain. Closes the original issue and creates a "
        "new one with the same problem statement and acceptance criteria, "
        "routed to the next agent. Use this when a delegation has been "
        "flagged stalled and the user wants to escalate. Requires the user's "
        "approval — this creates a visible GitHub issue and closes another."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "'owner/name' of the repo."},
            "issue_number": {"type": "integer", "description": "Number of the stalled Dash issue to refile."},
            "agent_id": {
                "type": "string",
                "description": "Optional: target agent id to override the fallback chain (e.g. 'codex').",
            },
        },
        "required": ["repo", "issue_number"],
    },
}

registry.register(
    name="fleet_refile_delegation",
    toolset="pm-github",
    schema=FLEET_REFILE_SCHEMA,
    handler=lambda args, **kw: fleet_refile_delegation(
        repo=args.get("repo", ""),
        issue_number=args.get("issue_number", 0),
        agent_id=args.get("agent_id", ""),
    ),
)


# =============================================================================
# Tool: fleet_activity_summary
# =============================================================================

def fleet_activity_summary(since_ts: float = 0.0, **kwargs) -> str:
    """Return a compact summary of fleet delegation activity for the brief.

    `since_ts` defaults to 24h ago when zero/missing — the brief skill
    should pass the previous brief's created_at so the section reflects
    "what changed since last brief."
    """
    from backend.tenant_context import require_tenant_context
    from backend.db.postgres_client import is_postgres_enabled

    tenant = require_tenant_context(kwargs=kwargs, consumer="fleet_activity_summary")

    if not is_postgres_enabled():
        return json.dumps({
            "available": False,
            "reason": "Fleet inventory is only persisted in Postgres mode.",
        })

    from backend import repos as pg_repos
    try:
        ts_arg: Optional[float] = float(since_ts) if since_ts else None
    except (TypeError, ValueError):
        ts_arg = None
    if ts_arg is not None and ts_arg <= 0:
        ts_arg = None

    summary = pg_repos.fleet_activity_summary(tenant.tenant_id, since_ts=ts_arg)
    summary["available"] = True

    # Convenience flag so the brief skill can decide whether to render the section.
    has_activity = (
        summary["open_total"] > 0
        or summary["new_since"] > 0
        or summary["completions"]
        or summary["failures"]
        or summary["cancellations"]
    )
    summary["has_activity"] = bool(has_activity)
    return json.dumps(summary)


FLEET_ACTIVITY_SUMMARY_SCHEMA = {
    "name": "fleet_activity_summary",
    "description": (
        "Summary of Dash's fleet of delegated coding tasks: open work by state, "
        "what completed/failed/was cancelled since the last brief. Use this in "
        "the daily brief AFTER you have the previous brief's timestamp via "
        "brief_get_latest, then pass that timestamp as since_ts. If has_activity "
        "is false, omit the Fleet Activity section from the brief entirely."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "since_ts": {
                "type": "number",
                "description": (
                    "Unix timestamp cutoff. Pass the previous brief's "
                    "created_at to scope to 'since last brief'. Omit or pass 0 "
                    "for a 24-hour default."
                ),
            },
        },
    },
}

registry.register(
    name="fleet_activity_summary",
    toolset="pm-github",
    schema=FLEET_ACTIVITY_SUMMARY_SCHEMA,
    handler=lambda args, **kw: fleet_activity_summary(
        since_ts=args.get("since_ts", 0.0),
        **kw,
    ),
)


# =============================================================================
# Tool: github_find_dash_issues
# =============================================================================

def github_find_dash_issues(repo: str, state: str = "open", **kwargs) -> str:
    """List all open Dash-authored delegation issues in a repo."""
    import os
    from agent_fleet.delegation import find_dash_issues
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token."})
    issues = find_dash_issues(repo, token, state=state)
    return json.dumps({"repo": repo, "count": len(issues), "issues": issues}, indent=2)


GITHUB_FIND_DASH_ISSUES_SCHEMA = {
    "name": "github_find_dash_issues",
    "description": "Find all Dash-authored delegation issues in a repo. Use this to check delegation status, find stalled tasks, or before running the PR watcher.",
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "'owner/name'"},
            "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "Issue state filter (default: open)."},
        },
        "required": ["repo"],
    },
}

registry.register(
    name="github_find_dash_issues",
    toolset="pm-github",
    schema=GITHUB_FIND_DASH_ISSUES_SCHEMA,
    handler=lambda args, **kw: github_find_dash_issues(
        repo=args.get("repo", ""),
        state=args.get("state", "open"),
    ),
)


# =============================================================================
# Tool: github_watch_delegations
# =============================================================================

def github_watch_delegations(repos: list = None, **kwargs) -> str:
    """Check delegation status for all open Dash issues across repos and post reviews."""
    import os
    from agent_fleet.watcher import watch_repo_delegations

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token."})

    if not repos:
        status, data = _github_request("GET", "/installation/repositories?per_page=100")
        if status != 200:
            return json.dumps({"error": f"Could not list repos: HTTP {status}"})
        repos = [r["full_name"] for r in (data or {}).get("repositories", [])]

    all_results = []
    for repo in repos:
        results = watch_repo_delegations(repo, token)
        for r in results:
            all_results.append({
                "repo": repo,
                "issue_number": r.issue_number,
                "task_id": r.task_id,
                "agent_id": r.agent_id,
                "status": r.status,
                "pr_number": r.pr_number,
                "verdict": r.review.verdict if r.review else None,
                "summary": r.review.summary if r.review else None,
                "error": r.error,
            })

    return json.dumps({
        "repos_checked": repos,
        "tasks_found": len(all_results),
        "results": all_results,
    }, indent=2)


GITHUB_WATCH_DELEGATIONS_SCHEMA = {
    "name": "github_watch_delegations",
    "description": (
        "Check status of all active Dash delegation tasks across repos. "
        "For each delegation issue, finds the linked PR, evaluates acceptance criteria "
        "against the diff, posts a structured review comment, and updates checkboxes. "
        "Run this after filing delegation issues, or during the daily brief to surface "
        "approved/stalled/needs-human tasks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Repos to watch as 'owner/name'. Defaults to all installation repos.",
            },
        },
    },
}

registry.register(
    name="github_watch_delegations",
    toolset="pm-github",
    schema=GITHUB_WATCH_DELEGATIONS_SCHEMA,
    handler=lambda args, **kw: github_watch_delegations(
        repos=args.get("repos") or None,
    ),
)


# =============================================================================
# Tool: github_check_delegation_health
# =============================================================================

def github_check_delegation_health(repos: list = None, **kwargs) -> str:
    """Evaluate health of all open delegation tasks and surface stalled/escalation items."""
    import os, time
    from agent_fleet.escalation import evaluate_task_health, load_delegation_policy, HealthStatus
    from agent_fleet.watcher import watch_repo_delegations
    from workspace_context import load_workspace_context

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return json.dumps({"error": "No GitHub token."})

    if not repos:
        status, data = _github_request("GET", "/installation/repositories?per_page=100")
        if status != 200:
            return json.dumps({"error": f"Could not list repos: HTTP {status}"})
        repos = [r["full_name"] for r in (data or {}).get("repositories", [])]

    ws_id = (
        os.environ.get("KAI_WORKSPACE_ID")
        or os.environ.get("HERMES_WORKSPACE_ID")
        or "default"
    )
    ctx = load_workspace_context(workspace_id=ws_id)
    bp = ctx.get_blueprint()
    policy = load_delegation_policy((bp or {}).get("data"))

    verdicts = []
    action_items = []

    for repo in repos:
        watch_results = watch_repo_delegations(repo, token)
        for wr in watch_results:
            verdict = evaluate_task_health(
                task_status=wr.status,
                agent_id=wr.agent_id,
                issue_number=wr.issue_number,
                issue_url=f"https://github.com/{repo}/issues/{wr.issue_number}",
                task_title=f"Delegation #{wr.issue_number}",
                created_at="",
                last_activity_at=None,
                pr_number=wr.pr_number,
                pr_url=f"https://github.com/{repo}/pull/{wr.pr_number}" if wr.pr_number else None,
                review_verdict=(wr.review.verdict if wr.review else None),
                ping_count=0,
                policy=policy,
            )
            verdicts.append({
                "repo": repo,
                "issue_number": wr.issue_number,
                "status": verdict.status,
                "reason": verdict.reason,
                "action": verdict.recommended_action,
                "should_re_ping": verdict.should_re_ping,
                "should_escalate": verdict.should_escalate,
                "fallback_agent": verdict.fallback_agent_id,
            })
            if verdict.action_item:
                action_items.append(verdict.action_item)

    return json.dumps({
        "tasks_evaluated": len(verdicts),
        "verdicts": verdicts,
        "action_items_for_brief": action_items,
    }, indent=2)


GITHUB_CHECK_DELEGATION_HEALTH_SCHEMA = {
    "name": "github_check_delegation_health",
    "description": (
        "Evaluate the health of all active delegation tasks. Detects stalled tasks, "
        "agents that need re-pinging, and tasks requiring human intervention. "
        "Returns action items ready for inclusion in the daily brief. "
        "Run this during the brief pipeline or when checking delegation status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Repos to check. Defaults to all installation repos.",
            },
        },
    },
}

registry.register(
    name="github_check_delegation_health",
    toolset="pm-github",
    schema=GITHUB_CHECK_DELEGATION_HEALTH_SCHEMA,
    handler=lambda args, **kw: github_check_delegation_health(
        repos=args.get("repos") or None,
    ),
)
