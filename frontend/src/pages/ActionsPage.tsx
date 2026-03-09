import { useState } from "react";
import { useActions, useApproveAction, useRejectAction } from "@/hooks/use-agents";
import { cn } from "@/lib/utils";
import type { Action } from "@/types/api";

const TYPE_ICONS: Record<string, { emoji: string; label: string }> = {
  github_issue: { emoji: "📋", label: "GitHub Issue" },
  github_comment: { emoji: "💬", label: "Comment" },
  slack_dm: { emoji: "💌", label: "Slack DM" },
  github_label: { emoji: "🏷️", label: "Label" },
  custom: { emoji: "⚡", label: "Custom" },
};

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  pending: { bg: "bg-warning/10", text: "text-warning" },
  approved: { bg: "bg-success/10", text: "text-success" },
  rejected: { bg: "bg-muted", text: "text-muted-foreground" },
  executed: { bg: "bg-success/10", text: "text-success" },
  failed: { bg: "bg-destructive/10", text: "text-destructive" },
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

export function ActionsPage() {
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const { data: actions } = useActions(filter);
  const approve = useApproveAction();
  const reject = useRejectAction();

  const pending = actions?.filter((a) => a.status === "pending") || [];
  const history = actions?.filter((a) => a.status !== "pending") || [];

  return (
    <div className="p-6 max-w-[1200px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Action Queue</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          Agent-proposed actions awaiting your approval
        </p>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-4">
        {[
          { label: "All", value: undefined },
          { label: "Pending", value: "pending" },
          { label: "Approved", value: "approved" },
          { label: "Rejected", value: "rejected" },
        ].map((tab) => (
          <button
            key={tab.label}
            onClick={() => setFilter(tab.value)}
            className={cn(
              "px-3 py-1 rounded text-[10px] font-medium uppercase tracking-wider transition-colors",
              filter === tab.value
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            {tab.label}
            {tab.value === "pending" && pending.length > 0 && (
              <span className="ml-1 text-warning">{pending.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* Pending actions */}
      {(!filter || filter === "pending") && pending.length > 0 && (
        <section className="mb-6">
          <h2 className="label-uppercase mb-3">
            AWAITING APPROVAL
            <span className="text-[9px] text-warning ml-2">{pending.length}</span>
          </h2>
          <div className="space-y-2">
            {pending.map((action) => (
              <ActionCard
                key={action.id}
                action={action}
                onApprove={() => approve.mutate(action.id)}
                onReject={() => reject.mutate(action.id)}
              />
            ))}
          </div>
        </section>
      )}

      {/* History */}
      {history.length > 0 && (
        <section>
          <h2 className="label-uppercase mb-3">HISTORY</h2>
          <div className="space-y-1.5">
            {history.map((action) => (
              <ActionCard key={action.id} action={action} compact />
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {(!actions || actions.length === 0) && (
        <div className="bg-card border border-border rounded-md p-8 text-center">
          <p className="text-sm text-muted-foreground">No actions proposed yet</p>
          <p className="text-[10px] text-muted-foreground mt-1">
            Agents will propose actions here during synthesis runs
          </p>
        </div>
      )}
    </div>
  );
}

function ActionCard({
  action,
  onApprove,
  onReject,
  compact,
}: {
  action: Action;
  onApprove?: () => void;
  onReject?: () => void;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const typeInfo = TYPE_ICONS[action.type] || TYPE_ICONS.custom;
  const statusStyle = STATUS_STYLES[action.status] || STATUS_STYLES.pending;
  const payload = action.payload;

  return (
    <div
      className={cn(
        "bg-card border border-border rounded-md overflow-hidden",
        action.status === "pending" && "border-warning/30"
      )}
    >
      <div
        className="px-4 py-3 flex items-start gap-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-base mt-0.5">{typeInfo.emoji}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-xs font-medium text-foreground truncate">
              {action.title}
            </span>
            <span
              className={cn(
                "text-[9px] px-1.5 py-0.5 rounded-full font-medium uppercase",
                statusStyle.bg,
                statusStyle.text
              )}
            >
              {action.status}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] text-muted-foreground">{typeInfo.label}</span>
            <span className="text-[8px] text-muted-foreground/40">·</span>
            <span className="text-[9px] text-muted-foreground">
              {timeAgo(action.createdAt)}
            </span>
          </div>
          {!compact && (
            <p className="text-[10px] text-foreground/70 mt-1.5 leading-relaxed line-clamp-2">
              {action.description}
            </p>
          )}
        </div>

        {/* Approve/Reject buttons for pending */}
        {action.status === "pending" && onApprove && onReject && (
          <div className="flex gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={onApprove}
              className="px-3 py-1.5 rounded text-[10px] font-medium bg-success/10 text-success hover:bg-success/20 transition-colors"
            >
              Approve
            </button>
            <button
              onClick={onReject}
              className="px-3 py-1.5 rounded text-[10px] font-medium bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors"
            >
              Reject
            </button>
          </div>
        )}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="px-4 pb-3 border-t border-border/50 pt-3">
          <div className="text-[10px] text-muted-foreground mb-2 uppercase tracking-wider">
            Payload
          </div>
          <pre className="text-[10px] text-foreground/80 bg-muted/30 rounded p-2 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(payload, null, 2)}
          </pre>
          {action.executionResult && (
            <>
              <div className="text-[10px] text-muted-foreground mb-2 mt-3 uppercase tracking-wider">
                Execution Result
              </div>
              <pre className="text-[10px] text-foreground/80 bg-muted/30 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {action.executionResult}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
