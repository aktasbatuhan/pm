"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
  runScheduleNow,
  fetchCronStatus,
  fetchReportTemplates,
  type Schedule,
  type CronStatus,
  type ReportTemplate,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Timer,
  Plus,
  Trash2,
  Play,
  Pause,
  Check,
  X,
  Loader2,
  ChevronDown,
  ChevronUp,
  FileText,
  BarChart3,
  Shield,
  Users,
  Zap,
  Clock,
  Rocket,
  AlertCircle,
} from "lucide-react";

const SCHEDULE_PRESETS = [
  { label: "Every 6 hours", value: "every 6h" },
  { label: "Daily at 9am", value: "0 9 * * *" },
  { label: "Weekly Monday", value: "0 9 * * 1" },
  { label: "Monthly 1st", value: "0 9 1 * *" },
  { label: "Every 30 minutes", value: "every 30m" },
  { label: "Every 2 hours", value: "every 2h" },
];

const ROUTINE_PRESETS = [
  {
    icon: FileText,
    name: "Daily Brief",
    prompt: "Load the pm-brief/daily-brief skill with skill_view and follow it exactly. For GitHub, authenticate via the App installation token ($GITHUB_TOKEN) using `gh api` — start with `gh api /installation/repositories` to see reachable repos. Do not use `gh pr list`/`gh repo list`/`gh issue list`, they don't work with installation tokens. Read workspace_get_blueprint and workspace_get_learnings. Compare to the last brief via brief_get_latest. Produce a structured brief with charts and store it with brief_store including suggested_prompts.",
    schedule: "every 6h",
    category: "briefs",
  },
  {
    icon: Shield,
    name: "Risk Assessment",
    prompt: "Run a risk assessment across the workspace. Check for stale PRs, open critical issues, blocked work, team members who've been quiet, and any security concerns. Store findings with workspace_add_learning using category='risk'.",
    schedule: "0 9 * * 1",
    category: "analysis",
  },
  {
    icon: Users,
    name: "Team Pulse",
    prompt: "Analyze team activity for the last 7 days using GitHub. Authenticate via $GITHUB_TOKEN (GitHub App installation token). Start with `gh api /installation/repositories` to see reachable repos. For each team member in workspace_get_blueprint, query `gh api \"/search/issues?q=repo:{owner}/{repo}+author:{handle}+is:pr+merged:>{date-7d}\"` and `gh api \"/repos/{owner}/{repo}/pulls/{num}/reviews\"`. For each person: count PRs merged, reviews done, days since last activity. Flag concentration risk. Store with workspace_add_learning category='team'.",
    schedule: "0 9 * * 1",
    category: "analysis",
  },
  {
    icon: BarChart3,
    name: "Changelog",
    prompt: "Generate a changelog of what shipped in the last 7 days. Authenticate via $GITHUB_TOKEN (GitHub App installation token). Start with `gh api /installation/repositories` for the repo list, then for each: `gh api \"/search/issues?q=repo:{owner}/{repo}+is:pr+merged:>{date-7d}&per_page=50\"`. Group merged PRs by feature area. Write clean markdown. Store with workspace_add_learning category='changelog'.",
    schedule: "0 9 * * 5",
    category: "reports",
  },
  {
    icon: Zap,
    name: "Signal Digest",
    prompt: "Fetch fresh signals from all configured sources. Analyze the most relevant ones. Summarize the top 5 signals into a digest. Store with workspace_add_learning using category='product'.",
    schedule: "every 6h",
    category: "signals",
  },
];

const CATEGORIES = [
  { id: "all", label: "All", icon: Timer },
  { id: "briefs", label: "Briefs", icon: FileText },
  { id: "analysis", label: "Analysis", icon: BarChart3 },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "signals", label: "Signals", icon: Zap },
  { id: "custom", label: "Custom", icon: Plus },
];

