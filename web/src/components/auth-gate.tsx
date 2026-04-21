"use client";

import { useState, useRef, useEffect } from "react";
import { DashLogo } from "@/components/dash-logo";
import { checkAuth, setupPassword, login } from "@/lib/api";
import { Loader2, Lock } from "lucide-react";

interface Props {
  children: React.ReactNode;
}

export function AuthGate({ children }: Props) {
  const [state, setState] = useState<"loading" | "setup" | "login" | "authenticated">("loading");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    checkAuth()
      .then((result) => {
        if (result.authenticated) {
          setState("authenticated");
        } else if (result.needs_setup) {
          setState("setup");
        } else {
          setState("login");
        }
      })
      .catch(() => {
        // API unreachable — let through (local dev)
        setState("authenticated");
      });
  }, []);

  useEffect(() => {
    if (state === "setup" || state === "login") {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [state]);

  async function handleSubmit() {
    if (!password.trim() || submitting) return;
    setSubmitting(true);
    setError("");

    const result =
      state === "setup"
        ? await setupPassword(password)
        : await login(password);

    if (result.ok) {
      setState("authenticated");
    } else {
      setError(result.error || "Something went wrong");
    }
    setSubmitting(false);
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
            : "Enter your password to continue."}
        </p>

        <div className="mt-8">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
            <Lock className="h-4 w-4 text-muted-foreground" />
            <input
              ref={inputRef}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder={isSetup ? "Choose a password" : "Password"}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/50"
            />
          </div>

          {error && (
            <p className="mt-3 text-sm text-red-600 text-center">{error}</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={!password.trim() || submitting}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-2.5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isSetup ? (
              "Create password"
            ) : (
              "Sign in"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
