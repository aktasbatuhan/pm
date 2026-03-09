import { cn } from "@/lib/utils";
import type { Kpi } from "@/types/agents";

const statusColors: Record<string, string> = {
  "on-track": "text-success",
  "at-risk": "text-warning",
  "breached": "text-destructive",
};

const barColors: Record<string, string> = {
  "on-track": "bg-success",
  "at-risk": "bg-warning",
  "breached": "bg-destructive",
};

interface KpiGaugeProps {
  kpi: Kpi;
}

export function KpiGauge({ kpi }: KpiGaugeProps) {
  const current = kpi.currentValue ?? 0;
  const target = kpi.targetValue || 1;
  const isLower = kpi.direction === "lower_is_better";
  const pct = isLower
    ? Math.max(0, Math.min(100, ((target - current) / target) * 100 + 50))
    : Math.max(0, Math.min(100, (current / target) * 100));

  return (
    <div className="bg-card border border-border rounded-md p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">{kpi.displayName}</span>
        <span className={cn("text-xs", statusColors[kpi.status])}>{kpi.status}</span>
      </div>

      <div className="flex items-baseline gap-1">
        <span className="text-lg font-bold text-foreground">
          {current}
        </span>
        <span className="text-xs text-muted-foreground">
          / {target} {kpi.unit}
        </span>
      </div>

      <div className="h-1 bg-muted rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", barColors[kpi.status])}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
