import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useProjectCtx } from "@/features/ProjectContext";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";

export const PROJECT_ACCENTS = ["#c6f24e", "#a78bfa", "#7ca2ff", "#e0b34a", "#5fd07a", "#ff8f8f"];

export function NewProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const { setActiveId } = useProjectCtx();
  const [name, setName] = React.useState("");
  const [accent, setAccent] = React.useState(PROJECT_ACCENTS[0]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  // Reset the form each time the dialog opens.
  React.useEffect(() => {
    if (open) {
      setName("");
      setAccent(PROJECT_ACCENTS[0]);
      setError("");
    }
  }, [open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const project = await api.createProject({ name: name.trim(), accent });
      await qc.invalidateQueries({ queryKey: keys.projects });
      setActiveId(project.id);
      onOpenChange(false);
    } catch {
      setError("Could not create the project. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-wide text-faint">
              Project name
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Web App"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-2 block font-mono text-[10px] uppercase tracking-wide text-faint">
              Accent
            </label>
            <div className="flex gap-2.5">
              {PROJECT_ACCENTS.map((c) => (
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
          </div>
          {error && <p className="text-[12px] text-st-blocked">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <DialogClose asChild>
              <Button type="button" variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" size="sm" disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create project"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
