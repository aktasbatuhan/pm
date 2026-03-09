import { useSubAgents, useEscalations, useKpis, useSynthesisRuns } from "@/hooks/use-agents";
import { AgentStatusCard } from "@/components/overview/AgentStatusCard";
import { KpiGauge } from "@/components/overview/KpiGauge";
import { EscalationFeed } from "@/components/overview/EscalationFeed";
import { SynthesisSummary } from "@/components/overview/SynthesisSummary";

export function OverviewPage() {
  const { data: agents, isLoading: agentsLoading } = useSubAgents();
  const { data: escalations, isLoading: escLoading } = useEscalations();
  const { data: kpis, isLoading: kpisLoading } = useKpis();
  const { data: synthesisRuns, isLoading: synthLoading } = useSynthesisRuns();

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Mission Control</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Autonomous PM team status</p>
      </div>

      {/* Agent Status Grid */}
      <section className="mb-6">
        <h2 className="label-uppercase mb-3">AGENT TEAM</h2>
        {agentsLoading ? (
          <div className="grid grid-cols-2 gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-card border border-border rounded-md p-4 h-28 animate-pulse" />
            ))}
          </div>
        ) : agents && agents.length > 0 ? (
          <div className="grid grid-cols-2 gap-3">
            {agents.map((agent) => (
              <AgentStatusCard key={agent.id} agent={agent} />
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-md p-6 text-center">
            <p className="text-sm text-muted-foreground">No agents configured yet</p>
            <p className="text-xs text-muted-foreground/50 mt-1">Complete setup to initialize the agent team</p>
          </div>
        )}
      </section>

      <div className="grid grid-cols-2 gap-6">
        {/* Left: KPIs + Synthesis */}
        <div className="flex flex-col gap-6">
          {/* KPIs */}
          <section>
            <h2 className="label-uppercase mb-3">KEY METRICS</h2>
            {kpisLoading ? (
              <div className="grid grid-cols-2 gap-3">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="bg-card border border-border rounded-md p-3 h-20 animate-pulse" />
                ))}
              </div>
            ) : kpis && kpis.length > 0 ? (
              <div className="grid grid-cols-2 gap-3">
                {kpis.map((kpi) => (
                  <KpiGauge key={kpi.id} kpi={kpi} />
                ))}
              </div>
            ) : (
              <div className="bg-card border border-border rounded-md p-4 text-center">
                <p className="text-xs text-muted-foreground">KPIs will be set by the Head of Product after first synthesis</p>
              </div>
            )}
          </section>

          {/* Synthesis */}
          <section>
            <h2 className="label-uppercase mb-3">SYNTHESIS</h2>
            <div className="bg-card border border-border rounded-md p-4">
              {synthLoading ? (
                <div className="h-24 animate-pulse" />
              ) : (
                <SynthesisSummary runs={synthesisRuns || []} />
              )}
            </div>
          </section>
        </div>

        {/* Right: Escalation Feed */}
        <section>
          <h2 className="label-uppercase mb-3">ESCALATIONS</h2>
          <div className="bg-card border border-border rounded-md p-2 max-h-[500px] overflow-y-auto">
            {escLoading ? (
              <div className="h-32 animate-pulse" />
            ) : (
              <EscalationFeed escalations={escalations || []} />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
