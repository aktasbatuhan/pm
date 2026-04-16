"""GitHub Jobs — fetch open PRs, review requests, and issues for the authenticated user.

Used by the /jobs slash command (CLI + gateway) to show a quick dashboard
of current work items from GitHub.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
TIMEOUT = 15


def _get_auth():
    """Lazy-import GitHubAuth to avoid circular imports."""
    from tools.skills_hub import GitHubAuth
    return GitHubAuth()


def _get(endpoint: str, headers: Dict[str, str], params: Optional[Dict[str, str]] = None) -> Any:
    """Make a GET request to the GitHub API."""
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(f"{API_BASE}{endpoint}", headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _get_username(headers: Dict[str, str]) -> Optional[str]:
    """Get the authenticated user's login name."""
    try:
        data = _get("/user", headers)
        return data.get("login")
    except Exception as e:
        logger.debug("Failed to get GitHub username: %s", e)
        return None


def _search_issues(query: str, headers: Dict[str, str], max_results: int = 25) -> List[Dict[str, Any]]:
    """Run a GitHub issue/PR search query and return items."""
    try:
        data = _get("/search/issues", headers, params={"q": query, "per_page": str(max_results), "sort": "updated"})
        return data.get("items", [])
    except Exception as e:
        logger.debug("GitHub search failed for query '%s': %s", query, e)
        return []


# ---------------------------------------------------------------------------
# Public fetch functions
# ---------------------------------------------------------------------------

def fetch_my_prs(repo: Optional[str] = None, max_results: int = 25) -> List[Dict[str, Any]]:
    """Fetch open PRs authored by the authenticated user."""
    auth = _get_auth()
    headers = auth.get_headers()
    username = _get_username(headers)
    if not username:
        return []

    q = f"is:pr is:open author:{username}"
    if repo:
        q += f" repo:{repo}"

    items = _search_issues(q, headers, max_results)
    return [
        {
            "title": item["title"],
            "number": item["number"],
            "url": item["html_url"],
            "repo": item["repository_url"].split("/repos/")[-1],
            "draft": item.get("draft", False),
            "updated_at": item["updated_at"][:10],
            "labels": [l["name"] for l in item.get("labels", [])],
        }
        for item in items
    ]


def fetch_review_requests(repo: Optional[str] = None, max_results: int = 25) -> List[Dict[str, Any]]:
    """Fetch open PRs where the authenticated user's review is requested."""
    auth = _get_auth()
    headers = auth.get_headers()
    username = _get_username(headers)
    if not username:
        return []

    q = f"is:pr is:open review-requested:{username}"
    if repo:
        q += f" repo:{repo}"

    items = _search_issues(q, headers, max_results)
    return [
        {
            "title": item["title"],
            "number": item["number"],
            "url": item["html_url"],
            "repo": item["repository_url"].split("/repos/")[-1],
            "author": item["user"]["login"],
            "updated_at": item["updated_at"][:10],
        }
        for item in items
    ]


def fetch_my_issues(repo: Optional[str] = None, max_results: int = 25) -> List[Dict[str, Any]]:
    """Fetch open issues assigned to the authenticated user."""
    auth = _get_auth()
    headers = auth.get_headers()
    username = _get_username(headers)
    if not username:
        return []

    q = f"is:issue is:open assignee:{username}"
    if repo:
        q += f" repo:{repo}"

    items = _search_issues(q, headers, max_results)
    return [
        {
            "title": item["title"],
            "number": item["number"],
            "url": item["html_url"],
            "repo": item["repository_url"].split("/repos/")[-1],
            "updated_at": item["updated_at"][:10],
            "labels": [l["name"] for l in item.get("labels", [])],
        }
        for item in items
    ]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_pr_line(pr: Dict[str, Any]) -> str:
    draft = " (draft)" if pr.get("draft") else ""
    labels = f'  [{", ".join(pr["labels"])}]' if pr.get("labels") else ""
    return f"  #{pr['number']}  {pr['title']}{draft}{labels}\n       {pr['repo']}  {pr['updated_at']}\n       {pr['url']}"


def _format_review_line(pr: Dict[str, Any]) -> str:
    return f"  #{pr['number']}  {pr['title']}  (by @{pr['author']})\n       {pr['repo']}  {pr['updated_at']}\n       {pr['url']}"


def _format_issue_line(issue: Dict[str, Any]) -> str:
    labels = f'  [{", ".join(issue["labels"])}]' if issue.get("labels") else ""
    return f"  #{issue['number']}  {issue['title']}{labels}\n       {issue['repo']}  {issue['updated_at']}\n       {issue['url']}"


