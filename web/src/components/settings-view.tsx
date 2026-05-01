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
  fetchGithubAppInstallUrl,
  disconnectGithubApp,
  fetchActiveWorkflow,
  saveWorkflow,
  fetchWorkflowRevisions,
  fetchWorkflowProposals,
  acceptWorkflowProposal,
  dismissWorkflowProposal,
  fetchDelegations,
  runSupervisor,
  refileDelegation,
  type Integration,
  type MCPServer,
  type GithubAppStatus,
  type WorkflowResponse,
  type WorkflowRevision,
  type WorkflowProposal,
  type Delegation,
  type SupervisorReportResponse,
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
  GitBranch,
  History,
  Bot,
  RefreshCw,
  Play,
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

interface SettingsViewProps {
  pendingProposalCount?: number;
}

export function SettingsView({ pendingProposalCount = 0 }: SettingsViewProps = {}) {
  // Auto-open the Workflow tab on first render when there are pending
  // proposals — the user came here to review them, not to scroll for them.
  const initialTab = pendingProposalCount > 0 ? "workflow" : "integrations";
  const [tab, setTab] = useState<"integrations" | "mcp" | "workflow" | "fleet">(initialTab);

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
          <button
            onClick={() => setTab("workflow")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
              tab === "workflow"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <GitBranch className="h-3.5 w-3.5" />
            Workflow
            {pendingProposalCount > 0 && (
              <span className="ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-semibold text-white">
                {pendingProposalCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("fleet")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
              tab === "fleet"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Bot className="h-3.5 w-3.5" />
            Fleet
          </button>
        </div>

        {tab === "integrations" && <IntegrationsSection />}
        {tab === "mcp" && <MCPServersSection />}
        {tab === "workflow" && <WorkflowSection />}
        {tab === "fleet" && <FleetSection />}

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

  async function openInstall() {
    const url = await fetchGithubAppInstallUrl();
    if (!url) {
      alert("Could not start GitHub install. Please retry or check that the GitHub App is configured.");
      return;
    }
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

      {/* Webhook setup nudge — visible right after the App is connected. */}
      <WebhookSetupRow installSlug={install.account_login} />
    </div>
  );
}


function WebhookSetupRow({ installSlug }: { installSlug: string }) {
  const [open, setOpen] = useState(false);
  // Best-effort: backend hostname is whatever served this page request via the
  // configured API URL; surface it so the user can copy without guessing.
  const apiBase = (typeof window !== "undefined" && process.env.NEXT_PUBLIC_API_URL)
    ? process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, "")
    : "https://your-dash-host";
  const webhookUrl = `${apiBase}/api/integrations/github/webhook`;
  return (
    <div className="mt-3 rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2.5 text-[11px]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left text-muted-foreground hover:text-foreground"
      >
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          <span className="font-medium">Webhooks: configure for real-time supervision</span>
        </span>
        <span className="text-[10px]">{open ? "Hide" : "Show steps"}</span>
      </button>
      {open && (
        <div className="mt-2 space-y-2 border-t border-border pt-2 text-foreground/80">
          <p>
            Without webhooks, Dash supervises every 12 minutes via cron. With them, it reacts to
            PR / comment / review events in seconds.
          </p>
          <ol className="list-decimal space-y-1 pl-4">
            <li>
              In your GitHub App settings ({installSlug}) → Webhooks, set the URL to:
              <div className="mt-1 select-all rounded bg-background px-2 py-1 font-mono text-[10px]">
                {webhookUrl}
              </div>
            </li>
            <li>
              Generate a strong secret (
              <code className="rounded bg-background px-1">
                python3 -c &quot;import secrets; print(secrets.token_urlsafe(48))&quot;
              </code>
              ), paste into both the GitHub App secret field AND the
              <code className="rounded bg-background px-1">GITHUB_APP_WEBHOOK_SECRET</code> env var
              on your Dash server.
            </li>
            <li>
              Subscribe to events: <span className="font-mono">Issues, Issue comment, Pull request, Pull request review</span>.
            </li>
            <li>
              Save. GitHub fires a <span className="font-mono">ping</span> — Dash should respond
              <span className="font-mono"> &#123;ok:true, pong:true&#125;</span> in Recent Deliveries.
            </li>
          </ol>
        </div>
      )}
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


// ── Workflow section ────────────────────────────────────────────────────

function WorkflowSection() {
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null);
  const [revisions, setRevisions] = useState<WorkflowRevision[]>([]);
  const [proposals, setProposals] = useState<WorkflowProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [w, h, p] = await Promise.all([
      fetchActiveWorkflow(),
      fetchWorkflowRevisions(),
      fetchWorkflowProposals(),
    ]);
    setWorkflow(w);
    setRevisions(h);
    setProposals(p);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function startEdit() {
    setDraft(workflow?.body ?? "");
    setRationale("");
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    const result = await saveWorkflow(draft, rationale.trim() || undefined);
    setSaving(false);
    if (!result.ok) {
      setError(result.error ?? "Save failed");
      return;
    }
    setEditing(false);
    await load();
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading workflow…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-1 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Workflow contract
        </h2>
        <p className="mb-4 text-xs text-muted-foreground">
          The declarative lifecycle Dash follows when delegating, reviewing, and closing GitHub issues.
          Customers and Dash itself can edit this. Each save creates a revision.
        </p>

        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{workflow?.name}</span>
                  {workflow?.is_default ? (
                    <Badge variant="secondary" className="text-[10px]">Dash default</Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px]">rev {workflow?.revision}</Badge>
                  )}
                </div>
                {workflow?.rationale && (
                  <p className="mt-1 text-xs text-muted-foreground">{workflow.rationale}</p>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowHistory((v) => !v)}
                  disabled={revisions.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
                >
                  <History className="h-3 w-3" />
                  History {revisions.length > 0 && `(${revisions.length})`}
                </button>
                {!editing && (
                  <button
                    onClick={startEdit}
                    className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Edit
                  </button>
                )}
              </div>
            </div>

            {!editing && (
              <pre className="max-h-[480px] overflow-auto rounded-md border border-border bg-muted/40 p-3 text-[11px] leading-relaxed font-mono whitespace-pre-wrap">
                {workflow?.body}
              </pre>
            )}

            {editing && (
              <div className="space-y-2">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={20}
                  spellCheck={false}
                  className="w-full rounded-md border border-border bg-background p-3 font-mono text-[11px] leading-relaxed focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/10"
                />
                <input
                  type="text"
                  placeholder="Optional: why this change?"
                  value={rationale}
                  onChange={(e) => setRationale(e.target.value)}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/10"
                />
                {error && <p className="text-xs text-red-600">{error}</p>}
                <div className="flex justify-end gap-2 pt-1">
                  <button
                    onClick={() => setEditing(false)}
                    className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={!draft.trim() || saving}
                    className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
                  >
                    {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                    Save revision
                  </button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <ProposalsPanel proposals={proposals} onChanged={load} />

        {showHistory && revisions.length > 0 && (
          <Card className="mt-3">
            <CardContent className="space-y-2 p-4">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Revision history
              </h3>
              <div className="space-y-1">
                {revisions.map((r) => (
                  <div
                    key={r.revision}
                    className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-xs"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px]">rev {r.revision}</span>
                        {r.is_active && <Badge variant="default" className="text-[9px]">active</Badge>}
                        <span className="text-muted-foreground">
                          {r.author === "dash" ? "Dash" : "you"}
                        </span>
                      </div>
                      {r.rationale && (
                        <p className="mt-0.5 text-[11px] text-muted-foreground">{r.rationale}</p>
                      )}
                    </div>
                    <span className="text-[10px] text-muted-foreground">
                      {timeAgo(r.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}


// ── Workflow proposals panel ────────────────────────────────────────────

function formatChangeValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length === 0 ? "[]" : `[${v.join(", ")}]`;
  if (typeof v === "object") {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

function ProposalsPanel({
  proposals,
  onChanged,
}: {
  proposals: WorkflowProposal[];
  onChanged: () => void | Promise<void>;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (proposals.length === 0) return null;

  async function handleAccept(id: string) {
    setBusyId(id);
    setError(null);
    const result = await acceptWorkflowProposal(id);
    setBusyId(null);
    if (!result.ok) {
      setError(result.error ?? "Accept failed");
      return;
    }
    await onChanged();
  }

  async function handleDismiss(id: string) {
    setBusyId(id);
    setError(null);
    const result = await dismissWorkflowProposal(id);
    setBusyId(null);
    if (!result.ok) {
      setError(result.error ?? "Dismiss failed");
      return;
    }
    await onChanged();
  }

  return (
    <Card className="mt-3 border-amber-200/60 dark:border-amber-900/40">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Workflow proposals from Dash ({proposals.length})
          </h3>
          <span className="text-[10px] text-muted-foreground">
            Accept applies the change as a new revision authored by you.
          </span>
        </div>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/40 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </div>
        )}

        <div className="space-y-2">
          {proposals.map((p) => {
            const change = p.suggested_change;
            const fieldPath = change?.section && change?.field
              ? `${change.section}.${change.field}`
              : "—";
            const busy = busyId === p.id;
            return (
              <div
                key={p.id}
                className="rounded-md border border-border bg-muted/30 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold">{p.signal_kind ?? p.title}</span>
                      {p.severity && (
                        <Badge
                          variant={p.severity === "warn" ? "destructive" : "secondary"}
                          className="text-[9px]"
                        >
                          {p.severity}
                        </Badge>
                      )}
                    </div>
                    {p.rationale && (
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {p.rationale}
                      </p>
                    )}
                    {change && (
                      <div className="mt-2 rounded border border-border bg-background px-2.5 py-1.5 font-mono text-[11px]">
                        <span className="text-muted-foreground">{fieldPath}:</span>{" "}
                        <span className="text-red-600 dark:text-red-400 line-through">
                          {formatChangeValue(change.from)}
                        </span>{" "}
                        →{" "}
                        <span className="text-green-700 dark:text-green-400">
                          {formatChangeValue(change.to)}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <button
                      onClick={() => handleAccept(p.id)}
                      disabled={!p.applicable || busy}
                      title={p.applicable ? "Apply as a new revision" : "Proposal payload is incomplete"}
                      className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
                    >
                      {busy ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Check className="h-3 w-3" />
                      )}
                      Accept
                    </button>
                    <button
                      onClick={() => handleDismiss(p.id)}
                      disabled={busy}
                      className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                    >
                      <X className="h-3 w-3" />
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}


// ── Fleet section ───────────────────────────────────────────────────────

function statusBadgeVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "approved" || status === "resolved") return "default";
  if (status === "changes_requested") return "destructive";
  if (status === "pr_opened" || status === "reviewed") return "secondary";
  return "outline";
}

function formatStatus(status: string): string {
  return status.replace(/_/g, " ");
}

function FleetStateChip({ color, label, desc }: { color: string; label: string; desc: string }) {
  return (
    <span
      title={desc}
      className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 font-mono text-[10px] text-foreground"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", color)} />
      {label}
    </span>
  );
}


function FleetSection() {
  const [delegations, setDelegations] = useState<Delegation[]>([]);
  const [summary, setSummary] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [supervising, setSupervising] = useState(false);
  const [report, setReport] = useState<SupervisorReportResponse | null>(null);
  const [refilingId, setRefilingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const data = await fetchDelegations();
    setLoading(false);
    if (!data) {
      setError("Could not load delegations.");
      setDelegations([]);
      return;
    }
    setDelegations(data.delegations || []);
    setSummary(data.summary || "");
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRunSupervisor() {
    setSupervising(true);
    setError(null);
    const r = await runSupervisor();
    setSupervising(false);
    if (!r) {
      setError("Supervisor run failed.");
      return;
    }
    setReport(r);
    await load();
  }

  async function handleRefile(d: Delegation) {
    if (!confirm(
      `Refile ${d.repo}#${d.issue_number} to the next agent in the workflow's fallback chain? ` +
      `This closes the current issue and creates a new one.`,
    )) return;
    const key = `${d.repo}#${d.issue_number}`;
    setRefilingId(key);
    setError(null);
    const result = await refileDelegation(d.repo, d.issue_number);
    setRefilingId(null);
    if (!result.ok) {
      setError(result.error || "Refile failed.");
      return;
    }
    await load();
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading delegations…
      </div>
    );
  }

  const stalled = delegations.filter((d) => d.has_stalled_marker && !d.has_refiled_marker);
  const refiled = delegations.filter((d) => d.has_refiled_marker);
  const active = delegations.filter((d) => !d.has_stalled_marker);

  return (
    <div className="space-y-6">
      {/* ── Explainer ─────────────────────────────────────────── */}
      <Card className="border-dashed">
        <CardContent className="space-y-3 p-4 text-xs leading-relaxed text-muted-foreground">
          <p>
            <span className="font-semibold text-foreground">Fleet</span> is Dash's pool of coding
            agents — Claude Code, Codex, Cursor, anything that listens on GitHub. When you delegate
            an issue to one (via comment-mention, label, or assignment), Dash files a structured
            task, watches the resulting PR, and supervises the lifecycle below.
          </p>
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <FleetStateChip color="bg-slate-400" label="pending" desc="filed, agent hasn't picked it up yet" />
            <span className="text-muted-foreground/50">→</span>
            <FleetStateChip color="bg-blue-500" label="running" desc="agent is working, PR opened" />
            <span className="text-muted-foreground/50">→</span>
            <FleetStateChip color="bg-amber-500" label="review" desc="Dash reviewed against your acceptance criteria" />
            <span className="text-muted-foreground/50">→</span>
            <FleetStateChip color="bg-emerald-500" label="done" desc="PR merged" />
            <span className="text-muted-foreground/30">|</span>
            <FleetStateChip color="bg-rose-500" label="failed" desc="PR closed without merge or agent gave up" />
            <FleetStateChip color="bg-zinc-400" label="cancelled" desc="you closed the issue" />
          </div>
          <p className="pt-1">
            The supervisor reconciles every 12 minutes per tenant, plus reacts in real time to
            GitHub webhooks if you've configured them. Stalled work gets refiled to the next agent
            in your workflow's fallback chain. See{" "}
            <span className="font-mono text-foreground">Settings → Workflow</span> to customize the
            policy.
          </p>
        </CardContent>
      </Card>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Active delegations
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">{summary}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh
            </button>
            <button
              onClick={handleRunSupervisor}
              disabled={supervising}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {supervising ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              Run supervisor
            </button>
          </div>
        </div>

        {error && (
          <Card className="mb-3 border-red-500/30 bg-red-500/5">
            <CardContent className="p-3 text-xs text-red-600">{error}</CardContent>
          </Card>
        )}

        {report && (
          <Card className="mb-3 bg-muted/30">
            <CardContent className="space-y-1 p-3 text-xs">
              <div className="font-medium">
                Last run: {report.delegations_seen} delegations across {report.repos_scanned} repos
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(report.by_kind).map(([kind, count]) => (
                  <Badge key={kind} variant="outline" className="text-[10px]">
                    {kind}: {count}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {stalled.length > 0 && (
          <div className="mb-4">
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Stalled — refile-eligible ({stalled.length})
            </h3>
            <div className="space-y-2">
              {stalled.map((d) => (
                <DelegationRow
                  key={`${d.repo}#${d.issue_number}`}
                  d={d}
                  isRefiling={refilingId === `${d.repo}#${d.issue_number}`}
                  onRefile={() => handleRefile(d)}
                />
              ))}
            </div>
          </div>
        )}

        {active.length > 0 && (
          <div className="mb-4">
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Active ({active.length})
            </h3>
            <div className="space-y-2">
              {active.map((d) => (
                <DelegationRow key={`${d.repo}#${d.issue_number}`} d={d} />
              ))}
            </div>
          </div>
        )}

        {refiled.length > 0 && (
          <div className="mb-4">
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Already refiled ({refiled.length})
            </h3>
            <div className="space-y-2">
              {refiled.map((d) => (
                <DelegationRow key={`${d.repo}#${d.issue_number}`} d={d} />
              ))}
            </div>
          </div>
        )}

        {delegations.length === 0 && (
          <Card>
            <CardContent className="p-4 text-xs text-muted-foreground">
              No Dash delegations found yet. File one with{" "}
              <code className="rounded bg-muted px-1 py-0.5">github_delegate_task</code>{" "}
              from chat or the brief.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function DelegationRow({
  d,
  isRefiling,
  onRefile,
}: {
  d: Delegation;
  isRefiling?: boolean;
  onRefile?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-card p-3 text-xs">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={d.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-[11px] text-foreground hover:text-primary"
          >
            {d.repo}#{d.issue_number}
          </a>
          <Badge variant={statusBadgeVariant(d.status)} className="text-[9px]">
            {formatStatus(d.status)}
          </Badge>
          <span className="text-[10px] text-muted-foreground">→ {d.agent_id}</span>
          {d.pr_number && (
            <a
              href={`https://github.com/${d.repo}/pull/${d.pr_number}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary"
            >
              <ExternalLink className="h-2.5 w-2.5" />
              PR #{d.pr_number}
            </a>
          )}
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          {d.has_dash_review && (
            <span className="text-[10px] text-muted-foreground">reviewed</span>
          )}
          {d.has_stalled_marker && !d.has_refiled_marker && (
            <span className="text-[10px] text-amber-600">stalled</span>
          )}
          {d.has_refiled_marker && (
            <span className="text-[10px] text-muted-foreground">refiled</span>
          )}
        </div>
      </div>
      {onRefile && (
        <button
          onClick={onRefile}
          disabled={!d.refile_eligible || isRefiling}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-40"
        >
          {isRefiling ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Refile
        </button>
      )}
    </div>
  );
}
