import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";

import { getSettingString } from "../db/settings.ts";

function getPostHogConfig() {
  const apiKey = getSettingString("integration.posthog_api_key");
  const host = getSettingString("integration.posthog_host", "https://us.posthog.com");
  const projectId = getSettingString("integration.posthog_project_id");

  if (!apiKey) throw new Error("PostHog not configured. Tell the user to go to Settings and add their PostHog API Key, Host, and Project ID.");
  if (!projectId) throw new Error("PostHog Project ID not configured. Tell the user to go to Settings and add their PostHog Project ID.");

  return { apiKey, host: host.replace(/\/+$/, ""), projectId };
}

async function posthogRequest<T>(endpoint: string, method: string, body?: unknown): Promise<T> {
  const { apiKey, host } = getPostHogConfig();
  const res = await fetch(`${host}${endpoint}`, {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PostHog API error ${res.status}: ${text.slice(0, 500)}`);
  }

  return res.json() as Promise<T>;
}

// --- Tools ---

const listEventsTool = tool(
  "posthog_list_events",
  "List available event definitions from PostHog. Call this first to discover what events exist before writing queries.",
  {
    limit: z.number().optional().describe("Max events to return (default 100)"),
  },
  async ({ limit }) => {
    const { projectId } = getPostHogConfig();
    const data = await posthogRequest<{ results: Array<{ name: string; description?: string; query_usage_30_day?: number }> }>(
      `/api/projects/${projectId}/event_definitions/?limit=${limit ?? 100}`,
      "GET",
    );

    const events = (data.results || []).map((e) => ({
      name: e.name,
      description: e.description || null,
      volume_30d: e.query_usage_30_day ?? null,
    }));

    return {
      content: [{ type: "text" as const, text: JSON.stringify(events, null, 2) }],
    };
  },
  { annotations: { readOnly: true } },
);

const queryTool = tool(
  "posthog_query",
  "Run a HogQL query against PostHog. HogQL is SQL-like. Example: SELECT event, count() FROM events WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY event ORDER BY count() DESC LIMIT 20",
  {
    query: z.string().describe("HogQL query string"),
    limit: z.number().optional().describe("Max rows to return (default 100)"),
  },
  async ({ query, limit }) => {
    const { projectId } = getPostHogConfig();
    const data = await posthogRequest(
      `/api/projects/${projectId}/query/`,
      "POST",
      {
        query: {
          kind: "HogQLQuery",
          query: limit ? `${query} LIMIT ${limit}` : query,
        },
      },
    );

    return {
      content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
    };
  },
  { annotations: { readOnly: true } },
);

const trendsTool = tool(
  "posthog_trends",
  "Query event trends over time from PostHog. Returns counts/aggregations per interval for one or more events.",
  {
    events: z.array(z.object({
      id: z.string().describe("Event name (e.g. '$pageview', 'user_signed_up')"),
      math: z.string().optional().describe("Aggregation: 'total' (default), 'dau', 'weekly_active', 'monthly_active', 'unique_group', 'hogql'"),
    })).describe("Events to query trends for"),
    date_from: z.string().describe("Start date. Relative: '-7d', '-1m', '-1y'. Absolute: '2024-01-01'"),
    date_to: z.string().optional().describe("End date (default 'now')"),
    interval: z.enum(["hour", "day", "week", "month"]).optional().describe("Bucket interval (default 'day')"),
  },
  async ({ events, date_from, date_to, interval }) => {
    const { projectId } = getPostHogConfig();
    const data = await posthogRequest(
      `/api/projects/${projectId}/query/`,
      "POST",
      {
        query: {
          kind: "TrendsQuery",
          series: events.map((e) => ({
            kind: "EventsNode",
            event: e.id,
            math: e.math || "total",
          })),
          dateRange: { date_from, date_to: date_to || undefined },
          interval: interval || "day",
        },
      },
    );

    return {
      content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
    };
  },
  { annotations: { readOnly: true } },
);

const funnelTool = tool(
  "posthog_funnel",
  "Query funnel conversion data from PostHog. Provide events in order — each is a funnel step. Returns step-by-step conversion rates.",
  {
    events: z.array(z.object({
      id: z.string().describe("Event name for this funnel step"),
    })).describe("Funnel steps in order"),
    date_from: z.string().describe("Start date (e.g. '-30d', '2024-01-01')"),
    date_to: z.string().optional().describe("End date (default 'now')"),
  },
  async ({ events, date_from, date_to }) => {
    const { projectId } = getPostHogConfig();
    const data = await posthogRequest(
      `/api/projects/${projectId}/query/`,
      "POST",
      {
        query: {
          kind: "FunnelsQuery",
          series: events.map((e) => ({
            kind: "EventsNode",
            event: e.id,
          })),
          dateRange: { date_from, date_to: date_to || undefined },
          funnelsFilter: { funnelOrderType: "ordered" },
        },
      },
    );

    return {
      content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
    };
  },
  { annotations: { readOnly: true } },
);

// --- Export ---

export const POSTHOG_WRITE_TOOL_NAMES: string[] = [];

export function createPostHogMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "posthog",
    version: "0.1.0",
    tools: [listEventsTool, queryTool, trendsTool, funnelTool],
  });
}