def format_jobs_summary(
    prs: List[Dict[str, Any]],
    reviews: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
    repo_filter: Optional[str] = None,
) -> str:
    """Format all job data into a readable summary string."""
    parts = []
    header = "GitHub Jobs"
    if repo_filter:
        header += f" ({repo_filter})"
    parts.append(header)
    parts.append("=" * len(header))

    # My PRs
    parts.append(f"\nOpen PRs ({len(prs)})")
    parts.append("-" * 20)
    if prs:
        for pr in prs:
            parts.append(_format_pr_line(pr))
    else:
        parts.append("  No open PRs")

    # Review requests
    parts.append(f"\nReview Requests ({len(reviews)})")
    parts.append("-" * 20)
    if reviews:
        for r in reviews:
            parts.append(_format_review_line(r))
    else:
        parts.append("  No pending reviews")

    # Issues
    parts.append(f"\nAssigned Issues ({len(issues)})")
    parts.append("-" * 20)
    if issues:
        for issue in issues:
            parts.append(_format_issue_line(issue))
    else:
        parts.append("  No assigned issues")

    return "\n".join(parts)


def check_auth_status() -> str:
    """Return a human-readable string about GitHub auth status."""
    auth = _get_auth()
    method = auth.auth_method()
    if method == "anonymous":
        return (
            "Not authenticated with GitHub.\n"
            "Options:\n"
            "  1. Run: gh auth login  (if you have GitHub CLI)\n"
            "  2. Set GITHUB_TOKEN in your .env file\n"
            "     Get a token at: https://github.com/settings/tokens"
        )
    username = _get_username(auth.get_headers())
    return f"Authenticated as @{username} (via {method})"


def run_jobs_command(args: str = "") -> str:
    """Main entry point for the /jobs command. Returns formatted output string.

    Subcommands:
        (empty)         — full summary (PRs + reviews + issues)
        prs             — only open PRs
        reviews         — only review requests
        issues          — only assigned issues
        auth            — show auth status
        <owner/repo>    — scope to a specific repo
    """
    parts = args.strip().split(maxsplit=1)
    subcommand = parts[0].lower() if parts else ""
    repo_filter = None

    # Help and auth don't require authentication
    if subcommand in ("help", "?"):
        return (
            "Usage: /jobs [subcommand] [owner/repo]\n\n"
            "Subcommands:\n"
            "  (none)       Show full summary (PRs + reviews + issues)\n"
            "  prs          List your open pull requests\n"
            "  reviews      List PRs awaiting your review\n"
            "  issues       List issues assigned to you\n"
            "  auth         Show GitHub authentication status\n"
            "  help         Show this help\n\n"
            "Examples:\n"
            "  /jobs\n"
            "  /jobs prs\n"
            "  /jobs collinear-ai/kai-agent\n"
            "  /jobs issues collinear-ai/kai-agent"
        )

    if subcommand == "auth":
        return check_auth_status()

    auth = _get_auth()
    if not auth.is_authenticated():
        return check_auth_status()

    # Detect owner/repo pattern
    if "/" in subcommand and subcommand not in ("",):
        repo_filter = subcommand
        subcommand = parts[1].lower() if len(parts) > 1 else ""

    # If second arg looks like a repo
    if len(parts) > 1 and "/" in parts[1] and subcommand in ("prs", "reviews", "issues"):
        repo_filter = parts[1]

    if subcommand == "prs":
        prs = fetch_my_prs(repo=repo_filter)
        lines = [f"Open PRs ({len(prs)})", "-" * 20]
        lines.extend(_format_pr_line(pr) for pr in prs) if prs else lines.append("  No open PRs")
        return "\n".join(lines)

    if subcommand == "reviews":
        reviews = fetch_review_requests(repo=repo_filter)
        lines = [f"Review Requests ({len(reviews)})", "-" * 20]
        lines.extend(_format_review_line(r) for r in reviews) if reviews else lines.append("  No pending reviews")
        return "\n".join(lines)

    if subcommand == "issues":
        issues = fetch_my_issues(repo=repo_filter)
        lines = [f"Assigned Issues ({len(issues)})", "-" * 20]
        lines.extend(_format_issue_line(i) for i in issues) if issues else lines.append("  No assigned issues")
        return "\n".join(lines)

    # Default: full summary
    prs = fetch_my_prs(repo=repo_filter)
    reviews = fetch_review_requests(repo=repo_filter)
    issues = fetch_my_issues(repo=repo_filter)
    return format_jobs_summary(prs, reviews, issues, repo_filter)
