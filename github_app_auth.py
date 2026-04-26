"""
GitHub App authentication helpers — shared between the FastAPI server and
the cron scheduler so every agent run (chat OR cron) mints a fresh
installation token before the agent touches GitHub.

Tokens are short-lived (1 hour). We cache the minted token in the
integrations DB until 5 min before expiry.
"""

import json
import logging
import os
import time
from typing import Optional

from kai_env import kai_home

logger = logging.getLogger(__name__)


def _integrations_db_path():
    return kai_home() / "integrations.db"


def github_app_config() -> Optional[dict]:
    """Return GitHub App credentials if configured, else None."""
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    slug = os.environ.get("GITHUB_APP_SLUG", "").strip()
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    if not (app_id and slug and private_key):
        return None
    # Railway/shell sometimes collapses literal "\n" into the var; normalize.
    if "\\n" in private_key and "-----BEGIN" in private_key:
        private_key = private_key.replace("\\n", "\n")
    return {
        "app_id": app_id,
        "slug": slug,
        "private_key": private_key,
        "client_id": os.environ.get("GITHUB_APP_CLIENT_ID", "").strip() or None,
        "client_secret": os.environ.get("GITHUB_APP_CLIENT_SECRET", "").strip() or None,
    }


def generate_app_jwt(cfg: dict) -> str:
    """Sign a short-lived JWT for GitHub App authentication (RS256, 10 min max)."""
    import jwt as _jwt
    now = int(time.time())
    payload = {
        "iat": now - 60,   # allow clock skew
        "exp": now + 9 * 60,
        "iss": cfg["app_id"],
    }
    return _jwt.encode(payload, cfg["private_key"], algorithm="RS256")


def get_installation_token(installation_id: str) -> Optional[str]:
    """Return a valid installation access token, minting a new one if the cache is stale.

    Tokens are cached in github_installations.cached_token until 5 min before expiry.
    """
    cfg = github_app_config()
    if not cfg:
        return None

    import sqlite3
    db = sqlite3.connect(str(_integrations_db_path()), check_same_thread=False, timeout=10.0)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            "SELECT cached_token, cached_token_expires_at FROM github_installations WHERE installation_id = ?",
            (installation_id,),
        ).fetchone()
        now = time.time()
        if row and row["cached_token"] and row["cached_token_expires_at"] and row["cached_token_expires_at"] > now + 300:
            return row["cached_token"]

        # Mint a fresh token
        import urllib.request
        app_jwt = generate_app_jwt(cfg)
        req = urllib.request.Request(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            method="POST",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Dash-PM",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        token = data.get("token")
        expires_at_str = data.get("expires_at")
        expires_at_ts = now + 3600
        if expires_at_str:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                expires_at_ts = dt.timestamp()
            except Exception:
                pass

        db.execute(
            "UPDATE github_installations SET cached_token = ?, cached_token_expires_at = ?, updated_at = ? "
            "WHERE installation_id = ?",
            (token, expires_at_ts, now, installation_id),
        )
        db.commit()
        return token
    except Exception as e:
        logger.error("Failed to mint GitHub installation token for %s: %s", installation_id, e)
        return None
    finally:
        db.close()


def refresh_github_token_env(tenant_id: Optional[str] = None) -> bool:
    """If a GitHub App installation exists, mint a fresh token and inject it as GITHUB_TOKEN.

    Resolution order:
      1. If tenant_id is provided AND Postgres is enabled, look up that tenant's installation in Neon.
      2. Else fall back to the most recent installation in the local SQLite (single-tenant legacy).

    Called at the start of every agent run (chat, cron, brief) so the agent
    always has a non-expired installation token available to `gh api` / `curl`.
    """
    installation_id: Optional[str] = None

    # Postgres path (multi-tenant)
    try:
        from backend.db.postgres_client import is_postgres_enabled
        from backend.tenant_context import get_current_tenant as _get_ctx
        if is_postgres_enabled():
            effective_tenant = tenant_id
            if not effective_tenant:
                ctx = _get_ctx()
                if ctx and ctx.tenant_id and ctx.tenant_id != "default":
                    effective_tenant = ctx.tenant_id
                else:
                    env_tid = os.getenv("KAI_TENANT_ID", "").strip()
                    if env_tid and env_tid != "default":
                        effective_tenant = env_tid
            if effective_tenant:
                from backend import repos
                inst = repos.get_github_installation(effective_tenant)
                if inst:
                    installation_id = inst["installation_id"]
    except Exception:
        pass

    # SQLite fallback
    if not installation_id:
        import sqlite3
        try:
            db = sqlite3.connect(str(_integrations_db_path()), check_same_thread=False, timeout=10.0)
            db.row_factory = sqlite3.Row
        except Exception:
            return False
        try:
            row = db.execute(
                "SELECT installation_id FROM github_installations ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        except Exception:
            row = None
        db.close()
        if row:
            installation_id = row["installation_id"]

    if not installation_id:
        return False
    token = get_installation_token(installation_id)
    if not token:
        return False
    os.environ["GITHUB_TOKEN"] = token
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    return True
