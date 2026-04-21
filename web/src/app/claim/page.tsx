"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { DashLogo, DashWordmark } from "@/components/dash-logo";
import { submitWaitlist } from "@/lib/api";
import {
  ArrowRight,
  ArrowLeft,
  Loader2,
  Check,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Step =
  | "welcome"
  | "name"
  | "email"
  | "org"
  | "role"
  | "team_size"
  | "pain"
  | "submitting"
  | "done";

const STEPS: Step[] = [
  "welcome",
  "name",
  "email",
  "org",
  "role",
  "team_size",
  "pain",
  "submitting",
  "done",
];

const ROLES = ["Founder / CEO", "Product Manager", "Engineering Lead", "Other"];
const TEAM_SIZES = ["1–5", "6–15", "16–40", "40+"];

export default function ClaimPage() {
  const [step, setStep] = useState<Step>("welcome");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [org, setOrg] = useState("");
  const [role, setRole] = useState("");
  const [teamSize, setTeamSize] = useState("");
  const [pain, setPain] = useState("");
  const [error, setError] = useState("");

  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const stepIndex = STEPS.indexOf(step);
  const visibleSteps = STEPS.filter(
    (s) => s !== "welcome" && s !== "submitting" && s !== "done"
  );

  useEffect(() => {
    setTimeout(() => {
      inputRef.current?.focus();
      textareaRef.current?.focus();
    }, 200);
  }, [step]);

  function next() {
    const i = STEPS.indexOf(step);
    if (i < STEPS.length - 1) setStep(STEPS[i + 1]);
  }

  function back() {
    const i = STEPS.indexOf(step);
    if (i > 0) setStep(STEPS[i - 1]);
  }

  function validEmail(v: string) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
  }

  async function handleSubmit() {
    setStep("submitting");
    try {
      await submitWaitlist({
        name,
        email,
        organization: org,
        role,
        team_size: teamSize,
        pain_point: pain,
      });
      // Pause briefly for effect
      setTimeout(() => setStep("done"), 1500);
    } catch {
      setError("Something went wrong. Please try again.");
      setStep("pain");
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      {/* Nav */}
      <nav className="border-b border-border/40">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center">
            <DashWordmark height={22} className="text-foreground" />
          </Link>
          {step !== "done" && step !== "submitting" && (
            <Link
              href="/"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              ← Back to home
            </Link>
          )}
        </div>
      </nav>

      {/* Body */}
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="w-full max-w-md">
          {/* Progress dots (hidden on welcome, submitting, done) */}
          {visibleSteps.includes(step as any) && (
            <div className="mb-12 flex justify-center gap-2">
              {visibleSteps.map((s) => {
                const realIdx = STEPS.indexOf(s);
                return (
                  <div
                    key={s}
                    className={cn(
                      "h-1.5 rounded-full transition-all duration-300",
                      realIdx === stepIndex
                        ? "w-8 bg-primary"
                        : realIdx < stepIndex
                          ? "w-1.5 bg-primary/40"
                          : "w-1.5 bg-border"
                    )}
                  />
                );
              })}
            </div>
          )}

          <div className="min-h-[340px]">
            {step === "welcome" && (
              <Fade>
                <div className="flex justify-center mb-8">
                  <DashLogo size={64} />
                </div>
                <h1 className="text-3xl font-bold tracking-tight text-center">
                  Request early access
                </h1>
                <p className="mt-3 text-center text-muted-foreground leading-relaxed">
                  A few quick questions so we can match Dash to your team. Takes about 60 seconds.
                  We review every request and onboard a few teams each week.
                </p>
                <div className="mt-10 flex justify-center">
                  <Primary onClick={next}>
                    Get started <ArrowRight className="h-4 w-4" />
                  </Primary>
                </div>
              </Fade>
            )}

            {step === "name" && (
              <Fade>
                <Label>Let's start</Label>
                <Question>What's your name?</Question>
                <TextInput
                  ref={inputRef}
                  value={name}
                  onChange={setName}
                  onEnter={() => name.trim() && next()}
                  placeholder="Your name"
                />
                <Nav onBack={back} onNext={next} disabled={!name.trim()} />
              </Fade>
            )}

            {step === "email" && (
              <Fade>
                <Label>Where should we reach you?</Label>
                <Question>What's your work email?</Question>
                <TextInput
                  ref={inputRef}
                  type="email"
                  value={email}
                  onChange={setEmail}
                  onEnter={() => validEmail(email) && next()}
                  placeholder="you@company.com"
                />
                <Nav onBack={back} onNext={next} disabled={!validEmail(email)} />
              </Fade>
            )}

            {step === "org" && (
              <Fade>
                <Label>Nice to meet you, {name.split(" ")[0]}</Label>
                <Question>What's your company or team?</Question>
                <TextInput
                  ref={inputRef}
                  value={org}
                  onChange={setOrg}
                  onEnter={() => org.trim() && next()}
                  placeholder="e.g. Acme Inc."
                />
                <Nav onBack={back} onNext={next} disabled={!org.trim()} />
              </Fade>
            )}

            {step === "role" && (
              <Fade>
                <Label>Your role</Label>
                <Question>What do you do at {org}?</Question>
                <div className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {ROLES.map((r) => (
                    <ChoiceButton
                      key={r}
                      selected={role === r}
                      onClick={() => {
                        setRole(r);
                        setTimeout(next, 250);
                      }}
                    >
                      {r}
                    </ChoiceButton>
                  ))}
                </div>
                <Nav onBack={back} onNext={next} disabled={!role} hideNext={!role} />
              </Fade>
            )}

            {step === "team_size" && (
              <Fade>
                <Label>Team size</Label>
                <Question>How big is your engineering team?</Question>
                <div className="mt-8 grid grid-cols-2 gap-2">
                  {TEAM_SIZES.map((s) => (
                    <ChoiceButton
                      key={s}
                      selected={teamSize === s}
                      onClick={() => {
                        setTeamSize(s);
                        setTimeout(next, 250);
                      }}
                    >
                      {s}
                    </ChoiceButton>
                  ))}
                </div>
                <Nav onBack={back} onNext={next} disabled={!teamSize} hideNext={!teamSize} />
              </Fade>
            )}

            {step === "pain" && (
              <Fade>
                <Label>Last one</Label>
                <Question>What's the biggest PM pain point right now?</Question>
                <p className="mt-2 text-sm text-muted-foreground">
                  Helps us prioritize what to build first for you.
                </p>
                <textarea
                  ref={textareaRef}
                  value={pain}
                  onChange={(e) => setPain(e.target.value)}
                  placeholder="e.g. Keeping track of what the team is actually shipping vs. what the roadmap says..."
                  rows={4}
                  className="mt-8 w-full rounded-xl border border-border bg-card px-4 py-3 text-sm leading-relaxed outline-none resize-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary/40"
                />
                {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
                <div className="mt-10 flex items-center justify-between">
                  <Back onClick={back} />
                  <Primary onClick={handleSubmit} disabled={!pain.trim()}>
                    Submit <ArrowRight className="h-4 w-4" />
                  </Primary>
                </div>
              </Fade>
            )}

            {step === "submitting" && (
              <Fade>
                <div className="flex justify-center mb-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
                <h2 className="text-xl font-semibold tracking-tight text-center">
                  Submitting your request
                </h2>
              </Fade>
            )}

            {step === "done" && (
              <Fade>
                <div className="flex justify-center mb-6">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-green-100">
                    <Sparkles className="h-7 w-7 text-green-600" />
                  </div>
                </div>
                <h2 className="text-2xl font-bold tracking-tight text-center">
                  You're on the list
                </h2>
                <p className="mt-4 text-center text-muted-foreground leading-relaxed">
                  We're onboarding a handful of teams each week. We'll email{" "}
                  <span className="font-semibold text-foreground">{email}</span> when your Dash workspace
                  is provisioned — usually within a few days.
                </p>
                <div className="mt-8 rounded-xl border border-border bg-card px-5 py-4 text-left">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                    What happens next
                  </p>
                  <ul className="space-y-2 text-sm">
                    <li className="flex items-start gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                      <span>We review your context and prioritize based on fit</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                      <span>You get a provisioning email with your workspace URL</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                      <span>15-minute onboarding to connect GitHub, Linear, and more</span>
                    </li>
                  </ul>
                </div>
                <div className="mt-8 flex justify-center">
                  <Link
                    href="/"
                    className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-muted"
                  >
                    Back to home
                  </Link>
                </div>
              </Fade>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Shared bits ───────────────────────────────────────────────────────

function Fade({ children }: { children: React.ReactNode }) {
  return (
    <div className="animate-in fade-in slide-in-from-right-4 duration-300">
      {children}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-sm font-medium text-primary">{children}</p>;
}

function Question({ children }: { children: React.ReactNode }) {
  return <h2 className="mt-2 text-2xl font-bold tracking-tight">{children}</h2>;
}

import { forwardRef } from "react";

const TextInput = forwardRef<
  HTMLInputElement,
  {
    type?: string;
    value: string;
    onChange: (v: string) => void;
    onEnter: () => void;
    placeholder: string;
  }
>(function TextInput({ type = "text", value, onChange, onEnter, placeholder }, ref) {
  return (
    <input
      ref={ref}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && onEnter()}
      placeholder={placeholder}
      className="mt-8 w-full border-b-2 border-border bg-transparent pb-3 text-xl font-medium outline-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary"
    />
  );
});

function ChoiceButton({
  children,
  selected,
  onClick,
}: {
  children: React.ReactNode;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-xl border px-4 py-3 text-sm font-medium transition-all text-left",
        selected
          ? "border-primary bg-primary/5 text-primary"
          : "border-border bg-card hover:border-primary/30 hover:bg-muted/50"
      )}
    >
      {children}
    </button>
  );
}

function Nav({
  onBack,
  onNext,
  disabled,
  hideNext,
}: {
  onBack: () => void;
  onNext: () => void;
  disabled?: boolean;
  hideNext?: boolean;
}) {
  return (
    <div className="mt-10 flex items-center justify-between">
      <Back onClick={onBack} />
      {!hideNext && (
        <Primary onClick={onNext} disabled={disabled}>
          Continue <ArrowRight className="h-4 w-4" />
        </Primary>
      )}
    </div>
  );
}

function Primary({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
    >
      <ArrowLeft className="h-3.5 w-3.5" /> Back
    </button>
  );
}
