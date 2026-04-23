"""External agent discovery — GitHub issue #11.

Four complementary methods to populate per-tenant AgentProfiles:

  B. Activity fingerprint  — PR/comment/signature scan, 90d lookback (always runs)
  C. Org installations     — GET /orgs/{org}/installations (gated, graceful no-op)
  D. Workflow scan         — .github/workflows/*.yml parsing (always runs)

Method A (manual override) is handled via the `github_manage_agent` tool in
pm_github_tools.py — it writes directly to the blueprint.

The public entry point is `discover_external_agents(repos, token)`.  It does
NOT write to the blueprint; the calling tool does that so it can present
results to the user before saving.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple

from agent_fleet.registry import (
    KnownAgent,
    find_by_bot_username,
    find_by_workflow_action,
    find_by_app_slug,
    list_known,
)
from agent_fleet.profile import (
    AgentProfile,
    DetectionMethod,
    ObservedInvocation,
    ObservedInvocationDetail,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tiny GitHub REST client (no deps beyond stdlib)
# ---------------------------------------------------------------------------

def _gh(method: str, path: str, token: str, body: dict = None, timeout: int = 20):
    """Make one GitHub API call.  Returns (status_code, parsed_body_or_None)."""
    url = "https://api.github.com" + (path if path.startswith("/") else "/" + path)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Dash-PM-Discovery",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode("utf-8")
            return e.code, (json.loads(body_text) if body_text else None)
        except Exception:
            return e.code, None
    except Exception as exc:
        logger.debug("GitHub request failed: %s %s — %s", method, path, exc)
        return 0, None


def _gh_paginate(path_template: str, token: str, max_pages: int = 5) -> List[dict]:
    """Collect up to max_pages of a paginated GitHub list endpoint."""
    results: List[dict] = []
    sep = "&" if "?" in path_template else "?"
    for page in range(1, max_pages + 1):
        status, data = _gh("GET", f"{path_template}{sep}per_page=100&page={page}", token)
        if status != 200 or not data:
            break
        items = data if isinstance(data, list) else data.get("items") or data.get("repositories") or []
        results.extend(items)
        if len(items) < 100:
            break
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _since_iso(days: int = 90) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _org_from_repo(repo: str) -> Optional[str]:
    parts = repo.split("/")
    return parts[0] if len(parts) == 2 else None


# ---------------------------------------------------------------------------
# Hit accumulator
# ---------------------------------------------------------------------------

class _Hits:
    """Accumulate detection signals per agent id before merging into profiles."""

    def __init__(self) -> None:
        self._methods: Dict[str, Set[DetectionMethod]] = {}
        self._activity: Dict[str, Dict[str, int]] = {}   # id -> {"prs", "comments", ...}
        self._repos: Dict[str, Set[str]] = {}
        self._first_seen: Dict[str, str] = {}
        self._last_active: Dict[str, str] = {}
        self._invocation_counts: Dict[str, Dict[str, int]] = {}  # id -> {type: count}

    def hit(
        self,
        agent_id: str,
        method: DetectionMethod,
        repo: str = None,
        ts: str = None,
        activity_key: str = None,
        invocation_type: str = None,
    ) -> None:
        self._methods.setdefault(agent_id, set()).add(method)
        if repo:
            self._repos.setdefault(agent_id, set()).add(repo)
        if ts:
            fs = self._first_seen.get(agent_id)
            if fs is None or ts < fs:
                self._first_seen[agent_id] = ts
            la = self._last_active.get(agent_id)
            if la is None or ts > la:
                self._last_active[agent_id] = ts
        if activity_key:
            self._activity.setdefault(agent_id, {})
            self._activity[agent_id][activity_key] = self._activity[agent_id].get(activity_key, 0) + 1
        if invocation_type:
            self._invocation_counts.setdefault(agent_id, {})
            self._invocation_counts[agent_id][invocation_type] = (
                self._invocation_counts[agent_id].get(invocation_type, 0) + 1
            )

    def agent_ids(self) -> Set[str]:
        return set(self._methods.keys())

    def methods_for(self, agent_id: str) -> Set[DetectionMethod]:
        return self._methods.get(agent_id, set())

    def to_profile(self, agent_id: str) -> AgentProfile:
        methods = sorted(self.methods_for(agent_id))
        activity = self._activity.get(agent_id, {})
        repos = sorted(self._repos.get(agent_id, set()))
        first_seen = self._first_seen.get(agent_id)
        last_active = self._last_active.get(agent_id)

        # Confidence: high if 2+ distinct methods (B counts as one even from multiple signals)
        method_categories = set()
        for m in methods:
            if m.startswith("fingerprint_"):
                method_categories.add("fingerprint")
            elif m == "org_installations":
                method_categories.add("installations")
            elif m == "workflow_scan":
                method_categories.add("workflow")
        if len(method_categories) >= 2:
            confidence = "high"
        elif "fingerprint" in method_categories or "workflow" in method_categories:
            confidence = "medium"
        else:
            confidence = "low"

        # Build observed_invocation from accumulated counts
        inv_counts = self._invocation_counts.get(agent_id, {})
        observed = _build_observed_invocation(inv_counts)

        return AgentProfile(
            id=agent_id,
            enabled=False,   # always starts disabled — user confirms
            detected_via=methods,
            first_seen=first_seen,
            last_active=last_active,
            activity_90d=activity,
            primary_repos=repos,
            observed_invocation=observed,
            confidence=confidence,
        )


def _build_observed_invocation(counts: Dict[str, int]) -> ObservedInvocation:
    if not counts:
        return ObservedInvocation()
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    slots = [None, None, None]
    for i, (inv_type, count) in enumerate(sorted_items[:3]):
        slots[i] = ObservedInvocationDetail(type=inv_type, count=count)
    return ObservedInvocation(primary=slots[0], secondary=slots[1], rare=slots[2])


# ---------------------------------------------------------------------------
# Method B — Activity fingerprint
# ---------------------------------------------------------------------------

def _method_b(repos: List[str], token: str, hits: _Hits, lookback_days: int = 90) -> None:
    since = _since_iso(lookback_days)
    known = list_known()

    for repo in repos:
        # B1: recent PRs — check user.login against bot_usernames + body for output_signatures
        prs = _gh_paginate(f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc", token, max_pages=3)
        for pr in prs:
            updated = pr.get("updated_at", "")
            if updated and updated < since:
                continue
            user = (pr.get("user") or {})
            login = (user.get("login") or "").lower()
            body = pr.get("body") or ""
            created_at = pr.get("created_at") or ""

            # match by bot username
            agent = find_by_bot_username(login)
            if agent:
                hits.hit(agent.id, "fingerprint_pr_author", repo=repo, ts=created_at, activity_key="prs")

            # match by output signature in PR body
            for a in known:
                for sig in a.output_signatures:
                    if sig.lower() in body.lower():
                        hits.hit(a.id, "fingerprint_signature", repo=repo, ts=created_at, activity_key="prs")
                        break

        # B2: recent issue comments
        comments = _gh_paginate(f"/repos/{repo}/issues/comments?since={since}", token, max_pages=2)
        for c in comments:
            user = (c.get("user") or {})
            login = (user.get("login") or "").lower()
            body = c.get("body") or ""
            created_at = c.get("created_at") or ""

            agent = find_by_bot_username(login)
            if agent:
                hits.hit(agent.id, "fingerprint_comment", repo=repo, ts=created_at, activity_key="comments")

            # check for @mention invocations in comments (so we learn invocation patterns)
            for a in known:
                for inv in a.documented_invocations:
                    if inv.type == "comment_mention" and inv.syntax:
                        if inv.syntax.lower() in body.lower():
                            hits.hit(a.id, "fingerprint_comment", repo=repo, ts=created_at,
                                     invocation_type="comment_mention")

        # B3: commits — check author email/name patterns
        commits = _gh_paginate(f"/repos/{repo}/commits?since={since}", token, max_pages=2)
        for c in commits:
            commit_data = c.get("commit") or {}
            author_name = (commit_data.get("author") or {}).get("name", "").lower()
            commit_ts = (commit_data.get("author") or {}).get("date", "")
            for a in known:
                for bot in a.bot_usernames:
                    clean = bot.replace("[bot]", "").lower()
                    if clean and clean in author_name:
                        hits.hit(a.id, "fingerprint_commit", repo=repo, ts=commit_ts, activity_key="commits")
                        break

    logger.debug("Method B complete. Hits: %s", {aid: sorted(hits.methods_for(aid)) for aid in hits.agent_ids()})


# ---------------------------------------------------------------------------
# Method C — Org installations
# ---------------------------------------------------------------------------

def _method_c(repos: List[str], token: str, hits: _Hits) -> None:
    orgs: Set[str] = set()
    for r in repos:
        org = _org_from_repo(r)
        if org:
            orgs.add(org)

    for org in orgs:
        status, data = _gh("GET", f"/orgs/{org}/installations?per_page=100", token)
        if status == 403 or status == 404:
            logger.debug("Method C: org %s returned %s (no admin:read or not an org) — skipping", org, status)
            continue
        if status != 200 or not isinstance(data, dict):
            logger.debug("Method C: unexpected %s for org %s", status, org)
            continue

        for inst in (data.get("installations") or []):
            app = inst.get("app_slug") or ""
            updated_at = inst.get("updated_at") or ""
            agent = find_by_app_slug(app)
            if agent:
                hits.hit(agent.id, "org_installations", ts=updated_at)

    logger.debug("Method C complete.")


# ---------------------------------------------------------------------------
# Method D — Workflow scan
# ---------------------------------------------------------------------------

def _method_d(repos: List[str], token: str, hits: _Hits) -> None:
    for repo in repos:
        status, listing = _gh("GET", f"/repos/{repo}/contents/.github/workflows", token)
        if status != 200 or not isinstance(listing, list):
            continue

        for entry in listing:
            name = entry.get("name", "")
            if not name.endswith((".yml", ".yaml")):
                continue

            url_path = entry.get("url", "")
            if not url_path:
                continue

            # Strip base URL to get path
            path = url_path.replace("https://api.github.com", "") if "api.github.com" in url_path else url_path
            s2, file_data = _gh("GET", path, token)
            if s2 != 200 or not isinstance(file_data, dict):
                continue

            raw = file_data.get("content", "")
            try:
                content = base64.b64decode(raw.replace("\n", "")).decode("utf-8", errors="replace")
            except Exception:
                continue

            # Grep for uses: lines (both bare "uses:" and YAML list "- uses:")
            for line in content.splitlines():
                stripped = line.strip().lstrip("- ").strip()
                if not stripped.startswith("uses:"):
                    continue
                action_ref = stripped[len("uses:"):].strip().strip('"').strip("'")
                agent = find_by_workflow_action(action_ref)
                if agent:
                    hits.hit(agent.id, "workflow_scan", repo=repo)

    logger.debug("Method D complete.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

DiscoveryResult = List[AgentProfile]


def discover_external_agents(
    repos: List[str],
    token: str,
    lookback_days: int = 90,
    skip_installations: bool = False,
) -> DiscoveryResult:
    """Run discovery methods B, C, D and return merged AgentProfiles.

    Results always start with `enabled=False` — the caller must ask the
    tenant before flipping to True (first-time discovery flow).

    Args:
        repos: list of "owner/repo" strings the token can read
        token: GitHub installation/PAT token
        lookback_days: how far back method B scans (default 90)
        skip_installations: set True to skip method C (no admin:read)

    Returns:
        List of AgentProfile, one per detected agent, merged across methods.
    """
    if not token:
        logger.warning("discover_external_agents: no token provided, returning empty")
        return []

    hits = _Hits()

    start = time.monotonic()
    _method_b(repos, token, hits, lookback_days)
    logger.debug("Method B took %.1fs", time.monotonic() - start)

    if not skip_installations:
        t = time.monotonic()
        _method_c(repos, token, hits)
        logger.debug("Method C took %.1fs", time.monotonic() - t)

    t = time.monotonic()
    _method_d(repos, token, hits)
    logger.debug("Method D took %.1fs", time.monotonic() - t)

    profiles = [hits.to_profile(aid) for aid in sorted(hits.agent_ids())]
    logger.info(
        "Discovery complete in %.1fs — found %d agent(s): %s",
        time.monotonic() - start,
        len(profiles),
        [p.id for p in profiles],
    )
    return profiles


def merge_with_existing(
    discovered: List[AgentProfile],
    existing: List[AgentProfile],
) -> Tuple[List[AgentProfile], List[str], List[str]]:
    """Merge newly discovered profiles into existing ones.

    - Preserves `enabled` and `display_name_override` from existing profiles.
    - Updates activity, repos, invocation, confidence, detected_via.
    - Returns (merged_list, new_agent_ids, updated_agent_ids).
    """
    existing_by_id = {p.id: p for p in existing}
    new_ids: List[str] = []
    updated_ids: List[str] = []
    result: List[AgentProfile] = []

    for disc in discovered:
        if disc.id in existing_by_id:
            old = existing_by_id[disc.id]
            # Preserve tenant-controlled fields
            disc.enabled = old.enabled
            disc.display_name_override = old.display_name_override
            disc.notes = old.notes
            updated_ids.append(disc.id)
        else:
            new_ids.append(disc.id)
        result.append(disc)

    # Keep existing profiles that weren't rediscovered (they may have been manually added)
    discovered_ids = {p.id for p in discovered}
    for p in existing:
        if p.id not in discovered_ids:
            result.append(p)

    return result, new_ids, updated_ids
