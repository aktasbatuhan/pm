import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSubAgents, useEscalations, useKpis, useSynthesisRuns, useReplySynthesis, useSuggestions, useDiscussSuggestion, useUpdateSuggestionStatus } from "@/hooks/use-agents";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ExpandableText } from "@/components/ui/expandable-text";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { openChatSession } from "@/components/layout/AppShell";
import type { DashboardResponse, DashboardWidget, Suggestion } from "@/types/api";
import type { SubAgent, Escalation } from "@/types/agents";

// Agent avatars (shared with AgentsPage)
const agentAvatars: Record<string, { emoji: string; color: string }> = {
  "sprint-health": { emoji: "🏃", color: "text-blue-400" },
  "code-quality": { emoji: "🔧", color: "text-purple-400" },
  "product-signals": { emoji: "📡", color: "text-green-400" },
  "team-dynamics": { emoji: "👥", color: "text-orange-400" },
};

function timeAgo(dateStr?: string): string {
  if (!dateStr) return "never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function OverviewPage() {
  const { data: agents } = useSubAgents();
  const { data: escalations } = useEscalations();
  const { data: kpis } = useKpis();
  const { data: synthesisRuns } = useSynthesisRuns(1);
  const { data: dashboard } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiGet<DashboardResponse>("/dashboard"),
    refetchInterval: 120_000,
  });
  const { data: widgetsData } = useQuery({
    queryKey: ["dashboard-layout"],
    queryFn: () => apiGet<{ widgets: DashboardWidget[] }>("/dashboard/layout"),
    refetchInterval: 120_000,
  });
  const { data: suggestions } = useSuggestions();

  const latestSynthesis = synthesisRuns?.[0];
  const pendingEsc = escalations?.filter((e) => e.status === "pending") || [];
  const criticalEsc = pendingEsc.filter((e) => e.urgency === "critical" || e.urgency === "urgent");
  const overview = dashboard?.stats?.overview;
  const widgets = widgetsData?.widgets || [];
  const activeSuggestions = suggestions?.filter((s) => s.status !== "dismissed") || [];

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Mission Control</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Executive overview, updated by the Head of Product</p>
      </div>

      {/* Executive Summary — latest synthesis */}
      <section className="mb-6">
        <div className={cn(
          "rounded-md p-5 border",
          criticalEsc.length > 0
            ? "bg-destructive/5 border-destructive/20"
            : "bg-card border-border"
        )}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">🧠</span>
            <span className="text-xs font-medium text-foreground">Head of Product</span>
            <span className="text-[8px] text-muted-foreground/40">·</span>
            <span className="label-uppercase">EXECUTIVE SUMMARY</span>
            {latestSynthesis && (
              <>
                <span className="text-[8px] text-muted-foreground/40">·</span>
                <span className="text-[9px] text-muted-foreground">{timeAgo(latestSynthesis.createdAt)}</span>
              </>
            )}
          </div>
          {latestSynthesis ? (
            <ExpandableText content={latestSynthesis.summary} collapsedLines={6} />
          ) : (
            <p className="text-xs text-muted-foreground">Waiting for first synthesis run...</p>
          )}
          {latestSynthesis && <SynthesisReply synthesisId={latestSynthesis.id} />}
        </div>
      </section>

      {/* Quick stats row */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        <QuickStat
          label="AGENTS"
          value={agents?.filter((a) => a.status === "active").length ?? 0}
          sub={`${agents?.length ?? 0} total`}
        />
        <QuickStat
          label="KPIS"
          value={kpis?.filter((k) => k.status === "on-track").length ?? 0}
          sub={`${kpis?.length ?? 0} tracked`}
          color={kpis?.some((k) => k.status === "breached") ? "text-destructive" : undefined}
        />
        <QuickStat
          label="ESCALATIONS"
          value={pendingEsc.length}
          sub={criticalEsc.length > 0 ? `${criticalEsc.length} critical` : "none critical"}
          color={criticalEsc.length > 0 ? "text-destructive" : undefined}
        />
        {overview && (
          <>
            <QuickStat label="ITEMS" value={overview.total} sub={`${overview.completionPct}% done`} />
            <QuickStat
              label="BLOCKED"
              value={overview.blocked}
              sub={`${overview.inProgressCount} in progress`}
              color={overview.blocked > 0 ? "text-warning" : undefined}
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Col 1: Agent status */}
        <section>
          <h2 className="label-uppercase mb-3">AGENT TEAM</h2>
          <div className="space-y-2">
            {/* Head of Product */}
            <div className="bg-card border border-border rounded-md px-3 py-2.5 flex items-center gap-3">
              <span className="text-base">🧠</span>
              <div className="flex-1 min-w-0">
                <span className="text-xs font-medium text-foreground">Head of Product</span>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[9px] text-success">● lead</span>
                  <span className="text-[9px] text-muted-foreground">
                    Last: {latestSynthesis ? timeAgo(latestSynthesis.createdAt) : "never"}
                  </span>
                </div>
              </div>
            </div>

            {(agents || []).map((agent) => {
              const av = agentAvatars[agent.name] || { emoji: "🤖", color: "text-muted-foreground" };
              const agentEsc = pendingEsc.filter((e) => e.agentId === agent.id);
              return (
                <div key={agent.id} className="bg-card border border-border rounded-md px-3 py-2.5 flex items-center gap-3">
                  <span className="text-base">{av.emoji}</span>
                  <div className="flex-1 min-w-0">
                    <span className="text-xs font-medium text-foreground">{agent.displayName}</span>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={cn("text-[9px]",
                        agent.status === "active" ? "text-success" : "text-warning"
                      )}>
                        ● {agent.status}
                      </span>
                      <span className="text-[9px] text-muted-foreground">Last: {timeAgo(agent.lastRunAt)}</span>
                      {agentEsc.length > 0 && (
                        <span className="text-[9px] text-warning">{agentEsc.length} alert{agentEsc.length !== 1 ? "s" : ""}</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Col 2: KPIs */}
        <section>
          <h2 className="label-uppercase mb-3">KEY METRICS</h2>
          {kpis && kpis.length > 0 ? (
            <div className="space-y-2">
              {kpis.map((kpi) => {
                const measured = kpi.currentValue != null;
                const current = kpi.currentValue ?? 0;
                const target = kpi.targetValue || 1;
                const pct = measured ? Math.max(0, Math.min(100, (current / target) * 100)) : 0;
                const color = kpi.status === "on-track" ? "bg-success" : kpi.status === "at-risk" ? "bg-warning" : "bg-destructive";
                const textColor = measured
                  ? (kpi.status === "on-track" ? "text-success" : kpi.status === "at-risk" ? "text-warning" : "text-destructive")
                  : "text-muted-foreground";
                const statusLabel = measured ? kpi.status : "pending";

                return (
                  <div key={kpi.id} className="bg-card border border-border rounded-md px-3 py-2.5">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-foreground">{kpi.displayName}</span>
                      <span className={cn("text-[9px]", textColor)}>{statusLabel}</span>
                    </div>
                    <div className="flex items-baseline gap-1 mb-1.5">
                      <span className="text-sm font-bold text-foreground">{measured ? current : "—"}</span>
                      <span className="text-[9px] text-muted-foreground">/ {target} {kpi.unit}</span>
                    </div>
                    <div className="h-1 bg-muted rounded-full overflow-hidden">
                      {measured && <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="bg-card border border-border rounded-md p-4 text-center">
              <p className="text-xs text-muted-foreground">KPIs pending first synthesis</p>
            </div>
          )}
        </section>

        {/* Col 3: Escalations */}
        <section>
          <h2 className="label-uppercase mb-3">
            ESCALATIONS
            {pendingEsc.length > 0 && (
              <span className="text-[9px] text-warning ml-2">{pendingEsc.length} pending</span>
            )}
          </h2>
          {pendingEsc.length > 0 ? (
            <div className="space-y-1.5">
              {pendingEsc.slice(0, 8).map((esc) => (
                <EscalationCard key={esc.id} esc={esc} agents={agents} />
              ))}
            </div>
          ) : (
            <div className="bg-card border border-border rounded-md p-4 text-center">
              <p className="text-xs text-muted-foreground">All clear</p>
            </div>
          )}
        </section>
      </div>

      {/* Suggestions from synthesis */}
      {activeSuggestions.length > 0 && (
        <section className="mt-6">
          <h2 className="label-uppercase mb-3">
            SUGGESTIONS
            <span className="text-[9px] text-muted-foreground ml-2">{activeSuggestions.length} open</span>
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {activeSuggestions.slice(0, 6).map((s) => (
              <SuggestionCard key={s.id} suggestion={s} />
            ))}
          </div>
        </section>
      )}

      {/* Agent-generated dashboard widgets */}
      {widgets.length > 0 && (
        <section className="mt-6">
          <h2 className="label-uppercase mb-3">DASHBOARD WIDGETS</h2>
          <div className="grid grid-cols-2 gap-3">
            {widgets.slice(0, 6).map((widget) => (
              <div
                key={widget.id}
                className={cn(
                  "bg-card border border-border rounded-md p-4",
                  widget.size === "full" && "col-span-2",
                  widget.size === "quarter" && "col-span-1"
                )}
              >
                <span className="label-uppercase mb-2 block">{widget.title}</span>
                <WidgetContent widget={widget} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function QuickStat({ label, value, sub, color }: { label: string; value: number; sub: string; color?: string }) {
  return (
    <div className="bg-card border border-border rounded-md px-3 py-2.5">
      <span className="label-uppercase">{label}</span>
      <p className={cn("text-xl font-bold mt-0.5", color || "text-foreground")}>{value}</p>
      <p className="text-[9px] text-muted-foreground">{sub}</p>
    </div>
  );
}

function WidgetContent({ widget }: { widget: DashboardWidget }) {
  const config = widget.config as Record<string, unknown>;

  if (widget.type === "stat-card") {
    return (
      <div>
        <p className={cn("text-xl font-bold", config.color === "red" ? "text-destructive" : config.color === "green" ? "text-success" : "text-foreground")}>
          {String(config.value || "")}
        </p>
        {config.label != null && <p className="text-[9px] text-muted-foreground">{String(config.label)}</p>}
        {config.trend != null && <p className="text-[9px] text-muted-foreground mt-0.5">{String(config.trend)}</p>}
      </div>
    );
  }

  if (widget.type === "markdown") {
    return <ExpandableText content={String(config.content || "")} collapsedLines={8} />;
  }

  if (widget.type === "list") {
    const items = (config.items as Array<{ text: string; color?: string }>) || [];
    return (
      <div className="space-y-1">
        {items.slice(0, 8).map((item, i) => (
          <p key={i} className="text-xs" style={item.color ? { color: item.color } : undefined}>{item.text}</p>
        ))}
      </div>
    );
  }

  if (widget.type === "table") {
    const headers = (config.headers as string[]) || [];
    const rows = (config.rows as string[][]) || [];
    return (
      <table className="w-full text-[10px]">
        <thead>
          <tr>{headers.map((h, i) => <th key={i} className="text-left py-1 text-muted-foreground font-normal">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 10).map((row, i) => (
            <tr key={i} className="border-t border-border/30">
              {row.map((cell, j) => <td key={j} className="py-1 text-foreground">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return <p className="text-[10px] text-muted-foreground">Widget type: {widget.type}</p>;
}

function EscalationCard({ esc, agents }: { esc: Escalation; agents?: SubAgent[] }) {
  const [expanded, setExpanded] = useState(false);
  const agent = agents?.find((a) => a.id === esc.agentId);
  const av = agent ? agentAvatars[agent.name] : undefined;
  const urgencyDot = esc.urgency === "critical" ? "bg-destructive" : esc.urgency === "urgent" ? "bg-orange-400" : esc.urgency === "attention" ? "bg-warning" : "bg-blue-400";

  return (
    <div className={cn("bg-card border border-border rounded-md overflow-hidden", expanded && "border-border/80")}>
      <button onClick={() => setExpanded(!expanded)} className="w-full px-3 py-2 text-left">
        <div className="flex items-start gap-2 mb-0.5">
          <div className={cn("w-1.5 h-1.5 rounded-full shrink-0 mt-1", urgencyDot)} />
          <span className="text-[10px] font-medium text-foreground leading-snug">{esc.title}</span>
        </div>
        <div className="flex items-center gap-2 pl-3.5">
          {av && <span className="text-[10px]">{av.emoji}</span>}
          <span className="text-[9px] text-muted-foreground">{agent?.displayName || "unknown"}</span>
          <span className="text-[8px] text-muted-foreground/40">·</span>
          <span className="text-[9px] text-muted-foreground">{timeAgo(esc.createdAt)}</span>
        </div>
      </button>
      {expanded && esc.summary && (
        <div className="px-3 pb-2.5 pt-1 border-t border-border/50">
          <MarkdownContent content={esc.summary} />
        </div>
      )}
    </div>
  );
}

function SynthesisReply({ synthesisId }: { synthesisId: string }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const reply = useReplySynthesis();

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-3 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      >
        💬 Reply with directive...
      </button>
    );
  }

  return (
    <div className="mt-3 border-t border-border/50 pt-3">
      <textarea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="e.g. Ignore the traffic spike — we started a campaign. Keep an eye on churn rate next week."
        className="w-full bg-background border border-border rounded px-2.5 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 resize-none focus:outline-none focus:ring-1 focus:ring-primary/30"
        rows={3}
        autoFocus
      />
      <div className="flex gap-2 mt-2">
        <button
          onClick={() => {
            if (!message.trim()) return;
            reply.mutate({ id: synthesisId, message: message.trim() });
            setMessage("");
            setOpen(false);
          }}
          disabled={reply.isPending || !message.trim()}
          className="px-3 py-1 text-[10px] font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
        >
          {reply.isPending ? "Saving..." : "Save directive"}
        </button>
        <button
          onClick={() => { setOpen(false); setMessage(""); }}
          className="px-3 py-1 text-[10px] text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

const categoryConfig: Record<string, { icon: string; color: string }> = {
  build: { icon: "🔨", color: "text-blue-400" },
  investigate: { icon: "🔍", color: "text-yellow-400" },
  improve: { icon: "📈", color: "text-green-400" },
  fix: { icon: "🔧", color: "text-orange-400" },
  experiment: { icon: "🧪", color: "text-purple-400" },
};

function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const [expanded, setExpanded] = useState(false);
  const discuss = useDiscussSuggestion();
  const updateStatus = useUpdateSuggestionStatus();
  const cat = categoryConfig[suggestion.category] || { icon: "💡", color: "text-muted-foreground" };

  const handleDiscuss = () => {
    discuss.mutate(suggestion.id, {
      onSuccess: (data) => {
        openChatSession(
          data.chatSessionId,
          `I'd like to discuss this suggestion: "${suggestion.title}". What's the full context and what would the implementation look like?`
        );
      },
    });
  };

  return (
    <div className="bg-card border border-border rounded-md overflow-hidden">
      <button onClick={() => setExpanded(!expanded)} className="w-full px-3 py-2.5 text-left">
        <div className="flex items-start gap-2">
          <span className="text-sm">{cat.icon}</span>
          <div className="flex-1 min-w-0">
            <span className="text-[10px] font-medium text-foreground leading-snug block">{suggestion.title}</span>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={cn("text-[9px]", cat.color)}>{suggestion.category}</span>
              <span className="text-[8px] text-muted-foreground/40">·</span>
              <span className="text-[9px] text-muted-foreground">{timeAgo(suggestion.createdAt)}</span>
              {suggestion.status === "discussing" && (
                <>
                  <span className="text-[8px] text-muted-foreground/40">·</span>
                  <span className="text-[9px] text-primary">discussing</span>
                </>
              )}
              {suggestion.status === "accepted" && (
                <>
                  <span className="text-[8px] text-muted-foreground/40">·</span>
                  <span className="text-[9px] text-success">accepted</span>
                </>
              )}
            </div>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 border-t border-border/50">
          <div className="pt-2">
            <MarkdownContent content={suggestion.rationale} />
          </div>
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleDiscuss}
              disabled={discuss.isPending}
              className="px-3 py-1 text-[10px] font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
            >
              {discuss.isPending ? "Opening..." : suggestion.chatSessionId ? "Continue discussion" : "Discuss"}
            </button>
            {suggestion.status !== "accepted" && (
              <button
                onClick={() => updateStatus.mutate({ id: suggestion.id, status: "accepted" })}
                className="px-3 py-1 text-[10px] text-success hover:bg-success/10 rounded"
              >
                Accept
              </button>
            )}
            <button
              onClick={() => updateStatus.mutate({ id: suggestion.id, status: "dismissed" })}
              className="px-3 py-1 text-[10px] text-muted-foreground hover:text-foreground"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
