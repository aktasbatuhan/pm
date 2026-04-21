"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RichResponse } from "@/components/rich-response";
import { fetchWorkspace, triggerBackgroundTask } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Users,
  RefreshCw,
  Loader2,
  GitPullRequest,
  Eye,
  Clock,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

const STORAGE_KEY = "dash_teampulse_generating";

interface Entry {
  id: number;
  content: string;
  created_at: number;
}

interface ParsedMember {
  name: string;
  handle: string;
  prsMerged: number;
  reviews: number;
  quiet: boolean;
  flags: string[];
  summary: string;
}

function parseMembersFromText(text: string): ParsedMember[] {
  const members: ParsedMember[] = [];

  // Try to extract per-person stats from the text
  // Pattern: "Name merged X PRs" or "Name with X merged PRs"
  const namePatterns = text.match(/(?:^|\n)(?:[-•]\s*)?(\w+)(?:\s*\([^)]*\))?\s*(?:merged|has|shipped|with)\s*(\d+)\s*(?:merged\s*)?PRs?/gi);

  if (namePatterns) {
    for (const match of namePatterns) {
      const parts = match.match(/(\w+).*?(\d+)\s*(?:merged\s*)?PRs?/i);
      if (parts) {
        const name = parts[1];
        const prs = parseInt(parts[2]);
        if (name.length > 1 && !["The", "With", "Has", "And", "For", "But"].includes(name)) {
          const existing = members.find((m) => m.name.toLowerCase() === name.toLowerCase());
          if (!existing) {
            members.push({
              name,
              handle: "",
              prsMerged: prs,
              reviews: 0,
              quiet: false,
              flags: [],
              summary: "",
            });
          }
        }
      }
    }
  }

  // Try to extract handles
  for (const m of members) {
    const handleMatch = text.match(new RegExp(`${m.name}.*?@(\\w+)`, "i"))
      ?? text.match(new RegExp(`${m.name}.*?github.*?(\\w+)`, "i"));
    if (handleMatch) m.handle = handleMatch[1];
  }

  // Extract review counts
  for (const m of members) {
    const reviewMatch = text.match(new RegExp(`${m.name}.*?(\\d+)\\s*(?:PRs?\\s*)?review`, "i"));
    if (reviewMatch) m.reviews = parseInt(reviewMatch[1]);
  }

  // Check for quiet flags
  const quietPattern = /(\w+)\s*(?:has been|is)\s*quiet|quiet.*?(\w+)/gi;
  for (const match of text.matchAll(quietPattern)) {
    const name = match[1] || match[2];
    const member = members.find((m) => m.name.toLowerCase() === name?.toLowerCase());
    if (member) {
      member.quiet = true;
      member.flags.push("quiet");
    }
  }

  // Check for concentration risk
  if (/concentration risk/i.test(text)) {
    const riskMatch = text.match(/(\w+).*?concentration risk/i) ?? text.match(/concentration risk.*?(\w+)/i);
    if (riskMatch) {
      const member = members.find((m) => m.name.toLowerCase() === riskMatch[1].toLowerCase());
      if (member) member.flags.push("concentration risk");
    }
  }

  // Sort by PRs merged descending
  members.sort((a, b) => b.prsMerged - a.prsMerged);

  return members;
}

