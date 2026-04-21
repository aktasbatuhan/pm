"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  getIntegrations,
  connectIntegration,
  disconnectIntegration,
  fetchMCPServers,
  createMCPServer,
  deleteMCPServer,
  fetchGithubAppStatus,
  githubAppInstallUrl,
  disconnectGithubApp,
  type Integration,
  type MCPServer,
  type GithubAppStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Plug,
  Server,
  Plus,
  Loader2,
  Trash2,
  Check,
  X,
  AlertCircle,
  CheckCircle2,
  ExternalLink,
} from "lucide-react";

// Simple inline GitHub mark — lucide dropped the brand icon.
function Github({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M12 .5C5.73.5.68 5.55.68 11.82c0 5.01 3.24 9.25 7.74 10.75.57.1.78-.25.78-.55 0-.27-.01-1.18-.02-2.13-3.15.68-3.82-1.34-3.82-1.34-.52-1.31-1.27-1.66-1.27-1.66-1.04-.71.08-.69.08-.69 1.15.08 1.76 1.19 1.76 1.19 1.02 1.76 2.68 1.25 3.34.96.1-.74.4-1.25.73-1.54-2.51-.29-5.15-1.26-5.15-5.6 0-1.24.44-2.25 1.16-3.04-.12-.29-.5-1.46.11-3.04 0 0 .95-.3 3.11 1.16.9-.25 1.87-.37 2.83-.38.96.01 1.93.13 2.83.38 2.16-1.46 3.11-1.16 3.11-1.16.62 1.58.23 2.75.11 3.04.73.79 1.16 1.8 1.16 3.04 0 4.35-2.65 5.31-5.17 5.59.41.36.78 1.06.78 2.14 0 1.55-.02 2.8-.02 3.18 0 .3.2.66.79.55 4.49-1.5 7.73-5.74 7.73-10.75C23.32 5.55 18.27.5 12 .5z"/>
    </svg>
  );
}

const PLATFORM_OPTIONS = [
  { id: "github", name: "GitHub", placeholder: "ghp_xxxxxxxxxxxx", hint: "Personal Access Token with repo, read:org scopes" },
  { id: "linear", name: "Linear", placeholder: "lin_api_xxxxxxxxxxxx", hint: "API key from Linear Settings → API" },
  { id: "posthog", name: "PostHog", placeholder: "phx_xxxxxxxxxxxx", hint: "Personal API key from Project Settings" },
  { id: "sentry", name: "Sentry", placeholder: "sntrys_xxxxxxxxxxxx", hint: "Auth token from Settings → API Keys" },
  { id: "stripe", name: "Stripe", placeholder: "sk_live_xxxxxxxxxxxx", hint: "Restricted API key (read-only recommended)" },
  { id: "notion", name: "Notion", placeholder: "secret_xxxxxxxxxxxx", hint: "Internal integration token" },
  { id: "slack", name: "Slack", placeholder: "xoxb-xxxxxxxxxxxx", hint: "Bot token from your Slack app" },
  { id: "figma", name: "Figma", placeholder: "figd_xxxxxxxxxxxx", hint: "Personal access token" },
];

