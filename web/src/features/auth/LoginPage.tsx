import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { useAuth } from "./AuthContext";

type Mode = "signin" | "signup";

export function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = React.useState<Mode>("signin");
  const [name, setName] = React.useState("");
  const [handle, setHandle] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const isSignup = mode === "signup";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (isSignup) {
        await register(name.trim(), email.trim(), handle.trim(), password);
      } else {
        await login(email.trim(), password);
      }
    } catch (err) {
      setError(
        isSignup
          ? messageFor(err, "Could not create account. That email or handle may already be in use.")
          : "Invalid email or password.",
      );
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError("");
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <LogoMark />
          <div className="leading-none">
            <div className="text-[17px] font-bold tracking-tight">AgentLedger</div>
            <div className="mt-1 font-mono text-[9.5px] tracking-[0.6px] text-faint">
              AGENT MEMORY · LINEAR EXECUTION
            </div>
          </div>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-[16px] border border-line bg-surface-3/70 p-6 shadow-[0_24px_60px_rgba(0,0,0,0.4)]"
        >
          <h1 className="mb-1 text-[16px] font-semibold">
            {isSignup ? "Create your account" : "Sign in"}
          </h1>
          <p className="mb-5 text-[12.5px] text-muted">
            {isSignup
              ? "Set up a workspace and start capturing agent memory."
              : "Welcome back. Pick up where the agents left off."}
          </p>

          {isSignup && (
            <>
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </Field>
              <Field label="Handle">
                <Input
                  value={handle}
                  onChange={(e) => setHandle(e.target.value)}
                  placeholder="yourhandle"
                  autoComplete="username"
                />
              </Field>
            </>
          )}

          <Field label="Email">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete={isSignup ? "email" : "username"}
            />
          </Field>

          <Field label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isSignup ? "new-password" : "current-password"}
            />
          </Field>

          {error && <p className="mb-4 text-[12px] text-st-blocked">{error}</p>}

          <Button type="submit" className="w-full" disabled={busy}>
            {busy
              ? isSignup
                ? "Creating account…"
                : "Signing in…"
              : isSignup
                ? "Create account"
                : "Sign in"}
          </Button>

          <div className="mt-5 text-center text-[12px] text-muted">
            {isSignup ? (
              <>
                Already have an account?{" "}
                <button type="button" onClick={() => switchMode("signin")} className="text-accent hover:underline">
                  Sign in
                </button>
              </>
            ) : (
              <>
                New here?{" "}
                <button type="button" onClick={() => switchMode("signup")} className="text-accent hover:underline">
                  Create an account
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wide text-faint">
        {label}
      </label>
      {children}
    </div>
  );
}

function messageFor(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "message" in err && typeof err.message === "string") {
    return err.message;
  }
  return fallback;
}

function LogoMark() {
  return (
    <div
      className="flex h-9 w-9 items-center justify-center rounded-[9px]"
      style={{
        background: "linear-gradient(150deg,#c6f24e,#8fd12e)",
        boxShadow: "0 0 0 1px rgba(198,242,78,.35),0 6px 18px rgba(198,242,78,.18)",
      }}
    >
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
        <path d="M3 2v12M3 4h8M3 8h6M3 12h9" stroke="#0a0c0e" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    </div>
  );
}
