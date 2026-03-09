import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Brain, GitBranch, BarChart3, Shield, Lightbulb, AlertTriangle, TrendingUp, ChevronDown, ChevronRight } from "lucide-react";
import type { Insight } from "@/types/api";

const categoryConfig: Record<string, { icon: typeof Brain; color: string; bg: string }> = {
  anomaly: { icon: AlertTriangle, color: "text-destructive", bg: "bg-destructive/10" },
  trend: { icon: TrendingUp, color: "text-blue-400", bg: "bg-blue-500/10" },
  recommendation: { icon: Lightbulb, color: "text-primary", bg: "bg-primary/10" },
  risk: { icon: Shield, color: "text-orange-400", bg: "bg-orange-500/10" },
  opportunity: { icon: BarChart3, color: "text-success", bg: "bg-success/10" },
  strategy: { icon: Brain, color: "text-purple-400", bg: "bg-purple-500/10" },
  operations: { icon: GitBranch, color: "text-blue-400", bg: "bg-blue-500/10" },
  "cross-domain": { icon: Brain, color: "text-primary", bg: "bg-primary/10" },
  "cross-domain-synthesis": { icon: Brain, color: "text-primary", bg: "bg-primary/10" },
  "product-strategy": { icon: Lightbulb, color: "text-primary", bg: "bg-primary/10" },
  process: { icon: GitBranch, color: "text-blue-400", bg: "bg-blue-500/10" },
};

const priorityDots: Record<string, string> = {
  critical: "bg-destructive",
  high: "bg-orange-400",
  medium: "bg-warning",
  low: "bg-muted-foreground",
};

const statusOptions = ["new", "acknowledged", "actioned", "dismissed"];

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = Date.now();
  const diff = now - date.getTime();
  const mins = Math.floor(diff / 60000);

  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function InsightsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
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
    <div className="p-6 max-w-[900px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Insights Feed</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Agent analysis and strategic findings</p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 mb-5">
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

      {/* Thread-style insights feed */}
      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-card border border-border rounded-md animate-pulse" />
          ))}
        </div>
      ) : insights.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-muted-foreground">No insights yet</p>
          <p className="text-xs text-muted-foreground/50 mt-1">Insights are generated from agent synthesis</p>
        </div>
      ) : (
        <div className="relative">
          {/* Timeline line */}
          <div className="absolute left-[19px] top-0 bottom-0 w-px bg-border" />

          <div className="space-y-1">
            {insights.map((insight) => {
              const config = categoryConfig[insight.category] || categoryConfig.recommendation;
              const Icon = config.icon;
              const isExpanded = expandedId === insight.id;

              return (
                <div key={insight.id} className="relative pl-11">
                  {/* Timeline dot */}
                  <div className={cn(
                    "absolute left-2.5 top-4 w-5 h-5 rounded-full flex items-center justify-center z-10",
                    config.bg
                  )}>
                    <Icon size={11} className={config.color} />
                  </div>

                  {/* Card */}
                  <div className={cn(
                    "border border-border rounded-md transition-colors",
                    isExpanded ? "bg-card" : "bg-card/50 hover:bg-card"
                  )}>
                    {/* Header row */}
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : insight.id)}
                      className="w-full flex items-start gap-3 px-4 py-3 text-left"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="label-uppercase">{insight.category}</span>
                          <span className="text-[8px] text-muted-foreground/40">·</span>
                          <div className={cn("w-1.5 h-1.5 rounded-full", priorityDots[insight.priority])} />
                          <span className="text-[9px] text-muted-foreground">{insight.priority}</span>
                          <span className="text-[8px] text-muted-foreground/40">·</span>
                          <span className="text-[9px] text-muted-foreground">{formatTime(insight.createdAt)}</span>
                        </div>
                        <p className="text-xs font-medium text-foreground leading-snug">{insight.title}</p>
                      </div>
                      {isExpanded
                        ? <ChevronDown size={12} className="text-muted-foreground mt-1 shrink-0" />
                        : <ChevronRight size={12} className="text-muted-foreground mt-1 shrink-0" />
                      }
                    </button>

                    {/* Expanded content */}
                    {isExpanded && (
                      <div className="px-4 pb-3 border-t border-border/50">
                        <p className="text-xs text-muted-foreground leading-relaxed mt-3 whitespace-pre-wrap">
                          {insight.summary}
                        </p>
                        <div className="flex items-center justify-between mt-3 pt-2 border-t border-border/30">
                          <div className="flex items-center gap-2">
                            <span className="label-uppercase">SOURCE</span>
                            <span className="text-[9px] text-primary">Head of Product (Synthesis)</span>
                          </div>
                          <select
                            value={insight.status}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              e.stopPropagation();
                              updateStatus.mutate({ id: insight.id, status: e.target.value });
                            }}
                            className="bg-muted border border-border rounded px-1.5 py-0.5 text-[10px] text-foreground focus:outline-none"
                          >
                            {statusOptions.map((s) => (
                              <option key={s} value={s}>{s}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
