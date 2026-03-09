import type { SynthesisRun } from "@/types/agents";

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface SynthesisSummaryProps {
  runs: SynthesisRun[];
}

export function SynthesisSummary({ runs }: SynthesisSummaryProps) {
  if (runs.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-muted-foreground">No synthesis runs yet</p>
        <p className="text-xs text-muted-foreground/50 mt-1">The Head of Product will synthesize agent findings</p>
      </div>
    );
  }

  const latest = runs[0];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="label-uppercase">LATEST SYNTHESIS</span>
        <span className="text-[9px] text-muted-foreground">{timeAgo(latest.createdAt)}</span>
      </div>
      <p className="text-xs text-foreground leading-relaxed">{latest.summary}</p>
      {latest.escalationsProcessed && latest.escalationsProcessed.length > 0 && (
        <span className="text-[9px] text-muted-foreground">
          Processed {latest.escalationsProcessed.length} escalation{latest.escalationsProcessed.length !== 1 ? "s" : ""}
        </span>
      )}
      {runs.length > 1 && (
        <div className="border-t border-border pt-2 mt-1">
          <span className="label-uppercase">PREVIOUS</span>
          <div className="flex flex-col gap-1.5 mt-1.5">
            {runs.slice(1).map((run) => (
              <div key={run.id} className="flex items-start gap-2">
                <span className="text-[9px] text-muted-foreground shrink-0 mt-0.5">
                  {timeAgo(run.createdAt)}
                </span>
                <p className="text-xs text-muted-foreground line-clamp-1">{run.summary}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
