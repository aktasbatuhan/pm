import { cn } from "@/lib/utils";
import type { Escalation } from "@/types/agents";

const urgencyColors: Record<string, string> = {
  info: "bg-blue-500/20 text-blue-400",
  attention: "bg-warning/20 text-warning",
  urgent: "bg-orange-500/20 text-orange-400",
  critical: "bg-destructive/20 text-destructive",
};

const urgencyDots: Record<string, string> = {
  info: "bg-blue-400",
  attention: "bg-warning",
  urgent: "bg-orange-400",
  critical: "bg-destructive",
};

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

interface EscalationFeedProps {
  escalations: Escalation[];
}

export function EscalationFeed({ escalations }: EscalationFeedProps) {
  if (escalations.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-muted-foreground">No escalations</p>
        <p className="text-xs text-muted-foreground/50 mt-1">All agents operating normally</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {escalations.map((esc) => (
        <div
          key={esc.id}
          className="flex items-start gap-3 px-3 py-2 rounded-md hover:bg-muted/50 transition-colors"
        >
          <div className={cn("w-1.5 h-1.5 rounded-full mt-1.5 shrink-0", urgencyDots[esc.urgency])} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-foreground truncate">{esc.title}</span>
              <span className={cn("text-[9px] px-1.5 py-0.5 rounded", urgencyColors[esc.urgency])}>
                {esc.urgency}
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{esc.summary}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="label-uppercase">{esc.agentId}</span>
              <span className="text-[9px] text-muted-foreground">{timeAgo(esc.createdAt)}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
