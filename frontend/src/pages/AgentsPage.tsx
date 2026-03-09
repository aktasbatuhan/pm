import { useState } from "react";
import { useSubAgents, useEscalations, useKpis, useSynthesisRuns } from "@/hooks/use-agents";
import { cn } from "@/lib/utils";
import type { SubAgent, Escalation } from "@/types/agents";

const statusColors: Record<string, string> = {
  active: "text-success",
  paused: "text-warning",
  disabled: "text-muted-foreground",
};

function formatInterval(ms: number): string {
  const hours = ms / (1000 * 60 * 60);
  if (hours >= 1) return `${hours}h`;
  return `${ms / (1000 * 60)}m`;
}

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

type Tab = "agents" | "escalations" | "kpis" | "synthesis";

export function AgentsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("agents");
  const { data: agents, isLoading: agentsLoading } = useSubAgents();
  const { data: escalations, isLoading: escLoading } = useEscalations();
  const { data: kpis, isLoading: kpisLoading } = useKpis();
  const { data: runs, isLoading: synthLoading } = useSynthesisRuns(20);

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "agents", label: "Sub-Agents", count: agents?.length },
    { id: "escalations", label: "Escalations", count: escalations?.length },
    { id: "kpis", label: "KPIs", count: kpis?.length },
    { id: "synthesis", label: "Synthesis", count: runs?.length },
  ];

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Agent Team</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Sub-agent management, escalations, and KPI tracking</p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border mb-6">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "px-3 py-2 text-xs transition-colors border-b-2 -mb-px",
              activeTab === tab.id
                ? "text-primary border-primary"
                : "text-muted-foreground border-transparent hover:text-foreground"
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-1.5 text-[9px] text-muted-foreground">{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {activeTab === "agents" && (
        <AgentsTab agents={agents || []} loading={agentsLoading} />
      )}
      {activeTab === "escalations" && (
        <EscalationsTab escalations={escalations || []} loading={escLoading} />
      )}
      {activeTab === "kpis" && (
        <KpisTab kpis={kpis || []} loading={kpisLoading} />
      )}
      {activeTab === "synthesis" && (
        <SynthesisTab runs={runs || []} loading={synthLoading} />
      )}
    </div>
  );
}

function AgentsTab({ agents, loading }: { agents: SubAgent[]; loading: boolean }) {
  if (loading) return <Skeleton rows={4} />;

  if (agents.length === 0) {
    return <EmptyState text="No agents configured" sub="Complete setup to initialize the agent team" />;
  }

  return (
    <div className="space-y-3">
      {agents.map((agent) => (
        <div key={agent.id} className="bg-card border border-border rounded-md p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-foreground">{agent.displayName}</span>
              <span className={cn("text-[10px] px-1.5 py-0.5 rounded bg-muted", statusColors[agent.status])}>
                {agent.status}
              </span>
            </div>
            <span className="text-[10px] text-muted-foreground">ID: {agent.name}</span>
          </div>
          <p className="text-xs text-muted-foreground mb-3">{agent.domain}</p>
          <div className="grid grid-cols-4 gap-4">
            <MetaItem label="CYCLE" value={formatInterval(agent.scheduleIntervalMs)} />
            <MetaItem label="LAST RUN" value={timeAgo(agent.lastRunAt)} />
            <MetaItem label="NEXT RUN" value={timeAgo(agent.nextRunAt)} />
            <MetaItem label="MEMORY" value={agent.memoryPartition} />
          </div>
        </div>
      ))}
    </div>
  );
}

