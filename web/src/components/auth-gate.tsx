"use client";

import { useState, useRef, useEffect } from "react";
import { DashLogo } from "@/components/dash-logo";
import {
  checkAuth,
  setupPassword,
  login,
  signInV2,
  fetchMe,
} from "@/lib/api";
import { Loader2, Lock, Mail } from "lucide-react";

interface Props {
  children: React.ReactNode;
}

type State = "loading" | "setup" | "login-legacy" | "login-v2" | "authenticated";

export function AuthGate({ children }: Props) {
  const [state, setState] = useState<State>("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    (async () => {
      // Probe mode: /api/auth/v2/me returns 503 in legacy mode, 401 if Postgres
      // is enabled but no/invalid token, or 200 with user if logged in.
      const me = await fetchMe();
      if (me.mode === "postgres") {
        if (me.user) setState("authenticated");
        else setState("login-v2");
        return;
      }
      // Legacy mode (demo): use the old single-password flow.
      try {
        const result = await checkAuth();
        if (result.authenticated) setState("authenticated");
        else if (result.needs_setup) setState("setup");
        else setState("login-legacy");
      } catch {
        setState("login-legacy"); // API unreachable — require login, don't bypass
      }
    })();
  }, []);

  useEffect(() => {
    if (state === "setup" || state === "login-legacy" || state === "login-v2") {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [state]);

  async function handleSubmit() {
    if (submitting) return;
    setError("");
    setSubmitting(true);

    try {
      if (state === "setup") {
        if (!password.trim()) return;
        const r = await setupPassword(password);
        if (r.ok) setState("authenticated");
        else setError(r.error || "Setup failed");
      } else if (state === "login-legacy") {
        if (!password.trim()) return;
        const r = await login(password);
        if (r.ok) setState("authenticated");
        else setError(r.error || "Login failed");
      } else if (state === "login-v2") {
        if (!email.trim() || !password.trim()) return;
        const r = await signInV2(email.trim(), password);
        if (r.token) setState("authenticated");
        else setError(r.error || "Sign-in failed");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (state === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (state === "authenticated") {
    return <>{children}</>;
  }

  const isSetup = state === "setup";
  const isV2 = state === "login-v2";

  return (
    <div className="flex h-full items-center justify-center bg-background">
      <div className="w-full max-w-sm px-6">
        <div className="flex justify-center mb-8">
          <DashLogo size={48} />
        </div>

        <h1 className="text-xl font-bold tracking-tight text-center">
          {isSetup ? "Set up your password" : "Welcome back"}
        </h1>
        <p className="mt-2 text-center text-sm text-muted-foreground">
          {isSetup
            ? "Choose a password to secure your Dash workspace."
            : isV2
            ? "Sign in to your Dash workspace."
            : "Enter your password to continue."}
        </p>

        <div className="mt-8 space-y-3">
          {isV2 && (
            <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
              <Mail className="h-4 w-4 text-muted-foreground" />
              <input
                ref={inputRef}
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/50"
              />
            </div>
          )}

          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
            <Lock className="h-4 w-4 text-muted-foreground" />
            <input
              ref={isV2 ? undefined : inputRef}
              type="password"
              autoComplete={isSetup ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder={isSetup ? "Choose a password" : "Password"}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/50"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 text-center">{error}</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={submitting || !password.trim() || (isV2 && !email.trim())}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-2.5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isSetup ? (
              "Create password"
            ) : (
              "Sign in"
            )}
          </button>

          {isV2 && (
            <button
              onClick={() => setState("login-legacy")}
              className="block w-full text-center text-xs text-muted-foreground hover:text-foreground"
            >
              Use legacy password instead
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
