import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useProjectCtx } from "@/features/ProjectContext";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";

const ACCENTS = ["#c6f24e", "#a78bfa", "#7ca2ff", "#e0b34a", "#5fd07a", "#ff8f8f"];

export function CreateFirstProject() {
  const qc = useQueryClient();
  const { setActiveId } = useProjectCtx();
  const [name, setName] = React.useState("");
  const [accent, setAccent] = React.useState(ACCENTS[0]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const project = await api.createProject({ name: name.trim(), accent });
      await qc.invalidateQueries({ queryKey: keys.projects });
      setActiveId(project.id);
    } catch {
      setError("Could not create the project. Please try again.");
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-[16px] border border-line bg-surface-3/70 p-7 shadow-[0_24px_60px_rgba(0,0,0,0.4)]"
      >
        <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-[11px] bg-[rgba(198,242,78,0.12)]">
          <Sparkles size={18} className="text-accent" />
        </div>
        <h1 className="mb-1 text-[17px] font-semibold tracking-tight">Create your first project</h1>
        <p className="mb-6 text-[12.5px] leading-relaxed text-muted">
          A project is a workspace for your tracker, agent memory, requests, and PRDs. You can add
          more later.
        </p>

        <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wide text-faint">
          Project name
        </label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Core Platform"
          autoFocus
          className="mb-5"
        />

        <label className="mb-2 block font-mono text-[10px] uppercase tracking-wide text-faint">
          Accent
        </label>
        <div className="mb-6 flex gap-2.5">
          {ACCENTS.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setAccent(c)}
              aria-label={`accent ${c}`}
              className="h-7 w-7 rounded-[8px] transition-transform hover:scale-110"
              style={{
                background: c,
                outline: accent === c ? "2px solid var(--color-fg)" : "none",
                outlineOffset: "2px",
              }}
            />
          ))}
        </div>

        {error && <p className="mb-4 text-[12px] text-st-blocked">{error}</p>}

        <Button type="submit" className="w-full" disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create project"}
        </Button>
      </form>
    </div>
  );
}
