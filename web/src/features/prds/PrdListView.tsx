import { FileText, Plus } from "lucide-react";
import * as React from "react";
import { useNavigate, useOutletContext } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useProjectCtx } from "@/features/ProjectContext";
import { api } from "@/lib/api";
import { keys, usePrds } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";

import { PRD_STATUS_META } from "./meta";

export function PrdListView() {
  const search = useOutletContext<string>();
  const { activeId } = useProjectCtx();
  const { data: prds = [], isLoading } = usePrds(activeId);
  const navigate = useNavigate();

  const visible = prds.filter((p) =>
    search ? p.title.toLowerCase().includes(search.toLowerCase()) : true,
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-none items-center gap-4 border-b border-line px-5 py-4">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight">PRDs</h1>
          <p className="mt-0.5 text-[12.5px] text-muted">
            Product specs with version history, linked items, and AI drafting commands.
          </p>
        </div>
        <div className="ml-auto">
          <NewPrdDialog onCreated={(id) => navigate(`/prds/${id}`)} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <div className="p-8 text-center text-[13px] text-muted">Loading…</div>
        ) : (
          <div className="space-y-2">
            {visible.map((p) => {
              const meta = PRD_STATUS_META[p.status];
              return (
                <button
                  key={p.id}
                  onClick={() => navigate(`/prds/${p.id}`)}
                  className="flex w-full items-center gap-3 rounded-[12px] border border-line-2 bg-surface-2 px-4 py-3 text-left transition-colors hover:border-line-hover"
                >
                  <FileText size={16} className="flex-none text-muted" />
                  <span className="w-[52px] flex-none font-mono text-[11px] text-faint">{p.id}</span>
                  <span className="min-w-0 flex-1 truncate text-[13.5px] text-fg-2">{p.title}</span>
                  <div className="flex flex-none items-center gap-1.5">
                    {p.linked.slice(0, 4).map((id) => (
                      <span key={id} className="rounded-md border border-line-2 px-1.5 py-0.5 font-mono text-[9.5px] text-muted">
                        {id}
                      </span>
                    ))}
                  </div>
                  <span className="flex-none rounded-md bg-surface-4 px-1.5 py-0.5 font-mono text-[10px] text-muted-2">
                    {p.version}
                  </span>
                  <span
                    className="flex flex-none items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide"
                    style={{ color: meta.color }}
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.color }} />
                    {meta.label}
                  </span>
                  <span className="w-[52px] flex-none text-right font-mono text-[10px] text-faint-2">
                    {p.updated}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function NewPrdDialog({ onCreated }: { onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [template, setTemplate] = React.useState("standard");
  const [busy, setBusy] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      const prd = await api.createPrd(title.trim(), template);
      qc.invalidateQueries({ queryKey: keys.prds });
      setOpen(false);
      setTitle("");
      onCreated(prd.id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus size={14} />
          New PRD
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New PRD</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <Input placeholder="PRD title" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
          <div className="flex gap-2">
            {["standard", "blank"].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTemplate(t)}
                className={
                  "flex-1 rounded-lg border px-3 py-2 text-[12.5px] capitalize transition-colors " +
                  (template === t
                    ? "border-line-hover bg-surface-3 text-fg"
                    : "border-line-2 bg-surface-2 text-muted hover:text-fg-2")
                }
              >
                {t} template
              </button>
            ))}
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <DialogClose asChild>
              <Button type="button" variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" size="sm" disabled={!title.trim() || busy}>
              Create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
