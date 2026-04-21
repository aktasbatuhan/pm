"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Session } from "@/lib/types";
import { MessageSquare, Plus, PanelLeftClose, Trash2 } from "lucide-react";
import { deleteSession } from "@/lib/api";
import { useState } from "react";

function timeLabel(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = now.getTime() - d.getTime();

  if (diff < 86400_000) return "Today";
  if (diff < 172800_000) return "Yesterday";
  if (diff < 604800_000) return `${Math.floor(diff / 86400_000)}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

interface Props {
  sessions: Session[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onRefresh: () => void;
  onClose: () => void;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onRefresh,
  onClose,
}: Props) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function handleDelete(e: React.MouseEvent, sessionId: string) {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) return;
    setDeletingId(sessionId);
    try {
      await deleteSession(sessionId);
      if (activeSessionId === sessionId) {
        onNewChat();
      }
      onRefresh();
    } finally {
      setDeletingId(null);
    }
  }

  // Group sessions by time
  const grouped: Record<string, Session[]> = {};
  for (const s of sessions) {
    const label = timeLabel(s.last_active || s.started_at);
    if (!grouped[label]) grouped[label] = [];
    grouped[label].push(s);
  }

  return (
    <aside className="flex w-64 flex-col border-r border-border bg-muted/30">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5">
        <button
          onClick={onNewChat}
          className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-4 w-4" />
          New chat
        </button>
        <button
          onClick={onClose}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* Session list */}
      <ScrollArea className="flex-1 px-2">
        {sessions.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            No conversations yet
          </p>
        ) : (
          Object.entries(grouped).map(([label, group]) => (
            <div key={label} className="mb-3">
              <p className="px-2 py-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {label}
              </p>
              {group.map((s) => (
                <div
                  key={s.id}
                  className={cn(
                    "group relative flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
                    activeSessionId === s.id
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                  )}
                >
                  <button
                    onClick={() => onSelectSession(s.id)}
                    className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
                  >
                    <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-50" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate pr-6 text-[13px] font-medium leading-tight">
                        {s.title || s.preview || "Untitled"}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {s.message_count} messages
                      </p>
                    </div>
                  </button>
                  <button
                    onClick={(e) => handleDelete(e, s.id)}
                    disabled={deletingId === s.id}
                    aria-label="Delete conversation"
                    className="absolute right-1.5 top-1.5 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-red-600 group-hover:opacity-100 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          ))
        )}
      </ScrollArea>
    </aside>
  );
}
