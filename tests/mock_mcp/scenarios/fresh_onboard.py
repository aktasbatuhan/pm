"""
Scenario: Fresh Onboarding — "Acme Corp"

A realistic SaaS company with 3 core services, some interesting problems:
- payment-service has a critical JWT confusion vulnerability in jsonwebtoken
- user-service has 47 changes in 30 days to auth/session.ts (hot file)
- notification-service is clean but hasn't been scanned
- 3 different error handling patterns across services (AI tool drift)
- lodash prototype pollution is reachable
- An exposed API key in git history (already rotated, but still in commits)

This scenario is designed to give the agent interesting things to find
during onboarding so we can test the full Phase 1→3 flow.
"""

import time
import uuid

WS_ID = "ws_acme_001"
USER_ID = "user_001"

# ── Workspace & repos ──────────────────────────────────────────────────

_WORKSPACES = [
    {
        "_id": WS_ID,
        "name": "Acme Corp",
        "createdBy": USER_ID,
        "isPersonal": False,
    }
]

_WORKSPACE_DETAILS = {
    "_id": WS_ID,
    "name": "Acme Corp",
    "createdBy": USER_ID,
    "memberCount": 8,
    "integrations": {
        "github": {"installationId": 12345, "status": "active"},
        "jira": None,
        "linear": {"teamId": "acme-eng", "status": "active"},
    },
    "createdAt": "2025-09-15T10:00:00Z",
}

_GITHUB_ALL_REPOS = [
    {"owner": "acme-corp", "name": "payment-service", "defaultBranch": "main", "description": "Payment processing microservice (Stripe, invoicing)", "private": True},
    {"owner": "acme-corp", "name": "user-service", "defaultBranch": "main", "description": "Auth, sessions, user management", "private": True},
    {"owner": "acme-corp", "name": "notification-service", "defaultBranch": "main", "description": "Email, SMS, push notifications via SNS", "private": True},
    {"owner": "acme-corp", "name": "api-gateway", "defaultBranch": "main", "description": "Kong-based API gateway config", "private": True},
    {"owner": "acme-corp", "name": "web-app", "defaultBranch": "main", "description": "Next.js 14 frontend", "private": True},
    {"owner": "acme-corp", "name": "mobile-app", "defaultBranch": "develop", "description": "React Native mobile client", "private": True},
    {"owner": "acme-corp", "name": "infra", "defaultBranch": "main", "description": "Terraform + Pulumi IaC", "private": True},
    {"owner": "acme-corp", "name": "docs", "defaultBranch": "main", "description": "Internal documentation (Docusaurus)", "private": False},
    {"owner": "acme-corp", "name": "sdk-python", "defaultBranch": "main", "description": "Python SDK for Acme API", "private": False},
    {"owner": "acme-corp", "name": "sdk-node", "defaultBranch": "main", "description": "Node.js SDK for Acme API", "private": False},
    {"owner": "acme-corp", "name": "data-pipeline", "defaultBranch": "main", "description": "Airflow DAGs for analytics", "private": True},
    {"owner": "acme-corp", "name": "ml-models", "defaultBranch": "main", "description": "Fraud detection + recommendation models", "private": True},
]

# Only 3 repos connected to workspace so far
_WORKSPACE_REPOS = [
    {
        "_id": "repo_payment",
        "workspaceId": WS_ID,
        "name": "payment-service",
        "kind": "github",
        "addedBy": USER_ID,
        "source": {"owner": "acme-corp", "repo": "payment-service", "branch": "main"},
    },
    {
        "_id": "repo_user",
        "workspaceId": WS_ID,
        "name": "user-service",
        "kind": "github",
        "addedBy": USER_ID,
        "source": {"owner": "acme-corp", "repo": "user-service", "branch": "main"},
    },
    {
        "_id": "repo_notif",
        "workspaceId": WS_ID,
        "name": "notification-service",
        "kind": "github",
        "addedBy": USER_ID,
        "source": {"owner": "acme-corp", "repo": "notification-service", "branch": "main"},
    },
]

# ── File trees ─────────────────────────────────────────────────────────

