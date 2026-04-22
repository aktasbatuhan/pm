import type { Brief, WorkspaceStatus, ChatEvent, Session, ChatMessage } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL || "";

// ── Auth ──────────────────────────────────────────────────────────────

function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("dash_token") || "";
}

function setToken(token: string) {
  localStorage.setItem("dash_token", token);
}

function clearToken() {
  localStorage.removeItem("dash_token");
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function checkAuth(): Promise<{
  authenticated: boolean;
  needs_setup: boolean;
}> {
  const res = await fetch(`${API}/api/auth/check`, { headers: authHeaders() });
  return res.json();
}

export async function setupPassword(
  password: string
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API}/api/auth/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  const data = await res.json();
  if (data.token) setToken(data.token);
  return data;
}

export async function login(
  password: string
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  const data = await res.json();
  if (data.token) setToken(data.token);
  return data;
}

export function logout() {
  clearToken();
}

export interface BriefSummary {
  id: string;
  headline: string;
  data_sources: string;
  created_at: number;
  cover_url: string;
  action_count: number;
  pending_count: number;
}

export async function fetchBriefs(limit: number = 20): Promise<BriefSummary[]> {
  const res = await fetch(`${API}/api/briefs?limit=${limit}`);
  const data = await res.json();
  return data.briefs ?? [];
}

export async function fetchBriefById(briefId: string): Promise<Brief | null> {
  const res = await fetch(`${API}/api/brief/${briefId}`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.brief ?? null;
}

export async function fetchBrief(): Promise<Brief | null> {
  const res = await fetch(`${API}/api/brief/latest`);
  const data = await res.json();
  return data.brief ?? null;
}

export async function fetchWorkspace(): Promise<WorkspaceStatus | null> {
  const res = await fetch(`${API}/api/workspace/status`);
  if (!res.ok) return null;
  return res.json();
}

export async function resolveAction(actionId: string): Promise<void> {
  await fetch(`${API}/api/brief/actions/${actionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "resolved" }),
  });
}

export async function fetchSessions(): Promise<Session[]> {
  const res = await fetch(`${API}/api/sessions`);
  const data = await res.json();
  return data.sessions ?? [];
}

export async function fetchSessionMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API}/api/sessions/${sessionId}`);
  const data = await res.json();
  return (data.messages ?? []).map((m: Record<string, unknown>) => ({
    id: String(m.id ?? crypto.randomUUID()),
    role: m.role as "user" | "assistant",
    content: String(m.content ?? ""),
  }));
}

// ── Onboarding & Integrations ─────────────────────────────────────────

export async function getOnboardingProfile(): Promise<Record<string, string>> {
  const res = await fetch(`${API}/api/onboarding/profile`);
  return res.json();
}

export async function saveOnboardingProfile(data: Record<string, string>): Promise<void> {
  await fetch(`${API}/api/onboarding/profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export interface Integration {
  platform: string;
  auth_type: string;
  credentials: string;
  status: string;
  display_name: string;
  connected_at: number | null;
  last_verified: number | null;
}

export async function getIntegrations(): Promise<Integration[]> {
  const res = await fetch(`${API}/api/integrations`);
  const data = await res.json();
  return data.integrations ?? [];
}

export async function connectIntegration(
  platform: string,
  credentials: string,
  authType: string = "token",
): Promise<{ ok: boolean; status: string; message: string }> {
  const res = await fetch(`${API}/api/integrations/${platform}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credentials, auth_type: authType }),
  });
  return res.json();
}

export async function disconnectIntegration(platform: string): Promise<void> {
  await fetch(`${API}/api/integrations/${platform}`, { method: "DELETE" });
}

