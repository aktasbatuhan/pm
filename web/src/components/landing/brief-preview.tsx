"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  Target,
  GitPullRequest,
  Users,
  AlertTriangle,
  Circle,
  FileText,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Realistic mock of the Dash brief view — used on the landing page.
 * This is not live data. It's a curated example showing what a brief looks like.
 */

const MOCK_ACTIONS = [
  {
    priority: "critical",
    category: "Risk",
    title: "JWT secret exposure in sandbox environment",
    description:
      "Auth service issue #42 exposes session tokens to sandbox environment. A compromised sandbox could impersonate users.",
    refs: [{ label: "acme-api#42", url: "#" }],
  },
  {
    priority: "high",
    category: "Team",
    title: "Clear the stale review queue",
    description:
      "3 PRs sitting in review for 9+ days across core repos. Team velocity is blocked on unassigned reviews.",
    refs: [
      { label: "acme-core#84", url: "#" },
      { label: "acme-core#86", url: "#" },
    ],
  },
  {
    priority: "high",
    category: "Update",
    title: "Sprint 59 board is lagging execution",
    description:
      "Backend shipped 6 merges in 24h but the board shows 8/14 items still not started. Project tracking needs reconciliation before standup.",
    refs: [],
  },
];

const SPRINT_DATA = [
  { name: "Done", value: 5, fill: "#10b981" },
  { name: "In Progress", value: 1, fill: "#3b82f6" },
  { name: "Review", value: 2, fill: "#f59e0b" },
  { name: "Todo", value: 6, fill: "#94a3b8" },
];

const PRIORITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-amber-500",
  medium: "bg-blue-500",
};

const PRIORITY_PILL: Record<string, string> = {
  critical: "text-red-600 bg-red-50 border-red-100",
  high: "text-amber-600 bg-amber-50 border-amber-100",
  medium: "text-blue-600 bg-blue-50 border-blue-100",
};

const CATEGORY_PILL: Record<string, string> = {
  Risk: "text-red-600 bg-red-50",
  Team: "text-violet-600 bg-violet-50",
  Update: "text-blue-600 bg-blue-50",
};

export function LandingBriefPreview() {
  return (
    <div className="relative mx-auto max-w-4xl">
      {/* Subtle glow */}
      <div className="pointer-events-none absolute -inset-x-6 -inset-y-8 rounded-3xl bg-gradient-to-b from-primary/5 to-transparent blur-2xl" />

      <div className="relative overflow-hidden rounded-2xl border border-border bg-card shadow-xl">
        {/* Window chrome */}
        <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-2.5">
          <div className="flex gap-1.5">
            <div className="h-2.5 w-2.5 rounded-full bg-red-400/60" />
            <div className="h-2.5 w-2.5 rounded-full bg-amber-400/60" />
            <div className="h-2.5 w-2.5 rounded-full bg-green-400/60" />
          </div>
          <div className="mx-auto text-xs text-muted-foreground">
            dash.acme.dev — Daily Brief
          </div>
        </div>

        {/* Brief content */}
        <div className="p-8">
          {/* Header */}
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>Good morning</span>
            <span className="text-border">/</span>
            <span>Brief from 12m ago</span>
            <span className="text-border">/</span>
            <span>3 sources</span>
          </div>

          {/* Headline */}
          <h2 className="mt-3 text-[22px] font-bold tracking-tight leading-snug max-w-2xl">
            Backend shipped 6 PRs but the sprint board is stale — tracking doesn't reflect reality.
          </h2>

          {/* Exec summary bullets */}
          <ul className="mt-4 space-y-1.5 max-w-2xl">
            {[
              "Backend carried the most execution yesterday: 6 PRs merged in 24h, including release 0.2.59 and payment webhook fix.",
              "Two high-severity reliability risks remain open: auth token exposure (#42) and session recovery (#14).",
              "Sprint board shows 8/14 items not started while actual commits imply ~36% completion.",
            ].map((b, i) => (
              <li
                key={i}
                className="flex items-start gap-2.5 text-[13px] text-muted-foreground leading-relaxed"
              >
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/40" />
                {b}
              </li>
            ))}
          </ul>

          {/* Metrics */}
          <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric icon={Target} label="Sprint" value="36%" detail="5/14 done" />
            <Metric icon={GitPullRequest} label="PRs Merged" value="6" detail="last 24h" />
            <Metric icon={Users} label="Active Team" value="8" detail="contributors" />
            <Metric
              icon={AlertTriangle}
              label="Stale Reviews"
              value="3"
              detail="need attention"
              warning
            />
          </div>

          {/* Chart */}
          <div className="mt-6 rounded-xl border border-border bg-muted/20 px-4 py-4">
            <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Sprint 59 status
            </p>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={SPRINT_DATA} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" horizontal={false} opacity={0.3} />
                <XAxis type="number" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={80}
                  tick={{ fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {SPRINT_DATA.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Actions */}
          <div className="mt-8">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Action Items</h3>
              </div>
              <span className="text-xs text-muted-foreground">3 pending</span>
            </div>
            <div className="space-y-2">
              {MOCK_ACTIONS.map((a, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-border bg-card px-4 py-3.5"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex flex-col items-center gap-1 pt-0.5">
                      <div className={cn("h-2 w-2 rounded-full", PRIORITY_DOT[a.priority])} />
                      <Circle className="mt-0.5 h-4 w-4 text-muted-foreground/30" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13.5px] font-medium leading-snug">{a.title}</p>
                      <p className="mt-1 text-[12.5px] text-muted-foreground leading-relaxed">
                        {a.description}
                      </p>
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-[11px] font-medium",
                            CATEGORY_PILL[a.category] || "text-zinc-600 bg-zinc-50"
                          )}
                        >
                          {a.category}
                        </span>
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                            PRIORITY_PILL[a.priority]
                          )}
                        >
                          {a.priority}
                        </span>
                        {a.refs.map((ref, j) => (
                          <span
                            key={j}
                            className="inline-flex items-center gap-1 rounded-full border border-primary/20 px-2 py-0.5 text-[11px] font-medium text-primary"
                          >
                            <span className="opacity-50">#</span>
                            {ref.label}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Suggestions */}
          <div className="mt-6 flex flex-wrap gap-2">
            {[
              "Why did the API repo have no merges today?",
              "Help me clear the stale review queue",
              "Plan the rollout for subscription tiers",
            ].map((s) => (
              <div
                key={s}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-[12.5px] text-muted-foreground"
              >
                {s}
              </div>
            ))}
          </div>

          {/* Collapsed report */}
          <div className="mt-8 flex items-center justify-between rounded-xl border border-border bg-card px-5 py-4">
            <div className="flex items-center gap-3">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-sm font-semibold">Full Report</p>
                <p className="text-xs text-muted-foreground">
                  Detailed analysis with context and recommendations
                </p>
              </div>
            </div>
            <span className="text-xs text-muted-foreground">Expand ↓</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  detail,
  warning,
}: {
  icon: typeof Target;
  label: string;
  value: string;
  detail: string;
  warning?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card px-4 py-3.5",
        warning ? "border-amber-200 bg-amber-50/30" : "border-border"
      )}
    >
      <div className="flex items-center gap-2">
        <Icon
          className={cn(
            "h-3.5 w-3.5",
            warning ? "text-amber-500" : "text-muted-foreground"
          )}
        />
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      </div>
      <p
        className={cn(
          "mt-1.5 text-2xl font-bold tracking-tight",
          warning && "text-amber-600"
        )}
      >
        {value}
      </p>
      <p className="text-[11px] text-muted-foreground">{detail}</p>
    </div>
  );
}