_FILE_TREES = {
    "repo_payment": {
        "tree": [
            {"path": "src/", "type": "dir"},
            {"path": "src/index.ts", "type": "file", "size": 1200},
            {"path": "src/routes/", "type": "dir"},
            {"path": "src/routes/checkout.ts", "type": "file", "size": 3400},
            {"path": "src/routes/webhook.ts", "type": "file", "size": 2800},
            {"path": "src/routes/invoice.ts", "type": "file", "size": 4200},
            {"path": "src/routes/refund.ts", "type": "file", "size": 1900},
            {"path": "src/lib/", "type": "dir"},
            {"path": "src/lib/stripe.ts", "type": "file", "size": 5600},
            {"path": "src/lib/auth.ts", "type": "file", "size": 2100},
            {"path": "src/lib/db.ts", "type": "file", "size": 1800},
            {"path": "src/middleware/", "type": "dir"},
            {"path": "src/middleware/verify-jwt.ts", "type": "file", "size": 980},
            {"path": "src/middleware/rate-limit.ts", "type": "file", "size": 650},
            {"path": "src/models/", "type": "dir"},
            {"path": "src/models/order.ts", "type": "file", "size": 3200},
            {"path": "src/models/invoice.ts", "type": "file", "size": 2400},
            {"path": "src/models/customer.ts", "type": "file", "size": 1600},
            {"path": "tests/", "type": "dir"},
            {"path": "tests/checkout.test.ts", "type": "file", "size": 4800},
            {"path": "tests/webhook.test.ts", "type": "file", "size": 2200},
            {"path": "package.json", "type": "file", "size": 1400},
            {"path": "Dockerfile", "type": "file", "size": 450},
            {"path": "tsconfig.json", "type": "file", "size": 380},
            {"path": ".env.example", "type": "file", "size": 320},
        ],
        "stats": {"totalFiles": 22, "totalDirs": 6, "languages": {"TypeScript": 85, "JSON": 10, "Docker": 5}},
    },
    "repo_user": {
        "tree": [
            {"path": "src/", "type": "dir"},
            {"path": "src/index.ts", "type": "file", "size": 900},
            {"path": "src/routes/", "type": "dir"},
            {"path": "src/routes/auth.ts", "type": "file", "size": 6200},
            {"path": "src/routes/session.ts", "type": "file", "size": 4800},
            {"path": "src/routes/user.ts", "type": "file", "size": 3100},
            {"path": "src/routes/oauth.ts", "type": "file", "size": 3900},
            {"path": "src/lib/", "type": "dir"},
            {"path": "src/lib/jwt.ts", "type": "file", "size": 1200},
            {"path": "src/lib/hash.ts", "type": "file", "size": 800},
            {"path": "src/lib/db.ts", "type": "file", "size": 1600},
            {"path": "src/middleware/", "type": "dir"},
            {"path": "src/middleware/auth-guard.ts", "type": "file", "size": 1400},
            {"path": "src/models/", "type": "dir"},
            {"path": "src/models/user.ts", "type": "file", "size": 2800},
            {"path": "src/models/session.ts", "type": "file", "size": 1900},
            {"path": "package.json", "type": "file", "size": 1200},
            {"path": "Dockerfile", "type": "file", "size": 420},
        ],
        "stats": {"totalFiles": 15, "totalDirs": 5, "languages": {"TypeScript": 90, "JSON": 7, "Docker": 3}},
    },
    "repo_notif": {
        "tree": [
            {"path": "src/", "type": "dir"},
            {"path": "src/index.ts", "type": "file", "size": 700},
            {"path": "src/channels/", "type": "dir"},
            {"path": "src/channels/email.ts", "type": "file", "size": 2400},
            {"path": "src/channels/sms.ts", "type": "file", "size": 1800},
            {"path": "src/channels/push.ts", "type": "file", "size": 2100},
            {"path": "src/templates/", "type": "dir"},
            {"path": "src/lib/sns.ts", "type": "file", "size": 1600},
            {"path": "package.json", "type": "file", "size": 900},
            {"path": "Dockerfile", "type": "file", "size": 380},
        ],
        "stats": {"totalFiles": 9, "totalDirs": 3, "languages": {"TypeScript": 88, "JSON": 8, "Docker": 4}},
    },
}