export function TeamPulse() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const ws = await fetchWorkspace();
    const all = ws?.learnings ?? [];
    setEntries(all.filter((l) => l.category === "team"));
    setLoading(false);
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const { startCount, startedAt } = JSON.parse(stored);
      if (Date.now() - startedAt < 180_000) {
        setGenerating(true);
        startPolling(startCount);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function startPolling(startCount: number) {
    const poll = setInterval(async () => {
      const ws = await fetchWorkspace();
      const updated = (ws?.learnings ?? []).filter((l) => l.category === "team");
      if (updated.length > startCount) {
        setEntries(updated);
        setGenerating(false);
        localStorage.removeItem(STORAGE_KEY);
        clearInterval(poll);
      }
    }, 5000);
    setTimeout(() => { clearInterval(poll); setGenerating(false); localStorage.removeItem(STORAGE_KEY); }, 180_000);
  }

  function handleGenerate() {
    setGenerating(true);
    const startCount = entries.length;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ startCount, startedAt: Date.now() }));
    triggerBackgroundTask(
      "Analyze team activity for the last 7 days. Check each team member in the workspace blueprint using gh CLI. " +
      "For each person: count PRs merged, PRs reviewed, and days since last activity. " +
      "Write a well-formatted markdown report with a section per person. " +
      "Include: activity summary, flags (quiet, overloaded, concentration risk, review bottleneck). " +
      "Store the result with workspace_add_learning using category='team'.",
      `pulse-${Date.now()}`
    );
    startPolling(startCount);
  }

  // Get the latest entry and try to parse members
  const latestEntry = entries.length > 0 ? entries[0] : null;
  const parsedMembers = latestEntry ? parseMembersFromText(latestEntry.content) : [];
  const maxPRs = Math.max(...parsedMembers.map((m) => m.prsMerged), 1);

  const FLAG_STYLES: Record<string, { label: string; color: string }> = {
    quiet: { label: "Quiet", color: "bg-amber-100 text-amber-700" },
    "concentration risk": { label: "Concentration risk", color: "bg-violet-100 text-violet-700" },
    overloaded: { label: "Overloaded", color: "bg-red-100 text-red-700" },
    bottleneck: { label: "Bottleneck", color: "bg-orange-100 text-orange-700" },
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2 pb-3">
        <Users className="h-4 w-4 text-muted-foreground" />
        <CardTitle className="text-base">Team Pulse</CardTitle>
        {latestEntry && (
          <span className="text-[11px] text-muted-foreground">
            {new Date(latestEntry.created_at * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </span>
        )}
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted disabled:opacity-50"
        >
          {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          {generating ? "Analyzing..." : "Refresh"}
        </button>
      </CardHeader>
      <CardContent>
        {generating && (
          <div className="mb-4 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <p className="text-sm text-primary font-medium">Analyzing team activity from GitHub...</p>
          </div>
        )}

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />)}
          </div>
        ) : entries.length === 0 && !generating ? (
          <div className="py-8 text-center">
            <Users className="mx-auto h-8 w-8 text-muted-foreground/30" />
            <p className="mt-2 text-sm text-muted-foreground">No team data yet</p>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
            >
              Analyze team activity
            </button>
          </div>
        ) : (
          <div>
            {/* Parsed member cards */}
            {parsedMembers.length > 0 && (
              <div className="space-y-2 mb-4">
                {parsedMembers.map((m, i) => (
                  <div
                    key={i}
                    className={cn(
                      "flex items-center gap-4 rounded-lg border px-4 py-3 transition-colors",
                      m.quiet ? "border-amber-200 bg-amber-50/30" : "border-border"
                    )}
                  >
                    {/* Avatar */}
                    <div className={cn(
                      "flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                      m.flags.includes("concentration risk")
                        ? "bg-violet-100 text-violet-700"
                        : m.quiet
                          ? "bg-amber-100 text-amber-700"
                          : "bg-primary/10 text-primary"
                    )}>
                      {m.name.charAt(0).toUpperCase()}
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold">{m.name}</span>
                        {m.handle && (
                          <span className="text-[11px] text-muted-foreground">@{m.handle}</span>
                        )}
                        {m.flags.map((f) => {
                          const style = FLAG_STYLES[f] ?? { label: f, color: "bg-zinc-100 text-zinc-600" };
                          return (
                            <Badge key={f} variant="secondary" className={cn("text-[10px] py-0", style.color)}>
                              {style.label}
                            </Badge>
                          );
                        })}
                      </div>
                      <div className="mt-1 flex items-center gap-4 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <GitPullRequest className="h-3 w-3" />
                          {m.prsMerged} merged
                        </span>
                        {m.reviews > 0 && (
                          <span className="flex items-center gap-1">
                            <Eye className="h-3 w-3" />
                            {m.reviews} reviews
                          </span>
                        )}
                        {m.quiet && (
                          <span className="flex items-center gap-1 text-amber-600">
                            <Clock className="h-3 w-3" />
                            Quiet recently
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Activity bar */}
                    <div className="w-20 shrink-0 hidden sm:block">
                      <div className="h-2 rounded-full bg-muted overflow-hidden">
                        <div
                          className={cn(
                            "h-full rounded-full transition-all",
                            m.flags.includes("concentration risk") ? "bg-violet-400" :
                            m.quiet ? "bg-amber-400" : "bg-primary"
                          )}
                          style={{ width: `${Math.max((m.prsMerged / maxPRs) * 100, 4)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Raw analysis toggle */}
            {latestEntry && (
              <button
                onClick={() => setShowRaw(!showRaw)}
                className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                {showRaw ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {showRaw ? "Hide" : "Show"} full analysis
              </button>
            )}

            {showRaw && latestEntry && (
              <div className="mt-3 rounded-lg border border-border px-4 py-3 animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
                  <RichResponse>{latestEntry.content}</RichResponse>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
