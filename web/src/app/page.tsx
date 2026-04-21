import Link from "next/link";
import { DashWordmark } from "@/components/dash-logo";
import { LandingBriefPreview } from "@/components/landing/brief-preview";
import { LandingChatPreview } from "@/components/landing/chat-preview";
import {
  ArrowRight,
  Zap,
  Target,
  GitPullRequest,
  Layers,
  FileText,
  Timer,
  Radar,
  BarChart3,
  Users,
  FileCode,
  MessageSquare,
  Lightbulb,
  CheckCircle2,
} from "lucide-react";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ── Nav ──────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center">
            <DashWordmark height={22} className="text-foreground" />
          </Link>
          <div className="flex items-center gap-1">
            <Link
              href="/dashboard"
              className="hidden rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground sm:inline-flex"
            >
              Sign in
            </Link>
            <Link
              href="/claim"
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Request early access
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden border-b border-border/40">
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage:
              "linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />
        <div className="relative mx-auto max-w-6xl px-6 pt-24 pb-20 sm:pt-32 sm:pb-28">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
              Early access for design partners
            </div>
            <h1 className="mt-6 text-5xl font-bold tracking-tight leading-[1.05] sm:text-6xl">
              Ship fast.
              <br />
              <span className="text-muted-foreground">Ship the right things.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">
              Coding agents made shipping cheap. Shipping the wrong thing is more expensive than ever.
              Dash is the autonomous PM that watches your entire stack and tells you
              what to build, what to fix, and what to kill.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-3">
              <Link
                href="/claim"
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 hover:shadow-lg hover:shadow-primary/20"
              >
                Request early access
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="#features"
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-5 py-3 text-sm font-semibold transition-colors hover:bg-muted"
              >
                See all features
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── The tension ──────────────────────────────────────────── */}
      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold text-primary">The new reality</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Your engineers ship 10× faster.
              <br />
              Your product judgment hasn't caught up.
            </h2>
            <p className="mt-6 text-base leading-relaxed text-muted-foreground">
              AI coding agents compressed months of work into days. But every feature still comes at a cost —
              complexity, maintenance, team focus, user attention. When shipping is cheap, shipping the wrong
              thing is what kills you.
            </p>
          </div>

          <div className="mt-12 grid gap-4 sm:grid-cols-3">
            <PainPoint
              icon={GitPullRequest}
              title="PRs outpace review"
              body="Engineers ship 6 merges before lunch. By the time you notice a pattern, it's already in production."
            />
            <PainPoint
              icon={Layers}
              title="Signals fragment"
              body="GitHub says 36% done. Linear says 80%. PostHog shows a regression. Nobody is connecting the dots."
            />
            <PainPoint
              icon={Target}
              title="Priorities drift"
              body="The roadmap from Monday is stale by Wednesday. Teams build what's easy, not what matters."
            />
          </div>
        </div>
      </section>

      {/* ── Feature grid ─────────────────────────────────────────── */}
      <section id="features" className="border-b border-border/40">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-primary">Everything a PM needs</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Six surfaces, one agent
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              Dash isn't a dashboard. It's an autonomous PM that reads your tools, connects signals,
              and takes action. Here's what it delivers.
            </p>
          </div>

          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            <FeatureCard
              icon={FileText}
              title="Daily Briefs"
              body="Every 6 hours, a structured snapshot of what shipped, what's blocked, and what needs your attention. With interactive charts, action items, and references to real PRs and issues."
              badge="Core"
            />
            <FeatureCard
              icon={MessageSquare}
              title="Chat"
              body="Ask anything with full workspace context. Sprint status, risk assessments, what to build next, stakeholder updates — with streaming responses and tool execution indicators."
              badge="Core"
            />
            <FeatureCard
              icon={Lightbulb}
              title="Insights"
              body="Goals you set, team pulse analysis, auto-generated changelogs, and workspace learnings — all powered by the agent's accumulated knowledge."
              badge="Strategic"
            />
            <FeatureCard
              icon={Radar}
              title="Signal Collector"
              body="Monitor Twitter, web search, and custom sources. Dash fetches, deduplicates, and surfaces what's relevant. Star, dismiss, or discuss any signal with the agent."
              badge="Intelligence"
            />
            <FeatureCard
              icon={FileCode}
              title="Report Templates"
              body="Design custom reports with markdown templates and variable placeholders. Dash fills them with real data from your workspace. Schedule weekly stakeholder updates, board reports, or custom formats."
              badge="Reporting"
            />
            <FeatureCard
              icon={Timer}
              title="Routines"
              body="Schedule any agent task on a cron: daily briefs, weekly risk assessments, team pulse checks, signal digests, report generation. One-click presets or custom prompts."
              badge="Automation"
            />
          </div>
        </div>
      </section>

      {/* ── Brief preview ────────────────────────────────────────── */}
      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-primary">Every 6 hours</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              A brief that actually tells you what to do
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              Dash reads your GitHub, Linear, PostHog, and Slack. It connects signals that no single tool can see,
              and surfaces the 3–5 things that actually need your attention.
            </p>
          </div>

          <div className="mt-12">
            <LandingBriefPreview />
          </div>
        </div>
      </section>

      {/* ── Chat preview ─────────────────────────────────────────── */}
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <div>
              <p className="text-sm font-semibold text-primary">Always available</p>
              <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
                A PM with full context, not generic advice
              </h2>
              <p className="mt-4 text-base leading-relaxed text-muted-foreground">
                Ask anything. Dash knows your team, repos, sprints, and metrics. It responds with the actual
                numbers and connections — not generic advice.
              </p>
              <ul className="mt-6 space-y-3 text-sm">
                {[
                  "Sprint status with velocity trends and team breakdowns",
                  "Risk assessments across code, product, and team signals",
                  "Feature prioritization grounded in real user data",
                  "Stakeholder updates drafted from live workspace state",
                  "Competitor analysis from your signal sources",
                ].map((t) => (
                  <li key={t} className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                      <CheckCircle2 className="h-3 w-3" />
                    </div>
                    <span className="text-foreground/80">{t}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <LandingChatPreview />
            </div>
          </div>
        </div>
      </section>

      {/* ── How routines work ────────────────────────────────────── */}
      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-primary">Set it and forget it</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Routines that run while you sleep
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              Schedule any agent task on a recurring cadence. One-click presets for common PM workflows,
              or write custom prompts for anything your team needs.
            </p>
          </div>

          <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <RoutineCard title="Daily Brief" schedule="Every 6 hours" desc="What happened, what matters, what to do next" />
            <RoutineCard title="Risk Assessment" schedule="Weekly Monday" desc="Stale work, blocked PRs, team bottlenecks, security concerns" />
            <RoutineCard title="Team Pulse" schedule="Weekly Monday" desc="Per-person activity, concentration risk, review bottlenecks" />
            <RoutineCard title="Changelog" schedule="Weekly Friday" desc="What shipped this week, grouped by feature area" />
            <RoutineCard title="Signal Digest" schedule="Every 6 hours" desc="Fresh signals from Twitter, web, and custom sources" />
            <RoutineCard title="Custom Report" schedule="Your schedule" desc="Markdown template + data sources = recurring report" />
          </div>
        </div>
      </section>

      {/* ── For who ──────────────────────────────────────────────── */}
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-primary">Who Dash is for</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              PMs and founders who lead engineering teams
            </h2>
          </div>
          <div className="mt-12 grid gap-4 sm:grid-cols-3">
            <PersonaLink
              title="Technical PMs"
              body="Stop context-switching between GitHub tabs and Slack threads. Dash reads it all and tells you what matters."
              href="/for/product-managers"
            />
            <PersonaLink
              title="Founders who ship"
              body="You're the PM, designer, and sometimes the engineer. Dash watches the work so you can make decisions."
              href="/for/founders"
            />
            <PersonaLink
              title="Eng leads wearing PM hats"
              body="You know the code. Dash tracks the product signals you don't have time to watch."
              href="/for/engineering-leads"
            />
          </div>
        </div>
      </section>

      {/* ── Use cases ─────────────────────────────────────────────── */}
      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-primary">Use cases</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Replace manual PM workflows
            </h2>
          </div>
          <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <UseCaseLink href="/use-cases/daily-standups" title="Automated daily standups" desc="A brief that's already written before the meeting" />
            <UseCaseLink href="/use-cases/sprint-retrospectives" title="Sprint retrospectives" desc="Data-backed retros, not memory-based guesses" />
            <UseCaseLink href="/use-cases/stakeholder-updates" title="Stakeholder updates" desc="One-click reports from live workspace data" />
            <UseCaseLink href="/use-cases/team-health-monitoring" title="Team health monitoring" desc="Per-person pulse with burnout and bottleneck flags" />
            <UseCaseLink href="/use-cases/signal-collection" title="Signal collection" desc="Market intelligence from Twitter, web, and custom sources" />
            <UseCaseLink href="/use-cases/report-automation" title="Report automation" desc="Markdown templates that fill themselves with real data" />
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────── */}
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-24 text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
            <Zap className="h-3 w-3" />
            Limited design partner slots
          </div>
          <h2 className="mt-6 text-4xl font-bold tracking-tight sm:text-5xl">
            Stop building the wrong things, fast.
          </h2>
          <p className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-muted-foreground">
            Daily briefs. Signal collection. Report automation. Team pulse. Goal tracking. All from one agent
            that learns your workspace and gets smarter every cycle.
          </p>
          <div className="mt-10">
            <Link
              href="/claim"
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 hover:shadow-lg hover:shadow-primary/20"
            >
              Request early access
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <footer className="mx-auto max-w-6xl px-6 py-16">
        <div className="grid gap-12 sm:grid-cols-2 lg:grid-cols-4 mb-12">
          <div>
            <DashWordmark height={20} className="text-foreground mb-4" />
            <p className="text-sm text-muted-foreground leading-relaxed">
              An autonomous PM agent that watches your stack and tells you what to build, fix, and kill.
            </p>
          </div>
          <div>
            <h4 className="text-sm font-semibold mb-3">For teams</h4>
            <div className="space-y-2 text-sm text-muted-foreground">
              <FooterLink href="/for/product-managers">Product Managers</FooterLink>
              <FooterLink href="/for/founders">Founders</FooterLink>
              <FooterLink href="/for/engineering-leads">Engineering Leads</FooterLink>
            </div>
          </div>
          <div>
            <h4 className="text-sm font-semibold mb-3">Use cases</h4>
            <div className="space-y-2 text-sm text-muted-foreground">
              <FooterLink href="/use-cases/daily-standups">Daily standups</FooterLink>
              <FooterLink href="/use-cases/stakeholder-updates">Stakeholder updates</FooterLink>
              <FooterLink href="/use-cases/team-health-monitoring">Team health</FooterLink>
              <FooterLink href="/use-cases/signal-collection">Signal collection</FooterLink>
              <FooterLink href="/use-cases/report-automation">Report automation</FooterLink>
            </div>
          </div>
          <div>
            <h4 className="text-sm font-semibold mb-3">Compare</h4>
            <div className="space-y-2 text-sm text-muted-foreground">
              <FooterLink href="/compare/vs-linear-insights">vs Linear Insights</FooterLink>
              <FooterLink href="/compare/vs-notion-pm">vs Notion PM</FooterLink>
              <FooterLink href="/compare/vs-manual-standups">vs Manual standups</FooterLink>
              <FooterLink href="/compare/vs-spreadsheet-reporting">vs Spreadsheets</FooterLink>
            </div>
          </div>
        </div>
        <div className="flex flex-col items-center justify-between gap-4 border-t border-border/40 pt-8 sm:flex-row">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} Dash PM
          </p>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <FooterLink href="/glossary/daily-brief">Glossary</FooterLink>
            <FooterLink href="/claim">Early access</FooterLink>
          </div>
        </div>
      </footer>
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────

function PainPoint({ icon: Icon, title, body }: { icon: typeof GitPullRequest; title: string; body: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <h3 className="mt-4 text-base font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

function FeatureCard({ icon: Icon, title, body, badge }: { icon: typeof FileText; title: string; body: string; badge: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-6 transition-all hover:shadow-sm hover:border-primary/20">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{badge}</span>
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

function RoutineCard({ title, schedule, desc }: { title: string; schedule: string; desc: string }) {
  return (
    <div className="flex items-start gap-4 rounded-xl border border-border bg-card p-5">
      <div className="flex h-2.5 w-2.5 shrink-0 rounded-full bg-green-500 mt-1.5" />
      <div>
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold">{title}</p>
          <span className="text-[10px] text-muted-foreground">{schedule}</span>
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{desc}</p>
      </div>
    </div>
  );
}

function PersonaLink({ title, body, href }: { title: string; body: string; href: string }) {
  return (
    <Link href={href} className="group rounded-xl border border-border bg-card p-6 transition-all hover:shadow-sm hover:border-primary/20">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">{title}</h3>
        <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </Link>
  );
}

function UseCaseLink({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <Link href={href} className="group flex items-start gap-3 rounded-xl border border-border bg-card px-5 py-4 transition-all hover:shadow-sm hover:border-primary/20">
      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <div>
        <p className="text-sm font-semibold group-hover:text-primary transition-colors">{title}</p>
        <p className="mt-0.5 text-[13px] text-muted-foreground">{desc}</p>
      </div>
    </Link>
  );
}

function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="block hover:text-foreground transition-colors">
      {children}
    </Link>
  );
}