# ── File contents (key files) ──────────────────────────────────────────

_FILE_CONTENTS = {
    # payment-service package.json — has vulnerable jsonwebtoken
    ("repo_payment", "package.json"): {
        "path": "package.json",
        "content": """{
  "name": "@acme/payment-service",
  "version": "2.4.1",
  "private": true,
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "test": "vitest"
  },
  "dependencies": {
    "express": "^4.18.2",
    "stripe": "^14.11.0",
    "jsonwebtoken": "8.5.1",
    "lodash": "4.17.20",
    "mongoose": "^8.0.3",
    "winston": "^3.11.0",
    "dotenv": "^16.3.1",
    "axios": "0.21.1",
    "helmet": "^7.1.0",
    "cors": "^2.8.5"
  },
  "devDependencies": {
    "typescript": "^5.3.3",
    "tsx": "^4.7.0",
    "vitest": "^1.2.0",
    "@types/express": "^4.17.21",
    "@types/jsonwebtoken": "^9.0.5",
    "@types/lodash": "^4.14.202"
  }
}""",
    },
    # user-service package.json
    ("repo_user", "package.json"): {
        "path": "package.json",
        "content": """{
  "name": "@acme/user-service",
  "version": "1.8.3",
  "private": true,
  "dependencies": {
    "express": "^4.18.2",
    "jsonwebtoken": "8.5.1",
    "bcryptjs": "^2.4.3",
    "mongoose": "^8.0.3",
    "passport": "^0.7.0",
    "passport-google-oauth20": "^2.0.0",
    "lodash": "4.17.20",
    "redis": "^4.6.12",
    "dotenv": "^16.3.1"
  }
}""",
    },
    # payment-service verify-jwt.ts — the vulnerable code
    ("repo_payment", "src/middleware/verify-jwt.ts"): {
        "path": "src/middleware/verify-jwt.ts",
        "content": """import jwt from 'jsonwebtoken';
import { Request, Response, NextFunction } from 'express';

const JWT_SECRET = process.env.JWT_SECRET || 'default-secret';

export function verifyJwt(req: Request, res: Response, next: NextFunction) {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) return res.status(401).json({ error: 'No token provided' });

  try {
    // VULNERABLE: jsonwebtoken 8.5.1 allows algorithm confusion attack
    // An attacker can craft a token using the HS256 algorithm with the
    // RSA public key as the HMAC secret, bypassing signature verification
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded;
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Invalid token' });
  }
}""",
    },
    # user-service auth.ts — inconsistent error handling
    ("repo_user", "src/routes/auth.ts"): {
        "path": "src/routes/auth.ts",
        "content": """import { Router } from 'express';
import jwt from 'jsonwebtoken';
import bcrypt from 'bcryptjs';
import { UserModel } from '../models/user';
import _ from 'lodash';

const router = Router();

// Pattern 1: try/catch with res.status
router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    const user = await UserModel.findOne({ email });
    if (!user) return res.status(404).json({ error: 'User not found' });

    const valid = await bcrypt.compare(password, user.passwordHash);
    if (!valid) return res.status(401).json({ error: 'Invalid password' });

    const token = jwt.sign({ userId: user._id }, process.env.JWT_SECRET!, { expiresIn: '7d' });
    res.json({ token, user: _.pick(user, ['_id', 'email', 'name']) });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Pattern 2: .catch() chain (different from Pattern 1)
router.post('/register', (req, res) => {
  const { email, password, name } = req.body;
  bcrypt.hash(password, 12)
    .then(hash => UserModel.create({ email, passwordHash: hash, name }))
    .then(user => {
      const token = jwt.sign({ userId: user._id }, process.env.JWT_SECRET!, { expiresIn: '7d' });
      res.status(201).json({ token });
    })
    .catch(err => {
      if (err.code === 11000) return res.status(409).json({ error: 'Email already exists' });
      res.status(500).json({ error: err.message });
    });
});

// Pattern 3: Result type (different from both above)
router.get('/me', async (req, res) => {
  const result = await getUserProfile(req.user?.userId);
  if (result.ok) {
    res.json(result.data);
  } else {
    res.status(result.statusCode).json({ error: result.error });
  }
});

async function getUserProfile(userId: string) {
  try {
    const user = await UserModel.findById(userId);
    if (!user) return { ok: false, statusCode: 404, error: 'Not found' };
    return { ok: true, data: _.omit(user.toObject(), ['passwordHash']) };
  } catch {
    return { ok: false, statusCode: 500, error: 'Database error' };
  }
}

export default router;""",
    },
}

