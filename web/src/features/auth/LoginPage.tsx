import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = React.useState("alex@ascme-labs.com");
  const [password, setPassword] = React.useState("agentledger");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password);
    } catch {
      setError("Invalid credentials. Try the seeded account below.");
    } finally {
      setBusy(false);
    }
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
          <h1 className="mb-1 text-[16px] font-semibold">Sign in</h1>
          <p className="mb-5 text-[12.5px] text-muted">Welcome back. Pick up where the agents left off.</p>

          <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wide text-faint">
            Email
          </label>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mb-4"
            autoComplete="username"
          />

          <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wide text-faint">
            Password
          </label>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mb-5"
            autoComplete="current-password"
          />

          {error && <p className="mb-4 text-[12px] text-st-blocked">{error}</p>}

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>

          <div className="mt-5 rounded-lg border border-line-2 bg-surface-2 p-3 font-mono text-[10.5px] text-muted">
            <div className="mb-1 text-faint">SEEDED DEMO ACCOUNT</div>
            alex@ascme-labs.com · agentledger
          </div>
        </form>
      </div>
    </div>
  );
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
