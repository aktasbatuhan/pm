"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchSignalSources,
  fetchSignals,
  createSignalSource,
  deleteSignalSource,
  updateSignalSource,
  updateSignalStatus,
  triggerSignalFetch,
  type SignalSource,
  type Signal,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Radar,
  Plus,
  AtSign,
  Globe,
  Search,
  RefreshCw,
  Loader2,
  ExternalLink,
  Star,
  Check,
  X,
  Trash2,
  Eye,
  Pencil,
} from "lucide-react";

const Twitter = AtSign;

const SOURCE_TYPES = [
  { id: "twitter", name: "Twitter/X", icon: Twitter, configField: "query", configLabel: "Search query — use OR, quotes. Commas work too.", configPlaceholder: `"AI agents" OR "coding agent"` },
  { id: "exa", name: "Web search (Exa)", icon: Search, configField: "query", configLabel: "Natural language search query", configPlaceholder: "AI coding agent vulnerabilities 2026" },
  { id: "firecrawl", name: "Website scrape", icon: Globe, configField: "url", configLabel: "URL to scrape", configPlaceholder: "https://example.com/blog" },
];

const SOURCE_ICON: Record<string, typeof Twitter> = {
  twitter: Twitter,
  exa: Search,
  firecrawl: Globe,
};

interface Props {
  onNavigateToChat: (prompt?: string) => void;
}

export function SignalsView({ onNavigateToChat }: Props) {
  const [sources, setSources] = useState<SignalSource[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [showAddSource, setShowAddSource] = useState(false);
  const [editingSourceId, setEditingSourceId] = useState<string | null>(null);
  const [fetchingSourceId, setFetchingSourceId] = useState<string | null>(null);
  const [filterSourceId, setFilterSourceId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [srcs, sigs] = await Promise.all([fetchSignalSources(), fetchSignals("all", 100)]);
    setSources(srcs);
    setSignals(sigs);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  function pollForNewSignals(startCount: number, onDone: () => void) {
    const poll = setInterval(async () => {
      const sigs = await fetchSignals("all", 100);
      if (sigs.length > startCount) {
        setSignals(sigs);
        onDone();
        clearInterval(poll);
      }
    }, 4000);
    setTimeout(() => { clearInterval(poll); onDone(); load(); }, 90_000);
  }

  async function handleFetchAll() {
    setFetching(true);
    triggerSignalFetch("all");
    pollForNewSignals(signals.length, () => setFetching(false));
  }

  async function handleFetchOne(sourceId: string) {
    setFetchingSourceId(sourceId);
    triggerSignalFetch(sourceId);
    pollForNewSignals(signals.length, () => setFetchingSourceId(null));
  }

  async function handleDeleteSource(id: string) {
    if (!confirm("Delete this source and all its signals?")) return;
    await deleteSignalSource(id);
    load();
  }

  async function handleMarkRead(id: string) {
    await updateSignalStatus(id, "read");
    setSignals((prev) => prev.map((s) => s.id === id ? { ...s, status: "read" } : s));
  }

  async function handleStar(id: string) {
    await updateSignalStatus(id, "starred");
    setSignals((prev) => prev.map((s) => s.id === id ? { ...s, status: "starred" } : s));
  }

  async function handleDismiss(id: string) {
    await updateSignalStatus(id, "dismissed");
    setSignals((prev) => prev.filter((s) => s.id !== id));
  }

  const filteredSignals = filterSourceId
    ? signals.filter((s) => s.source_id === filterSourceId && s.status !== "dismissed")
    : signals.filter((s) => s.status !== "dismissed");

  return (
    <div className="flex h-full">
      {/* ── Sidebar: sources ──────────────────────────────── */}
      <aside className="w-72 shrink-0 border-r border-border flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="text-sm font-semibold">Sources</h2>
          <button
            onClick={() => setShowAddSource(true)}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted"
          >
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>

        <ScrollArea className="flex-1 px-2 py-2">
          {showAddSource && (
            <AddSourceForm
              onClose={() => setShowAddSource(false)}
              onCreated={() => { setShowAddSource(false); load(); }}
            />
          )}

          <button
            onClick={() => setFilterSourceId(null)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] transition-colors mb-1",
              filterSourceId === null ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/60"
            )}
          >
            <Radar className="h-3.5 w-3.5" />
            All signals
            <span className="ml-auto text-[11px]">{signals.filter((s) => s.status !== "dismissed").length}</span>
          </button>

          {sources.length === 0 && !showAddSource && (
            <div className="px-3 py-6 text-center">
              <p className="text-xs text-muted-foreground">No sources yet</p>
              <button
                onClick={() => setShowAddSource(true)}
                className="mt-2 text-xs text-primary hover:underline"
              >
                Add your first source
              </button>
            </div>
          )}

          {sources.map((src) => {
            const Icon = SOURCE_ICON[src.type] ?? Radar;
            const count = signals.filter((s) => s.source_id === src.id && s.status !== "dismissed").length;
            const isEditing = editingSourceId === src.id;
            const isFetchingThis = fetchingSourceId === src.id;
            const isActive = filterSourceId === src.id;

            if (isEditing) {
              return (
                <EditSourceForm
                  key={src.id}
                  source={src}
                  onClose={() => setEditingSourceId(null)}
                  onSaved={() => { setEditingSourceId(null); load(); }}
                />
              );
            }

            return (
              <div key={src.id} className="group relative mb-0.5">
                <button
                  onClick={() => setFilterSourceId(isActive ? null : src.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md pl-2.5 pr-16 py-2 text-left text-[13px] transition-colors",
                    isActive ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/60"
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0 opacity-60" />
                  <span className="truncate flex-1">{src.name}</span>
                  <span className="text-[11px] shrink-0">{count}</span>
                </button>

                {/* Inline actions — always visible for active source, hover-only for others */}
                <div className={cn(
                  "absolute right-1 top-1 flex items-center gap-0.5 transition-opacity",
                  isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                )}>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleFetchOne(src.id); }}
                    disabled={isFetchingThis || fetching}
                    className="p-1 rounded text-muted-foreground hover:text-primary hover:bg-primary/5 disabled:opacity-50"
                    title="Fetch this source"
                  >
                    {isFetchingThis ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setEditingSourceId(src.id); }}
                    className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted"
                    title="Edit"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDeleteSource(src.id); }}
                    className="p-1 rounded text-muted-foreground hover:text-red-600 hover:bg-red-50"
                    title="Delete"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            );
          })}
        </ScrollArea>

        <div className="border-t border-border px-3 py-2">
          <button
            onClick={handleFetchAll}
            disabled={fetching || sources.length === 0}
            className="flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {fetching ? <><Loader2 className="h-3 w-3 animate-spin" /> Fetching...</> : <><RefreshCw className="h-3 w-3" /> Fetch all</>}
          </button>
        </div>
      </aside>

      {/* ── Main: signal feed ──────────────────────────────── */}
      <ScrollArea className="flex-1">
        <div className="mx-auto max-w-3xl px-8 py-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Signals</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {filterSourceId
                  ? sources.find((s) => s.id === filterSourceId)?.name
                  : "Everything Dash is tracking for you"}
              </p>
            </div>
            <div className="text-sm text-muted-foreground">
              {filteredSignals.length} {filteredSignals.length === 1 ? "signal" : "signals"}
            </div>
          </div>

          {fetching && (
            <div className="mb-4 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <p className="text-sm text-primary font-medium">Fetching fresh signals from all sources...</p>
            </div>
          )}

          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-muted" />)}
            </div>
          ) : filteredSignals.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Radar className="mx-auto h-8 w-8 text-muted-foreground/30" />
                <p className="mt-3 text-sm font-medium text-muted-foreground">No signals yet</p>
                <p className="mt-1 text-xs text-muted-foreground max-w-md mx-auto">
                  {sources.length === 0
                    ? "Add a source — Twitter handle, Hacker News query, or web search — and Dash starts collecting matching items every 6 hours. Star, dismiss, or discuss any signal in chat."
                    : "Sources are configured. Click Fetch all to pull fresh signals now, or wait for the next scheduled fetch."}
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {filteredSignals.map((sig) => (
                <SignalCard
                  key={sig.id}
                  signal={sig}
                  onMarkRead={() => handleMarkRead(sig.id)}
                  onStar={() => handleStar(sig.id)}
                  onDismiss={() => handleDismiss(sig.id)}
                  onDiscuss={() => onNavigateToChat(
                    `Let's discuss this signal from ${sig.source_name}:\n\n${sig.title}\n\n${sig.body.slice(0, 500)}\n\n${sig.url}`
                  )}
                />
              ))}
            </div>
          )}

          <div className="h-16" />
        </div>
      </ScrollArea>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────