# ── Security scans & vulnerabilities ───────────────────────────────────

_SECURITY_SCANS = {
    "repo_payment": [
        {
            "_id": "scan_pay_001",
            "repoId": "repo_payment",
            "status": "completed",
            "tier": "quick",
            "startedAt": "2026-03-15T08:00:00Z",
            "completedAt": "2026-03-15T08:12:00Z",
            "stats": {"total": 5, "critical": 1, "high": 2, "medium": 1, "low": 1},
        }
    ],
    "repo_user": [],
    "repo_notif": [],
}

_VULNERABILITIES = {
    "repo_payment": [
        {
            "_id": "vuln_001",
            "executionId": "scan_pay_001",
            "title": "JWT Algorithm Confusion allows authentication bypass",
            "severity": "critical",
            "status": "open",
            "filePath": "src/middleware/verify-jwt.ts",
            "lineNumber": 14,
            "description": "jsonwebtoken 8.5.1 is vulnerable to algorithm confusion attacks (CVE-2022-23529). An attacker can forge valid JWT tokens by exploiting the algorithm switching from RS256 to HS256, using the public key as HMAC secret.",
            "recommendation": "Upgrade jsonwebtoken to >=9.0.0 and explicitly specify the allowed algorithms in verify(): jwt.verify(token, secret, { algorithms: ['HS256'] })",
            "cwe": "CWE-327",
        },
        {
            "_id": "vuln_002",
            "executionId": "scan_pay_001",
            "title": "Prototype pollution via lodash merge/defaultsDeep",
            "severity": "high",
            "status": "open",
            "filePath": "package.json",
            "lineNumber": None,
            "description": "lodash 4.17.20 is vulnerable to prototype pollution (CVE-2021-23337). The merge() and defaultsDeep() functions allow an attacker to inject properties into Object.prototype, potentially leading to RCE.",
            "recommendation": "Upgrade lodash to >=4.17.21",
            "cwe": "CWE-1321",
        },
        {
            "_id": "vuln_003",
            "executionId": "scan_pay_001",
            "title": "SSRF via axios in proxy configuration",
            "severity": "high",
            "status": "open",
            "filePath": "src/lib/stripe.ts",
            "lineNumber": 42,
            "description": "axios 0.21.1 follows redirects by default and does not validate the redirect URL. An attacker-controlled URL in webhook configurations could trigger SSRF to internal services.",
            "recommendation": "Upgrade axios to >=0.21.2 or >=1.6.0, and configure maxRedirects: 0 for webhook handlers",
            "cwe": "CWE-918",
        },
        {
            "_id": "vuln_004",
            "executionId": "scan_pay_001",
            "title": "Missing rate limiting on checkout endpoint",
            "severity": "medium",
            "status": "open",
            "filePath": "src/routes/checkout.ts",
            "lineNumber": 8,
            "description": "The /checkout endpoint accepts unlimited requests without rate limiting, enabling card testing attacks.",
            "recommendation": "Apply the existing rate-limit middleware to the checkout route",
            "cwe": "CWE-770",
        },
        {
            "_id": "vuln_005",
            "executionId": "scan_pay_001",
            "title": "Verbose error messages expose stack traces",
            "severity": "low",
            "status": "open",
            "filePath": "src/routes/webhook.ts",
            "lineNumber": 67,
            "description": "Unhandled errors in the Stripe webhook handler return full stack traces to the client in non-production environments. The NODE_ENV check is missing.",
            "recommendation": "Add global error handler that strips stack traces regardless of environment",
            "cwe": "CWE-209",
        },
    ],
    "repo_user": [],
    "repo_notif": [],
}

