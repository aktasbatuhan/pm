"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fetchSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
  type Schedule,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Clock,
  Plus,
  Trash2,
  Play,
  Pause,
  Check,
  X,
  Loader2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

const SCHEDULE_PRESETS = [
  { label: "Every 6 hours", value: "every 6h", desc: "Runs 4 times a day" },
  { label: "Daily at 9am", value: "0 9 * * *", desc: "Once per morning" },
  { label: "Weekly Monday", value: "0 9 * * 1", desc: "Monday at 9am" },
  { label: "Monthly 1st", value: "0 9 1 * *", desc: "1st of each month" },
];

export function SchedulesPanel() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const s = await fetchSchedules();
    setSchedules(s);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleToggle(id: string, enabled: boolean) {
    await updateSchedule(id, { enabled: !enabled });
    setSchedules((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !enabled } : s))
    );
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this scheduled task?")) return;
    await deleteSchedule(id);
    load();
  }

  function timeUntil(iso: string | null): string {
    if (!iso) return "—";
    const diff = new Date(iso).getTime() - Date.now();
    if (diff < 0) return "overdue";
    if (diff < 3600_000) return `${Math.ceil(diff / 60_000)}m`;
    if (diff < 86400_000) return `${Math.ceil(diff / 3600_000)}h`;
    return `${Math.ceil(diff / 86400_000)}d`;
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2 pb-3">
        <Clock className="h-4 w-4 text-muted-foreground" />
        <CardTitle className="text-base">Scheduled Tasks</CardTitle>
        <Badge variant="secondary" className="ml-1">
          {schedules.filter((s) => s.enabled).length} active
        </Badge>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted"
        >
          <Plus className="h-3 w-3" /> New
        </button>
      </CardHeader>
      <CardContent>
        {showAdd && (
          <AddScheduleForm
            onClose={() => setShowAdd(false)}
            onCreated={() => { setShowAdd(false); load(); }}
          />
        )}

        {loading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />)}
          </div>
        ) : schedules.length === 0 && !showAdd ? (
          <div className="py-8 text-center">
            <Clock className="mx-auto h-8 w-8 text-muted-foreground/30" />
            <p className="mt-2 text-sm text-muted-foreground">No scheduled tasks</p>
            <p className="mt-1 text-xs text-muted-foreground">Daily briefs and report schedules show up here</p>
          </div>
        ) : (
          <div className="space-y-2">
            {schedules.map((s) => {
              const isExpanded = expandedId === s.id;
              return (
                <div key={s.id} className={cn(
                  "rounded-lg border transition-colors",
                  s.enabled ? "border-border" : "border-border/50 opacity-60"
                )}>
                  <div className="flex items-center gap-3 px-4 py-3">
                    {/* Status dot */}
                    <div className={cn(
                      "h-2 w-2 rounded-full shrink-0",
                      s.enabled ? "bg-green-500" : "bg-muted-foreground/30"
                    )} />

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{s.name}</p>
                      <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
                        <span>{s.schedule_display}</span>
                        {s.next_run_at && (
                          <>
                            <span className="text-border">·</span>
                            <span>Next: {timeUntil(s.next_run_at)}</span>
                          </>
                        )}
                        {s.last_status && (
                          <>
                            <span className="text-border">·</span>
                            <span className={s.last_status === "success" ? "text-green-600" : "text-red-600"}>
                              Last: {s.last_status}
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : s.id)}
                        className="rounded-md p-1 text-muted-foreground hover:bg-muted"
                        title="Show prompt"
                      >
                        {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        onClick={() => handleToggle(s.id, s.enabled)}
                        className={cn(
                          "rounded-md p-1 transition-colors",
                          s.enabled
                            ? "text-amber-600 hover:bg-amber-50"
                            : "text-green-600 hover:bg-green-50"
                        )}
                        title={s.enabled ? "Pause" : "Resume"}
                      >
                        {s.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        onClick={() => handleDelete(s.id)}
                        className="rounded-md p-1 text-muted-foreground hover:text-red-600 hover:bg-red-50"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Expanded: show the prompt */}
                  {isExpanded && (
                    <div className="border-t border-border px-4 py-3 animate-in fade-in slide-in-from-top-2 duration-200">
                      <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">Agent prompt</p>
                      <pre className="text-xs text-muted-foreground whitespace-pre-wrap max-h-40 overflow-y-auto bg-muted rounded-md p-2">
                        {s.prompt}
                      </pre>
                      <div className="mt-2 flex items-center gap-4 text-[10px] text-muted-foreground">
                        <span>Runs: {s.repeat.times === null ? "forever" : `${s.repeat.completed}/${s.repeat.times}`}</span>
                        {s.last_run_at && <span>Last ran: {new Date(s.last_run_at).toLocaleString()}</span>}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AddScheduleForm({
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

  async function handleSave() {
    if (!prompt.trim() || !schedule.trim()) return;
    setSaving(true);
    await createSchedule({
      name: name.trim() || prompt.slice(0, 40),
      prompt: prompt.trim(),
      schedule: schedule.trim(),
    });
    setSaving(false);
    onCreated();
  }

  return (
    <div className="mb-4 rounded-lg border border-primary/20 bg-primary/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-primary">New scheduled task</p>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>
      </div>

      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name (e.g. Daily Risk Check)"
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40"
        autoFocus
      />

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="What should Dash do? Write a self-contained prompt. The agent won't have context from this conversation."
        rows={4}
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none resize-none focus:border-primary/40"
      />

      <div>
        <p className="text-[11px] text-muted-foreground mb-1.5">Schedule</p>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {SCHEDULE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => setSchedule(p.value)}
              className={cn(
                "rounded-md border px-2.5 py-1 text-[11px] transition-colors",
                schedule === p.value
                  ? "border-primary bg-primary/10 text-primary font-medium"
                  : "border-border text-muted-foreground hover:border-primary/30"
              )}
              title={p.desc}
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
          className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[11px] outline-none focus:border-primary/40"
        />
      </div>

      <button
        onClick={handleSave}
        disabled={!prompt.trim() || !schedule.trim() || saving}
        className="w-full flex items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
      >
        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
        Create schedule
      </button>
    </div>
  );
}
