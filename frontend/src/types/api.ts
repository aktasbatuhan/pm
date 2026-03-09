// Shared API response types

export interface SetupStatus {
  configured: boolean;
  hasToken: boolean;
  org: string;
  projectNumber: number;
}

export interface ChatSession {
  id: string;
  name: string;
  sessionId?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: Record<string, unknown>;
  createdAt: string;
}

// Matches ProjectItem from src/tools/github.ts
export interface ProjectItem {
  title: string;
  number: number | null;
  state: string | null;
  status: string | null;
  priority: string | null;
  size: string | number | null;
  estimate: string | number | null;
  repository: string | null;
  issue_url: string | null;
  assignees: string[];
  custom_fields: Record<string, string | number | null>;
}

export interface DashboardStats {
  statusCounts: Record<string, number>;
  assigneeWorkload: Record<string, Record<string, number>>;
  inProgress: ProjectItem[];
  priorityCounts: Record<string, number>;
  sprintBreakdown: Record<string, Record<string, number>>;
  overview: {
    total: number;
    done: number;
    completionPct: number;
    inProgressCount: number;
    blocked: number;
  };
}

export interface DashboardResponse {
  items: ProjectItem[];
  stats: DashboardStats;
  filters: {
    sprints: string[];
    assignees: string[];
    priorities: string[];
    statuses: string[];
    repositories: string[];
  };
  fetchedAt: string;
}

export interface DashboardTab {
  id: string;
  name: string;
  position: number;
  filters?: Record<string, string> | null;
  refreshPrompt?: string | null;
  refreshIntervalMs?: number | null;
  lastRefreshedAt?: string | null;
}

export interface DashboardWidget {
  id: string;
  tabId?: string;
  type: "stat-card" | "chart" | "table" | "list" | "markdown";
  title: string;
  size: "quarter" | "half" | "full";
  config: Record<string, unknown>;
  position: number;
}

export interface Insight {
  id: string;
  title: string;
  summary: string;
  signalIds?: string;
  category: string;
  priority: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface Signal {
  id: string;
  source: string;
  type: string;
  data: string;
  summary?: string;
  createdAt: string;
}

export interface KnowledgeFile {
  path: string;
  size: number;
}

export interface SettingsMap {
  [key: string]: unknown;
}
