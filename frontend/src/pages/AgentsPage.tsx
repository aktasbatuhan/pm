import { useState } from "react";
import { useSubAgents, useEscalations, useKpis, useSynthesisRuns, useReplySynthesis } from "@/hooks/use-agents";
import { cn } from "@/lib/utils";
import { ExpandableText } from "@/components/ui/expandable-text";
import type { SubAgent, Escalation, Kpi, SynthesisRun } from "@/types/agents";

// Pixel-art style agent avatars using emoji + colored backgrounds
const agentAvatars: Record<string, { emoji: string; bg: string; border: string }> = {
  "sprint-health": { emoji: "🏃", bg: "bg-blue-500/15", border: "border-blue-500/30" },
  "code-quality": { emoji: "🔧", bg: "bg-purple-500/15", border: "border-purple-500/30" },
  "product-signals": { emoji: "📡", bg: "bg-green-500/15", border: "border-green-500/30" },
  "team-dynamics": { emoji: "👥", bg: "bg-orange-500/15", border: "border-orange-500/30" },
};

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

type Tab = "team" | "escalations" | "kpis" | "synthesis";

export function AgentsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("team");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const { data: agents, isLoading: agentsLoading } = useSubAgents();
  const { data: escalations, isLoading: escLoading } = useEscalations();
  const { data: kpis, isLoading: kpisLoading } = useKpis();
  const { data: runs, isLoading: synthLoading } = useSynthesisRuns(20);

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "team", label: "Team", count: agents ? agents.length + 1 : undefined },
    { id: "escalations", label: "Escalations", count: escalations?.length },
    { id: "kpis", label: "KPIs", count: kpis?.length },
    { id: "synthesis", label: "Synthesis", count: runs?.length },
  ];

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Agent Team</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Your autonomous PM team</p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border mb-6">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => { setActiveTab(tab.id); setSelectedAgent(null); }}
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

      {activeTab === "team" && (
        <TeamTab
          agents={agents || []}
          kpis={kpis || []}
          escalations={escalations || []}
          loading={agentsLoading}
          selectedAgent={selectedAgent}
          onSelectAgent={setSelectedAgent}
        />
      )}
      {activeTab === "escalations" && (
        <EscalationsTab escalations={escalations || []} agents={agents || []} loading={escLoading} />
      )}
      {activeTab === "kpis" && (
        <KpisTab kpis={kpis || []} agents={agents || []} loading={kpisLoading} />
      )}
      {activeTab === "synthesis" && (
        <SynthesisTab runs={runs || []} loading={synthLoading} />
      )}
    </div>
  );
}

