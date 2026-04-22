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