export async function completeOnboarding(organization: string): Promise<void> {
  await fetch(`${API}/api/onboarding/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ organization }),
  });
}

// ── Waitlist ──────────────────────────────────────────────────────────

export async function submitWaitlist(data: {
  name: string;
  email: string;
  organization: string;
  role: string;
  team_size: string;
  pain_point: string;
}): Promise<{ ok: boolean }> {
  const res = await fetch(`${API}/api/waitlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return res.json();
}

export function requestNewBrief(): void {
  triggerBackgroundTask(
    "Load the pm-brief/daily-brief skill with skill_view and follow it exactly. " +
    "For GitHub, use the App installation token exposed as $GITHUB_TOKEN via `gh api` " +
    "(start with `gh api /installation/repositories` to see reachable repos). " +
    "Read your workspace blueprint with workspace_get_blueprint and recent learnings with workspace_get_learnings. " +
    "Compare to the last brief via brief_get_latest. " +
    "Produce a structured brief with charts and store it with brief_store including suggested_prompts.",
    `brief-${Date.now()}`
  );
}

/** Fire an agent task in the background. Does NOT read the SSE stream. */
export function triggerBackgroundTask(message: string, threadId?: string): void {
  fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      threadId: threadId ?? `system-${Date.now()}`,
      source: "system",
    }),
  }).catch(() => {});
}

// ── Changelog ─────────────────────────────────────────────────────────

export interface Changelog {
  id: string;
  content: string;
  period_start: number;
  period_end: number;
  pr_count: number;
  created_at: number;
}

export async function fetchChangelogs(limit: number = 10): Promise<Changelog[]> {
  const res = await fetch(`${API}/api/changelogs?limit=${limit}`);
  const data = await res.json();
  return data.changelogs ?? [];
}

export async function fetchLatestChangelog(): Promise<Changelog | null> {
  const res = await fetch(`${API}/api/changelogs/latest`);
  const data = await res.json();
  return data.changelog ?? null;
}

export function generateChangelog(): void {
  fetch(`${API}/api/changelogs/generate`, { method: "POST" }).catch(() => {});
}

// ── Goals ─────────────────────────────────────────────────────────────

export interface GoalActionItem {
  title: string;
  description?: string;
  priority?: "critical" | "high" | "medium" | "low";
  references?: Array<{ type: string; url?: string; title: string }>;
  status?: "pending" | "in-progress" | "resolved" | "dismissed";
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  target_date: string;
  status: "active" | "completed" | "paused" | "missed";
  progress: number;
  trajectory: string;
  related_items: Array<{ title: string; url?: string; status?: string }>;
  action_items: GoalActionItem[];
  last_evaluated_at: number | null;
  created_at: number;
  updated_at: number;
}

export interface GoalSnapshot {
  id: string;
  goal_id: string;
  progress: number;
  trajectory: string;
  action_items: GoalActionItem[];
  brief_id: string | null;
  notes: string | null;
  created_at: number;
}

export async function fetchGoalHistory(goalId: string, limit: number = 20): Promise<GoalSnapshot[]> {
  const res = await fetch(`${API}/api/goals/${goalId}/history?limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.snapshots ?? [];
}

export async function fetchGoals(status: string = "active"): Promise<Goal[]> {
  const res = await fetch(`${API}/api/goals?status=${status}`);
  const data = await res.json();
  return data.goals ?? [];
}

export async function createGoal(goal: {
  title: string;
  description?: string;
  target_date?: string;
}): Promise<{ ok: boolean; id: string }> {
  const res = await fetch(`${API}/api/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(goal),
  });
  return res.json();
}

export async function updateGoal(
  goalId: string,
  updates: Partial<Goal>
): Promise<void> {
  await fetch(`${API}/api/goals/${goalId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
}

export async function deleteGoal(goalId: string): Promise<void> {
  await fetch(`${API}/api/goals/${goalId}`, { method: "DELETE" });
}

// ── Team Pulse ────────────────────────────────────────────────────────

export interface TeamMember {
  id: string;
  member_name: string;
  github_handle: string;
  prs_merged: number;
  reviews_done: number;
  days_since_active: number;
  flags: string[];
  period: string;
  created_at: number;
}

export async function fetchTeamPulse(): Promise<TeamMember[]> {
  const res = await fetch(`${API}/api/team/pulse`);
  const data = await res.json();
  return data.members ?? [];
}

export function generateTeamPulse(): void {
  fetch(`${API}/api/team/pulse/generate`, { method: "POST" }).catch(() => {});
}

// ── Reports ───────────────────────────────────────────────────────────

export interface ReportTemplate {
  id: string;
  name: string;
  body: string;
  resources: {
    repos?: string[];
    learning_categories?: string[];
    brief_depth?: number;
    signal_sources?: string[];
  };
  schedule: "none" | "daily" | "weekly" | "monthly";
  cron_job_id: string | null;
  report_count: number;
  created_at: number;
  updated_at: number;
}

export interface Report {
  id: string;
  template_id: string;
  content: string;
  created_at: number;
}

export async function fetchReportTemplates(): Promise<ReportTemplate[]> {
  const res = await fetch(`${API}/api/reports/templates`);
  const data = await res.json();
  return data.templates ?? [];
}

export async function fetchReportTemplate(id: string): Promise<ReportTemplate | null> {
  const res = await fetch(`${API}/api/reports/templates/${id}`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.template ?? null;
}

export async function createReportTemplate(t: {
  name: string;
  body: string;
  resources?: Record<string, unknown>;
  schedule?: string;
}): Promise<{ ok: boolean; id: string }> {
  const res = await fetch(`${API}/api/reports/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(t),
  });
  return res.json();
}