function TeamTab({
  agents, kpis, escalations, loading, selectedAgent, onSelectAgent,
}: {
  agents: SubAgent[];
  kpis: Kpi[];
  escalations: Escalation[];
  loading: boolean;
  selectedAgent: string | null;
  onSelectAgent: (id: string | null) => void;
}) {
  if (loading) return <Skeleton rows={4} />;
  if (agents.length === 0) return <EmptyState text="No agents configured" sub="Complete setup to initialize the agent team" />;

  const selected = selectedAgent ? agents.find((a) => a.id === selectedAgent) : null;

  return (
    <div className="flex gap-6">
      {/* Agent grid */}
      <div className="flex-1">
        {/* Head of Product card */}
        <div className="mb-4">
          <div className="bg-card border border-primary/20 rounded-md p-4">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center text-lg">
                🧠
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">Head of Product</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-primary/15 text-primary">lead</span>
                </div>
                <p className="text-[10px] text-muted-foreground">Cross-domain synthesis, KPI management, strategic decisions</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 mt-3">
              <MetaItem label="TOOLS" value="All MCP servers" />
              <MetaItem label="TRIGGER" value="2h / critical esc." />
              <MetaItem label="MEMORY" value="synthesis/" />
            </div>
          </div>
        </div>

        {/* Sub-agent cards */}
        <div className="grid grid-cols-2 gap-3">
          {agents.map((agent) => {
            const avatar = agentAvatars[agent.name] || { emoji: "🤖", bg: "bg-muted", border: "border-border" };
            const agentKpis = kpis.filter((k) => k.agentId === agent.id);
            const agentEsc = escalations.filter((e) => e.agentId === agent.id && e.status === "pending");
            const isSelected = selectedAgent === agent.id;

            return (
              <button
                key={agent.id}
                onClick={() => onSelectAgent(isSelected ? null : agent.id)}
                className={cn(
                  "bg-card border rounded-md p-4 text-left transition-all",
                  isSelected ? "border-primary/50 ring-1 ring-primary/20" : "border-border hover:border-border/80"
                )}
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center text-lg border", avatar.bg, avatar.border)}>
                    {avatar.emoji}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-foreground">{agent.displayName}</span>
                      <span className={cn("text-[9px]", statusColors[agent.status])}>
                        {agent.status === "active" ? "●" : agent.status === "paused" ? "◆" : "○"}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground truncate">{agent.domain}</p>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <span className="label-uppercase">CYCLE</span>
                    <p className="text-[10px] text-foreground mt-0.5">{formatInterval(agent.scheduleIntervalMs)}</p>
                  </div>
                  <div>
                    <span className="label-uppercase">LAST</span>
                    <p className="text-[10px] text-foreground mt-0.5">{timeAgo(agent.lastRunAt)}</p>
                  </div>
                  <div>
                    <span className="label-uppercase">ALERTS</span>
                    <p className={cn("text-[10px] mt-0.5", agentEsc.length > 0 ? "text-warning" : "text-foreground")}>
                      {agentEsc.length > 0 ? `${agentEsc.length} pending` : "none"}
                    </p>
                  </div>
                </div>

                {/* Mini KPI bars */}
                {agentKpis.length > 0 && (
                  <div className="mt-3 pt-2 border-t border-border/50 space-y-1.5">
                    {agentKpis.slice(0, 2).map((kpi) => {
                      const pct = Math.max(0, Math.min(100, ((kpi.currentValue ?? 0) / (kpi.targetValue || 1)) * 100));
                      const color = kpi.status === "on-track" ? "bg-success" : kpi.status === "at-risk" ? "bg-warning" : "bg-destructive";
                      return (
                        <div key={kpi.id}>
                          <div className="flex items-center justify-between">
                            <span className="text-[9px] text-muted-foreground">{kpi.displayName}</span>
                            <span className="text-[9px] text-foreground">{kpi.currentValue ?? 0}/{kpi.targetValue}</span>
                          </div>
                          <div className="h-1 bg-muted rounded-full overflow-hidden mt-0.5">
                            <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="w-80 shrink-0">
          <AgentDetail agent={selected} kpis={kpis} escalations={escalations} />
        </div>
      )}
    </div>
  );
}

function AgentDetail({ agent, kpis, escalations }: { agent: SubAgent; kpis: Kpi[]; escalations: Escalation[] }) {
  const avatar = agentAvatars[agent.name] || { emoji: "🤖", bg: "bg-muted", border: "border-border" };
  const agentKpis = kpis.filter((k) => k.agentId === agent.id);
  const agentEsc = escalations.filter((e) => e.agentId === agent.id);

  return (
    <div className="bg-card border border-border rounded-md p-4 sticky top-6">
      <div className="flex items-center gap-3 mb-4">
        <div className={cn("w-12 h-12 rounded-lg flex items-center justify-center text-xl border", avatar.bg, avatar.border)}>
          {avatar.emoji}
        </div>
        <div>
          <h3 className="text-sm font-medium text-foreground">{agent.displayName}</h3>
          <p className="text-[10px] text-muted-foreground">{agent.name}</p>
        </div>
      </div>

      <p className="text-xs text-muted-foreground mb-4">{agent.domain}</p>

      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <MetaItem label="STATUS" value={agent.status} />
          <MetaItem label="CYCLE" value={formatInterval(agent.scheduleIntervalMs)} />
          <MetaItem label="LAST RUN" value={timeAgo(agent.lastRunAt)} />
          <MetaItem label="NEXT RUN" value={timeAgo(agent.nextRunAt)} />
        </div>

        <div>
          <MetaItem label="MEMORY PARTITION" value={agent.memoryPartition} />
        </div>

        {/* KPIs */}
        {agentKpis.length > 0 && (
          <div className="border-t border-border pt-3">
            <span className="label-uppercase">ASSIGNED KPIS</span>
            <div className="space-y-2 mt-2">
              {agentKpis.map((kpi) => {
                const statusColor = kpi.status === "on-track" ? "text-success" : kpi.status === "at-risk" ? "text-warning" : "text-destructive";
                return (
                  <div key={kpi.id} className="bg-muted/30 rounded px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-foreground">{kpi.displayName}</span>
                      <span className={cn("text-[9px]", statusColor)}>{kpi.status}</span>
                    </div>
                    <span className="text-[9px] text-muted-foreground">
                      {kpi.currentValue ?? "?"} / {kpi.targetValue} {kpi.unit}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recent escalations */}
        {agentEsc.length > 0 && (
          <div className="border-t border-border pt-3">
            <span className="label-uppercase">RECENT ESCALATIONS</span>
            <div className="space-y-1.5 mt-2">
              {agentEsc.slice(0, 5).map((esc) => (
                <div key={esc.id} className="text-[10px]">
                  <span className="text-foreground">{esc.title}</span>
                  <span className="text-muted-foreground ml-1">· {timeAgo(esc.createdAt)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function EscalationsTab({ escalations, agents, loading }: { escalations: Escalation[]; agents: SubAgent[]; loading: boolean }) {
  if (loading) return <Skeleton rows={5} />;
  if (escalations.length === 0) return <EmptyState text="No escalations" sub="All agents operating normally" />;

  const agentMap = new Map(agents.map((a) => [a.id, a]));
  const urgencyOrder: Record<string, number> = { critical: 0, urgent: 1, attention: 2, info: 3 };
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
            <th className="text-left px-3 py-2 label-uppercase font-normal w-36">Agent</th>
            <th className="text-left px-3 py-2 label-uppercase font-normal w-20">Time</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((esc) => {
            const agent = agentMap.get(esc.agentId);
            const avatar = agent ? agentAvatars[agent.name] : undefined;
            return (
              <tr key={esc.id} className="border-b border-border last:border-0 hover:bg-muted/20 transition-colors">
                <td className="px-3 py-2">
                  <div className="text-foreground">{esc.title}</div>
                  <ExpandableText content={esc.summary} collapsedLines={2} className="mt-0.5 text-muted-foreground" />
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
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    {avatar && <span className="text-xs">{avatar.emoji}</span>}
                    <span className="text-muted-foreground">{agent?.displayName || esc.agentId.slice(0, 8)}</span>
                  </div>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{timeAgo(esc.createdAt)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function KpisTab({ kpis, agents, loading }: { kpis: Kpi[]; agents: SubAgent[]; loading: boolean }) {
  if (loading) return <Skeleton rows={4} />;
  if (kpis.length === 0) return <EmptyState text="No KPIs set" sub="The Head of Product will assign KPIs after first synthesis run" />;

  const agentMap = new Map(agents.map((a) => [a.id, a]));

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
        const agent = kpi.agentId ? agentMap.get(kpi.agentId) : undefined;
        const avatar = agent ? agentAvatars[agent.name] : undefined;

        return (
          <div key={kpi.id} className="bg-card border border-border rounded-md p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {avatar && <span className="text-sm">{avatar.emoji}</span>}
                <span className="text-xs font-medium text-foreground">{kpi.displayName}</span>
              </div>
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
            <div className="flex items-center gap-4">
              <MetaItem label="DIRECTION" value={kpi.direction === "higher_is_better" ? "Higher =" : "Lower ="} />
              {kpi.thresholdWarning != null && <MetaItem label="WARN" value={String(kpi.thresholdWarning)} />}
              {kpi.thresholdCritical != null && <MetaItem label="CRIT" value={String(kpi.thresholdCritical)} />}
              {agent && <MetaItem label="OWNER" value={agent.displayName} />}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SynthesisTab({ runs, loading }: { runs: SynthesisRun[]; loading: boolean }) {
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");
  const replySynthesis = useReplySynthesis();

  if (loading) return <Skeleton rows={3} />;
  if (runs.length === 0) return <EmptyState text="No synthesis runs yet" sub="Synthesis triggers when escalations accumulate or on critical events" />;

  const handleReply = (runId: string) => {
    if (!replyText.trim()) return;
    replySynthesis.mutate({ id: runId, message: replyText });
    setReplyText("");
    setReplyingTo(null);
  };

  return (
    <div className="space-y-3">
      {runs.map((run) => (
        <div key={run.id} className="bg-card border border-border rounded-md p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">🧠</span>
            <span className="text-xs font-medium text-foreground">Head of Product</span>
            <span className="text-[8px] text-muted-foreground/40">·</span>
            <span className="text-[10px] text-muted-foreground">{timeAgo(run.createdAt)}</span>
            {run.escalationsProcessed && run.escalationsProcessed.length > 0 && (
              <>
                <span className="text-[8px] text-muted-foreground/40">·</span>
                <span className="text-[9px] text-muted-foreground">
                  {run.escalationsProcessed.length} escalation{run.escalationsProcessed.length !== 1 ? "s" : ""}
                </span>
              </>
            )}
          </div>
          <ExpandableText content={run.summary} collapsedLines={6} />

          {/* Reply button */}
          <div className="mt-3 pt-2 border-t border-border/50">
            {replyingTo === run.id ? (
              <div className="space-y-2">
                <textarea
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  placeholder='Give context or directives, e.g. "ignore PR #91, erhant is on vacation", "we started a marketing campaign", "watch conversion rate closely"'
                  className="w-full bg-muted/30 border border-border rounded-md px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 resize-none focus:outline-none focus:ring-1 focus:ring-primary/50"
                  rows={3}
                  autoFocus
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => handleReply(run.id)}
                    disabled={!replyText.trim() || replySynthesis.isPending}
                    className="px-3 py-1 rounded text-[10px] font-medium bg-primary/15 text-primary hover:bg-primary/25 disabled:opacity-50 transition-colors"
                  >
                    {replySynthesis.isPending ? "Saving..." : "Save directive"}
                  </button>
                  <button
                    onClick={() => { setReplyingTo(null); setReplyText(""); }}
                    className="px-3 py-1 rounded text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setReplyingTo(run.id)}
                className="text-[10px] text-muted-foreground hover:text-primary transition-colors"
              >
                Reply with context or directive...
              </button>
            )}
          </div>
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
