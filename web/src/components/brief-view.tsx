"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RichResponse } from "@/components/rich-response";
import { cn } from "@/lib/utils";
import {
  fetchBrief,
  fetchBriefById,
  fetchBriefs,
  fetchWorkspace,
  resolveAction,
  requestNewBrief,
  fetchGithubAppStatus,
  fetchGithubRepos,
  createIssueFromAction,
  type BriefSummary,
  type GithubAppStatus,
  type GithubRepo,
} from "@/lib/api";
import type { Brief, ActionItem, WorkspaceStatus } from "@/lib/types";
import {
  CheckCircle2,
  Circle,
  ArrowRight,
  ArrowUpRight,
  AlertTriangle,
  Loader2,
  RefreshCw,
  GitPullRequest,
  Users,
  Target,
  Clock,
  FileText,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

// ── Styles ────────────────────────────────────────────────────────────

const PRIORITY_COLORS: Record<string, string> = {
  critical: "text-red-600 bg-red-50 border-red-100",
  high: "text-amber-600 bg-amber-50 border-amber-100",
  medium: "text-blue-600 bg-blue-50 border-blue-100",
  low: "text-zinc-500 bg-zinc-50 border-zinc-100",
};

const PRIORITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-amber-500",
  medium: "bg-blue-500",
  low: "bg-zinc-400",
};

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  risk: { label: "Risk", color: "text-red-600 bg-red-50" },
  "pain-point": { label: "Pain Point", color: "text-amber-600 bg-amber-50" },
  team: { label: "Team", color: "text-violet-600 bg-violet-50" },
  "stakeholder-update": { label: "Update", color: "text-blue-600 bg-blue-50" },
  "next-feature": { label: "Feature", color: "text-emerald-600 bg-emerald-50" },
};

