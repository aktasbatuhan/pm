// Multi-agent system types

export interface SubAgent {
  id: string;
  name: string;
  displayName: string;
  domain: string;
  status: "active" | "paused" | "disabled";
  scheduleIntervalMs: number;
  lastRunAt?: string;
  nextRunAt?: string;
  memoryPartition: string;
}

export interface Escalation {
  id: string;
  agentId: string;
  urgency: "info" | "attention" | "urgent" | "critical";
  category: string;
  title: string;
  summary: string;
  data?: Record<string, unknown>;
  status: "pending" | "synthesized" | "actioned" | "dismissed";
  synthesizedIn?: string;
  createdAt: string;
  updatedAt: string;
}

export interface Kpi {
  id: string;
  agentId?: string;
  name: string;
  displayName: string;
  targetValue: number;
  currentValue?: number;
  unit: string;
  direction: "higher_is_better" | "lower_is_better";
  thresholdWarning?: number;
  thresholdCritical?: number;
  measuredAt?: string;
  status: "on-track" | "at-risk" | "breached";
  history?: Array<{ value: number; timestamp: number }>;
}

export interface SynthesisRun {
  id: string;
  chatSessionId?: string;
  escalationsProcessed?: string[];
  summary: string;
  actions?: Record<string, unknown>;
  createdAt: string;
}