function SignalCard({
  signal,
  onMarkRead,
  onStar,
  onDismiss,
  onDiscuss,
}: {
  signal: Signal;
  onMarkRead: () => void;
  onStar: () => void;
  onDismiss: () => void;
  onDiscuss: () => void;
}) {
  const Icon = SOURCE_ICON[signal.source_type] ?? Radar;
  const isStarred = signal.status === "starred";
  const isRead = signal.status === "read";

  return (
    <div className={cn(
      "group rounded-xl border border-border bg-card px-5 py-4 transition-all hover:shadow-sm",
      isRead && "opacity-60"
    )}>
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-[11px] font-medium text-muted-foreground">{signal.source_name}</span>
            {signal.author && (
              <>
                <span className="text-border">·</span>
                <span className="text-[11px] text-muted-foreground">{signal.author}</span>
              </>
            )}
            {isStarred && (
              <Star className="h-3 w-3 fill-amber-500 text-amber-500" />
            )}
          </div>

          {signal.title && (
            <p className="text-sm font-semibold leading-snug">{signal.title}</p>
          )}

          {signal.body && signal.body !== signal.title && (
            <p className="mt-1 text-[13px] text-muted-foreground leading-relaxed line-clamp-4">
              {signal.body}
            </p>
          )}

          {/* Footer actions */}
          <div className="mt-3 flex items-center gap-1">
            {signal.url && (
              <a
                href={signal.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <ExternalLink className="h-3 w-3" /> Open
              </a>
            )}
            <button
              onClick={onDiscuss}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-primary hover:bg-primary/5"
            >
              Discuss with Dash →
            </button>

            <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={onStar}
                title="Star"
                className="rounded-md p-1 text-muted-foreground hover:text-amber-500 hover:bg-amber-50"
              >
                <Star className={cn("h-3.5 w-3.5", isStarred && "fill-amber-500 text-amber-500")} />
              </button>
              {!isRead && (
                <button
                  onClick={onMarkRead}
                  title="Mark read"
                  className="rounded-md p-1 text-muted-foreground hover:text-green-600 hover:bg-green-50"
                >
                  <Eye className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                onClick={onDismiss}
                title="Dismiss"
                className="rounded-md p-1 text-muted-foreground hover:text-red-600 hover:bg-red-50"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AddSourceForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"twitter" | "exa" | "firecrawl">("exa");
  const [configValue, setConfigValue] = useState("");
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);

  const typeConfig = SOURCE_TYPES.find((t) => t.id === type)!;

  async function handleSave() {
    if (!name.trim() || !configValue.trim()) return;
    setSaving(true);
    await createSignalSource({
      name: name.trim(),
      type,
      config: { [typeConfig.configField]: configValue.trim() },
      filter: filter.trim(),
    });
    setSaving(false);
    onCreated();
  }

  return (
    <div className="mb-3 rounded-lg border border-primary/20 bg-primary/5 p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-primary">New source</p>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name (e.g. AI Coding News)"
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40"
        autoFocus
      />

      <div className="grid grid-cols-3 gap-1">
        {SOURCE_TYPES.map((t) => (
          <button
            key={t.id}
            onClick={() => setType(t.id as any)}
            className={cn(
              "flex flex-col items-center gap-1 rounded-md border px-2 py-2 text-[10px] transition-colors",
              type === t.id
                ? "border-primary bg-primary/10 text-primary font-medium"
                : "border-border text-muted-foreground hover:border-primary/30"
            )}
          >
            <t.icon className="h-3.5 w-3.5" />
            {t.name.split(" ")[0]}
          </button>
        ))}
      </div>

      <input
        type="text"
        value={configValue}
        onChange={(e) => setConfigValue(e.target.value)}
        placeholder={typeConfig.configPlaceholder}
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40"
      />
      <p className="text-[10px] text-muted-foreground">{typeConfig.configLabel}</p>

      <textarea
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Optional: natural language filter (e.g. only posts about AI agents, skip crypto)"
        rows={2}
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40 resize-none"
      />

      <button
        onClick={handleSave}
        disabled={!name.trim() || !configValue.trim() || saving}
        className="w-full flex items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
      >
        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
        Create source
      </button>
    </div>
  );
}

function EditSourceForm({
  source,
  onClose,
  onSaved,
}: {
  source: SignalSource;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(source.name);
  const [type, setType] = useState<"twitter" | "exa" | "firecrawl">(source.type);
  const [configValue, setConfigValue] = useState(() => {
    const cfg = source.config as Record<string, string>;
    return cfg.query || cfg.url || "";
  });
  const [filter, setFilter] = useState(source.filter || "");
  const [saving, setSaving] = useState(false);

  const typeConfig = SOURCE_TYPES.find((t) => t.id === type)!;

  async function handleSave() {
    if (!name.trim() || !configValue.trim()) return;
    setSaving(true);
    await updateSignalSource(source.id, {
      name: name.trim(),
      type,
      config: { [typeConfig.configField]: configValue.trim() },
      filter: filter.trim(),
    });
    setSaving(false);
    onSaved();
  }

  return (
    <div className="mb-3 rounded-lg border border-primary/20 bg-primary/5 p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-primary">Edit source</p>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name"
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40"
        autoFocus
      />

      <div className="grid grid-cols-3 gap-1">
        {SOURCE_TYPES.map((t) => (
          <button
            key={t.id}
            onClick={() => setType(t.id as "twitter" | "exa" | "firecrawl")}
            className={cn(
              "flex flex-col items-center gap-1 rounded-md border px-2 py-2 text-[10px] transition-colors",
              type === t.id
                ? "border-primary bg-primary/10 text-primary font-medium"
                : "border-border text-muted-foreground hover:border-primary/30"
            )}
          >
            <t.icon className="h-3.5 w-3.5" />
            {t.name.split(" ")[0]}
          </button>
        ))}
      </div>

      <input
        type="text"
        value={configValue}
        onChange={(e) => setConfigValue(e.target.value)}
        placeholder={typeConfig.configPlaceholder}
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40"
      />
      <p className="text-[10px] text-muted-foreground">{typeConfig.configLabel}</p>

      <textarea
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Optional: natural language filter"
        rows={2}
        className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-primary/40 resize-none"
      />

      <button
        onClick={handleSave}
        disabled={!name.trim() || !configValue.trim() || saving}
        className="w-full flex items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
      >
        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
        Save changes
      </button>
    </div>
  );
}
