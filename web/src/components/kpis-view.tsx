"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchKPIs,
  createKPI,
  deleteKPI,
  refreshKPI,
  updateKPIFlag,
  type KPI,
  type KPIFlag,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Target,
  Plus,
  Trash2,
  Loader2,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  Sparkles,
  X,
  Check,
  ArrowRight,
} from "lucide-react";

const STATUS_TEXT: Record<string, string> = {
  pending: "Dash is configuring…",
  configured: "Auto-measured",
  failed: "Couldn't wire this up",
};

function formatValue(v: number | null, unit: string | null | undefined) {
  if (v === null || v === undefined) return "—";
  const abs = Math.abs(v);
  let body: string;
  if (abs >= 1_000_000) body = (v / 1_000_000).toFixed(1) + "M";
  else if (abs >= 1_000) body = (v / 1_000).toFixed(1) + "k";
  else if (abs < 10 && !Number.isInteger(v)) body = v.toFixed(2);
  else body = v.toString();
  return unit ? `${body} ${unit}` : body;
}

function changePct(curr: number | null, prev: number | null): number | null {
  if (curr === null || prev === null || prev === 0) return null;
  return ((curr - prev) / Math.abs(prev)) * 100;
}

function timeAgo(ts: number | null): string {
  if (!ts) return "never";
  const diff = Date.now() - ts * 1000;
  if (diff < 60_000) return "just now";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
  if (diff < 604800_000) return `${Math.floor(diff / 86400_000)}d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

function Sparkline({ values, direction }: { values: number[]; direction: "higher" | "lower" }) {
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const W = 120;
  const H = 32;
  const step = W / (values.length - 1);
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(H - ((v - min) / range) * H).toFixed(1)}`)
    .join(" ");
  const lastIdx = values.length - 1;
  const trend = values[lastIdx] - values[0];
  const goingWithDirection = direction === "higher" ? trend > 0 : trend < 0;
  const stroke = Math.abs(trend) < range * 0.05
    ? "#9ca3af"
    : goingWithDirection
    ? "#10b981"
    : "#ef4444";
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="shrink-0">
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

interface Props {
  onNavigateToChat: (prompt: string) => void;
}

export function KPIsView({ onNavigateToChat }: Props) {
  const [kpis, setKpis] = useState<KPI[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const ks = await fetchKPIs("active");
    setKpis(ks);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    // Poll more often when any KPI is still configuring
    const anyPending = kpis.some((k) => k.measurement_status === "pending");
    if (!anyPending) return;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [kpis, load]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this KPI and its history?")) return;
    await deleteKPI(id);
    load();
  }

  async function handleRefresh(id: string) {
    setRefreshingId(id);
    await refreshKPI(id);
    setTimeout(() => { setRefreshingId(null); load(); }, 4000);
  }

  async function handleDismissFlag(flagId: string) {
    await updateKPIFlag(flagId, "dismissed");
    load();
  }

  async function handleResolveFlag(flagId: string) {
    await updateKPIFlag(flagId, "resolved");
    load();
  }

  function flagPrompt(kpi: KPI, flag: KPIFlag): string {
    const refs = (flag.references || [])
      .map((r) => (r.url ? `${r.title} (${r.url})` : r.title))
      .join(", ");
    return (
      `KPI: ${kpi.name} — currently ${formatValue(kpi.current_value, kpi.unit)}\n` +
      `${flag.kind === "risk" ? "Risk" : "Opportunity"}: ${flag.title}\n` +
      (flag.description ? `Context: ${flag.description}\n` : "") +
      (refs ? `References: ${refs}\n` : "") +
      `Help me address this.`
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-4xl px-8 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">KPIs</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Dash tracks these metrics, auto-measures them, and flags only what matters.
            </p>
          </div>
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-3.5 w-3.5" /> Add KPI
          </button>
        </div>

        {creating && (
          <AddKPIForm onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />
        )}

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-muted" />)}
          </div>
        ) : kpis.length === 0 && !creating ? (
          <Card>
            <CardContent className="py-12 text-center">
              <Target className="mx-auto h-8 w-8 text-muted-foreground/30" />
              <p className="mt-3 text-sm font-medium">No KPIs yet</p>
              <p className="mt-1 text-xs text-muted-foreground max-w-sm mx-auto">
                Add a KPI like &ldquo;weekly active users&rdquo; or &ldquo;signup conversion rate&rdquo;.
                Dash will figure out how to measure it from your connected platforms,
                refresh values daily, and flag risks/opportunities in your daily brief.
              </p>
              <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                <button
                  onClick={() => setCreating(true)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <Plus className="h-3 w-3" /> Add your first KPI
                </button>
                <span className="text-[10px] text-muted-foreground">or</span>
                <button
                  onClick={() => onNavigateToChat("Suggest 3 KPIs we should track based on my workspace.")}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  Ask Dash to suggest some
                </button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {kpis.map((k) => (
              <KPICard
                key={k.id}
                kpi={k}
                refreshing={refreshingId === k.id}
                onRefresh={() => handleRefresh(k.id)}
                onDelete={() => handleDelete(k.id)}
                onDismissFlag={handleDismissFlag}
                onResolveFlag={handleResolveFlag}
                onChat={(prompt) => onNavigateToChat(prompt)}
                flagPrompt={(f) => flagPrompt(k, f)}
              />
            ))}
          </div>
        )}

        <div className="h-16" />
      </div>
    </ScrollArea>
  );
}

