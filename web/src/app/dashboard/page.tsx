"use client";

import { useState, useEffect, useCallback } from "react";
import { BriefView } from "@/components/brief-view";
import { ChatView } from "@/components/chat-view";
import { OnboardingView } from "@/components/onboarding-view";
import { SessionSidebar } from "@/components/session-sidebar";
import { cn } from "@/lib/utils";
import {
  fetchSessions, fetchWorkspace, logout, fetchWorkflowProposals,
} from "@/lib/api";
import type { Session, WorkspaceStatus } from "@/lib/types";
import { FileText, FileCode, MessageSquare, Lightbulb, Radar, Timer, Plus, Loader2, LogOut, Target, Settings } from "lucide-react";
import { InsightsView } from "@/components/insights-view";
import { SignalsView } from "@/components/signals-view";
import { ReportsView } from "@/components/reports-view";
import { RoutinesView } from "@/components/routines-view";
import { KPIsView } from "@/components/kpis-view";
import { SettingsView } from "@/components/settings-view";
import { DashLogo, DashWordmark } from "@/components/dash-logo";
import { AuthGate } from "@/components/auth-gate";
import { ModelSelector } from "@/components/model-selector";
import { TenantSwitcher } from "@/components/tenant-switcher";

export default function Home() {
  const [view, setView] = useState<"brief" | "chat" | "insights" | "signals" | "kpis" | "reports" | "routines" | "settings">("brief");
  const [chatPrompt, setChatPrompt] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [wsLoading, setWsLoading] = useState(true);
  const [onboarding, setOnboarding] = useState(false);
  const [pendingProposalCount, setPendingProposalCount] = useState(0);

  const loadWorkspace = useCallback(async () => {
    try {
      const ws = await fetchWorkspace();
      setWorkspace(ws);
    } catch {
      // API unreachable — leave workspace null but don't trigger onboarding;
      // a transient failure shouldn't push the user into the welcome flow.
      setWorkspace(null);
    }
    setWsLoading(false);
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const s = await fetchSessions();
      setSessions(s);
    } catch {
      setSessions([]);
    }
  }, []);

  const loadProposalCount = useCallback(async () => {
    try {
      const proposals = await fetchWorkflowProposals();
      setPendingProposalCount(proposals.length);
    } catch {
      // Endpoint requires Postgres; legacy mode silently returns 503 → 0.
      setPendingProposalCount(0);
    }
  }, []);

  useEffect(() => {
    loadWorkspace();
    loadSessions();
    loadProposalCount();
    // Re-poll every 5 minutes so the badge stays fresh between cron ticks.
    const t = setInterval(loadProposalCount, 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [loadWorkspace, loadSessions, loadProposalCount]);

  // Only show onboarding when we have a confirmed not_started status from
  // the API. A null workspace (transient error, 401, etc.) is NOT enough —
  // otherwise a stale session traps the user on the welcome screen.
  const needsOnboarding =
    !wsLoading && !!workspace && workspace.onboarding === "not_started";

  function handleOnboardingComplete() {
    setOnboarding(false);
    loadWorkspace();
    loadSessions();
    setView("brief");
  }

  function handleOnboardingChat(prompt: string) {
    setOnboarding(true);
    setChatPrompt(prompt);
    setActiveSessionId(null);
    setView("chat");
  }

  function goToChat(prompt?: string) {
    if (prompt) setChatPrompt(prompt);
    setActiveSessionId(null);
    setView("chat");
  }

  function newChat() {
    setActiveSessionId(null);
    setChatPrompt(null);
    setView("chat");
  }

  function resumeSession(sessionId: string) {
    setActiveSessionId(sessionId);
    setChatPrompt(null);
    setView("chat");
  }

  function onSessionCreated() {
    loadSessions();
    // Re-check workspace in case onboarding completed
    if (needsOnboarding) loadWorkspace();
  }

  // Loading state
  if (wsLoading) {
    return (
      <AuthGate>
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </AuthGate>
    );
  }

  // Onboarding needed and user hasn't started the agent scan yet
  if (needsOnboarding && !onboarding) {
    return (
      <AuthGate>
        <OnboardingView
          onComplete={handleOnboardingComplete}
          onStartChat={() => {}}
        />
      </AuthGate>
    );
  }

  return (
    <AuthGate>
    <div className="flex h-full">
      {/* Sidebar */}
      {sidebarOpen && (
        <SessionSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={resumeSession}
          onNewChat={newChat}
          onRefresh={loadSessions}
          onClose={() => setSidebarOpen(false)}
        />
      )}

      {/* Main */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center gap-3 border-b border-border px-4 py-2.5">
          {!sidebarOpen && (
            <button
              onClick={() => setSidebarOpen(true)}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            </button>
          )}

          <DashWordmark height={20} className="text-foreground" />

          {/* Tab switcher */}
          <div className="ml-4 flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
            <button
              onClick={() => setView("brief")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "brief"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <FileText className="h-3.5 w-3.5" />
              Brief
            </button>
            <button
              onClick={() => setView("chat")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "chat"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Chat
            </button>
            <button
              onClick={() => setView("insights")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "insights"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Lightbulb className="h-3.5 w-3.5" />
              Insights
            </button>
            <button
              onClick={() => setView("signals")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "signals"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Radar className="h-3.5 w-3.5" />
              Signals
            </button>
            <button
              onClick={() => setView("kpis")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "kpis"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Target className="h-3.5 w-3.5" />
              KPIs
            </button>
            <button
              onClick={() => setView("reports")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "reports"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <FileCode className="h-3.5 w-3.5" />
              Reports
            </button>
            <button
              onClick={() => setView("routines")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "routines"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Timer className="h-3.5 w-3.5" />
              Routines
            </button>
            <button
              onClick={() => setView("settings")}
              className={cn(
                "relative flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-all",
                view === "settings"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
              title={pendingProposalCount > 0
                ? `${pendingProposalCount} pending workflow proposal${pendingProposalCount === 1 ? "" : "s"}`
                : undefined}
            >
              <Settings className="h-3.5 w-3.5" />
              Settings
              {pendingProposalCount > 0 && (
                <span className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-semibold text-white">
                  {pendingProposalCount}
                </span>
              )}
            </button>
          </div>

          <div className="flex-1" />

          <TenantSwitcher />

          <ModelSelector />

          <button
            onClick={() => { logout(); window.location.reload(); }}
            title="Sign out"
            className="inline-flex items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-muted-foreground transition-colors hover:text-foreground"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>

          <button
            onClick={newChat}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
            New chat
          </button>
        </header>

        {/* Views */}
        <main className="flex-1 overflow-hidden">
          {view === "brief" && (
            <BriefView onNavigateToChat={goToChat} />
          )}
          {view === "chat" && (
            <ChatView
              key={activeSessionId ?? "new"}
              initialPrompt={chatPrompt}
              resumeSessionId={activeSessionId}
              onPromptConsumed={() => setChatPrompt(null)}
              onSessionCreated={onSessionCreated}
            />
          )}
          {view === "insights" && (
            <InsightsView onNavigateToChat={goToChat} />
          )}
          {view === "signals" && (
            <SignalsView onNavigateToChat={goToChat} />
          )}
          {view === "kpis" && (
            <KPIsView onNavigateToChat={goToChat} />
          )}
          {view === "reports" && (
            <ReportsView onNavigateToChat={goToChat} />
          )}
          {view === "routines" && (
            <RoutinesView />
          )}
          {view === "settings" && (
            <SettingsView pendingProposalCount={pendingProposalCount} />
          )}
        </main>
      </div>
    </div>
    </AuthGate>
  );
}