_SCAN_TIERS = [
    {"_id": "tier_quick", "name": "Quick Scan", "description": "Dependency + config analysis. ~5 minutes.", "credits": 5},
    {"_id": "tier_standard", "name": "Standard Scan", "description": "Multi-agent vulnerability analysis. ~15 minutes.", "credits": 25},
    {"_id": "tier_deep", "name": "Deep Scan", "description": "Full exploit verification with PoC generation. ~45 minutes.", "credits": 100},
]

# ── Lifecycle actions (empty for fresh onboard) ───────────────────────

_LIFECYCLE_ACTIONS = []
_LIFECYCLE_EVENTS = []

# Track actions created during the session
_created_actions = []


# ── Dynamic handlers ───────────────────────────────────────────────────

def _list_repos(**kwargs):
    ws = kwargs.get("workspaceId", "")
    if ws == WS_ID:
        return _WORKSPACE_REPOS
    return []


def _get_repo_details(**kwargs):
    repo_id = kwargs.get("repoId", "")
    for r in _WORKSPACE_REPOS:
        if r["_id"] == repo_id:
            return r
    return {"error": "Repository not found"}


def _browse_files(**kwargs):
    repo_id = kwargs.get("repoId", "")
    return _FILE_TREES.get(repo_id, {"tree": [], "stats": {}})


def _read_files(**kwargs):
    repo_id = kwargs.get("repoId", "")
    paths = kwargs.get("paths", "")
    results = []
    for p in paths.split(","):
        p = p.strip()
        key = (repo_id, p)
        if key in _FILE_CONTENTS:
            results.append(_FILE_CONTENTS[key])
        else:
            results.append({"path": p, "content": f"// File content not available in mock: {p}"})
    return {"files": results}


def _list_scans(**kwargs):
    repo_id = kwargs.get("repoId", "")
    return _SECURITY_SCANS.get(repo_id, [])


def _list_vulns_by_repo(**kwargs):
    repo_id = kwargs.get("repoId", "")
    return _VULNERABILITIES.get(repo_id, [])


def _list_vulns(**kwargs):
    exec_id = kwargs.get("executionId", "")
    for vulns in _VULNERABILITIES.values():
        matching = [v for v in vulns if v.get("executionId") == exec_id]
        if matching:
            return matching
    return []


def _get_vuln_details(**kwargs):
    vuln_id = kwargs.get("exploitId", "") or kwargs.get("vulnerabilityId", "")
    for vulns in _VULNERABILITIES.values():
        for v in vulns:
            if v["_id"] == vuln_id:
                return v
    return {"error": "Vulnerability not found"}


def _start_scan(**kwargs):
    scan_id = f"scan_{uuid.uuid4().hex[:8]}"
    return {
        "_id": scan_id,
        "executionId": scan_id,
        "status": "running",
        "message": f"Scan started. Use get_security_scan_details(executionId='{scan_id}') to check progress.",
    }


def _get_scan_details(**kwargs):
    exec_id = kwargs.get("executionId", "")
    # Check if it's the existing completed scan
    if exec_id == "scan_pay_001":
        return _SECURITY_SCANS["repo_payment"][0]
    # Otherwise it's a new scan — simulate progress
    return {
        "_id": exec_id,
        "status": "running",
        "progress": 65,
        "message": "Analyzing dependencies and scanning for vulnerability patterns...",
    }


def _lifecycle_actions_list(**kwargs):
    return {"actions": _LIFECYCLE_ACTIONS + _created_actions, "total": len(_LIFECYCLE_ACTIONS) + len(_created_actions)}


