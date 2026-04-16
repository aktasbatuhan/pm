"""
Established workspace scenario — Acme Corp, post-onboarding.

Same org as fresh_onboard but the workspace is already onboarded with
blueprint, learnings, threads, and pending work pre-populated. Use this
to test the returning-visit flow (agent should NOT trigger onboarding,
should query context selectively).
"""

import importlib.util
import uuid
from pathlib import Path

# Re-use the base Acme Corp data from fresh_onboard
_spec = importlib.util.spec_from_file_location(
    "fresh_onboard", str(Path(__file__).parent / "fresh_onboard.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_BASE_RESPONSES = _mod.RESPONSES

# ── Pre-populated workspace context ───────────────────────────────────

_ws_onboarding_status = "completed"
_ws_onboarding_phase = "complete"

_ws_blueprint = {
    "summary": (
        "Acme Corp — 12 repos across payment processing, user management, "
        "notifications, API gateway, web app, and infrastructure. "
        "Tech stack: Node.js (Express/Fastify), Python (FastAPI), React, PostgreSQL, Redis. "
        "5 repos connected to Kai. Key risk: payment-service has critical JWT vulnerability "
        "(CVE-2022-23529) and lodash prototype pollution. user-service has inconsistent "
        "error handling patterns (3 different approaches from different AI tools). "
        "notification-service clean but unscanned. 487 credits remaining on pro plan."
    ),
    "data": {
        "repos": 12,
        "connected": 5,
        "languages": ["javascript", "typescript", "python"],
        "frameworks": ["express", "fastify", "fastapi", "react"],
        "criticalVulns": 1,
        "highVulns": 2,
    },
    "updatedAt": "2026-03-29T18:00:00Z",
    "updatedBy": "agent",
}

_ws_learnings = [
    {
        "id": 1,
        "category": "security",
        "content": "payment-service uses jsonwebtoken@8.5.1 which has CVE-2022-23529 (critical). JWTs validated in auth middleware — affects all authenticated endpoints.",
        "sourceThread": "onboarding",
        "createdAt": "2026-03-29T18:00:00Z",
    },
    {
        "id": 2,
        "category": "security",
        "content": "lodash@4.17.20 in payment-service has prototype pollution (CVE-2021-23337). Used in deep merge for config loading.",
        "sourceThread": "onboarding",
        "createdAt": "2026-03-29T18:00:00Z",
    },
    {
        "id": 3,
        "category": "architecture",
        "content": "user-service has 3 different error handling patterns: try/catch with custom errors, express-async-errors middleware, and manual next(err). Evidence of multiple AI tools writing code without coordination.",
        "sourceThread": "onboarding",
        "createdAt": "2026-03-29T18:00:00Z",
    },
    {
        "id": 4,
        "category": "architecture",
        "content": "notification-service is cleanest codebase. No vulnerabilities found in manual review. Has never been scanned by Kai.",
        "sourceThread": "onboarding",
        "createdAt": "2026-03-29T18:00:00Z",
    },
    {
        "id": 5,
        "category": "dependency",
        "content": "axios@0.21.1 in payment-service has SSRF vulnerability (CVE-2021-3749). Used for payment gateway callbacks.",
        "sourceThread": "onboarding",
        "createdAt": "2026-03-29T18:00:00Z",
    },
]

_ws_threads = [
    {
        "threadId": "onboarding",
        "platform": "web",
        "summary": "Initial onboarding: discovered 12 repos, connected 5, found 1 critical + 2 high vulns in payment-service",
        "userId": None,
        "lastActive": "2026-03-29T18:00:00Z",
    },
    {
        "threadId": "cron:daily_20260330",
        "platform": "cron",
        "summary": "Daily cycle: re-scanned payment-service, verified CVE-2022-23529 still present, proposed upgrade plan",
        "userId": None,
        "lastActive": "2026-03-30T06:00:00Z",
    },
]

_ws_pending_work = {
    "fix_jwt_vuln": {
        "workId": "fix_jwt_vuln",
        "type": "security_fix",
        "status": "approved",
        "description": "Upgrade jsonwebtoken to >=9.0.0 in payment-service to fix CVE-2022-23529",
        "linkedThread": "onboarding",
        "updatedAt": "2026-03-29T18:30:00Z",
    },
    "unify_error_handling": {
        "workId": "unify_error_handling",
        "type": "cleanup",
        "status": "pending",
        "description": "Unify error handling in user-service to use express-async-errors pattern consistently",
        "linkedThread": "onboarding",
        "updatedAt": "2026-03-29T18:30:00Z",
    },
    "scan_notification_svc": {
        "workId": "scan_notification_svc",
        "type": "security_scan",
        "status": "pending",
        "description": "Run first security scan on notification-service",
        "linkedThread": "onboarding",
        "updatedAt": "2026-03-29T18:30:00Z",
    },
}


# ── Workspace context handlers (stateful) ──────────────────────────────

def _workspace_status(**kwargs):
    return {
        "onboardingStatus": _ws_onboarding_status,
        "onboardingPhase": _ws_onboarding_phase,
        "blueprintUpdatedAt": _ws_blueprint["updatedAt"] if _ws_blueprint else None,
        "learningsCount": len(_ws_learnings),
        "threadsCount": len(_ws_threads),
        "pendingWorkCount": len([w for w in _ws_pending_work.values()
                                  if w.get("status") in ("pending", "in_progress", "approved", "blocked")]),
    }


def _workspace_status_update(**kwargs):
    global _ws_onboarding_status, _ws_onboarding_phase
    _ws_onboarding_status = kwargs.get("onboardingStatus", _ws_onboarding_status)
    _ws_onboarding_phase = kwargs.get("onboardingPhase", _ws_onboarding_phase)
    return {"ok": True, "onboardingStatus": _ws_onboarding_status}


def _workspace_blueprint_get(**kwargs):
    return _ws_blueprint or {"blueprint": None}


def _workspace_blueprint_update(**kwargs):
    global _ws_blueprint
    import time as _time
    _ws_blueprint = {
        "summary": kwargs.get("summary", ""),
        "data": kwargs.get("data", {}),
        "updatedAt": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updatedBy": "agent",
    }
    return _ws_blueprint


def _workspace_learnings_list(**kwargs):
    category = kwargs.get("category")
    limit = int(kwargs.get("limit", 30))
    filtered = [l for l in _ws_learnings if not category or l["category"] == category]
    return {"learnings": filtered[:limit], "total": len(filtered)}


def _workspace_learnings_add(**kwargs):
    import time as _time
    entry = {
        "id": len(_ws_learnings) + 1,
        "category": kwargs.get("category", "general"),
        "content": kwargs.get("content", ""),
        "sourceThread": kwargs.get("sourceThread"),
        "createdAt": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _ws_learnings.append(entry)
    return entry


def _workspace_threads_list(**kwargs):
    platform = kwargs.get("platform")
    limit = int(kwargs.get("limit", 10))
    filtered = [t for t in _ws_threads if not platform or t["platform"] == platform]
    return {"threads": filtered[:limit], "total": len(filtered)}


def _workspace_threads_update(**kwargs):
    import time as _time
    thread_id = kwargs.get("threadId", "")
    entry = {
        "threadId": thread_id,
        "platform": kwargs.get("platform", "unknown"),
        "summary": kwargs.get("summary", ""),
        "userId": kwargs.get("userId"),
        "lastActive": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for i, t in enumerate(_ws_threads):
        if t["threadId"] == thread_id:
            _ws_threads[i] = entry
            return entry
    _ws_threads.append(entry)
    return entry


def _workspace_pending_work_list(**kwargs):
    status_filter = kwargs.get("status", "")
    limit = int(kwargs.get("limit", 20))
    items = list(_ws_pending_work.values())
    if status_filter:
        statuses = set(s.strip() for s in status_filter.split(","))
        items = [w for w in items if w.get("status") in statuses]
    return {"items": items[:limit], "total": len(items)}


def _workspace_pending_work_upsert(**kwargs):
    import time as _time
    work_id = kwargs.get("workId", f"work_{uuid.uuid4().hex[:6]}")
    entry = {
        "workId": work_id,
        "type": kwargs.get("type", "general"),
        "status": kwargs.get("status", "pending"),
        "description": kwargs.get("description", ""),
        "linkedThread": kwargs.get("linkedThread"),
        "updatedAt": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _ws_pending_work[work_id] = entry
    return entry


# ── Override workspace context tools in base responses ─────────────────

RESPONSES = dict(_BASE_RESPONSES)
RESPONSES.update({
    "workspace_status": _workspace_status,
    "workspace_status_update": _workspace_status_update,
    "workspace_blueprint_get": _workspace_blueprint_get,
    "workspace_blueprint_update": _workspace_blueprint_update,
    "workspace_learnings_list": _workspace_learnings_list,
    "workspace_learnings_add": _workspace_learnings_add,
    "workspace_threads_list": _workspace_threads_list,
    "workspace_threads_update": _workspace_threads_update,
    "workspace_pending_work_list": _workspace_pending_work_list,
    "workspace_pending_work_upsert": _workspace_pending_work_upsert,
})
