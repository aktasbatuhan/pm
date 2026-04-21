"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { RichResponse } from "@/components/rich-response";
import { fetchWorkspace, triggerBackgroundTask } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  FileText,
  RefreshCw,
  Loader2,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
} from "lucide-react";

const STORAGE_KEY = "dash_changelog_generating";

interface Entry {
  id: number;
  content: string;
  created_at: number;
}

export function ChangelogView() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [copied, setCopied] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const ws = await fetchWorkspace();
    const all = ws?.learnings ?? [];
    const changelogEntries = all.filter((l) => l.category === "changelog");
    setEntries(changelogEntries);
    // Auto-expand the latest
    if (changelogEntries.length > 0 && expandedId === null) {
      setExpandedId(changelogEntries[0].id);
    }
    setLoading(false);
    return changelogEntries;
  }, []);

  // Restore generating state from localStorage + poll
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const { startCount, startedAt } = JSON.parse(stored);
      const elapsed = Date.now() - startedAt;
      if (elapsed < 180_000) {
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
      const updated = (ws?.learnings ?? []).filter((l) => l.category === "changelog");
      if (updated.length > startCount) {
        setEntries(updated);
        setExpandedId(updated[0].id);
        setGenerating(false);
        localStorage.removeItem(STORAGE_KEY);
        clearInterval(poll);
      }
    }, 5000);
    setTimeout(() => {
      clearInterval(poll);
      setGenerating(false);
      localStorage.removeItem(STORAGE_KEY);
    }, 180_000);
  }

  function handleGenerate() {
    setGenerating(true);
    const startCount = entries.length;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ startCount, startedAt: Date.now() }));
    triggerBackgroundTask(
      "Generate a changelog of what shipped in the last 7 days. " +
      "Use gh CLI to list merged PRs across all repos in the workspace blueprint. " +
      "Group changes by feature area (not by repo). Write clean, well-formatted markdown with sections and bullet points. " +
      "Include PR numbers as references. Use ## headers for each feature area. " +
      "Store the result with workspace_add_learning using category='changelog'.",
      `changelog-${Date.now()}`
    );
    startPolling(startCount);
  }

  function handleCopy(id: number, content: string) {
    navigator.clipboard.writeText(content);
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  }

  function formatDate(ts: number) {
    return new Date(ts * 1000).toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold">Changelog</h2>
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1.5 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          {generating ? "Generating..." : "Generate"}
        </button>
      </div>

      {generating && (
        <div className="mb-4 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <p className="text-sm text-primary font-medium">Analyzing merged PRs and generating changelog...</p>
        </div>
      )}

      {loading ? (
        <div className="h-32 animate-pulse rounded-xl bg-muted" />
      ) : entries.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center">
            <FileText className="mx-auto h-8 w-8 text-muted-foreground/30" />
            <p className="mt-2 text-sm text-muted-foreground">No changelogs yet</p>
            <p className="mt-1 text-xs text-muted-foreground">Click Generate to create one from recent PRs</p>
          </CardContent>
        </Card>
      ) : (
        /* Timeline view */
        <div className="relative ml-4">
          {/* Vertical line */}
          <div className="absolute left-0 top-2 bottom-2 w-px bg-border" />

          {entries.map((e, i) => {
            const isExpanded = expandedId === e.id;
            const isLatest = i === 0;
            return (
              <div key={e.id} className="relative pl-8 pb-6 last:pb-0">
                {/* Timeline dot */}
                <div className={cn(
                  "absolute left-0 -translate-x-1/2 top-1.5 flex items-center justify-center",
                )}>
                  <div className={cn(
                    "h-3 w-3 rounded-full border-2 border-background",
                    isLatest ? "bg-primary" : "bg-muted-foreground/30"
                  )} />
                </div>

                {/* Content */}
                <button
                  onClick={() => setExpandedId(isExpanded ? null : e.id)}
                  className="flex w-full items-center justify-between text-left group"
                >
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      "text-sm font-medium",
                      isLatest ? "text-foreground" : "text-muted-foreground"
                    )}>
                      {formatDate(e.created_at)}
                    </span>
                    {isLatest && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                        Latest
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {!isExpanded && (
                      <span className="text-xs text-muted-foreground max-w-[200px] truncate hidden sm:inline">
                        {e.content.split("\n")[0]?.slice(0, 60)}
                      </span>
                    )}
                    {isExpanded ? (
                      <ChevronUp className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    )}
                  </div>
                </button>

                {isExpanded && (
                  <div className="mt-3 rounded-xl border border-border bg-card px-5 py-4 animate-in fade-in slide-in-from-top-2 duration-200">
                    <div className="flex justify-end mb-2">
                      <button
                        onClick={(ev) => { ev.stopPropagation(); handleCopy(e.id, e.content); }}
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted"
                      >
                        {copied === e.id ? <><Check className="h-3 w-3 text-green-500" /> Copied</> : <><Copy className="h-3 w-3" /> Copy</>}
                      </button>
                    </div>
                    <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
                      <RichResponse>{e.content}</RichResponse>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
