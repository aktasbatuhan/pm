"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { DashLogo } from "@/components/dash-logo";
import {
  saveOnboardingProfile,
  connectIntegration,
  completeOnboarding,
  triggerBackgroundTask,
  fetchWorkspace,
  fetchBrief,
  fetchGithubAppStatus,
  fetchGithubAppInstallUrl,
  type GithubAppStatus,
} from "@/lib/api";
import type { Brief, WorkspaceStatus } from "@/lib/types";
import {
  ArrowRight,
  ArrowLeft,
  Check,
  Loader2,
  Globe,
  BarChart3,
  MessageSquare,
  Layout,
  AlertCircle,
  Search,
  Users,
  FileText,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Platform definitions ──────────────────────────────────────────────

const PLATFORMS = [
  {
    id: "github",
    name: "GitHub",
    description: "Repos, PRs, issues, project boards, team activity",
    icon: Globe,
    placeholder: "ghp_xxxxxxxxxxxx",
    hint: "Personal Access Token with repo, read:org scopes",
    required: true,
  },
  {
    id: "linear",
    name: "Linear",
    description: "Sprints, cycles, issues, team workload",
    icon: Layout,
    placeholder: "lin_api_xxxxxxxxxxxx",
    hint: "Personal API key from Settings → API",
    required: false,
  },
  {
    id: "posthog",
    name: "PostHog",
    description: "Product analytics, funnels, feature flags",
    icon: BarChart3,
    placeholder: "phx_xxxxxxxxxxxx",
    hint: "Personal API key from Project Settings",
    required: false,
  },
  {
    id: "sentry",
    name: "Sentry",
    description: "Error tracking, release health, performance",
    icon: AlertCircle,
    placeholder: "sntrys_xxxxxxxxxxxx",
    hint: "Auth token from Settings → API Keys",
    required: false,
  },
  {
    id: "stripe",
    name: "Stripe",
    description: "Revenue, subscriptions, MRR, churn",
    icon: BarChart3,
    placeholder: "sk_live_xxxxxxxxxxxx",
    hint: "Restricted API key with read access",
    required: false,
  },
  {
    id: "notion",
    name: "Notion",
    description: "PRDs, roadmaps, knowledge base, OKRs",
    icon: FileText,
    placeholder: "secret_xxxxxxxxxxxx",
    hint: "Internal integration token from Notion Settings",
    required: false,
  },
  {
    id: "slack",
    name: "Slack",
    description: "Team messages, decisions, context",
    icon: MessageSquare,
    placeholder: "xoxb-xxxxxxxxxxxx",
    hint: "Bot token from your Slack App",
    required: false,
  },
];

// ── Steps ─────────────────────────────────────────────────────────────

type Step =
  | "welcome"
  | "name"
  | "org"
  | "platforms"
  | "q_product"
  | "q_team"
  | "q_priorities"
  | "q_metrics"
  | "q_pain"
  | "building"
  | "reveal";

const STEPS: Step[] = [
  "welcome", "name", "org", "platforms",
  "q_product", "q_team", "q_priorities", "q_metrics", "q_pain",
  "building", "reveal",
];

// ── Progress steps for the building phase ─────────────────────────────

interface ProgressStep {
  label: string;
  icon: typeof Search;
  status: "pending" | "active" | "done";
}

const INITIAL_PROGRESS: ProgressStep[] = [
  { label: "Discovering repos and projects", icon: Search, status: "pending" },
  { label: "Analyzing team activity", icon: Users, status: "pending" },
  { label: "Building workspace blueprint", icon: Layout, status: "pending" },
  { label: "Generating your first brief", icon: FileText, status: "pending" },
];

// ── Component ─────────────────────────────────────────────────────────

interface Props {
  onComplete: () => void;
  onStartChat: (prompt: string) => void;
}

export function OnboardingView({ onComplete }: Props) {
  const [step, setStep] = useState<Step>("welcome");
  const [name, setName] = useState("");
  const [org, setOrg] = useState("");
  const [connections, setConnections] = useState<
    Record<string, { status: string; message: string }>
  >({});
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [activePlatform, setActivePlatform] = useState<string | null>(null);
  const [githubApp, setGithubApp] = useState<GithubAppStatus | null>(null);
  const [githubAppWaiting, setGithubAppWaiting] = useState(false);

  // Interview answers
  const [aProduct, setAProduct] = useState("");
  const [aTeam, setATeam] = useState("");
  const [aPriorities, setAPriorities] = useState("");
  const [aMetrics, setAMetrics] = useState("");
  const [aPain, setAPain] = useState("");

  // Building phase
  const [progress, setProgress] = useState<ProgressStep[]>(INITIAL_PROGRESS);
  const [revealData, setRevealData] = useState<{
    workspace: WorkspaceStatus | null;
    brief: Brief | null;
  } | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const stepIndex = STEPS.indexOf(step);

  useEffect(() => {
    setTimeout(() => {
      inputRef.current?.focus();
      textareaRef.current?.focus();
    }, 200);
  }, [step]);

  // Check whether the backend has a GitHub App configured — swaps the GitHub card to the install flow.
  useEffect(() => {
    fetchGithubAppStatus().then((s) => {
      setGithubApp(s);
      if (s?.installation) {
        setConnections((prev) => ({
          ...prev,
          github: { status: "connected", message: `${s.installation!.account_login} (GitHub App)` },
        }));
      }
    });
  }, []);

  // When the install popup completes, mark GitHub as connected.
  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.data && e.data.type === "github-app-installed") {
        setGithubAppWaiting(false);
        fetchGithubAppStatus().then((s) => {
          setGithubApp(s);
          if (s?.installation) {
            setConnections((prev) => ({
              ...prev,
              github: { status: "connected", message: `${s.installation!.account_login} (GitHub App)` },
            }));
          }
        });
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  async function openGithubInstall() {
    setGithubAppWaiting(true);
    const url = await fetchGithubAppInstallUrl();
    if (!url) {
      setGithubAppWaiting(false);
      alert("Could not start GitHub install. Please retry.");
      return;
    }
    window.open(url, "github-app-install", "width=780,height=720");
  }

  function next() {
    const i = STEPS.indexOf(step);
    if (i < STEPS.length - 1) setStep(STEPS[i + 1]);
  }

  function back() {
    const i = STEPS.indexOf(step);
    if (i > 0) setStep(STEPS[i - 1]);
  }

  async function handleNameSubmit() {
    if (!name.trim()) return;
    try { await saveOnboardingProfile({ user_name: name.trim() }); } catch {}
    next();
  }

  async function handleOrgSubmit() {
    if (!org.trim()) return;
    try { await saveOnboardingProfile({ organization: org.trim() }); } catch {}
    next();
  }

  async function handleConnect(platformId: string) {
    if (!tokenInput.trim()) return;
    setConnectingPlatform(platformId);
    try {
      const result = await connectIntegration(platformId, tokenInput.trim());
      setConnections((prev) => ({
        ...prev,
        [platformId]: { status: result.status, message: result.message },
      }));
    } catch {
      setConnections((prev) => ({
        ...prev,
        [platformId]: { status: "invalid", message: "Could not reach the server." },
      }));
    }
    setConnectingPlatform(null);
    setTokenInput("");
    setActivePlatform(null);
  }

  async function handleInterviewAnswer(field: string, value: string, goNext: () => void) {
    try { await saveOnboardingProfile({ [field]: value }); } catch {}
    goNext();
  }

  // ── Building phase: fire agent + poll for completion ─────────────────

  async function handleStartBuild() {
    next(); // → "building" step

    try { await completeOnboarding(org); } catch {}

    const connected = Object.entries(connections)
      .filter(([, c]) => c.status === "connected")
      .map(([p]) => p)
      .join(", ");

    // Fire agent in background
    triggerBackgroundTask(
      `I just completed onboarding. Here's my context:\n\n` +
      `Name: ${name}\nOrganization: ${org}\n` +
      `Connected platforms: ${connected || "github"}\n\n` +
      `About our product: ${aProduct}\n` +
      `Key team members: ${aTeam}\n` +
      `Current priorities: ${aPriorities}\n` +
      `Metrics that matter: ${aMetrics}\n` +
      `Biggest pain point: ${aPain}\n\n` +
      `Please scan my organization with this context, build the workspace blueprint focused on what I told you matters, store learnings from my answers, generate the first daily brief with charts and action items, schedule a recurring daily brief every 6 hours, and mark onboarding complete.`
    );

    // Animate progress steps with timed intervals
    const timings = [2000, 6000, 12000, 18000];
    for (let i = 0; i < INITIAL_PROGRESS.length; i++) {
      setTimeout(() => {
        setProgress((prev) =>
          prev.map((s, j) => ({
            ...s,
            status: j < i ? "done" : j === i ? "active" : "pending",
          }))
        );
      }, timings[i]);
    }

    // Poll for real completion
    const startTime = Date.now();
    const maxWait = 5 * 60 * 1000; // 5 min

    const poll = setInterval(async () => {
      try {
        const [ws, brief] = await Promise.all([fetchWorkspace(), fetchBrief()]);
        const elapsed = Date.now() - startTime;

        // Check if onboarding completed
        const isComplete = ws?.onboarding === "completed";
        const hasBrief = brief !== null;
        const hasBlueprint = ws?.blueprint !== null;

        // Update progress based on real state
        setProgress((prev) =>
          prev.map((s, i) => {
            if (i === 0) return { ...s, status: hasBlueprint || isComplete ? "done" : elapsed > 5000 ? "active" : s.status };
            if (i === 1) return { ...s, status: hasBlueprint || isComplete ? "done" : elapsed > 10000 ? "active" : s.status };
            if (i === 2) return { ...s, status: hasBlueprint ? "done" : elapsed > 15000 ? "active" : s.status };
            if (i === 3) return { ...s, status: hasBrief ? "done" : isComplete ? "active" : s.status };
            return s;
          })
        );

        // Reveal when we have enough data (blueprint exists, or timeout with completed status)
        if ((hasBlueprint && hasBrief) || (isComplete && elapsed > 30000) || elapsed > maxWait) {
          clearInterval(poll);
          // Mark all progress as done
          setProgress((prev) => prev.map((s) => ({ ...s, status: "done" as const })));
          // Wait a beat for the animation
          setTimeout(() => {
            setRevealData({ workspace: ws, brief });
            setStep("reveal");
          }, 1500);
        }
      } catch {
        // Keep polling
      }
    }, 4000);

    return () => clearInterval(poll);
  }

  const connectedCount = Object.values(connections).filter(
    (c) => c.status === "connected"
  ).length;

  return (
    <div className="flex h-full items-center justify-center bg-background">
      <div className="w-full max-w-lg px-6">
        {/* Progress dots — hide during building/reveal */}
        {step !== "building" && step !== "reveal" && (
          <div className="mb-12 flex justify-center gap-2">
            {STEPS.filter((s) => s !== "building" && s !== "reveal").map((s, i) => {
              const realIndex = STEPS.indexOf(s);
              return (
                <div
                  key={s}
                  className={cn(
                    "h-1.5 rounded-full transition-all duration-300",
                    realIndex === stepIndex
                      ? "w-8 bg-primary"
                      : realIndex < stepIndex
                        ? "w-1.5 bg-primary/40"
                        : "w-1.5 bg-border"
                  )}
                />
              );
            })}
          </div>
        )}

        <div className="min-h-[360px]">
          {/* Welcome */}
          {step === "welcome" && (
            <StepContainer>
              <div className="flex justify-center mb-8">
                <DashLogo size={64} />
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-center">
                Welcome to Dash
              </h1>
              <p className="mt-3 text-center text-muted-foreground leading-relaxed">
                Your autonomous PM agent. Let's get to know your team so Dash can deliver briefs that actually matter.
              </p>
              <div className="mt-10 flex justify-center">
                <PrimaryButton onClick={next}>
                  Get started <ArrowRight className="h-4 w-4" />
                </PrimaryButton>
              </div>
            </StepContainer>
          )}

          {/* Name */}
          {step === "name" && (
            <StepContainer>
              <StepLabel>Let's start</StepLabel>
              <h2 className="mt-2 text-2xl font-bold tracking-tight">What's your name?</h2>
              <input
                ref={inputRef}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleNameSubmit()}
                placeholder="Your name"
                className="mt-8 w-full border-b-2 border-border bg-transparent pb-3 text-xl font-medium outline-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary"
              />
              <StepNav onBack={back} onNext={handleNameSubmit} disabled={!name.trim()} />
            </StepContainer>
          )}

          {/* Organization */}
          {step === "org" && (
            <StepContainer>
              <StepLabel>Nice to meet you, {name}</StepLabel>
              <h2 className="mt-2 text-2xl font-bold tracking-tight">What's your organization?</h2>
              <p className="mt-2 text-sm text-muted-foreground">GitHub org name, company, or team</p>
              <input
                ref={inputRef}
                type="text"
                value={org}
                onChange={(e) => setOrg(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleOrgSubmit()}
                placeholder="e.g. acme-corp"
                className="mt-8 w-full border-b-2 border-border bg-transparent pb-3 text-xl font-medium outline-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary"
              />
              <StepNav onBack={back} onNext={handleOrgSubmit} disabled={!org.trim()} />
            </StepContainer>
          )}

          {/* Platforms */}
          {step === "platforms" && (
            <StepContainer>
              <StepLabel>Connect your tools</StepLabel>
              <h2 className="mt-2 text-2xl font-bold tracking-tight">Where does {org} work?</h2>
              <p className="mt-2 text-sm text-muted-foreground">Connect at least GitHub. Others are optional.</p>
              <div className="mt-6 space-y-3">
                {PLATFORMS.map((p) => {
                  const conn = connections[p.id];
                  const isConnected = conn?.status === "connected";
                  const isFailed = conn?.status === "invalid";
                  const isActive = activePlatform === p.id;
                  const isConnecting = connectingPlatform === p.id;
                  const useGithubApp = p.id === "github" && githubApp?.configured;
                  return (
                    <div key={p.id}>
                      <button
                        onClick={() => {
                          if (isConnected) return;
                          if (useGithubApp) { openGithubInstall(); return; }
                          setActivePlatform(isActive ? null : p.id);
                          setTokenInput("");
                        }}
                        className={cn(
                          "flex w-full items-center gap-4 rounded-xl border px-4 py-3.5 text-left transition-all",
                          isConnected ? "border-green-200 bg-green-50" : isFailed ? "border-red-200 bg-red-50" : "border-border hover:border-primary/30 hover:bg-muted/50"
                        )}
                      >
                        <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", isConnected ? "bg-green-100 text-green-600" : "bg-muted text-muted-foreground")}>
                          {isConnected ? <Check className="h-5 w-5" /> : <p.icon className="h-5 w-5" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold">{p.name}</span>
                            {p.required && !isConnected && <span className="text-[10px] font-medium text-primary bg-primary/10 px-1.5 py-0.5 rounded">Required</span>}
                            {useGithubApp && !isConnected && <span className="text-[10px] font-medium text-primary bg-primary/10 px-1.5 py-0.5 rounded">GitHub App</span>}
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {isConnected
                              ? conn.message
                              : isFailed
                              ? conn.message
                              : useGithubApp
                              ? (githubAppWaiting ? "Waiting for install to complete…" : "Install the GitHub App to pick which repos Dash can see.")
                              : p.description}
                          </p>
                        </div>
                        {!isConnected && (
                          useGithubApp
                            ? (githubAppWaiting ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : <ArrowRight className="h-4 w-4 text-muted-foreground" />)
                            : <ArrowRight className={cn("h-4 w-4 text-muted-foreground transition-transform", isActive && "rotate-90")} />
                        )}
                      </button>
                      {isActive && !isConnected && !useGithubApp && (
                        <div className="mt-2 ml-14 mr-4 space-y-2">
                          <div className="flex gap-2">
                            <input type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleConnect(p.id)} placeholder={p.placeholder} className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/40" autoFocus />
                            <button onClick={() => handleConnect(p.id)} disabled={!tokenInput.trim() || isConnecting} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40">
                              {isConnecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Connect
                            </button>
                          </div>
                          <p className="text-[11px] text-muted-foreground">{p.hint}</p>
                          {isFailed && <p className="flex items-center gap-1 text-[11px] text-red-600"><AlertCircle className="h-3 w-3" /> {conn.message}</p>}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <StepNav onBack={back} onNext={next} disabled={!connections.github || connections.github.status !== "connected"} label={connectedCount > 0 ? "Continue" : "Connect GitHub to continue"} />
            </StepContainer>
          )}

          {/* Interview Q1-Q5 */}
          {step === "q_product" && (
            <InterviewStep label={`Tell me about ${org}`} question={`What does ${org} build, and who uses it?`} value={aProduct} onChange={setAProduct} placeholder="e.g. We build a developer analytics platform used by engineering teams..." onBack={back} onNext={() => handleInterviewAnswer("product_description", aProduct, next)} ref={textareaRef} />
          )}
          {step === "q_team" && (
            <InterviewStep label="Your team" question="Who are the key people I should track?" hint="Engineering leads, PMs, anyone whose activity signals something important." value={aTeam} onChange={setATeam} placeholder="e.g. Alice (eng lead, owns backend), Bob (frontend + design)..." onBack={back} onNext={() => handleInterviewAnswer("key_team_members", aTeam, next)} ref={textareaRef} />
          )}
          {step === "q_priorities" && (
            <InterviewStep label="Current focus" question="What's the team working on right now?" hint="The most important thing shipping this month." value={aPriorities} onChange={setAPriorities} placeholder="e.g. Launching v2 of the dashboard with real-time alerts..." onBack={back} onNext={() => handleInterviewAnswer("current_priorities", aPriorities, next)} ref={textareaRef} />
          )}
          {step === "q_metrics" && (
            <InterviewStep label="What matters" question="What metrics do you check first thing in the morning?" hint="Sprint velocity, user growth, conversion, deployment frequency, anything." value={aMetrics} onChange={setAMetrics} placeholder="e.g. Weekly active users, sprint completion rate, P0 bug count..." onBack={back} onNext={() => handleInterviewAnswer("key_metrics", aMetrics, next)} ref={textareaRef} />
          )}
          {step === "q_pain" && (
            <StepContainer>
              <StepLabel>Last one</StepLabel>
              <h2 className="mt-2 text-2xl font-bold tracking-tight">What's the biggest pain point right now?</h2>
              <p className="mt-2 text-sm text-muted-foreground">Slow reviews, unclear priorities, missed deadlines, something else?</p>
              <textarea ref={textareaRef} value={aPain} onChange={(e) => setAPain(e.target.value)} placeholder="e.g. PRs sit in review for days. Nobody knows what's actually blocking the sprint..." rows={3} className="mt-8 w-full rounded-xl border border-border bg-card px-4 py-3 text-sm leading-relaxed outline-none resize-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary/40" />
              <div className="mt-10 flex items-center justify-between">
                <BackButton onClick={back} />
                <PrimaryButton onClick={() => handleInterviewAnswer("pain_points", aPain, handleStartBuild)} disabled={!aPain.trim()}>
                  Set up my workspace <ArrowRight className="h-4 w-4" />
                </PrimaryButton>
              </div>
            </StepContainer>
          )}

          {/* Building phase */}
          {step === "building" && (
            <StepContainer>
              <div className="flex justify-center mb-8">
                <div className="relative">
                  <DashLogo size={56} />
                  <div className="absolute -bottom-1 -right-1 h-5 w-5 rounded-full bg-primary flex items-center justify-center">
                    <Loader2 className="h-3 w-3 animate-spin text-primary-foreground" />
                  </div>
                </div>
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-center">
                Building your workspace
              </h2>
              <p className="mt-2 text-center text-sm text-muted-foreground">
                Dash is scanning {org} with what you told us. This takes about a minute.
              </p>

              {/* Progress steps */}
              <div className="mt-10 space-y-4">
                {progress.map((p, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className={cn(
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-all duration-500",
                      p.status === "done" ? "bg-green-100 text-green-600" :
                      p.status === "active" ? "bg-primary/10 text-primary" :
                      "bg-muted text-muted-foreground/40"
                    )}>
                      {p.status === "done" ? (
                        <Check className="h-4 w-4" />
                      ) : p.status === "active" ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <p.icon className="h-4 w-4" />
                      )}
                    </div>
                    <span className={cn(
                      "text-sm transition-colors duration-300",
                      p.status === "done" ? "text-foreground" :
                      p.status === "active" ? "text-foreground font-medium" :
                      "text-muted-foreground/60"
                    )}>
                      {p.label}
                    </span>
                  </div>
                ))}
              </div>
            </StepContainer>
          )}

          {/* Reveal: what Dash found */}
          {step === "reveal" && (
            <StepContainer>
              <div className="flex justify-center mb-6">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-green-100">
                  <Sparkles className="h-7 w-7 text-green-600" />
                </div>
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-center">
                Your workspace is ready
              </h2>

              {/* Blueprint summary */}
              {revealData?.workspace?.blueprint && (
                <div className="mt-6 rounded-xl border border-border bg-card px-5 py-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">What Dash understood</p>
                  <p className="text-sm leading-relaxed text-foreground">
                    {revealData.workspace.blueprint.summary}
                  </p>
                </div>
              )}

              {/* Brief preview */}
              {revealData?.brief && (
                <div className="mt-4 rounded-xl border border-border bg-card px-5 py-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Your first brief</p>
                  <p className="text-sm font-medium text-foreground">
                    {revealData.brief.action_items?.filter((a) => a.status === "pending").length || 0} action items found
                  </p>
                  {revealData.brief.action_items?.slice(0, 3).map((a, i) => (
                    <div key={i} className="mt-2 flex items-start gap-2">
                      <div className={cn(
                        "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                        a.priority === "critical" ? "bg-red-500" : a.priority === "high" ? "bg-amber-500" : "bg-blue-500"
                      )} />
                      <p className="text-sm text-muted-foreground">{a.title}</p>
                    </div>
                  ))}
                </div>
              )}

              {/* Learnings count */}
              {revealData?.workspace && (
                <p className="mt-4 text-center text-xs text-muted-foreground">
                  {revealData.workspace.learnings_count} learnings stored &middot; Daily briefs scheduled every 6h
                </p>
              )}

              <div className="mt-8 flex justify-center">
                <PrimaryButton onClick={onComplete}>
                  Go to dashboard <ArrowRight className="h-4 w-4" />
                </PrimaryButton>
              </div>
            </StepContainer>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Interview step (reusable) ─────────────────────────────────────────

import { forwardRef } from "react";

const InterviewStep = forwardRef<HTMLTextAreaElement, {
  label: string;
  question: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  onBack: () => void;
  onNext: () => void;
}>(function InterviewStep({ label, question, hint, value, onChange, placeholder, onBack, onNext }, ref) {
  return (
    <StepContainer>
      <StepLabel>{label}</StepLabel>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">{question}</h2>
      {hint && <p className="mt-2 text-sm text-muted-foreground">{hint}</p>}
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="mt-8 w-full rounded-xl border border-border bg-card px-4 py-3 text-sm leading-relaxed outline-none resize-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary/40"
      />
      <StepNav onBack={onBack} onNext={onNext} disabled={!value.trim()} />
    </StepContainer>
  );
});

// ── Shared components ─────────────────────────────────────────────────

function StepContainer({ children }: { children: React.ReactNode }) {
  return <div className="animate-in fade-in slide-in-from-right-4 duration-300">{children}</div>;
}

function StepLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-sm font-medium text-primary">{children}</p>;
}

function StepNav({ onBack, onNext, disabled, label }: { onBack: () => void; onNext: () => void; disabled?: boolean; label?: string }) {
  return (
    <div className="mt-10 flex items-center justify-between">
      <BackButton onClick={onBack} />
      <PrimaryButton onClick={onNext} disabled={disabled}>{label ?? "Continue"} <ArrowRight className="h-4 w-4" /></PrimaryButton>
    </div>
  );
}

function PrimaryButton({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed">
      {children}
    </button>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
      <ArrowLeft className="h-3.5 w-3.5" /> Back
    </button>
  );
}
