"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fetchWorkspace, fetchBrief, triggerBackgroundTask } from "@/lib/api";
import type { WorkspaceStatus, Brief } from "@/lib/types";
import { TeamPulse } from "@/components/team-pulse";
import { GoalsPanel } from "@/components/goals-panel";
import { ChangelogView } from "@/components/changelog-view";
// SchedulesPanel moved to its own Routines tab
import { cn } from "@/lib/utils";
import {
  Lightbulb,
  ArrowRight,
  ArrowUpRight,
  Brain,
  Loader2,
  RefreshCw,
  TrendingUp,
  Shield,
  Users,
  Wrench,
  Zap,
} from "lucide-react";

const CATEGORY_CONFIG: Record<string, { icon: typeof TrendingUp; color: string; label: string }> = {
  product: { icon: TrendingUp, color: "text-blue-600 bg-blue-50", label: "Product" },
  technical: { icon: Wrench, color: "text-violet-600 bg-violet-50", label: "Technical" },
  team: { icon: Users, color: "text-emerald-600 bg-emerald-50", label: "Team" },
  process: { icon: Zap, color: "text-amber-600 bg-amber-50", label: "Process" },
  risk: { icon: Shield, color: "text-red-600 bg-red-50", label: "Risk" },
};

interface Props {
  onNavigateToChat: (prompt?: string) => void;
}

export function InsightsView({ onNavigateToChat }: Props) {
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [ws, b] = await Promise.all([fetchWorkspace(), fetchBrief()]);
    setWorkspace(ws);
    setBrief(b);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  function handleGenerateInsights() {
    setGenerating(true);
    triggerBackgroundTask(
      "Analyze the workspace deeply. Look at the blueprint, all learnings, the latest brief, and recent GitHub activity. " +
      "Generate a set of strategic insights:\n" +
      "1. What patterns do you see across recent briefs and learnings?\n" +
      "2. What should the team build next and why? (data-backed)\n" +
      "3. What risks are compounding that nobody is addressing?\n" +
      "4. What process improvements would have the biggest impact?\n" +
      "5. Any team dynamics observations worth surfacing?\n\n" +
      "Store each insight as a workspace learning with the appropriate category. " +
      "Be specific with numbers and references, not generic advice.",
      `insights-${Date.now()}`
    );
    // Poll for new learnings
    const startCount = workspace?.learnings_count ?? 0;
    const poll = setInterval(async () => {
      const ws = await fetchWorkspace();
      if (ws && (ws.learnings_count ?? 0) > startCount) {
        setWorkspace(ws);
        setGenerating(false);
        clearInterval(poll);
      }
    }, 5000);
    setTimeout(() => { clearInterval(poll); setGenerating(false); }, 180_000);
  }

  const learnings = workspace?.learnings ?? [];
  const blueprint = workspace?.blueprint;

  // Group learnings by category
  const grouped: Record<string, typeof learnings> = {};
  for (const l of learnings) {
    const cat = l.category || "general";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(l);
  }

  // Build suggested actions from brief + learnings
  const suggestedActions: string[] = [];
  if (brief?.suggested_prompts) {
    suggestedActions.push(...brief.suggested_prompts.slice(0, 3));
  }
  suggestedActions.push(
    "What feature should we prioritize next quarter?",
    "Run a risk assessment across all open work",
  );

  if (loading) {
    return (
      <ScrollArea className="h-full">
        <div className="mx-auto max-w-4xl px-8 py-10 space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      </ScrollArea>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-4xl px-8 py-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Insights</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Strategic patterns and recommendations from Dash's analysis
            </p>
          </div>
          <button
            onClick={handleGenerateInsights}
            disabled={generating}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {generating ? (
              <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Analyzing...</>
            ) : (
              <><Brain className="h-3.5 w-3.5" /> Generate new insights</>
            )}
          </button>
        </div>

        {generating && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <p className="text-sm text-primary font-medium">Dash is analyzing your workspace for new insights...</p>
          </div>
        )}

        {/* Goals */}
        <div className="mb-6">
          <GoalsPanel onNavigateToChat={onNavigateToChat} />
        </div>

        {/* Team Pulse */}
        <div className="mb-6">
          <TeamPulse />
        </div>

        {/* Changelog */}
        <div className="mb-6">
          <ChangelogView />
        </div>


        {/* Blueprint summary */}
        {blueprint && (
          <Card className="mb-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Workspace Blueprint</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-muted-foreground">{blueprint.summary}</p>
            </CardContent>
          </Card>
        )}

        {/* Learnings by category */}
        {Object.entries(grouped).length > 0 ? (
          <div className="space-y-4">
            {Object.entries(grouped).map(([category, items]) => {
              const config = CATEGORY_CONFIG[category] ?? {
                icon: Lightbulb,
                color: "text-zinc-600 bg-zinc-50",
                label: category.charAt(0).toUpperCase() + category.slice(1),
              };
              return (
                <Card key={category}>
                  <CardHeader className="flex flex-row items-center gap-2 pb-3">
                    <div className={cn("flex h-7 w-7 items-center justify-center rounded-lg", config.color)}>
                      <config.icon className="h-3.5 w-3.5" />
                    </div>
                    <CardTitle className="text-base">{config.label}</CardTitle>
                    <Badge variant="secondary" className="ml-auto">{items.length}</Badge>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {items.map((l) => (
                      <div key={l.id} className="flex items-start gap-3 group">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/30" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm leading-relaxed text-foreground/80">{l.content}</p>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            {new Date(l.created_at * 1000).toLocaleDateString("en-US", {
                              month: "short",
                              day: "numeric",
                            })}
                          </p>
                        </div>
                        <button
                          onClick={() => onNavigateToChat(`Let's discuss this insight: "${l.content.slice(0, 80)}..."`)}
                          className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-xs text-primary hover:underline mt-0.5"
                        >
                          Discuss →
                        </button>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : (
          <Card>
            <CardContent className="py-12 text-center">
              <Lightbulb className="mx-auto h-8 w-8 text-muted-foreground/30" />
              <p className="mt-3 text-sm font-medium text-muted-foreground">No insights yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Generate briefs and chat with Dash to build up insights over time.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Suggested deep-dives */}
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-foreground mb-3">Go deeper</h2>
          <div className="flex flex-wrap gap-2">
            {suggestedActions.slice(0, 5).map((s) => (
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
        </div>

        <div className="h-16" />
      </div>
    </ScrollArea>
  );
}