export async function updateReportTemplate(
  id: string,
  updates: Partial<ReportTemplate>,
): Promise<void> {
  await fetch(`${API}/api/reports/templates/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
}

export async function deleteReportTemplate(id: string): Promise<void> {
  await fetch(`${API}/api/reports/templates/${id}`, { method: "DELETE" });
}

export function generateReport(templateId: string): void {
  fetch(`${API}/api/reports/templates/${templateId}/generate`, {
    method: "POST",
  }).catch(() => {});
}

export async function fetchReports(templateId?: string, limit: number = 20): Promise<Report[]> {
  const url = templateId
    ? `${API}/api/reports?template_id=${templateId}&limit=${limit}`
    : `${API}/api/reports?limit=${limit}`;
  const res = await fetch(url);
  const data = await res.json();
  return data.reports ?? [];
}

export async function deleteReport(id: string): Promise<void> {
  await fetch(`${API}/api/reports/${id}`, { method: "DELETE" });
}

// ── Schedules ─────────────────────────────────────────────────────────

export interface Schedule {
  id: string;
  name: string;
  prompt: string;
  schedule: { kind: string; display?: string; [key: string]: unknown };
  schedule_display: string;
  repeat: { times: number | null; completed: number };
  enabled: boolean;
  created_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
}

export async function fetchSchedules(): Promise<Schedule[]> {
  const res = await fetch(`${API}/api/schedules`);
  const data = await res.json();
  return data.schedules ?? [];
}

export async function createSchedule(s: {
  name: string;
  prompt: string;
  schedule: string;
}): Promise<{ ok: boolean; job?: Schedule; error?: string }> {
  const res = await fetch(`${API}/api/schedules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { ok: false, error: data?.error || `HTTP ${res.status}` };
  }
  return { ok: true, ...data };
}

export async function updateSchedule(
  id: string,
  updates: { enabled?: boolean; name?: string },
): Promise<void> {
  await fetch(`${API}/api/schedules/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
}

export async function deleteSchedule(id: string): Promise<void> {
  await fetch(`${API}/api/schedules/${id}`, { method: "DELETE" });
}

export async function runScheduleNow(id: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API}/api/cron/run/${id}`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: data?.error || `HTTP ${res.status}` };
  return { ok: true };
}

export interface CronStatus {
  ticker: {
    started_at: number | null;
    last_tick_at: number | null;
    last_error: string | null;
    ticks: number;
    jobs_run: number;
  };
  now: number;
  job_count: number;
  jobs: Array<{
    id: string;
    name: string;
    enabled: boolean;
    schedule_display: string;
    next_run_at: string | null;
    last_run_at: string | null;
    last_status: string | null;
    last_error: string | null;
  }>;
}

