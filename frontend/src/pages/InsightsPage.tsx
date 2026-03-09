import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Insight } from "@/types/api";

const categoryColors: Record<string, string> = {
  anomaly: "bg-destructive/20 text-destructive",
  trend: "bg-blue-500/20 text-blue-400",
  recommendation: "bg-primary/20 text-primary",
  risk: "bg-orange-500/20 text-orange-400",
  opportunity: "bg-success/20 text-success",
};

const priorityColors: Record<string, string> = {
  critical: "text-destructive",
  high: "text-orange-400",
  medium: "text-warning",
  low: "text-muted-foreground",
};

const statusOptions = ["new", "acknowledged", "actioned", "dismissed"];

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function InsightsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["insights"],
    queryFn: () => apiGet<{ insights: Insight[] }>("/insights").then((r) => r.insights),
    refetchInterval: 30_000,
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiPatch(`/insights/${id}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["insights"] }),
  });

  const insights = (data || []).filter((i) => {
    if (statusFilter && i.status !== statusFilter) return false;
    if (categoryFilter && i.category !== categoryFilter) return false;
    return true;
  });

  const categories = [...new Set((data || []).map((i) => i.category))];

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Insights</h1>
        <p className="text-xs text-muted-foreground mt-0.5">AI-generated insights from signals and agent analysis</p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-card border border-border rounded-md px-2 py-1 text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
        >
          <option value="">Status: All</option>
          {statusOptions.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="bg-card border border-border rounded-md px-2 py-1 text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
        >
          <option value="">Category: All</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <span className="text-[10px] text-muted-foreground ml-auto">
          {insights.length} insight{insights.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Insights list */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-card border border-border rounded-md h-20 animate-pulse" />
          ))}
        </div>
      ) : insights.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-muted-foreground">No insights yet</p>
          <p className="text-xs text-muted-foreground/50 mt-1">Insights are generated from signals and agent analysis</p>
        </div>
      ) : (
        <div className="space-y-2">
          {insights.map((insight) => (
            <div key={insight.id} className="bg-card border border-border rounded-md p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-foreground">{insight.title}</span>
                    <span className={cn("text-[9px] px-1.5 py-0.5 rounded", categoryColors[insight.category] || "bg-muted text-muted-foreground")}>
                      {insight.category}
                    </span>
                    <span className={cn("text-[9px]", priorityColors[insight.priority])}>
                      {insight.priority}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">{insight.summary}</p>
                  <span className="text-[9px] text-muted-foreground/50 mt-1 block">{timeAgo(insight.createdAt)}</span>
                </div>
                <select
                  value={insight.status}
                  onChange={(e) => updateStatus.mutate({ id: insight.id, status: e.target.value })}
                  className="bg-muted border border-border rounded px-1.5 py-0.5 text-[10px] text-foreground focus:outline-none shrink-0"
                >
                  {statusOptions.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