function timeAgo(ts: number | null): string {
  if (!ts) return "never";
  const diff = Date.now() - ts * 1000;
  if (diff < 60_000) return "just now";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export function SettingsView() {
  const [tab, setTab] = useState<"integrations" | "mcp">("integrations");

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-4xl px-8 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Connect data sources and extend Dash with MCP servers.
          </p>
        </div>

        <div className="mb-6 flex items-center gap-0.5 rounded-lg bg-muted p-0.5 w-fit">
          <button
            onClick={() => setTab("integrations")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
              tab === "integrations"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Plug className="h-3.5 w-3.5" />
            Integrations
          </button>
          <button
            onClick={() => setTab("mcp")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
              tab === "mcp"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Server className="h-3.5 w-3.5" />
            MCP Servers
          </button>
        </div>

        {tab === "integrations" ? <IntegrationsSection /> : <MCPServersSection />}

        <div className="h-16" />
      </div>
    </ScrollArea>
  );
}

// ── GitHub App card ─────────────────────────────────────────────────────

function GithubAppCard({
  status,
  onChanged,
}: {
  status: GithubAppStatus;
  onChanged: () => void;
}) {
  const install = status.installation;
  const [busy, setBusy] = useState(false);

  function openInstall() {
    const url = githubAppInstallUrl();
    window.open(url, "github-app-install", "width=780,height=720");
  }

  async function handleDisconnect() {
    if (!confirm("Disconnect GitHub? Dash will stop reading GitHub data.")) return;
    setBusy(true);
    const result = await disconnectGithubApp();
    setBusy(false);
    if (result.uninstall_hint) {
      window.open(result.uninstall_hint, "_blank");
    }
    onChanged();
  }

  if (!install) {
    return (
      <div className="rounded-xl border border-border bg-card px-5 py-4">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Github className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">GitHub</p>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Connect Dash to your GitHub org via the official GitHub App. You pick the repos,
              Dash gets short-lived scoped tokens — no PAT management.
            </p>
          </div>
          <button
            onClick={openInstall}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Github className="h-3.5 w-3.5" /> Connect GitHub
          </button>
        </div>
      </div>
    );
  }

  const manageUrl =
    install.account_type === "Organization"
      ? `https://github.com/organizations/${install.account_login}/settings/installations/${install.installation_id}`
      : `https://github.com/settings/installations/${install.installation_id}`;

  return (
    <div className="rounded-xl border border-border bg-card px-5 py-4">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Github className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold">{install.account_login}</p>
            <Badge variant="secondary" className="gap-1 text-[10px]">
              <CheckCircle2 className="h-3 w-3 text-green-600" /> GitHub App
            </Badge>
            {install.account_type && (
              <Badge variant="outline" className="text-[10px]">{install.account_type}</Badge>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Repos: {install.repo_selection === "all" ? "all" : "selected"} · installed {timeAgo(install.installed_at)}
          </p>
          <div className="mt-2 flex items-center gap-3 text-[11px]">
            <a
              href={manageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" /> Manage repos on GitHub
            </a>
            <button
              onClick={openInstall}
              className="text-muted-foreground hover:text-foreground"
            >
              Reconfigure
            </button>
          </div>
        </div>
        <button
          onClick={handleDisconnect}
          disabled={busy}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
          title="Disconnect"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}


// ── Integrations section ────────────────────────────────────────────────

function IntegrationsSection() {
  const [items, setItems] = useState<Integration[]>([]);
  const [githubApp, setGithubApp] = useState<GithubAppStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [rows, gh] = await Promise.all([getIntegrations(), fetchGithubAppStatus()]);
    setItems(rows);
    setGithubApp(gh);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Refresh when the install popup completes
  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.data && e.data.type === "github-app-installed") {
        load();
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [load]);

  async function handleDisconnect(platform: string) {
    if (!confirm(`Disconnect ${platform}?`)) return;
    await disconnectIntegration(platform);
    load();
  }

  const githubAppConnected = Boolean(githubApp?.configured && githubApp?.installation);
  // If GitHub App is connected, don't show the "legacy github" row via PAT
  const tokenItems = items.filter((i) => !(i.platform === "github" && githubAppConnected));
  const existingIds = new Set(tokenItems.map((i) => i.platform));
  if (githubAppConnected) existingIds.add("github");
  // Hide GitHub from the "Add token" dropdown when the App is available
  const available = PLATFORM_OPTIONS.filter((p) => {
    if (existingIds.has(p.id)) return false;
    if (p.id === "github" && githubApp?.configured) return false;
    return true;
  });

  return (
    <>
      {githubApp?.configured && (
        <>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wider">GitHub</h2>
          <GithubAppCard status={githubApp} onChanged={load} />
        </>
      )}

      <div className="mb-3 mt-6 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Token integrations</h2>
        {available.length > 0 && (
          <button
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-3.5 w-3.5" /> Add integration
          </button>
        )}
      </div>

      {adding && (
        <AddIntegrationForm
          available={available}
          onClose={() => setAdding(false)}
          onAdded={() => { setAdding(false); load(); }}
        />
      )}

      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />)}
        </div>
      ) : tokenItems.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <Plug className="mx-auto h-8 w-8 text-muted-foreground/30" />
            <p className="mt-3 text-sm font-medium text-muted-foreground">No token integrations yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Connect a platform so Dash can read your data.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {tokenItems.map((it) => {
            const platformDef = PLATFORM_OPTIONS.find((p) => p.id === it.platform);
            const isValid = it.status === "connected";
            return (
              <div
                key={it.platform}
                className="flex items-center gap-4 rounded-xl border border-border bg-card px-5 py-3"
              >
                <div
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-lg text-xs font-semibold uppercase",
                    isValid ? "bg-primary/10 text-primary" : "bg-red-50 text-red-600"
                  )}
                >
                  {(platformDef?.name || it.platform).slice(0, 2)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold">{platformDef?.name || it.display_name || it.platform}</p>
                    {isValid ? (
                      <Badge variant="secondary" className="gap-1 text-[10px]">
                        <CheckCircle2 className="h-3 w-3 text-green-600" /> Connected
                      </Badge>
                    ) : (
                      <Badge variant="destructive" className="gap-1 text-[10px]">
                        <AlertCircle className="h-3 w-3" /> {it.status}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    Credentials {it.credentials} · connected {timeAgo(it.connected_at)}
                  </p>
                </div>
                <button
                  onClick={() => handleDisconnect(it.platform)}
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-600"
                  title="Disconnect"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

function AddIntegrationForm({
  available,
  onClose,
  onAdded,
}: {
  available: typeof PLATFORM_OPTIONS;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [platform, setPlatform] = useState(available[0]?.id || "github");
  const [credentials, setCredentials] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const def = available.find((p) => p.id === platform) || available[0];

  async function handleSave() {
    if (!credentials.trim()) return;
    setSaving(true);
    setError(null);
    const result = await connectIntegration(platform, credentials.trim(), "token");
    setSaving(false);
    if (!result.ok) {
      setError(result.message || "Invalid credentials");
      return;
    }
    onAdded();
  }

  return (
    <Card className="mb-4 border-primary/20 bg-primary/5">
      <CardContent className="pt-5 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-primary">New integration</p>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <select
          value={platform}
          onChange={(e) => { setPlatform(e.target.value); setError(null); }}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/40"
        >
          {available.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <div>
          <input
            type="password"
            value={credentials}
            onChange={(e) => setCredentials(e.target.value)}
            placeholder={def?.placeholder}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary/40"
          />
          {def?.hint && (
            <p className="mt-1 text-[11px] text-muted-foreground">{def.hint}</p>
          )}
        </div>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!credentials.trim() || saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            Connect
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

// ── MCP servers section ─────────────────────────────────────────────────

function MCPServersSection() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const rows = await fetchMCPServers();
    setServers(rows);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(name: string) {
    if (!confirm(`Remove MCP server "${name}"?`)) return;
    const result = await deleteMCPServer(name);
    if (!result.ok) {
      alert(result.error || "Failed to remove");
      return;
    }
    load();
  }

  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">MCP Servers</h2>
        <button
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="h-3.5 w-3.5" /> Add MCP server
        </button>
      </div>

      <p className="mb-4 text-xs text-muted-foreground">
        MCP servers add new tools to Dash. Stdio servers spawn a subprocess (e.g. <code className="rounded bg-muted px-1 py-0.5">npx -y server-name</code>); HTTP servers connect to a URL. Changes take effect on the next agent run.
      </p>

      {adding && (
        <AddMCPServerForm onClose={() => setAdding(false)} onAdded={() => { setAdding(false); load(); }} />
      )}

      {loading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />)}
        </div>
      ) : servers.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <Server className="mx-auto h-8 w-8 text-muted-foreground/30" />
            <p className="mt-3 text-sm font-medium text-muted-foreground">No MCP servers configured</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Add a Linear, Stripe, Notion, or any custom MCP server.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {servers.map((s) => (
            <div
              key={s.name}
              className="flex items-start gap-4 rounded-xl border border-border bg-card px-5 py-3"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                <Server className="h-4 w-4 text-primary" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold">{s.name}</p>
                  <Badge variant="secondary" className="text-[10px]">{s.transport}</Badge>
                </div>
                <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                  {s.transport === "stdio"
                    ? `${s.command} ${(s.args || []).join(" ")}`
                    : s.url}
                </p>
                {s.transport === "stdio" && Object.keys(s.env || {}).length > 0 && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    env: {Object.keys(s.env).join(", ")}
                  </p>
                )}
                {s.transport === "http" && Object.keys(s.headers || {}).length > 0 && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    headers: {Object.keys(s.headers).join(", ")}
                  </p>
                )}
              </div>
              <button
                onClick={() => handleDelete(s.name)}
                className="rounded-md p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-600"
                title="Remove"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 rounded-lg border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        <p className="flex items-center gap-2 font-medium text-foreground">
          <ExternalLink className="h-3 w-3" />
          MCP server directory
        </p>
        <p className="mt-1">
          Browse available servers at <a href="https://github.com/modelcontextprotocol/servers" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">modelcontextprotocol/servers</a>.
          Values like <code className="rounded bg-muted px-1 py-0.5">${"{MY_TOKEN}"}</code> in env/headers expand from environment variables at runtime.
        </p>
      </div>
    </>
  );
}

function AddMCPServerForm({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("npx");
  const [argsText, setArgsText] = useState("");
  const [envText, setEnvText] = useState("");
  const [url, setUrl] = useState("");
  const [headersText, setHeadersText] = useState("");
  const [timeout, setTimeoutVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function parseKeyVals(text: string): Record<string, string> {
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const idx = trimmed.indexOf("=");
      const colonIdx = trimmed.indexOf(":");
      const sep = idx >= 0 && (colonIdx < 0 || idx < colonIdx) ? idx : colonIdx;
      if (sep > 0) {
        const k = trimmed.slice(0, sep).trim();
        const v = trimmed.slice(sep + 1).trim();
        if (k) out[k] = v;
      }
    }
    return out;
  }

  async function handleSave() {
    setError(null);
    if (!name.trim()) { setError("Name required"); return; }
    if (transport === "stdio" && !command.trim()) { setError("Command required"); return; }
    if (transport === "http" && !url.trim()) { setError("URL required"); return; }

    setSaving(true);
    const payload: Parameters<typeof createMCPServer>[0] = {
      name: name.trim(),
      transport,
    };
    if (transport === "stdio") {
      payload.command = command.trim();
      const args = argsText.trim().split(/\s+/).filter(Boolean);
      if (args.length) payload.args = args;
      const env = parseKeyVals(envText);
      if (Object.keys(env).length) payload.env = env;
    } else {
      payload.url = url.trim();
      const headers = parseKeyVals(headersText);
      if (Object.keys(headers).length) payload.headers = headers;
    }
    const t = Number(timeout);
    if (Number.isFinite(t) && t > 0) payload.timeout = t;

    const result = await createMCPServer(payload);
    setSaving(false);
    if (!result.ok) {
      setError(result.error || "Failed to add server");
      return;
    }
    onAdded();
  }

  return (
    <Card className="mb-4 border-primary/20 bg-primary/5">
      <CardContent className="pt-5 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-primary">New MCP server</p>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-border p-0.5 text-[11px]">
            <button
              onClick={() => setTransport("stdio")}
              className={cn("rounded px-3 py-1", transport === "stdio" ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
            >
              Stdio (subprocess)
            </button>
            <button
              onClick={() => setTransport("http")}
              className={cn("rounded px-3 py-1", transport === "http" ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
            >
              HTTP
            </button>
          </div>
        </div>

        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Server name (e.g. linear, stripe, custom-tool)"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/40"
          autoFocus
        />

        {transport === "stdio" ? (
          <>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="Command (e.g. npx)"
                className="w-40 rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary/40"
              />
              <input
                type="text"
                value={argsText}
                onChange={(e) => setArgsText(e.target.value)}
                placeholder="Args (space-separated, e.g. -y @modelcontextprotocol/server-linear)"
                className="flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary/40"
              />
            </div>
            <textarea
              value={envText}
              onChange={(e) => setEnvText(e.target.value)}
              rows={3}
              placeholder={`Env vars, one per line:\nLINEAR_API_KEY=${"${LINEAR_API_KEY}"}\nFOO=bar`}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none resize-none focus:border-primary/40"
            />
          </>
        ) : (
          <>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://mcp.example.com/v1/sse"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary/40"
            />
            <textarea
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
              rows={3}
              placeholder={`Headers, one per line:\nAuthorization: Bearer ${"${API_KEY}"}\nX-Extra: value`}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none resize-none focus:border-primary/40"
            />
          </>
        )}

        <input
          type="text"
          value={timeout}
          onChange={(e) => setTimeoutVal(e.target.value)}
          placeholder="Timeout in seconds (optional, default 120)"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs outline-none focus:border-primary/40"
        />

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim() || saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            Add server
          </button>
        </div>
      </CardContent>
    </Card>
  );
}