function EscalationsTab({ escalations, loading }: { escalations: Escalation[]; loading: boolean }) {
  if (loading) return <Skeleton rows={5} />;
  if (escalations.length === 0) return <EmptyState text="No escalations" sub="All agents operating normally" />;

  const urgencyOrder = { critical: 0, urgent: 1, attention: 2, info: 3 };
  const sorted = [...escalations].sort(
    (a, b) => (urgencyOrder[a.urgency] ?? 4) - (urgencyOrder[b.urgency] ?? 4)
  );

  const urgencyBadge: Record<string, string> = {
    info: "bg-blue-500/20 text-blue-400",
    attention: "bg-warning/20 text-warning",
    urgent: "bg-orange-500/20 text-orange-400",
    critical: "bg-destructive/20 text-destructive",
  };

  const statusBadge: Record<string, string> = {
    pending: "bg-warning/20 text-warning",
    synthesized: "bg-blue-500/20 text-blue-400",
    actioned: "bg-success/20 text-success",
    dismissed: "bg-muted text-muted-foreground",
  };

  return (
    <div className="border border-border rounded-md overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-muted/30 border-b border-border">
            <th className="text-left px-3 py-2 label-uppercase font-normal">Title</th>
            <th className="text-left px-3 py-2 label-uppercase font-normal w-20">Urgency</th>
            <th className="text-left px-3 py-2 label-uppercase font-normal w-24">Status</th>
            <th className="text-left px-3 py-2 label-uppercase font-normal w-28">Agent</th>
            <th className="text-left px-3 py-2 label-uppercase font-normal w-20">Time</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((esc) => (
            <tr key={esc.id} className="border-b border-border last:border-0 hover:bg-muted/20 transition-colors">
              <td className="px-3 py-2">
                <div className="text-foreground">{esc.title}</div>
                <div className="text-muted-foreground mt-0.5 line-clamp-1">{esc.summary}</div>
              </td>
              <td className="px-3 py-2">
                <span className={cn("text-[9px] px-1.5 py-0.5 rounded", urgencyBadge[esc.urgency])}>
                  {esc.urgency}
                </span>
              </td>
              <td className="px-3 py-2">
                <span className={cn("text-[9px] px-1.5 py-0.5 rounded", statusBadge[esc.status])}>
                  {esc.status}
                </span>
              </td>
              <td className="px-3 py-2 text-muted-foreground">{esc.agentId}</td>
              <td className="px-3 py-2 text-muted-foreground">{timeAgo(esc.createdAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KpisTab({ kpis, loading }: { kpis: import("@/types/agents").Kpi[]; loading: boolean }) {
  if (loading) return <Skeleton rows={4} />;
  if (kpis.length === 0) return <EmptyState text="No KPIs set" sub="The Head of Product will assign KPIs after first synthesis run" />;

  const statusColor: Record<string, string> = {
    "on-track": "text-success",
    "at-risk": "text-warning",
    "breached": "text-destructive",
  };

  const barColor: Record<string, string> = {
    "on-track": "bg-success",
    "at-risk": "bg-warning",
    "breached": "bg-destructive",
  };

  return (
    <div className="grid grid-cols-2 gap-3">
      {kpis.map((kpi) => {
        const current = kpi.currentValue ?? 0;
        const target = kpi.targetValue || 1;
        const pct = Math.max(0, Math.min(100, (current / target) * 100));

        return (
          <div key={kpi.id} className="bg-card border border-border rounded-md p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-foreground">{kpi.displayName}</span>
              <span className={cn("text-[10px]", statusColor[kpi.status])}>{kpi.status}</span>
            </div>
            <div className="flex items-baseline gap-1 mb-2">
              <span className="text-2xl font-bold text-foreground">{current}</span>
              <span className="text-xs text-muted-foreground">/ {target} {kpi.unit}</span>
            </div>
            <div className="h-1.5 bg-muted rounded-full overflow-hidden mb-3">
              <div
                className={cn("h-full rounded-full transition-all", barColor[kpi.status])}
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <MetaItem label="DIRECTION" value={kpi.direction === "higher_is_better" ? "Higher =" : "Lower ="} />
              {kpi.thresholdWarning != null && <MetaItem label="WARNING" value={String(kpi.thresholdWarning)} />}
              {kpi.thresholdCritical != null && <MetaItem label="CRITICAL" value={String(kpi.thresholdCritical)} />}
              {kpi.agentId && <MetaItem label="AGENT" value={kpi.agentId} />}
              {kpi.measuredAt && <MetaItem label="MEASURED" value={timeAgo(kpi.measuredAt)} />}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SynthesisTab({ runs, loading }: { runs: import("@/types/agents").SynthesisRun[]; loading: boolean }) {
  if (loading) return <Skeleton rows={3} />;
  if (runs.length === 0) return <EmptyState text="No synthesis runs yet" sub="Synthesis runs automatically every 2 hours or on critical escalations" />;

  return (
    <div className="space-y-3">
      {runs.map((run) => (
        <div key={run.id} className="bg-card border border-border rounded-md p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="label-uppercase">SYNTHESIS RUN</span>
            <span className="text-[10px] text-muted-foreground">{timeAgo(run.createdAt)}</span>
          </div>
          <p className="text-xs text-foreground leading-relaxed">{run.summary}</p>
          {run.escalationsProcessed && run.escalationsProcessed.length > 0 && (
            <span className="text-[9px] text-muted-foreground mt-2 block">
              Processed {run.escalationsProcessed.length} escalation{run.escalationsProcessed.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="label-uppercase">{label}</span>
      <p className="text-xs text-foreground mt-0.5">{value}</p>
    </div>
  );
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="bg-card border border-border rounded-md h-16 animate-pulse" />
      ))}
    </div>
  );
}

function EmptyState({ text, sub }: { text: string; sub: string }) {
  return (
    <div className="text-center py-12">
      <p className="text-sm text-muted-foreground">{text}</p>
      <p className="text-xs text-muted-foreground/50 mt-1">{sub}</p>
    </div>
  );
}
