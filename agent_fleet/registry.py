"""Static registry of known external coding agents.

Ships with Dash. Facts here are the *default* — what the vendor documents.
Per-tenant deviations (learned invocation patterns, enabled state, activity)
live in AgentProfile, not here.

To add a new agent: append a KnownAgent to `_REGISTRY`. No DB migration needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


InvocationType = str  # "comment_mention" | "issue_assignment" | "label" | "workflow_trigger"


@dataclass(frozen=True)
class DocumentedInvocation:
    type: InvocationType
    syntax: Optional[str] = None   # e.g. "@claude" for comment_mention
    label: Optional[str] = None    # e.g. "claude" for label

    def to_dict(self) -> dict:
        out: dict = {"type": self.type}
        if self.syntax is not None:
            out["syntax"] = self.syntax
        if self.label is not None:
            out["label"] = self.label
        return out


@dataclass(frozen=True)
class KnownAgent:
    id: str
    display_name: str
    vendor: str
    github_app_slug: Optional[str]
    bot_usernames: Tuple[str, ...]
    workflow_actions: Tuple[str, ...]
    documented_invocations: Tuple[DocumentedInvocation, ...]
    default_invocation: InvocationType
    expected_pr_back_seconds: Tuple[int, int]  # (min, max)
    output_signatures: Tuple[str, ...]
    docs_url: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "vendor": self.vendor,
            "github_app_slug": self.github_app_slug,
            "bot_usernames": list(self.bot_usernames),
            "workflow_actions": list(self.workflow_actions),
            "documented_invocations": [i.to_dict() for i in self.documented_invocations],
            "default_invocation": self.default_invocation,
            "expected_pr_back_seconds": list(self.expected_pr_back_seconds),
            "output_signatures": list(self.output_signatures),
            "docs_url": self.docs_url,
        }


_REGISTRY: Tuple[KnownAgent, ...] = (
    KnownAgent(
        id="claude-code",
        display_name="Claude Code",
        vendor="Anthropic",
        github_app_slug="claude",
        bot_usernames=("claude[bot]", "claude-code[bot]"),
        workflow_actions=("anthropics/claude-code-action",),
        documented_invocations=(
            DocumentedInvocation(type="comment_mention", syntax="@claude"),
            DocumentedInvocation(type="issue_assignment"),
            DocumentedInvocation(type="label", label="claude"),
        ),
        default_invocation="comment_mention",
        expected_pr_back_seconds=(300, 1800),   # 5–30 min
        output_signatures=("Generated with Claude Code",),
        docs_url="https://docs.anthropic.com/claude-code",
    ),
    KnownAgent(
        id="codex",
        display_name="OpenAI Codex",
        vendor="OpenAI",
        github_app_slug="codex",
        bot_usernames=("codex[bot]", "chatgpt-codex-connector[bot]"),
        workflow_actions=(),
        documented_invocations=(
            DocumentedInvocation(type="comment_mention", syntax="@codex"),
        ),
        default_invocation="comment_mention",
        expected_pr_back_seconds=(300, 1800),
        output_signatures=("Generated with Codex",),
        docs_url="https://platform.openai.com/docs/codex",
    ),
    KnownAgent(
        id="devin",
        display_name="Devin",
        vendor="Cognition",
        github_app_slug="devin-ai-integration",
        bot_usernames=("devin-ai-integration[bot]",),
        workflow_actions=(),
        documented_invocations=(
            DocumentedInvocation(type="comment_mention", syntax="@devin"),
            DocumentedInvocation(type="issue_assignment"),
        ),
        default_invocation="comment_mention",
        expected_pr_back_seconds=(600, 7200),   # 10 min – 2 h
        output_signatures=("Devin",),
        docs_url="https://docs.devin.ai/",
    ),
    KnownAgent(
        id="jules",
        display_name="Jules",
        vendor="Google",
        github_app_slug="google-jules",
        bot_usernames=("google-jules[bot]",),
        workflow_actions=(),
        documented_invocations=(
            DocumentedInvocation(type="comment_mention", syntax="@jules"),
            DocumentedInvocation(type="label", label="jules"),
        ),
        default_invocation="comment_mention",
        expected_pr_back_seconds=(600, 3600),
        output_signatures=("Generated with Jules",),
        docs_url="https://jules.google/",
    ),
    KnownAgent(
        id="copilot-swe",
        display_name="GitHub Copilot SWE Agent",
        vendor="GitHub",
        github_app_slug="copilot-swe-agent",
        bot_usernames=("copilot-swe-agent[bot]", "github-copilot[bot]"),
        workflow_actions=(),
        documented_invocations=(
            DocumentedInvocation(type="issue_assignment"),
            DocumentedInvocation(type="comment_mention", syntax="@copilot"),
        ),
        default_invocation="issue_assignment",
        expected_pr_back_seconds=(300, 1800),
        output_signatures=("Co-authored-by: Copilot",),
        docs_url="https://docs.github.com/copilot/github-copilot-in-coding-agent",
    ),
    KnownAgent(
        id="cursor-background",
        display_name="Cursor background agents",
        vendor="Cursor",
        github_app_slug="cursor-agent",
        bot_usernames=("cursoragent[bot]", "cursor-agent[bot]"),
        workflow_actions=(),
        documented_invocations=(
            DocumentedInvocation(type="comment_mention", syntax="@cursoragent"),
            DocumentedInvocation(type="label", label="cursor"),
        ),
        default_invocation="comment_mention",
        expected_pr_back_seconds=(600, 3600),
        output_signatures=("Generated with Cursor",),
        docs_url="https://docs.cursor.com/background-agent",
    ),
)


# Public indexes ---------------------------------------------------------------

KNOWN_AGENTS: Dict[str, KnownAgent] = {a.id: a for a in _REGISTRY}


def lookup(agent_id: str) -> Optional[KnownAgent]:
    """Return the KnownAgent for a given id, or None."""
    return KNOWN_AGENTS.get(agent_id)


def list_known() -> List[KnownAgent]:
    """Return all known agents in registry order."""
    return list(_REGISTRY)


def find_by_bot_username(username: str) -> Optional[KnownAgent]:
    """Match a GitHub bot username (case-insensitive) to a known agent."""
    u = (username or "").lower()
    for a in _REGISTRY:
        if any(u == b.lower() for b in a.bot_usernames):
            return a
    return None


def find_by_workflow_action(action_ref: str) -> Optional[KnownAgent]:
    """Match a workflow `uses:` reference (e.g. 'anthropics/claude-code-action@v1')
    to a known agent by stripping the version."""
    if not action_ref:
        return None
    slug = action_ref.split("@", 1)[0].strip().lower()
    for a in _REGISTRY:
        if any(slug == w.lower() for w in a.workflow_actions):
            return a
    return None


def find_by_app_slug(slug: str) -> Optional[KnownAgent]:
    """Match a GitHub App slug to a known agent."""
    s = (slug or "").lower()
    for a in _REGISTRY:
        if a.github_app_slug and a.github_app_slug.lower() == s:
            return a
    return None
