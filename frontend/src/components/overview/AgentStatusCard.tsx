import { cn } from "@/lib/utils";
import type { SubAgent } from "@/types/agents";

const statusColors: Record<string, string> = {
  active: "text-success",
  paused: "text-warning",
  disabled: "text-muted-foreground",
};

const statusDots: Record<string, string> = {
  active: "bg-success",
  paused: "bg-warning",
  disabled: "bg-muted-foreground",
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

interface AgentStatusCardProps {
  agent: SubAgent;
}

export function AgentStatusCard({ agent }: AgentStatusCardProps) {
  return (
    <div className="bg-card border border-border rounded-md p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={cn("w-1.5 h-1.5 rounded-full", statusDots[agent.status])} />
          <span className="text-sm font-medium text-foreground">{agent.displayName}</span>
        </div>
        <span className={cn("text-xs", statusColors[agent.status])}>
          {agent.status}
        </span>
      </div>

      <p className="text-xs text-muted-foreground leading-relaxed">{agent.domain}</p>

      <div className="flex items-center gap-4 mt-auto">
        <div>
          <span className="label-uppercase">CYCLE</span>
          <p className="text-xs text-foreground mt-0.5">{formatInterval(agent.scheduleIntervalMs)}</p>
        </div>
        <div>
          <span className="label-uppercase">LAST RUN</span>
          <p className="text-xs text-foreground mt-0.5">{timeAgo(agent.lastRunAt)}</p>
        </div>
        <div>
          <span className="label-uppercase">NEXT</span>
          <p className="text-xs text-foreground mt-0.5">{timeAgo(agent.nextRunAt)}</p>
        </div>
      </div>
    </div>
  );
}
