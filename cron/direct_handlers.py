"""Direct-call cron handlers.

Direct cron jobs (kind="direct" in jobs.json) skip the LLM agent loop and
invoke a registered Python callable. Used for deterministic ops work like
the fleet supervisor and observer — both produce structured artifacts the
brief and Settings UI render, no judgment needed at run time.

Each handler signature:
    handler(tenant_id: str, **kwargs) -> str  (a short status message)

Handlers are responsible for:
  - Setting tenant context (set_current_tenant) before touching tenant data
  - Refreshing GitHub token via _refresh_github_token_env(tenant_id=...)
  - Logging at INFO so Railway logs show what ran

Failures should raise; the scheduler catches and records them on the job row.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


_HANDLERS: Dict[str, Callable[..., str]] = {}


def register(name: str) -> Callable[[Callable], Callable]:
    """Decorator: register a direct-call handler by name."""
    def decorator(fn: Callable) -> Callable:
        if name in _HANDLERS:
            logger.warning("re-registering direct handler '%s' (was %s)", name, _HANDLERS[name])
        _HANDLERS[name] = fn
        return fn
    return decorator


def get(name: str) -> Callable[..., str]:
    """Look up a handler by name. Raises KeyError when missing — the scheduler
    surfaces the error on the job's last_error so the user sees it."""
    fn = _HANDLERS.get(name)
    if fn is None:
        raise KeyError(f"No direct cron handler registered as '{name}'. "
                       f"Known: {sorted(_HANDLERS)}")
    return fn


def list_handlers() -> list[str]:
    return sorted(_HANDLERS.keys())


# ---------------------------------------------------------------------------
# Fleet supervisor — runs every 12 minutes per tenant
# ---------------------------------------------------------------------------