def _lifecycle_actions_create(**kwargs):
    action = {
        "_id": f"action_{uuid.uuid4().hex[:8]}",
        "workspaceId": kwargs.get("workspaceId", WS_ID),
        "type": kwargs.get("type", "investigate"),
        "title": kwargs.get("title", ""),
        "description": kwargs.get("description", ""),
        "priority": kwargs.get("priority", "medium"),
        "status": "proposed",
        "reasoning": kwargs.get("reasoning", ""),
        "createdBy": "agent",
        "cycleTag": kwargs.get("cycleTag", ""),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _created_actions.append(action)
    return action


def _lifecycle_actions_update(**kwargs):
    action_id = kwargs.get("actionId", "")
    for a in _created_actions:
        if a["_id"] == action_id:
            for k in ("status", "priority", "title", "description"):
                if k in kwargs:
                    a[k] = kwargs[k]
            return a
    return {"error": "Action not found"}


def _lifecycle_events_list(**kwargs):
    return {"events": _LIFECYCLE_EVENTS, "total": len(_LIFECYCLE_EVENTS)}


# ── Workspace context (in-memory state) ────────────────────────────────

_ws_onboarding_status = "not_started"
_ws_onboarding_phase = None
_ws_blueprint = None
_ws_learnings = []
_ws_threads = []
_ws_pending_work = {}


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
    if _ws_blueprint:
        return _ws_blueprint
    return {"blueprint": None}


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
    # Upsert
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


# ── Response mapping ───────────────────────────────────────────────────

RESPONSES = {
    # Workspaces
    "list_my_workspaces": _WORKSPACES,
    "get_workspace_details": _WORKSPACE_DETAILS,

    # Repos
    "list_repositories": _list_repos,
    "get_repository_details": _get_repo_details,
    "list_github_user_repos": {"repos": _GITHUB_ALL_REPOS, "total": len(_GITHUB_ALL_REPOS), "installationId": 12345},
    "add_github_repository": lambda **kw: {"_id": f"repo_{uuid.uuid4().hex[:6]}", "status": "added", **kw},
    "remove_repository": lambda **kw: {"ok": True},
    "browse_repository_files": _browse_files,
    "read_repository_files": _read_files,

    # Security
    "list_scan_tiers": _SCAN_TIERS,
    "list_security_scans": _list_scans,
    "start_security_scan": _start_scan,
    "get_security_scan_details": _get_scan_details,
    "get_scan_progress_logs": lambda **kw: {"logs": ["Scanning dependencies...", "Analyzing source code...", "Verifying findings..."]},
    "abort_security_scan": lambda **kw: {"ok": True, "status": "aborted"},
    "list_all_user_scans": lambda **kw: _SECURITY_SCANS.get("repo_payment", []),

    # Vulnerabilities
    "list_vulnerabilities": _list_vulns,
    "list_vulnerabilities_by_repo": _list_vulns_by_repo,
    "get_vulnerability_details": _get_vuln_details,

    # Integrations (issue filing)
    "create_github_security_issue": lambda **kw: {"issueUrl": f"https://github.com/acme-corp/payment-service/issues/{47}", "issueNumber": 47},
    "create_jira_security_ticket": lambda **kw: {"ticketKey": "ACME-142", "ticketUrl": "https://acme.atlassian.net/browse/ACME-142"},

    # Evolutions
    "list_code_generation_tasks": lambda **kw: [],
    "start_evolutionary_coding": lambda **kw: {"evolutionId": f"evo_{uuid.uuid4().hex[:8]}", "status": "started"},
    "get_code_generation_progress": lambda **kw: {"status": "running", "progress": 30, "currentIteration": 3, "totalIterations": 20},
    "abort_code_generation": lambda **kw: {"ok": True},
    "get_evolution_iterations": lambda **kw: {"iterations": []},
    "get_generated_programs": lambda **kw: {"programs": []},
    "evolutions_agents_list": lambda **kw: {"agents": []},
    "evolutions_agents_start": lambda **kw: {"agentId": f"agent_{uuid.uuid4().hex[:6]}"},
    "evolutions_agents_view": lambda **kw: {"status": "idle"},

    # Evaluators
    "list_code_evaluators": lambda **kw: [],
    "get_evaluator_details": lambda **kw: {"error": "Not found"},
    "create_ai_evaluator": lambda **kw: {"evaluatorId": f"eval_{uuid.uuid4().hex[:6]}"},

    # Billing
    "check_workspace_credits": {"credits": 487, "plan": "pro", "billingCycle": "monthly"},
    "view_billing_history": {"transactions": []},

    # Reports
    "reports_start": lambda **kw: {"reportId": f"report_{uuid.uuid4().hex[:6]}"},
    "reports_status": lambda **kw: {"status": "completed"},
    "reports_view": lambda **kw: {"content": "# Report\n\nNo data yet."},

    # Lifecycle actions
    "lifecycle_actions_list": _lifecycle_actions_list,
    "lifecycle_actions_create": _lifecycle_actions_create,
    "lifecycle_actions_view": lambda **kw: next((a for a in _created_actions if a["_id"] == kw.get("actionId")), {"error": "Not found"}),
    "lifecycle_actions_update": _lifecycle_actions_update,
    "lifecycle_actions_delete": lambda **kw: {"ok": True},
    "lifecycle_events_list": _lifecycle_events_list,
    "lifecycle_action_events": lambda **kw: {"events": []},

    # Workspace context
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
}

# ── Tool schemas (optional, gives LLM proper parameter names) ─────────

TOOL_SCHEMAS = {
    "workspace_status": {
        "description": "Get workspace onboarding status, blueprint freshness, and context counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
            },
        },
    },
    "workspace_status_update": {
        "description": "Update workspace onboarding status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "onboardingStatus": {"type": "string", "description": "Status: not_started, in_progress, completed"},
                "onboardingPhase": {"type": "string", "description": "Current phase (e.g. introduction, scanning, complete)"},
            },
            "required": ["onboardingStatus"],
        },
    },
    "workspace_blueprint_get": {
        "description": "Get the workspace blueprint (codebase summary, architecture, tech stack). Returns null if no blueprint exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
            },
        },
    },
    "workspace_blueprint_update": {
        "description": "Write or replace the workspace blueprint. Call after onboarding or when the assessment changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "summary": {"type": "string", "description": "Concise text summary of the workspace (max 4000 chars)"},
                "data": {"type": "object", "description": "Structured blueprint data (repos, tech stack, security posture, etc.)"},
            },
            "required": ["summary"],
        },
    },
    "workspace_learnings_list": {
        "description": "List things the agent has discovered about this workspace. Newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "category": {"type": "string", "description": "Filter by category (security, architecture, dependency, pattern, team, preferences)"},
                "limit": {"type": "number", "description": "Max results (default 30)"},
            },
        },
    },
    "workspace_learnings_add": {
        "description": "Record something you discovered about the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "category": {"type": "string", "description": "Category: security, architecture, dependency, pattern, team, preferences"},
                "content": {"type": "string", "description": "What you learned (concise, factual)"},
                "sourceThread": {"type": "string", "description": "Thread ID where this was discovered"},
            },
            "required": ["category", "content"],
        },
    },
    "workspace_threads_list": {
        "description": "List recent conversation threads across all platforms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "platform": {"type": "string", "description": "Filter by platform (cli, slack, web, cron)"},
                "limit": {"type": "number", "description": "Max results (default 10)"},
            },
        },
    },
    "workspace_threads_update": {
        "description": "Update the summary for a conversation thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "threadId": {"type": "string", "description": "Thread identifier (e.g. cli:abc123, slack:C04xyz)"},
                "platform": {"type": "string", "description": "Platform name (cli, slack, web, cron)"},
                "summary": {"type": "string", "description": "Brief summary of what happened (max 200 chars)"},
                "userId": {"type": "string", "description": "User ID associated with this thread"},
            },
            "required": ["threadId", "platform", "summary"],
        },
    },
    "workspace_pending_work_list": {
        "description": "List work items being tracked across sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "status": {"type": "string", "description": "Filter by status (comma-separated: pending,in_progress,approved,blocked)"},
                "limit": {"type": "number", "description": "Max results (default 20)"},
            },
        },
    },
    "workspace_pending_work_upsert": {
        "description": "Create or update a pending work item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "Workspace ID"},
                "workId": {"type": "string", "description": "Unique work item ID"},
                "type": {"type": "string", "description": "Work type (security_fix, evolution, investigation, cleanup)"},
                "status": {"type": "string", "description": "Status: pending, in_progress, approved, blocked, completed, rejected"},
                "description": {"type": "string", "description": "Work item description"},
                "linkedThread": {"type": "string", "description": "Thread ID that created this item"},
            },
            "required": ["workId", "type", "status", "description"],
        },
    },
}