function KPICard({
  kpi,
  refreshing,
  onRefresh,
  onDelete,
  onDismissFlag,
  onResolveFlag,
  onChat,
  flagPrompt,
}: {
  kpi: KPI;
  refreshing: boolean;
  onRefresh: () => void;
  onDelete: () => void;
  onDismissFlag: (id: string) => void;
  onResolveFlag: (id: string) => void;
  onChat: (prompt: string) => void;
  flagPrompt: (f: KPIFlag) => string;
}) {
  const change = changePct(kpi.current_value, kpi.previous_value);
  const goingWithDirection =
    change !== null && (kpi.direction === "higher" ? change > 0 : change < 0);
  const steady = change === null || Math.abs(change) < 1;
  const TrendIcon = steady ? Minus : goingWithDirection ? TrendingUp : TrendingDown;
  const trendClass = steady
    ? "text-muted-foreground"
    : goingWithDirection
    ? "text-green-600"
    : "text-red-600";

  const sparkValues = [...kpi.history].reverse().slice(-20).map((h) => h.value);

  const openFlags = (kpi.flags || []).filter((f) => f.status === "open");

  return (
    <div className="rounded-xl border border-border bg-card transition-all">
      <div className="flex items-start gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold">{kpi.name}</p>
            {kpi.measurement_status === "pending" && (
              <Badge variant="secondary" className="text-[10px]">
                <Loader2 className="mr-1 h-2.5 w-2.5 animate-spin" />
                Configuring
              </Badge>
            )}
            {kpi.measurement_status === "failed" && (
              <Badge variant="destructive" className="text-[10px]">Failed</Badge>
            )}
          </div>
          {kpi.description && (
            <p className="mt-0.5 text-[12px] text-muted-foreground">{kpi.description}</p>
          )}

          <div className="mt-3 flex items-baseline gap-3">
            <span className="text-2xl font-semibold tabular-nums">
              {formatValue(kpi.current_value, kpi.unit)}
            </span>
            {change !== null && (
              <span className={cn("inline-flex items-center gap-1 text-[12px] font-medium", trendClass)}>
                <TrendIcon className="h-3 w-3" />
                {change >= 0 ? "+" : ""}{change.toFixed(1)}%
              </span>
            )}
            {kpi.target_value !== null && kpi.target_value !== undefined && (
              <span className="text-[11px] text-muted-foreground">
                target {formatValue(kpi.target_value, kpi.unit)}
              </span>
            )}
          </div>

          <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
            <span>{STATUS_TEXT[kpi.measurement_status] || kpi.measurement_status}</span>
            <span>· measured {timeAgo(kpi.last_measured_at)}</span>
            {kpi.measurement_error && (
              <span className="text-red-600" title={kpi.measurement_error}>
                · {kpi.measurement_error}
              </span>
            )}
          </div>
        </div>

        <Sparkline values={sparkValues} direction={kpi.direction} />

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
            title="Refresh now"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button
            onClick={onDelete}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-600"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {openFlags.length > 0 && (
        <div className="border-t border-border bg-muted/30 px-5 py-3 space-y-2">
          {openFlags.map((f) => (
            <div
              key={f.id}
              className={cn(
                "flex items-start gap-3 rounded-lg border px-3 py-2",
                f.kind === "risk"
                  ? "border-red-200 bg-red-50/40"
                  : "border-emerald-200 bg-emerald-50/40"
              )}
            >
              {f.kind === "risk" ? (
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
              ) : (
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium">{f.title}</p>
                {f.description && (
                  <p className="mt-0.5 text-[12px] text-muted-foreground">{f.description}</p>
                )}
                {(f.references || []).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {f.references.map((ref, i) => (
                      <a
                        key={i}
                        href={ref.url || undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]",
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
              <div className="flex shrink-0 items-center gap-1">
                <button
                  onClick={() => onChat(flagPrompt(f))}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-primary hover:bg-primary/5"
                >
                  Address <ArrowRight className="h-3 w-3" />
                </button>
                <button
                  onClick={() => onResolveFlag(f.id)}
                  className="rounded-md p-1 text-muted-foreground hover:bg-green-100 hover:text-green-600"
                  title="Mark resolved"
                >
                  <Check className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => onDismissFlag(f.id)}
                  className="rounded-md p-1 text-muted-foreground hover:bg-muted"
                  title="Dismiss"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AddKPIForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [unit, setUnit] = useState("");
  const [direction, setDirection] = useState<"higher" | "lower">("higher");
  const [target, setTarget] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    const targetValue = target.trim() === "" ? null : Number(target);
    const result = await createKPI({
      name: name.trim(),
      description: description.trim(),
      unit: unit.trim(),
      direction,
      target_value: Number.isFinite(targetValue) ? targetValue : null,
    });
    setSaving(false);
    if (!result.ok) {
      setError(result.error || "Failed to create KPI");
      return;
    }
    onCreated();
  }

  return (
    <Card className="mb-6 border-primary/20 bg-primary/5">
      <CardContent className="pt-5 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-primary">New KPI</p>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Weekly active users"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/40"
          autoFocus
        />

        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional: what this measures, any caveats. Dash uses this to pick the right measurement."
          rows={2}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none resize-none focus:border-primary/40"
        />

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="Unit (%, $, users)"
            className="w-32 rounded-lg border border-border bg-background px-3 py-1.5 text-xs outline-none focus:border-primary/40"
          />
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="Target (optional)"
            className="w-36 rounded-lg border border-border bg-background px-3 py-1.5 text-xs outline-none focus:border-primary/40"
          />
          <div className="flex rounded-lg border border-border p-0.5 text-[11px]">
            <button
              onClick={() => setDirection("higher")}
              className={cn(
                "rounded px-2 py-1",
                direction === "higher" ? "bg-primary text-primary-foreground" : "text-muted-foreground"
              )}
            >
              Higher better
            </button>
            <button
              onClick={() => setDirection("lower")}
              className={cn(
                "rounded px-2 py-1",
                direction === "lower" ? "bg-primary text-primary-foreground" : "text-muted-foreground"
              )}
            >
              Lower better
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between pt-1">
          <p className="text-[11px] text-muted-foreground">
            Dash will figure out how to measure this from your connected platforms.
          </p>
          <div className="flex gap-2">
            <button onClick={onClose} className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted">
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!name.trim() || saving}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
              Add KPI
            </button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
