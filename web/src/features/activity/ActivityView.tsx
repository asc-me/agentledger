import { KeyRound, User as UserIcon } from "lucide-react";

import { useProjectCtx } from "@/features/ProjectContext";
import { useEvents } from "@/lib/queries";
import type { Event } from "@/lib/types";

/** The audit ledger (AL-43): who did what, most-recent-first. */
export function ActivityView() {
  const { activeId } = useProjectCtx();
  const { data, isLoading } = useEvents(activeId);

  if (isLoading || !data) {
    return <div className="flex h-full items-center justify-center text-[13px] text-muted">Loading…</div>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-none items-center gap-4 border-b border-line px-5 py-4">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight">Activity</h1>
          <p className="mt-0.5 text-[12.5px] text-muted">
            Every accepted mutation, attributed to the agent key or user that made it.
          </p>
        </div>
        <div className="ml-auto font-mono text-[10.5px] text-faint">{data.total} EVENTS</div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {data.results.length === 0 ? (
          <div className="mt-16 text-center text-[13px] text-muted">
            No activity yet. Agent and user mutations will appear here.
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-1.5">
            {data.results.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EventRow({ event: e }: { event: Event }) {
  const isAgent = e.actor_type === "apikey";
  return (
    <div className="flex items-center gap-3 rounded-[10px] border border-line-2 bg-surface-2 px-3.5 py-2.5">
      <span
        className={`flex h-7 w-7 flex-none items-center justify-center rounded-full ${
          isAgent ? "bg-[rgba(167,139,250,0.12)] text-[#a78bfa]" : "bg-[rgba(95,208,122,0.1)] text-st-done"
        }`}
        title={e.actor_type}
      >
        {isAgent ? <KeyRound size={13} /> : <UserIcon size={13} />}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13px]">
          <span className="font-medium text-ink">{e.actor_label || e.actor_id}</span>
          <span className="font-mono text-[11.5px] text-accent">{e.action}</span>
          {e.target_id && <span className="font-mono text-[11px] text-muted">{e.target_id}</span>}
        </div>
        {e.meta && Object.keys(e.meta).length > 0 && (
          <div className="mt-0.5 truncate font-mono text-[10.5px] text-faint">{summarizeMeta(e.meta)}</div>
        )}
      </div>

      <span className="rounded border border-line px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-faint">
        {e.surface}
      </span>
      <span className="flex-none font-mono text-[10.5px] text-faint" title={e.ts ?? ""}>
        {relTime(e.ts)}
      </span>
    </div>
  );
}

function summarizeMeta(meta: Record<string, unknown>): string {
  return Object.entries(meta)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join(" · ");
}

function relTime(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
