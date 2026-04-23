"""Tests for agent_fleet (GitHub issue #10): registry, AgentProfile, blueprint helpers."""

from __future__ import annotations

import pytest

from agent_fleet.registry import (
    KNOWN_AGENTS,
    lookup,
    list_known,
    find_by_bot_username,
    find_by_workflow_action,
    find_by_app_slug,
)
from agent_fleet.profile import (
    AgentProfile,
    AgentProfileError,
    ObservedInvocation,
    ObservedInvocationDetail,
)
from agent_fleet.blueprint import (
    get_external_agents,
    get_agent_profile,
    get_enabled_agents,
    upsert_agent_profile,
    remove_agent_profile,
)
from workspace_context import WorkspaceContext


# ── Registry ─────────────────────────────────────────────────────────────────


def test_registry_has_required_agents():
    """Issue #10 requires at least 6 seeded entries."""
    expected = {"claude-code", "codex", "devin", "jules", "copilot-swe", "cursor-background"}
    assert expected.issubset(set(KNOWN_AGENTS.keys()))
    assert len(list_known()) >= 6


def test_registry_entries_are_well_formed():
    for agent in list_known():
        assert agent.id
        assert agent.display_name
        assert agent.vendor
        assert agent.default_invocation in {
            "comment_mention", "issue_assignment", "label", "workflow_trigger"
        }
        lo, hi = agent.expected_pr_back_seconds
        assert 0 < lo <= hi


def test_registry_lookup_unknown_returns_none():
    assert lookup("does-not-exist") is None
    assert lookup("") is None


def test_find_by_bot_username_case_insensitive():
    assert find_by_bot_username("Claude[bot]").id == "claude-code"
    assert find_by_bot_username("cursoragent[bot]").id == "cursor-background"
    assert find_by_bot_username("no-such-bot") is None


def test_find_by_workflow_action_strips_version():
    match = find_by_workflow_action("anthropics/claude-code-action@v1")
    assert match is not None
    assert match.id == "claude-code"
    assert find_by_workflow_action("unknown/action@main") is None


def test_find_by_app_slug():
    assert find_by_app_slug("claude").id == "claude-code"
    assert find_by_app_slug("devin-ai-integration").id == "devin"
    assert find_by_app_slug("mystery") is None


# ── AgentProfile validation ──────────────────────────────────────────────────


def test_profile_validate_minimal_ok():
    AgentProfile(id="claude-code").validate()


def test_profile_validate_rejects_unknown_id():
    with pytest.raises(AgentProfileError):
        AgentProfile(id="totally-made-up").validate()


def test_profile_validate_accepts_custom_prefix():
    AgentProfile(id="custom:internal-bot").validate()


def test_profile_validate_rejects_bad_confidence():
    p = AgentProfile(id="claude-code", confidence="super-duper")
    with pytest.raises(AgentProfileError):
        p.validate()


def test_profile_validate_rejects_bad_detection_method():
    p = AgentProfile(id="claude-code", detected_via=["psychic"])
    with pytest.raises(AgentProfileError):
        p.validate()


def test_profile_validate_rejects_bad_invocation_type():
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="astral_projection", count=5),
    )
    p = AgentProfile(id="claude-code", observed_invocation=inv)
    with pytest.raises(AgentProfileError):
        p.validate()


def test_profile_roundtrip_to_dict():
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="comment_mention", syntax="@claude", count=19),
        secondary=ObservedInvocationDetail(type="label", label="claude", count=3),
    )
    original = AgentProfile(
        id="claude-code",
        enabled=True,
        detected_via=["fingerprint_pr_author", "workflow_scan"],
        first_seen="2026-02-14T10:00:00Z",
        last_active="2026-04-18T14:22:00Z",
        activity_90d={"prs": 23, "comments": 41},
        primary_repos=["acme/api", "acme/web"],
        observed_invocation=inv,
        confidence="high",
    )
    original.validate()
    serialized = original.to_dict()
    restored = AgentProfile.from_dict(serialized)
    assert restored.id == original.id
    assert restored.enabled is True
    assert restored.activity_90d == {"prs": 23, "comments": 41}
    assert restored.observed_invocation.primary.syntax == "@claude"
    assert restored.observed_invocation.secondary.label == "claude"
    assert restored.confidence == "high"


