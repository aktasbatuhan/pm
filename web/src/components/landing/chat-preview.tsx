"use client";

import { DashLogo } from "@/components/dash-logo";
import { ArrowUp } from "lucide-react";

export function LandingChatPreview() {
  return (
    <div className="relative">
      {/* Subtle glow */}
      <div className="pointer-events-none absolute -inset-x-4 -inset-y-6 rounded-3xl bg-gradient-to-b from-primary/5 to-transparent blur-2xl" />

      <div className="relative overflow-hidden rounded-2xl border border-border bg-card shadow-xl">
        {/* Chrome */}
        <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-2.5">
          <div className="flex gap-1.5">
            <div className="h-2.5 w-2.5 rounded-full bg-red-400/60" />
            <div className="h-2.5 w-2.5 rounded-full bg-amber-400/60" />
            <div className="h-2.5 w-2.5 rounded-full bg-green-400/60" />
          </div>
          <div className="mx-auto text-xs text-muted-foreground">Chat with Dash</div>
        </div>

        <div className="px-5 py-6 space-y-5">
          {/* User message */}
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
              What should we build next?
            </div>
          </div>

          {/* Assistant */}
          <div className="flex gap-3">
            <div className="shrink-0">
              <DashLogo size={28} />
            </div>
            <div className="flex-1 space-y-3">
              {/* Tool badges */}
              <div className="flex flex-wrap gap-1.5">
                <ToolBadge name="brief_get_latest" />
                <ToolBadge name="workspace_get_learnings" />
                <ToolBadge name="terminal: gh pr list" />
              </div>

              <div className="text-sm leading-relaxed text-foreground/90 space-y-3">
                <p>
                  Three signals are aligning on{" "}
                  <span className="font-semibold">subscription tiers</span>:
                </p>
                <ul className="space-y-2 pl-4">
                  <li className="flex items-start gap-2">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                    <span>
                      acme-api #62 was opened this morning — your first pricing conversation in 3
                      weeks
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                    <span>
                      PostHog shows 42% of active users hit the feature gate last 7 days (up from 18%)
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                    <span>
                      3 support tickets this week mentioning "when's paid plan coming?"
                    </span>
                  </li>
                </ul>
                <p>
                  <span className="font-semibold">My call:</span> ship pricing tiers before v2 dashboard.
                  Revenue unlocks hiring. Want me to draft the rollout plan?
                </p>
              </div>

              {/* Follow-ups */}
              <div className="flex flex-wrap gap-1.5 pt-1">
                <Pill>Draft the rollout plan</Pill>
                <Pill>Show me the PostHog trend</Pill>
                <Pill>What's the risk of delaying v2?</Pill>
              </div>
            </div>
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-border px-4 py-3">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2">
            <div className="flex-1 text-sm text-muted-foreground/60">Message Dash...</div>
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/20 text-primary">
              <ArrowUp className="h-3.5 w-3.5" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ToolBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
      <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
      {name}
    </span>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <div className="inline-flex items-center rounded-full border border-border bg-card px-3 py-1 text-[11.5px] text-muted-foreground">
      {children}
    </div>
  );
}