export function RoutinesView() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [cronStatus, setCronStatus] = useState<CronStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    const [s, t, c] = await Promise.all([fetchSchedules(), fetchReportTemplates(), fetchCronStatus()]);
    setSchedules(s);
    setTemplates(t);
    setCronStatus(c);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleRunNow(id: string) {
    setRunningId(id);
    const result = await runScheduleNow(id);
    if (!result.ok) {
      alert(result.error || "Failed to run routine");
    }
    setRunningId(null);
    setTimeout(load, 3000);
  }

  async function handleToggle(id: string, enabled: boolean) {
    await updateSchedule(id, { enabled: !enabled });
    setSchedules((prev) => prev.map((s) => (s.id === id ? { ...s, enabled: !enabled } : s)));
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this routine?")) return;
    await deleteSchedule(id);
    load();
  }

  async function handleQuickCreate(preset: typeof ROUTINE_PRESETS[0]) {
    await createSchedule({
      name: preset.name,
      prompt: preset.prompt,
      schedule: preset.schedule,
    });
    load();
  }

  function categorize(s: Schedule): string {
    const name = (s.name || "").toLowerCase();
    const prompt = (s.prompt || "").toLowerCase();
    if (name.includes("brief") || prompt.includes("brief_store")) return "briefs";
    if (name.includes("report") || prompt.includes("report_save")) return "reports";
    if (name.includes("risk") || name.includes("team") || name.includes("pulse") || prompt.includes("risk")) return "analysis";
    if (name.includes("signal") || name.includes("digest") || prompt.includes("signal")) return "signals";
    return "custom";
  }

  function timeUntil(iso: string | null): string {
    if (!iso) return "—";
    const diff = new Date(iso).getTime() - Date.now();
    if (diff < 0) return "overdue";
    if (diff < 3600_000) return `${Math.ceil(diff / 60_000)}m`;
    if (diff < 86400_000) return `${Math.ceil(diff / 3600_000)}h`;
    return `${Math.ceil(diff / 86400_000)}d`;
  }

  const filtered = filterCategory === "all"
    ? schedules
    : schedules.filter((s) => categorize(s) === filterCategory);

  // Which presets aren't already scheduled
  const existingNames = new Set(schedules.map((s) => s.name.toLowerCase()));
  const availablePresets = ROUTINE_PRESETS.filter((p) => !existingNames.has(p.name.toLowerCase()));

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-4xl px-8 py-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Routines</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Automated tasks Dash runs on a schedule
            </p>
          </div>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-3.5 w-3.5" /> New routine
          </button>
        </div>

        {/* Cron health */}
        {cronStatus && (
          <div className="mb-4 flex items-center gap-3 rounded-md border border-border bg-muted/30 px-3 py-2 text-[11px]">
            {cronStatus.ticker.started_at ? (
              <>
                <span className="flex items-center gap-1.5 text-green-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                  Scheduler running
                </span>
                <span className="text-muted-foreground">
                  {cronStatus.ticker.last_tick_at
                    ? `Last tick ${Math.floor((cronStatus.now - cronStatus.ticker.last_tick_at))}s ago`
                    : "Awaiting first tick"}
                </span>
                <span className="text-muted-foreground">{cronStatus.ticker.ticks} ticks · {cronStatus.ticker.jobs_run} jobs run</span>
                {cronStatus.ticker.last_error && (
                  <span className="flex items-center gap-1 text-red-600" title={cronStatus.ticker.last_error}>
                    <AlertCircle className="h-3 w-3" /> tick error
                  </span>
                )}
              </>
            ) : (
              <span className="flex items-center gap-1.5 text-amber-600">
                <AlertCircle className="h-3 w-3" /> Scheduler not started
              </span>
            )}
          </div>
        )}

        {/* Quick presets */}
        {availablePresets.length > 0 && !showAdd && (
          <div className="mb-6">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Quick start</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {availablePresets.map((p) => (
                <button
                  key={p.name}
                  onClick={() => handleQuickCreate(p)}
                  className="flex items-start gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left transition-all hover:shadow-sm hover:border-primary/30"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary mt-0.5">
                    <p.icon className="h-3.5 w-3.5" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">{p.name}</p>
                    <p className="text-[11px] text-muted-foreground">{p.schedule}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Add custom */}
        {showAdd && (
          <AddRoutineForm onClose={() => setShowAdd(false)} onCreated={() => { setShowAdd(false); load(); }} />
        )}

        {/* Category filter */}
        <div className="flex items-center gap-1 mb-4">
          {CATEGORIES.map((c) => {
            const count = c.id === "all"
              ? schedules.length
              : schedules.filter((s) => categorize(s) === c.id).length;
            return (
              <button
                key={c.id}
                onClick={() => setFilterCategory(c.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  filterCategory === c.id
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {c.label}
                {count > 0 && <span className="text-[10px] opacity-60">{count}</span>}
              </button>
            );
          })}
        </div>

        {/* Routines list */}
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-muted" />)}
          </div>
        ) : filtered.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center">
              <Timer className="mx-auto h-8 w-8 text-muted-foreground/30" />
              <p className="mt-3 text-sm font-medium text-muted-foreground">
                {schedules.length === 0 ? "No routines yet" : "No routines in this category"}
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {filtered.map((s) => {
              const isExpanded = expandedId === s.id;
              const cat = categorize(s);
              return (
                <div
                  key={s.id}
                  className={cn(
                    "rounded-xl border bg-card transition-all",
                    s.enabled ? "border-border" : "border-border/50 opacity-60"
                  )}
                >
                  <div className="flex items-center gap-4 px-5 py-4">
                    <div className={cn(
                      "h-2.5 w-2.5 rounded-full shrink-0",
                      s.enabled ? "bg-green-500" : "bg-muted-foreground/30"
                    )} />

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold">{s.name}</p>
                        <Badge variant="secondary" className="text-[10px]">{cat}</Badge>
                      </div>
                      <div className="flex items-center gap-4 mt-1 text-[12px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {s.schedule_display}
                        </span>
                        {s.next_run_at && s.enabled && (
                          <span>Next in {timeUntil(s.next_run_at)}</span>
                        )}
                        {s.last_status && (
                          <span className={s.last_status === "success" ? "text-green-600" : "text-red-600"}>
                            Last: {s.last_status}
                          </span>
                        )}
                        <span>
                          {s.repeat.times === null ? "Repeats forever" : `${s.repeat.completed}/${s.repeat.times} runs`}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : s.id)}
                        className="rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                      >
                        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </button>
                      <button
                        onClick={() => handleRunNow(s.id)}
                        disabled={runningId === s.id}
                        className="rounded-md p-1.5 text-primary hover:bg-primary/10 disabled:opacity-50"
                        title="Run now"
                      >
                        {runningId === s.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                      </button>
                      <button
                        onClick={() => handleToggle(s.id, s.enabled)}
                        className={cn(
                          "rounded-md p-1.5 transition-colors",
                          s.enabled ? "text-amber-600 hover:bg-amber-50" : "text-green-600 hover:bg-green-50"
                        )}
                        title={s.enabled ? "Pause" : "Resume"}
                      >
                        {s.enabled ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button
                        onClick={() => handleDelete(s.id)}
                        className="rounded-md p-1.5 text-muted-foreground hover:text-red-600 hover:bg-red-50"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="border-t border-border px-5 py-4 animate-in fade-in slide-in-from-top-2 duration-200">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">Agent prompt</p>
                      <pre className="text-xs text-muted-foreground whitespace-pre-wrap max-h-48 overflow-y-auto bg-muted rounded-lg p-3 leading-relaxed">
                        {s.prompt}
                      </pre>
                      <div className="mt-3 flex items-center gap-4 text-[11px] text-muted-foreground">
                        <span>Created: {new Date(s.created_at).toLocaleDateString()}</span>
                        {s.last_run_at && <span>Last ran: {new Date(s.last_run_at).toLocaleString()}</span>}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="h-16" />
      </div>
    </ScrollArea>
  );
}

function AddRoutineForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [schedule, setSchedule] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!prompt.trim() || !schedule.trim()) return;
    setSaving(true);
    setError(null);
    const result = await createSchedule({
      name: name.trim() || prompt.slice(0, 40),
      prompt: prompt.trim(),
      schedule: schedule.trim(),
    });
    setSaving(false);
    if (!result.ok) {
      setError(result.error || "Failed to create routine");
      return;
    }
    onCreated();
  }

  return (
    <Card className="mb-6 border-primary/20 bg-primary/5">
      <CardContent className="pt-5 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-primary">New custom routine</p>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>

        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name (e.g. Weekly competitor check)"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/40"
          autoFocus
        />

        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What should Dash do? Write a self-contained prompt — the agent won't have context from this conversation."
          rows={4}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none resize-none focus:border-primary/40"
        />

        <div>
          <p className="text-xs text-muted-foreground mb-2">Schedule</p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {SCHEDULE_PRESETS.map((p) => (
              <button
                key={p.value}
                onClick={() => setSchedule(p.value)}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-xs transition-colors",
                  schedule === p.value
                    ? "border-primary bg-primary/10 text-primary font-medium"
                    : "border-border text-muted-foreground hover:border-primary/30"
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            placeholder="Or type: every 30m, 0 9 * * *, etc."
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs outline-none focus:border-primary/40"
          />
        </div>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted">Cancel</button>
          <button
            onClick={handleSave}
            disabled={!prompt.trim() || !schedule.trim() || saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            Create routine
          </button>
        </div>
      </CardContent>
    </Card>
  );
}