def test_effective_invocation_uses_learned_pattern_when_confident():
    inv = ObservedInvocation(
        primary=ObservedInvocationDetail(type="label", label="claude-please", count=10),
    )
    p = AgentProfile(id="claude-code", confidence="high", observed_invocation=inv)
    t, syntax, label = p.effective_invocation()
    assert t == "label"
    assert label == "claude-please"


def test_effective_invocation_falls_back_to_registry_default_when_low():
    p = AgentProfile(id="claude-code", confidence="low")
    t, syntax, _ = p.effective_invocation()
    assert t == "comment_mention"
    assert syntax == "@claude"


def test_effective_invocation_for_custom_agent_without_learning():
    p = AgentProfile(id="custom:internal-bot", confidence="low")
    t, _, _ = p.effective_invocation()
    assert t == "none"


# ── Blueprint persistence ────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path):
    db = tmp_path / "workspace.db"
    context = WorkspaceContext(workspace_id="test-ws", db_path=db)
    # Seed an empty blueprint so update works.
    context.update_blueprint({"team_members": []}, summary="test", updated_by="test")
    return context


def test_blueprint_roundtrip_upsert_and_read(ctx):
    assert get_external_agents(ctx) == []
    p = AgentProfile(id="claude-code", enabled=True, confidence="high")
    upsert_agent_profile(ctx, p)

    profiles = get_external_agents(ctx)
    assert len(profiles) == 1
    assert profiles[0].id == "claude-code"
    assert profiles[0].enabled is True

    # Other blueprint data must survive the write.
    bp = ctx.get_blueprint()
    assert bp["data"]["team_members"] == []


def test_upsert_replaces_existing_by_id(ctx):
    upsert_agent_profile(ctx, AgentProfile(id="claude-code", enabled=False))
    upsert_agent_profile(ctx, AgentProfile(id="claude-code", enabled=True, confidence="high"))
    profiles = get_external_agents(ctx)
    assert len(profiles) == 1
    assert profiles[0].enabled is True
    assert profiles[0].confidence == "high"


def test_get_enabled_agents_filters(ctx):
    upsert_agent_profile(ctx, AgentProfile(id="claude-code", enabled=True))
    upsert_agent_profile(ctx, AgentProfile(id="codex", enabled=False))
    enabled = get_enabled_agents(ctx)
    assert len(enabled) == 1
    assert enabled[0].id == "claude-code"


def test_get_agent_profile_lookup(ctx):
    upsert_agent_profile(ctx, AgentProfile(id="devin", enabled=True))
    assert get_agent_profile(ctx, "devin").id == "devin"
    assert get_agent_profile(ctx, "jules") is None


def test_remove_agent_profile(ctx):
    upsert_agent_profile(ctx, AgentProfile(id="claude-code"))
    upsert_agent_profile(ctx, AgentProfile(id="codex"))
    assert remove_agent_profile(ctx, "claude-code") is True
    assert remove_agent_profile(ctx, "claude-code") is False   # idempotent
    remaining = [p.id for p in get_external_agents(ctx)]
    assert remaining == ["codex"]


def test_upsert_validates_profile(ctx):
    bad = AgentProfile(id="not-a-known-agent")
    with pytest.raises(AgentProfileError):
        upsert_agent_profile(ctx, bad)
    assert get_external_agents(ctx) == []


def test_get_external_agents_skips_malformed_entries(ctx, caplog):
    # Poke a broken entry in directly to simulate corruption.
    bp = ctx.get_blueprint()
    data = bp["data"]
    data["external_agents"] = [
        {"id": "claude-code", "enabled": True},
        {"not_even_an_agent": "garbage"},
    ]
    ctx.update_blueprint(data, summary="", updated_by="test")

    profiles = get_external_agents(ctx)
    # The valid one survives; the broken one is dropped.
    assert [p.id for p in profiles] == ["claude-code"]