@register("fleet_supervise")
def _run_fleet_supervise(tenant_id: str, **_kw) -> str:
    """Walk every reachable repo for this tenant, advance Dash-tracked
    delegations through the supervisor state machine. Idempotent."""
    from backend.tenant_context import (
        TenantContext, set_current_tenant, reset_current_tenant,
    )

    # Resolve user_id + role from tenant_memberships so downstream tools that
    # require a full TenantContext have one.
    from backend.db.postgres_client import get_pool
    user_id = "dash"
    role = "owner"
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT user_id, role FROM tenant_memberships
                        WHERE tenant_id = %s AND is_default = TRUE
                        LIMIT 1""",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row:
                    user_id = str(row["user_id"])
                    role = str(row["role"] or "owner")
    except Exception:
        pass

    ctx_token = set_current_tenant(TenantContext(
        user_id=user_id, tenant_id=tenant_id, role=role,
    ))
    try:
        from github_app_auth import refresh_github_token_env
        if not refresh_github_token_env(tenant_id=tenant_id):
            return "no GitHub installation for this tenant; skipping"
        token = os.environ.get("GITHUB_TOKEN", "")

        from tools.pm_github_tools import github_list_repos
        import json as _json
        try:
            data = _json.loads(github_list_repos())
        except Exception as e:
            return f"github_list_repos failed: {e}"
        repos_list = [r["full_name"] for r in data.get("repos", []) if r.get("full_name")]
        if not repos_list:
            return "no repos reachable for this tenant"

        # Resolve active workflow (or default)
        from agent_fleet import workflow as wf_module
        from backend import repos as pg_repos
        active = pg_repos.get_active_workflow(tenant_id)
        if active:
            try:
                workflow_obj = wf_module.parse_workflow(active["body"])
            except Exception:
                workflow_obj = wf_module.default_workflow()
        else:
            workflow_obj = wf_module.default_workflow()

        from agent_fleet.supervisor import run_supervisor
        report = run_supervisor(
            tenant_id=tenant_id,
            repos_list=repos_list,
            token=token,
            workflow=workflow_obj,
        )
        counts = report.by_kind()
        delegated = report.delegations_seen
        return (
            f"supervisor: scanned={report.repos_scanned} delegations={delegated} "
            f"actions={dict(counts)}"
        )
    finally:
        reset_current_tenant(ctx_token)


# ---------------------------------------------------------------------------
# Fleet observer + evolver — weekly per tenant
# ---------------------------------------------------------------------------

@register("fleet_observe")
def _run_fleet_observe(tenant_id: str, **_kw) -> str:
    """Run the observer + evolver loop. Auto-applies what's allowed; surfaces
    the rest as workflow proposals for the user to accept in Settings."""
    from backend.tenant_context import (
        TenantContext, set_current_tenant, reset_current_tenant,
    )
    from backend.db.postgres_client import get_pool

    user_id = "dash"
    role = "owner"
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT user_id, role FROM tenant_memberships
                        WHERE tenant_id = %s AND is_default = TRUE
                        LIMIT 1""",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row:
                    user_id = str(row["user_id"])
                    role = str(row["role"] or "owner")
    except Exception:
        pass

    ctx_token = set_current_tenant(TenantContext(
        user_id=user_id, tenant_id=tenant_id, role=role,
    ))
    try:
        from github_app_auth import refresh_github_token_env
        if not refresh_github_token_env(tenant_id=tenant_id):
            return "no GitHub installation; skipping observer"
        token = os.environ.get("GITHUB_TOKEN", "")

        from tools.pm_github_tools import github_list_repos
        import json as _json
        data = _json.loads(github_list_repos())
        repos_list = [r["full_name"] for r in data.get("repos", []) if r.get("full_name")]

        from agent_fleet import workflow as wf_module
        from backend import repos as pg_repos
        active = pg_repos.get_active_workflow(tenant_id)
        if active:
            try:
                workflow_obj = wf_module.parse_workflow(active["body"])
                workflow_text = active["body"]
            except Exception:
                workflow_obj = wf_module.default_workflow()
                workflow_text = wf_module.DEFAULT_WORKFLOW_TEXT
        else:
            workflow_obj = wf_module.default_workflow()
            workflow_text = wf_module.DEFAULT_WORKFLOW_TEXT

        from agent_fleet.observer import gather_signals
        signals = gather_signals(
            workflow=workflow_obj,
            repos_list=repos_list,
            token=token,
            tenant_id=tenant_id,
        )

        # Mirror server.py /api/fleet/observe persistence injection.
        import json as _j
        import uuid as _uuid

        def _save_revision(*, tenant_id, name, body, author, rationale, based_on_signals):
            return pg_repos.save_workflow_revision(
                tenant_id, name=name, body=body, author=author,
                rationale=rationale, based_on_signals=based_on_signals,
            )

        def _file_proposal(tenant_id_, signal):
            action_id = _uuid.uuid4().hex[:8]
            change = signal.suggested_change or {}
            payload = [{
                "type": "workflow_proposal",
                "signal_kind": signal.kind,
                "severity": signal.severity,
                "rationale": signal.rationale,
                "suggested_change": change,
                "evidence": signal.evidence,
            }]
            try:
                with pg_repos.get_pool().connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO brief_actions
                                   (id, tenant_id, brief_id, category, title, description,
                                    priority, status, references_json)
                               VALUES (%s, %s, NULL, 'workflow-proposal', %s, %s, 'medium',
                                       'pending', %s)""",
                            (action_id, tenant_id_,
                             f"Workflow proposal: {signal.kind}",
                             f"{signal.rationale}\n\nSuggested change: "
                             f"`{change.get('section')}.{change.get('field')}`: "
                             f"`{change.get('from')}` → `{change.get('to')}`",
                             _j.dumps(payload)),
                        )
                return action_id
            except Exception:
                logger.exception("file_proposal failed in cron observer")
                return None

        from agent_fleet.evolver import EvolverContext, evolve
        ctx = EvolverContext(
            tenant_id=tenant_id,
            workflow=workflow_obj,
            workflow_text=workflow_text,
            save_revision=_save_revision,
            file_proposal=_file_proposal,
        )
        decisions = evolve(ctx=ctx, signals=signals)
        applied = sum(1 for d in decisions if d.outcome == "applied")
        proposed = sum(1 for d in decisions if d.outcome == "proposed")
        skipped = sum(1 for d in decisions if d.outcome == "skipped")
        return (
            f"observer: signals={len(signals)} applied={applied} "
            f"proposed={proposed} skipped={skipped}"
        )
    finally:
        reset_current_tenant(ctx_token)


def run_handler(name: str, tenant_id: str, **kwargs: Any) -> str:
    """Public entry point used by cron.scheduler.run_job."""
    fn = get(name)
    return fn(tenant_id, **kwargs)
