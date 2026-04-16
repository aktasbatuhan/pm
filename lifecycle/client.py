"""HTTP client for kai-backend internal API.

Provides two interfaces:

1. KaiBackendClient — lifecycle callbacks (finalize) using E2B sandbox
   Basic Auth, modeled after kai-executor's backend_client.py.

2. scan_integrations() — standalone function for fetching integration
   data (GitHub, Linear, Jira) via the internal scan endpoint.

Env vars:
  KAI_BACKEND_URL              — backend base URL (default: http://localhost:3000)
  BACKEND_URL                  — fallback for KAI_BACKEND_URL
  BACKEND_INTERNAL_AUTH_SECRET — one-time secret injected by backend at sandbox creation
  E2B_SANDBOX_ID               — sandbox ID (set automatically by E2B runtime)
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 30


def _backend_url() -> str:
    return (
        os.getenv("KAI_BACKEND_URL")
        or os.getenv("BACKEND_URL")
        or "http://localhost:3000"
    ).rstrip("/")


class KaiBackendClient:
    """Backend client for agent lifecycle callbacks.

    Uses HTTP Basic Auth with (sandboxId, BACKEND_INTERNAL_AUTH_SECRET)
    to authenticate against /internal/* routes — same pattern as kai-executor.
    """

    def __init__(self, base_url: Optional[str] = None, sandbox_id: Optional[str] = None):
        self.base_url = base_url or _backend_url()
        self._auth = self._build_auth(sandbox_id)

    @staticmethod
    def _build_auth(sandbox_id: Optional[str] = None) -> Optional[Tuple[str, str]]:
        sid = sandbox_id or os.getenv("E2B_SANDBOX_ID", "")
        secret = os.getenv("BACKEND_INTERNAL_AUTH_SECRET", "")
        if sid and secret:
            return (sid, secret)
        logger.warning("Backend auth not available — sandbox_id or auth_secret missing")
        return None

    def set_sandbox_id(self, sandbox_id: str) -> None:
        """Override sandbox ID (e.g. from MongoDB agent doc)."""
        self._auth = self._build_auth(sandbox_id)

    def finalize_agent(
        self, agent_id: str, reason: str = "destroyed", error: Optional[str] = None
    ) -> bool:
        """Notify backend that the agent is shutting down.

        POST /internal/v1/agents/{agentId}/finalize
        """
        url = f"{self.base_url}/internal/v1/agents/{agent_id}/finalize"
        body: Dict[str, str] = {"reason": reason}
        if error:
            body["error"] = error

        try:
            resp = httpx.post(url, json=body, auth=self._auth, timeout=TIMEOUT)
            if resp.status_code == 200:
                logger.info("Agent %s finalized (reason=%s)", agent_id, reason)
                return True
            logger.warning(
                "Agent finalize returned %d: %s", resp.status_code, resp.text[:200]
            )
            return False
        except Exception as e:
            logger.error("Failed to finalize agent %s: %s", agent_id, e)
            return False

    def fetch_secrets(self, agent_id: str) -> Dict[str, str]:
        """Fetch agent secrets from backend and return as dict.

        GET /internal/v1/agents/{agentId}/secrets
        """
        url = f"{self.base_url}/internal/v1/agents/{agent_id}/secrets"
        try:
            resp = httpx.get(url, auth=self._auth, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                secrets = data.get("secrets", {})
                logger.info("Fetched %d secrets for agent %s", len(secrets), agent_id)
                return secrets
            logger.warning(
                "Fetch secrets returned %d: %s", resp.status_code, resp.text[:200]
            )
            return {}
        except Exception as e:
            logger.error("Failed to fetch secrets for agent %s: %s", agent_id, e)
            return {}

    def ping(self) -> bool:
        """Health check against backend."""
        try:
            resp = httpx.get(f"{self.base_url}/health", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False


# ── Standalone integration scan ────────────────────────────────────


def scan_integrations(workspace_id: str) -> Dict[str, Any]:
    """Aggregate data from all connected integrations (GitHub, Linear, Jira).

    Returns raw integration data — repos, PRs, issues, sprints, scan history.
    This is the one endpoint from the old lifecycle API worth keeping.
    """
    url = f"{_backend_url()}/internal/v1/lifecycle/{workspace_id}/scan"
    with httpx.Client(timeout=TIMEOUT) as c:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.json()