// ── Helpers ───────────────────────────────────────────────────────────

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts * 1000;
  if (diff < 3600_000) return `${Math.max(1, Math.floor(diff / 60_000))}m ago`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
  return new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function extractHeadline(summary: string): string {
  const whatHappened = summary.match(/## What Happened\n+([\s\S]*?)(?=\n##|\n```|$)/);
  if (whatHappened) {
    const lines = whatHappened[1].split("\n").filter((l) => l.trim().startsWith("-") || l.trim().length > 20);
    if (lines.length > 0) {
      return lines[0].replace(/^[-*]\s*/, "").trim();
    }
  }
  const firstSentence = summary.match(/[A-Z][^.!?]*[.!?]/);
  return firstSentence?.[0] ?? "Your daily operating snapshot is ready.";
}

function extractExecutiveSummary(summary: string): string[] {
  // Pull the key bullets from "What Happened" and "Current State"
  const bullets: string[] = [];

  const whatHappened = summary.match(/## What Happened\n+([\s\S]*?)(?=\n##|\n```|$)/);
  if (whatHappened) {
    const lines = whatHappened[1]
      .split("\n")
      .filter((l) => l.trim().startsWith("-"))
      .map((l) => l.replace(/^[-*]\s*/, "").trim())
      .filter((l) => l.length > 10);
    bullets.push(...lines.slice(0, 3));
  }

  const currentState = summary.match(/## Current State\n+([\s\S]*?)(?=\n##|\n```|$)/);
  if (currentState) {
    const lines = currentState[1]
      .split("\n")
      .filter((l) => l.trim().startsWith("-"))
      .map((l) => l.replace(/^[-*]\s*/, "").trim())
      .filter((l) => l.length > 10);
    bullets.push(...lines.slice(0, 2));
  }

  // If we got nothing from sections, take first few sentences
  if (bullets.length === 0) {
    const sentences = summary
      .replace(/^#.*$/gm, "")
      .replace(/```[\s\S]*?```/g, "")
      .split(/[.!?]\s+/)
      .filter((s) => s.trim().length > 20)
      .slice(0, 4)
      .map((s) => s.trim() + ".");
    return sentences;
  }

  return bullets.slice(0, 5);
}

function extractMetrics(summary: string, actions: ActionItem[]): Metric[] {
  const metrics: Metric[] = [];

  // Sprint completion
  const sprint = summary.match(/(\d+)\s*(?:of|\/)\s*(\d+)\s*(?:done|complete)/i)
    ?? summary.match(/(\d+)%\s*complete/i);
  if (sprint) {
    if (sprint[2]) {
      const pct = Math.round((parseInt(sprint[1]) / parseInt(sprint[2])) * 100);
      metrics.push({ label: "Sprint", value: `${pct}%`, detail: `${sprint[1]}/${sprint[2]} done`, icon: Target });
    } else {
      metrics.push({ label: "Sprint", value: sprint[1] + "%", detail: "completion", icon: Target });
    }
  }

  // PRs merged
  const prs = summary.match(/(\d+)\s*PRs?\s*merged/i);
  if (prs) {
    metrics.push({ label: "PRs Merged", value: prs[1], detail: "since last brief", icon: GitPullRequest });
  }

  // Team size / active
  const team = summary.match(/(\d+)\s*(?:contributors?|members?|engineers?)\s*(?:are\s*)?active/i)
    ?? summary.match(/(\d+)\s*active/i);
  if (team) {
    metrics.push({ label: "Active Team", value: team[1], detail: "contributors", icon: Users });
  }

  // Stale reviews
  const stale = summary.match(/(\d+)\s*(?:PRs?|reviews?)\s*(?:are\s*)?stale/i)
    ?? summary.match(/stale.*?(\d+)/i);
  if (stale) {
    metrics.push({ label: "Stale Reviews", value: stale[1], detail: "need attention", icon: Clock, warning: true });
  }

  // If we couldn't extract enough, add action-based metrics
  if (metrics.length < 3) {
    const critical = actions.filter((a) => a.priority === "critical" && a.status === "pending").length;
    if (critical > 0) {
      metrics.push({ label: "Critical", value: String(critical), detail: "blockers", icon: AlertTriangle, warning: true });
    }
  }

  if (metrics.length < 3) {
    metrics.push({ label: "Action Items", value: String(actions.filter((a) => a.status === "pending").length), detail: "pending", icon: Target });
  }

  return metrics.slice(0, 4);
}

interface Metric {
  label: string;
  value: string;
  detail: string;
  icon: typeof Target;
  warning?: boolean;
}

function generateSuggestions(summary: string, actions: ActionItem[]): string[] {
  const suggestions: string[] = [];
  const pending = actions.filter((a) => a.status === "pending" || a.status === "in-progress");

  // 1. Top critical/high item → investigate
  const critical = pending.find((a) => a.priority === "critical");
  const high = pending.find((a) => a.priority === "high");
  if (critical) {
    suggestions.push(`Investigate: ${critical.title}`);
  } else if (high) {
    suggestions.push(`Look into: ${high.title}`);
  }

  // 2. Stale reviews → clear them
  if (/stale.*review|review.*stale|awaiting review/i.test(summary)) {
    suggestions.push("Help me clear the stale review queue");
  }

  // 3. Sprint behind → why
  const sprintMatch = summary.match(/sprint\s*(\d+)/i);
  if (sprintMatch && /behind|lagging|not started|stale/i.test(summary)) {
    suggestions.push(`Why is Sprint ${sprintMatch[1]} behind?`);
  }

  // 4. Stakeholder update — always useful
  suggestions.push("Draft a stakeholder update from this brief");

  // 5. Feature prioritization — if mentioned
  if (/feature|roadmap|build next|subscription|pricing|launch/i.test(summary)) {
    const featureItem = pending.find((a) => a.category === "next-feature");
    if (featureItem) {
      suggestions.push(`Plan the rollout for: ${featureItem.title}`);
    } else {
      suggestions.push("What should we build next?");
    }
  } else {
    suggestions.push("What should we build next?");
  }

  // 6. Team-specific if flagged
  const teamItem = pending.find((a) => a.category === "team");
  if (teamItem) {
    suggestions.push(`Dive into team issue: ${teamItem.title}`);
  }

  // 7. Risk assessment if multiple risks
  const risks = pending.filter((a) => a.category === "risk");
  if (risks.length >= 2) {
    suggestions.push("Run a full risk assessment");
  }

  // Dedupe and cap at 4
  const seen = new Set<string>();
  return suggestions.filter((s) => {
    const key = s.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 4);
}

// ── Main Component ────────────────────────────────────────────────────

interface Props {
  onNavigateToChat: (prompt?: string) => void;
}

export function BriefView({ onNavigateToChat }: Props) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [narrativeExpanded, setNarrativeExpanded] = useState(false);
  const [briefHistory, setBriefHistory] = useState<BriefSummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [githubApp, setGithubApp] = useState<GithubAppStatus | null>(null);
  const [githubRepos, setGithubRepos] = useState<GithubRepo[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    const [b, w, history] = await Promise.all([
      fetchBrief(),
      fetchWorkspace(),
      fetchBriefs(10),
    ]);
    setBrief(b);
    setWorkspace(w);
    setBriefHistory(history);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Load GitHub App status + repos (for the "file as issue" button on action cards)
  useEffect(() => {
    fetchGithubAppStatus().then((s) => {
      setGithubApp(s);
      if (s?.installation && s?.can_write_issues) {
        fetchGithubRepos().then(setGithubRepos).catch(() => {});
      }
    });
  }, []);

  async function handleSelectBrief(briefId: string) {
    const b = await fetchBriefById(briefId);
    if (b) setBrief(b);
    setHistoryOpen(false);
  }

  function handleRequestBrief() {
    setGenerating(true);
    requestNewBrief();
    // Poll for new brief
    const pollInterval = setInterval(async () => {
      const b = await fetchBrief();
      if (b && b.id !== brief?.id) {
        setBrief(b);
        setGenerating(false);
        clearInterval(pollInterval);
        // Refresh history
        fetchBriefs(10).then(setBriefHistory);
      }
    }, 5000);
    // Stop polling after 5 min
    setTimeout(() => {
      clearInterval(pollInterval);
      setGenerating(false);
    }, 300_000);
  }

  const allActions = brief?.action_items ?? [];
  const pending = allActions.filter((a) => a.status === "pending" || a.status === "in-progress");
  const resolved = allActions.filter((a) => a.status === "resolved" || a.status === "dismissed");

  async function handleResolve(id: string) {
    // Optimistic update
    setBrief((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        action_items: prev.action_items.map((a) =>
          a.id === id ? { ...a, status: "resolved" as const } : a
        ),
      };
    });
    await resolveAction(id);
  }

  // Skeleton loading
  if (loading) {
    return (
      <ScrollArea className="h-full">
        <div className="mx-auto max-w-4xl px-8 py-10">
          <div className="h-6 w-48 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-8 w-96 animate-pulse rounded bg-muted" />
          <div className="mt-8 grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl bg-muted" />
            ))}
          </div>
          <div className="mt-8 h-64 animate-pulse rounded-xl bg-muted" />
        </div>
      </ScrollArea>
    );
  }

  // Empty state
  if (!brief) {
    return (
      <ScrollArea className="h-full">
        <div className="mx-auto max-w-4xl px-8 py-10">
          <p className="text-sm font-medium text-muted-foreground">{greeting()}</p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight">No briefs yet</h1>
          <p className="mt-2 text-muted-foreground">
            Start a chat and ask Dash to generate your first daily brief.
          </p>
          <button
            onClick={() => onNavigateToChat("Give me today's brief")}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Generate first brief <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </ScrollArea>
    );
  }

  // Prefer the agent-authored headline from brief_store. Fall back to body
  // extraction only for older briefs stored before the field existed.
  const headline = (brief.headline && brief.headline.trim()) || extractHeadline(brief.summary);
  const execSummary = extractExecutiveSummary(brief.summary);
  const metrics = extractMetrics(brief.summary, allActions);

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-4xl px-8 py-10">

        {/* ── Toolbar ───────────────────────────────────────────── */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>{greeting()}</span>
            <span className="text-border">/</span>
            <span>Brief from {timeAgo(brief.created_at)}</span>
            {brief.data_sources && (
              <>
                <span className="text-border">/</span>
                <span>{brief.data_sources.split(",").length} sources</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {briefHistory.length > 1 && (
              <button
                onClick={() => setHistoryOpen(!historyOpen)}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Clock className="h-3.5 w-3.5" />
                History ({briefHistory.length})
              </button>
            )}
            <button
              onClick={handleRequestBrief}
              disabled={generating}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {generating ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating...</>
              ) : (
                <><RefreshCw className="h-3.5 w-3.5" /> New brief</>
              )}
            </button>
          </div>
        </div>

        {/* ── History panel ──────────────────────────────────────── */}
        {historyOpen && (
          <div className="mb-6 rounded-xl border border-border bg-card p-3 space-y-1">
            <p className="px-2 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">Past briefs</p>
            {briefHistory.map((b) => (
              <button
                key={b.id}
                onClick={() => handleSelectBrief(b.id)}
                className={cn(
                  "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                  b.id === brief.id && "bg-muted"
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-[13px]">{b.headline || "Brief"}</p>
                  <p className="text-[11px] text-muted-foreground">{timeAgo(b.created_at)} · {b.action_count} items{b.pending_count > 0 ? ` (${b.pending_count} pending)` : ""}</p>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* ── Generating indicator ──────────────────────────────── */}
        {generating && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <p className="text-sm text-primary font-medium">Dash is generating a new brief. This usually takes 1-2 minutes.</p>
          </div>
        )}

        {/* ── Layer 1: Headline ──────────────────────────────────── */}
        <section>

          <h1 className="mt-3 text-2xl font-bold tracking-tight leading-snug max-w-2xl">
            {headline}
          </h1>

          {/* Executive summary */}
          {execSummary.length > 0 && (
            <ul className="mt-4 space-y-1.5 max-w-2xl">
              {execSummary.map((bullet, i) => (
                <li key={i} className="flex items-start gap-2.5 text-[14px] text-muted-foreground leading-relaxed">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/40" />
                  {bullet}
                </li>
              ))}
            </ul>
          )}

          {/* Cover image */}
          {brief.cover_url && (
            <div className="mt-6 overflow-hidden rounded-xl">
              <img
                src={brief.cover_url}
                alt=""
                className="h-40 w-full object-cover"
              />
            </div>
          )}
        </section>

        {/* ── Layer 2: Metrics + Actions ─────────────────────────── */}
        <section className="mt-8">
          {/* Metric cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {metrics.map((m, i) => (
              <MetricCard key={i} metric={m} />
            ))}
          </div>

          {/* Action items */}
          {pending.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-foreground">
                  Action Items
                </h2>
                <span className="text-xs text-muted-foreground">
                  {pending.length} pending{resolved.length > 0 ? ` · ${resolved.length} done` : ""}
                </span>
              </div>
              <div className="space-y-2">
                {pending.map((item) => (
                  <ActionCard
                    key={item.id}
                    item={item}
                    canCreateIssue={Boolean(githubApp?.can_write_issues)}
                    repos={githubRepos}
                    onResolve={() => handleResolve(item.id)}
                    onChat={() =>
                      onNavigateToChat(`Let's look at this action item: "${item.title}" — ${item.description}`)
                    }
                    onIssueCreated={async () => {
                      // Reload the brief so the new reference shows up on the card
                      const fresh = await fetchBrief();
                      if (fresh) setBrief(fresh);
                    }}
                  />
                ))}
              </div>

              {/* Resolved items collapsed */}
              {resolved.length > 0 && (
                <div className="mt-3 rounded-xl border border-border/50 bg-muted/30 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                    <span>{resolved.length} resolved item{resolved.length > 1 ? "s" : ""}</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Quick actions — agent-generated or extracted from content */}
          <div className="mt-6 flex flex-wrap gap-2">
            {(brief.suggested_prompts?.length > 0
              ? brief.suggested_prompts.slice(0, 4)
              : generateSuggestions(brief.summary, allActions)
            ).map((s) => (
              <button
                key={s}
                onClick={() => onNavigateToChat(s)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
              >
                {s}
                <ArrowUpRight className="h-3 w-3 opacity-40" />
              </button>
            ))}
          </div>
        </section>

        {/* ── Layer 3: Full Narrative ────────────────────────────── */}
        <section className="mt-10">
          <button
            onClick={() => setNarrativeExpanded(!narrativeExpanded)}
            className="flex w-full items-center justify-between rounded-xl border border-border bg-card px-5 py-4 text-left transition-colors hover:bg-muted/50"
          >
            <div className="flex items-center gap-3">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-sm font-semibold">Full Report</p>
                <p className="text-xs text-muted-foreground">
                  Detailed analysis with context and recommendations
                </p>
              </div>
            </div>
            {narrativeExpanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>

          {narrativeExpanded && (
            <div className="mt-3 rounded-xl border border-border bg-card px-6 py-5">
              <RichResponse>{brief.summary}</RichResponse>
            </div>
          )}
        </section>

        <div className="h-16" />
      </div>
    </ScrollArea>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────

function MetricCard({ metric }: { metric: Metric }) {
  return (
    <div className={cn(
      "rounded-xl border bg-card px-4 py-3.5 transition-colors",
      metric.warning ? "border-amber-200 bg-amber-50/30" : "border-border"
    )}>
      <div className="flex items-center gap-2">
        <metric.icon className={cn(
          "h-3.5 w-3.5",
          metric.warning ? "text-amber-500" : "text-muted-foreground"
        )} />
        <span className="text-xs font-medium text-muted-foreground">{metric.label}</span>
      </div>
      <p className={cn(
        "mt-1.5 text-2xl font-bold tracking-tight",
        metric.warning && "text-amber-600"
      )}>
        {metric.value}
      </p>
      <p className="text-[11px] text-muted-foreground">{metric.detail}</p>
    </div>
  );
}

const REF_ICONS: Record<string, string> = {
  pr: "PR",
  issue: "#",
  link: "↗",
  email: "@",
};

function ActionCard({
  item,
  canCreateIssue,
  repos,
  onResolve,
  onChat,
  onIssueCreated,
}: {
  item: ActionItem;
  canCreateIssue: boolean;
  repos: GithubRepo[];
  onResolve: () => void;
  onChat: () => void;
  onIssueCreated: () => void;
}) {
  const isDone = item.status === "resolved" || item.status === "dismissed";
  const refs = item.references ?? [];
  const cat = CATEGORY_LABELS[item.category] ?? { label: item.category, color: "text-zinc-600 bg-zinc-50" };
  const alreadyHasIssue = refs.some((r) => (r.url || "").includes("/issues/"));

  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedRepo, setSelectedRepo] = useState(repos[0]?.full_name || "");
  const [filing, setFiling] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedRepo && repos.length > 0) setSelectedRepo(repos[0].full_name);
  }, [repos, selectedRepo]);

  async function handleFile() {
    if (!selectedRepo) return;
    setFiling(true);
    setFileError(null);
    const result = await createIssueFromAction(item.id, { repo: selectedRepo });
    setFiling(false);
    if (!result.ok) {
      setFileError(result.error === "permission_denied"
        ? "GitHub App needs Issues: Write permission. Update on github.com/settings/apps."
        : (result.hint || result.error || "Failed to file issue."));
      return;
    }
    setPickerOpen(false);
    onIssueCreated();
  }

  return (
    <div className={cn(
      "group rounded-xl border bg-card px-4 py-3.5 transition-all",
      isDone ? "opacity-50 border-border/50" : "border-border hover:shadow-sm"
    )}>
      <div className="flex items-start gap-3">
        {/* Priority dot + checkbox */}
        <div className="flex flex-col items-center gap-1 pt-0.5">
          <div className={cn("h-2 w-2 rounded-full", PRIORITY_DOT[item.priority])} />
          {!isDone && (
            <button
              onClick={onResolve}
              className="mt-0.5 text-muted-foreground/40 transition-colors hover:text-green-500"
              title="Mark resolved"
            >
              <Circle className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className={cn("text-sm font-medium leading-snug", isDone && "line-through text-muted-foreground")}>
              {item.title}
            </p>
            {!isDone && (
              <div className="flex shrink-0 items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100">
                {canCreateIssue && !alreadyHasIssue && repos.length > 0 && (
                  <button
                    onClick={() => setPickerOpen((v) => !v)}
                    className="text-xs text-primary hover:underline"
                    title="Create a GitHub issue from this action"
                  >
                    File issue
                  </button>
                )}
                <button
                  onClick={onChat}
                  className="text-xs text-primary hover:underline"
                >
                  Discuss →
                </button>
              </div>
            )}
          </div>
          <p className="mt-1 text-[13px] text-muted-foreground leading-relaxed">
            {item.description}
          </p>

          {/* Inline repo picker */}
          {pickerOpen && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
              <span className="text-[11px] text-muted-foreground">File in:</span>
              <select
                value={selectedRepo}
                onChange={(e) => setSelectedRepo(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1 text-[12px] outline-none"
              >
                {repos.map((r) => (
                  <option key={r.full_name} value={r.full_name}>{r.full_name}</option>
                ))}
              </select>
              <button
                onClick={handleFile}
                disabled={filing || !selectedRepo}
                className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground disabled:opacity-40"
              >
                {filing ? "Filing…" : "Create issue"}
              </button>
              <button
                onClick={() => { setPickerOpen(false); setFileError(null); }}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              {fileError && (
                <p className="basis-full text-[11px] text-red-600">{fileError}</p>
              )}
            </div>
          )}

          {/* References + badges */}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", cat.color)}>
              {cat.label}
            </span>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", PRIORITY_COLORS[item.priority])}>
              {item.priority}
            </span>
            {refs.map((ref, i) => (
              <a
                key={i}
                href={ref.url || undefined}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors",
                  ref.url
                    ? "border-primary/20 text-primary hover:bg-primary/5"
                    : "border-border text-muted-foreground"
                )}
              >
                <span className="opacity-50">{REF_ICONS[ref.type] ?? "↗"}</span>
                {ref.title}
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