export async function fetchCronStatus(): Promise<CronStatus | null> {
  try {
    const res = await fetch(`${API}/api/cron/status`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ── Signal Collector ──────────────────────────────────────────────────

export interface SignalSource {
  id: string;
  name: string;
  type: "twitter" | "exa" | "firecrawl";
  config: Record<string, unknown>;
  filter: string;
  enabled: number;
  last_fetched_at: number | null;
  created_at: number;
}

export interface Signal {
  id: string;
  source_id: string;
  source_name: string;
  source_type: string;
  title: string;
  body: string;
  url: string;
  author: string;
  relevance_score: number;
  status: "new" | "read" | "starred" | "dismissed";
  metadata: Record<string, unknown>;
  external_created_at: number;
  created_at: number;
}

export async function fetchSignalSources(): Promise<SignalSource[]> {
  const res = await fetch(`${API}/api/signals/sources`);
  const data = await res.json();
  return data.sources ?? [];
}

export async function createSignalSource(source: {
  name: string;
  type: string;
  config: Record<string, unknown>;
  filter?: string;
}): Promise<{ ok: boolean; id: string }> {
  const res = await fetch(`${API}/api/signals/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(source),
  });
  return res.json();
}

export async function updateSignalSource(
  id: string,
  updates: Partial<SignalSource>,
): Promise<void> {
  await fetch(`${API}/api/signals/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
}

export async function deleteSignalSource(id: string): Promise<void> {
  await fetch(`${API}/api/signals/sources/${id}`, { method: "DELETE" });
}

export async function fetchSignals(status: string = "all", limit: number = 50): Promise<Signal[]> {
  const res = await fetch(`${API}/api/signals?status=${status}&limit=${limit}`);
  const data = await res.json();
  return data.signals ?? [];
}

export async function updateSignalStatus(id: string, status: string): Promise<void> {
  await fetch(`${API}/api/signals/${id}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export function triggerSignalFetch(sourceId: string = "all"): void {
  fetch(`${API}/api/signals/sources/${sourceId}/fetch`, { method: "POST" }).catch(() => {});
}

// ── KPIs ──────────────────────────────────────────────────────────────

export interface KPIValue {
  id: string;
  value: number;
  source: string | null;
  notes: string | null;
  recorded_at: number;
}

export interface KPIFlag {
  id: string;
  kpi_id: string;
  kind: "risk" | "opportunity";
  title: string;
  description: string | null;
  references: Array<{ type: string; url?: string; title: string }>;
  brief_id: string | null;
  status: "open" | "resolved" | "dismissed";
  created_at: number;
  updated_at: number;
}

export interface KPI {
  id: string;
  name: string;
  description: string | null;
  unit: string | null;
  direction: "higher" | "lower";
  target_value: number | null;
  current_value: number | null;
  previous_value: number | null;
  measurement_plan: string;
  measurement_status: "pending" | "configured" | "failed";
  measurement_error: string | null;
  cron_job_id: string | null;
  status: "active" | "paused" | "archived";
  created_at: number;
  updated_at: number;
  last_measured_at: number | null;
  history: KPIValue[];
  flags: KPIFlag[];
}

export async function fetchKPIs(status: string = "active"): Promise<KPI[]> {
  const res = await fetch(`${API}/api/kpis?status=${status}`);
  const data = await res.json();
  return data.kpis ?? [];
}

export async function fetchKPI(id: string): Promise<KPI | null> {
  const res = await fetch(`${API}/api/kpis/${id}`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.kpi ?? null;
}

export async function createKPI(kpi: {
  name: string;
  description?: string;
  unit?: string;
  direction?: "higher" | "lower";
  target_value?: number | null;
}): Promise<{ ok: boolean; id?: string; error?: string }> {
  const res = await fetch(`${API}/api/kpis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(kpi),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: data?.error || `HTTP ${res.status}` };
  return { ok: true, id: data?.id };
}

export async function updateKPI(id: string, updates: Partial<KPI>): Promise<void> {
  await fetch(`${API}/api/kpis/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
}

export async function deleteKPI(id: string): Promise<void> {
  await fetch(`${API}/api/kpis/${id}`, { method: "DELETE" });
}

export function refreshKPI(id: string): Promise<Response> {
  return fetch(`${API}/api/kpis/${id}/refresh`, { method: "POST" });
}

export async function updateKPIFlag(flagId: string, status: string): Promise<void> {
  await fetch(`${API}/api/kpis/flags/${flagId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

// ── Settings ──────────────────────────────────────────────────────────

export interface ModelOption {
  id: string;
  label: string;
  family: string;
}

export interface ModelSetting {
  current: string;
  options: ModelOption[];
}

export async function fetchModelSetting(): Promise<ModelSetting | null> {
  try {
    const res = await fetch(`${API}/api/settings/model`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function updateModelSetting(model: string): Promise<{ ok: boolean; error?: string; current?: string }> {
  const res = await fetch(`${API}/api/settings/model`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: data?.error || `HTTP ${res.status}` };
  return { ok: true, current: data?.current };
}

// ── GitHub App ────────────────────────────────────────────────────────

export interface GithubAppInstallation {
  installation_id: string;
  account_login: string;
  account_type: string | null;
  repo_selection: string | null;
  installed_at: number;
  updated_at: number;
}

export interface GithubAppStatus {
  configured: boolean;
  slug?: string;
  installation?: GithubAppInstallation | null;
}

export async function fetchGithubAppStatus(): Promise<GithubAppStatus> {
  const res = await fetch(`${API}/api/integrations/github/app-status`);
  if (!res.ok) return { configured: false };
  return res.json();
}

export function githubAppInstallUrl(): string {
  return `${API}/api/integrations/github/install`;
}

export async function disconnectGithubApp(): Promise<{ ok: boolean; uninstall_hint?: string | null }> {
  const res = await fetch(`${API}/api/integrations/github/app`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, uninstall_hint: data?.uninstall_hint };
}

// ── MCP Servers ───────────────────────────────────────────────────────

export interface MCPServer {
  name: string;
  transport: "stdio" | "http" | "unknown";
  command?: string | null;
  args: string[];
  env: Record<string, string>;
  url?: string | null;
  headers: Record<string, string>;
  timeout?: number | null;
}

export async function fetchMCPServers(): Promise<MCPServer[]> {
  const res = await fetch(`${API}/api/mcp/servers`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.servers ?? [];
}

export async function createMCPServer(server: {
  name: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  timeout?: number;
}): Promise<{ ok: boolean; error?: string; name?: string }> {
  const res = await fetch(`${API}/api/mcp/servers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(server),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: data?.error || `HTTP ${res.status}` };
  return { ok: true, name: data?.name };
}

export async function deleteMCPServer(name: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API}/api/mcp/servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: data?.error || `HTTP ${res.status}` };
  return { ok: true };
}

// ── Sessions ──────────────────────────────────────────────────────────

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`${API}/api/sessions/${sessionId}`, { method: "DELETE" });
}

/**
 * Stream chat via SSE using fetch + ReadableStream.
 * Calls onEvent for each parsed SSE event.
 * Returns a promise that resolves when the stream ends.
 */
export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (event: ChatEvent) => void,
  attachments?: Array<{ name: string; type: string; content: string; isImage: boolean }>,
  externalAbort?: AbortController,
): Promise<void> {
  const controller = externalAbort ?? new AbortController();
  const timeout = setTimeout(() => controller.abort(), 900_000);

  // If there are attachments, append their content to the message
  let fullMessage = message;
  if (attachments && attachments.length > 0) {
    const attachmentText = attachments
      .map((a) => {
        if (a.isImage) {
          return `\n\n[Attached image: ${a.name}]`;
        }
        return `\n\n--- Attached file: ${a.name} ---\n${a.content}\n--- End of ${a.name} ---`;
      })
      .join("");
    fullMessage = message + attachmentText;
  }

  try {
    const res = await fetch(`${API}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: fullMessage, threadId }),
      signal: controller.signal,
    });

    if (!res.ok) {
      onEvent({ type: "error", message: `HTTP ${res.status}: ${res.statusText}` });
      return;
    }

    if (!res.body) {
      onEvent({ type: "error", message: "No response body" });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete lines
      let nlIdx;
      while ((nlIdx = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, nlIdx);
        buffer = buffer.slice(nlIdx + 1);

        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6)) as ChatEvent;
            onEvent(event);
            if (event.type === "done" || event.type === "error") {
              return;
            }
          } catch {
            // skip malformed JSON
          }
        }
        // Ignore keepalive comments (lines starting with ":")
      }
    }
  } catch (e) {
    if (controller.signal.aborted) {
      onEvent({ type: "error", message: "Request timed out" });
    } else {
      onEvent({
        type: "error",
        message: e instanceof Error ? e.message : "Connection lost",
      });
    }
  } finally {
    clearTimeout(timeout);
  }
}
