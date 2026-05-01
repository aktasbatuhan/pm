"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fetchGoals,
  createGoal,
  updateGoal,
  deleteGoal,
  type Goal,
  type GoalActionItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Target,
  Plus,
  Check,
  Calendar,
  TrendingUp,
  Trash2,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Clock,
} from "lucide-react";

const TRAJECTORY_COLOR: Record<string, string> = {
  "on-track": "text-green-600 bg-green-50",
  "ahead": "text-emerald-600 bg-emerald-50",
  "at-risk": "text-amber-600 bg-amber-50",
  "behind": "text-red-600 bg-red-50",
  "stalled": "text-zinc-600 bg-zinc-100",
};

const PRIORITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-amber-500",
  medium: "bg-blue-500",
  low: "bg-zinc-400",
};

function timeAgo(ts: number | null): string {
  if (!ts) return "not yet evaluated";
  const diff = Date.now() - ts * 1000;
  if (diff < 3600_000) return `${Math.max(1, Math.floor(diff / 60_000))}m ago`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
  if (diff < 604800_000) return `${Math.floor(diff / 86400_000)}d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

interface Props {
  onNavigateToChat: (prompt: string) => void;
}

export function GoalsPanel({ onNavigateToChat }: Props) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDate, setNewDate] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const g = await fetchGoals("all");
    setGoals(g);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    if (!newTitle.trim()) return;
    await createGoal({
      title: newTitle.trim(),
      description: newDesc.trim(),
      target_date: newDate,
    });
    setNewTitle("");
    setNewDate("");
    setNewDesc("");
    setCreating(false);
    load();
  }

  async function handleComplete(goalId: string) {
    await updateGoal(goalId, { status: "completed", progress: 100 });
    load();
  }

  async function handleDelete(goalId: string) {
    if (!confirm("Delete this goal and its progress history?")) return;
    await deleteGoal(goalId);
    load();
  }

  const active = goals.filter((g) => g.status === "active");
  const done = goals.filter((g) => g.status !== "active");

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2 pb-3">
        <Target className="h-4 w-4 text-muted-foreground" />
        <CardTitle className="text-base">Goals</CardTitle>
        <Badge variant="secondary" className="ml-1">{active.length} active</Badge>
        <button
          onClick={() => setCreating(!creating)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted"
        >
          <Plus className="h-3 w-3" /> Add goal
        </button>
      </CardHeader>
      <CardContent>
        {creating && (
          <div className="mb-4 rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-3">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Goal title (e.g. Launch pricing by April 30)"
              className="w-full bg-transparent text-sm font-medium outline-none placeholder:text-muted-foreground/50"
              autoFocus
            />
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Describe what success looks like — Dash uses this to judge progress."
              rows={2}
              className="w-full bg-transparent text-sm outline-none resize-none placeholder:text-muted-foreground/50"
            />
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                <input
                  type="date"
                  value={newDate}
                  onChange={(e) => setNewDate(e.target.value)}
                  className="bg-transparent text-xs text-muted-foreground outline-none"
                />
              </div>
              <div className="flex-1" />
              <button
                onClick={() => setCreating(false)}
                className="rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={!newTitle.trim()}
                className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground disabled:opacity-40"
              >
                Create
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="space-y-3">
            {[1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />)}
          </div>
        ) : goals.length === 0 && !creating ? (
          <div className="py-8 text-center">
            <Target className="mx-auto h-8 w-8 text-muted-foreground/30" />
            <p className="mt-2 text-sm font-medium">No goals yet</p>
            <p className="mt-1 text-xs text-muted-foreground max-w-sm mx-auto">
              Add a goal like &ldquo;ship onboarding v2 by end of May&rdquo; or
              &ldquo;double signup conversion by Q3.&rdquo; Dash re-evaluates every brief —
              estimating progress, setting trajectory, and proposing weekly action items.
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <button
                onClick={() => setCreating(true)}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3 w-3" /> Add your first goal
              </button>
              <span className="text-[10px] text-muted-foreground">or</span>
              <button
                onClick={() => onNavigateToChat("What goals should I be tracking based on what we're working on?")}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                Ask Dash to suggest some
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {active.map((g) => (
              <GoalCard
                key={g.id}
                goal={g}
                expanded={expandedId === g.id}
                onToggle={() => setExpandedId(expandedId === g.id ? null : g.id)}
                onComplete={() => handleComplete(g.id)}
                onDelete={() => handleDelete(g.id)}
                onChat={(prompt) => onNavigateToChat(prompt)}
              />
            ))}
            {done.length > 0 && (
              <div className="pt-2">
                <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                  Completed ({done.length})
                </p>
                {done.slice(0, 3).map((g) => (
                  <div key={g.id} className="flex items-center gap-2 py-1.5 opacity-50">
                    <Check className="h-3.5 w-3.5 text-green-500" />
                    <span className="text-sm line-through">{g.title}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GoalCard({
  goal,
  expanded,
  onToggle,
  onComplete,
  onDelete,
  onChat,
}: {
  goal: Goal;
  expanded: boolean;
  onToggle: () => void;
  onComplete: () => void;
  onDelete: () => void;
  onChat: (prompt: string) => void;
}) {
  const daysLeft = goal.target_date
    ? Math.ceil((new Date(goal.target_date).getTime() - Date.now()) / 86400_000)
    : null;
  const isOverdue = daysLeft !== null && daysLeft < 0;
  const isUrgent = daysLeft !== null && daysLeft >= 0 && daysLeft <= 7;
  const trajectoryStyle = goal.trajectory ? TRAJECTORY_COLOR[goal.trajectory] : "";
  const items = goal.action_items || [];

  function actionPrompt(item: GoalActionItem) {
    const refs = (item.references || [])
      .map((r) => (r.url ? `${r.title} (${r.url})` : r.title))
      .join(", ");
    return (
      `Goal: "${goal.title}" (${goal.progress}% — ${goal.trajectory || "unrated"})\n` +
      `Action: ${item.title}\n` +
      (item.description ? `Context: ${item.description}\n` : "") +
      (refs ? `References: ${refs}\n` : "") +
      `Help me make progress on this.`
    );
  }

  return (
    <div className="group rounded-xl border border-border transition-all hover:shadow-sm">
      <div className="px-4 py-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium">{goal.title}</p>
              {goal.trajectory && (
                <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-medium", trajectoryStyle)}>
                  {goal.trajectory}
                </span>
              )}
            </div>
            {goal.description && (
              <p className="mt-0.5 text-[13px] text-muted-foreground">{goal.description}</p>
            )}

            <div className="mt-3 flex items-center gap-3">
              <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    isOverdue
                      ? "bg-red-400"
                      : goal.progress >= 80
                      ? "bg-green-500"
                      : goal.trajectory === "at-risk" || goal.trajectory === "behind"
                      ? "bg-amber-500"
                      : "bg-primary"
                  )}
                  style={{ width: `${Math.min(goal.progress, 100)}%` }}
                />
              </div>
              <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
                {goal.progress}%
              </span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
              {goal.target_date && (
                <div className={cn("flex items-center gap-1", isOverdue && "text-red-600", isUrgent && "text-amber-600")}>
                  <Calendar className="h-3 w-3" />
                  {isOverdue ? `${Math.abs(daysLeft!)}d overdue` : `${daysLeft}d left`}
                </div>
              )}
              <div className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                Evaluated {timeAgo(goal.last_evaluated_at)}
              </div>
              {items.length > 0 && (
                <div className="flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" />
                  {items.length} action{items.length === 1 ? "" : "s"}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            {items.length > 0 && (
              <button
                onClick={onToggle}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted"
                title={expanded ? "Hide actions" : "Show actions"}
              >
                {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              </button>
            )}
            <button
              onClick={onComplete}
              className="rounded-md p-1 text-muted-foreground hover:bg-green-50 hover:text-green-600"
              title="Mark complete"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={onDelete}
              className="rounded-md p-1 text-muted-foreground hover:bg-red-50 hover:text-red-600"
              title="Delete"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {expanded && items.length > 0 && (
        <div className="border-t border-border bg-muted/20 px-4 py-3 space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Action items (from latest brief)
          </p>
          {items.map((item, i) => (
            <div key={i} className="flex items-start gap-2 rounded-lg bg-background px-3 py-2">
              <span
                className={cn(
                  "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                  PRIORITY_DOT[item.priority || "medium"]
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium leading-snug">{item.title}</p>
                {item.description && (
                  <p className="mt-0.5 text-[12px] text-muted-foreground">{item.description}</p>
                )}
                {(item.references || []).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(item.references || []).map((ref, j) => (
                      <a
                        key={j}
                        href={ref.url || undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                          ref.url
                            ? "border-primary/20 text-primary hover:bg-primary/5"
                            : "border-border text-muted-foreground"
                        )}
                      >
                        {ref.title}
                      </a>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => onChat(actionPrompt(item))}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-primary hover:bg-primary/5"
              >
                Address <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
