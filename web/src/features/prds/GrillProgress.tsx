import { Check, CircleDashed, PauseCircle } from "lucide-react";

import { cn } from "@/lib/cn";
import type { GrillDimensionState, GrillState } from "@/lib/types";

/** How approval was earned (AL-301 / PRD-15 D7).
 *
 *  `approved` is reached, not picked, so the editor has to show the WORK rather than a
 *  chosen value: which of the four dimensions were answered, which the author
 *  deliberately left open, and what is still outstanding.
 *
 *  It also shows what set the bar. On the shipped default (`CHAT_PROVIDER=stub`) that is
 *  a mechanical rule — answers counted, substance not assessed — and a reader who cannot
 *  see that would take a stub-graded approval for a judged one. */

const DIMENSION_LABEL: Record<string, string> = {
  scope_edges: "Scope edges",
  failure_modes: "Failure modes",
  contracts: "Contracts",
  open_decisions: "Open decisions",
};

const OUTCOME_META = {
  resolved: { icon: Check, color: "#5fd07a", label: "answered" },
  deferred: { icon: PauseCircle, color: "#e0b34a", label: "deferred" },
  unanswered: { icon: CircleDashed, color: "#8b949e", label: "open" },
} as const;

export function GrillProgress({ state }: { state: GrillState }) {
  const names = Object.keys(state.dimensions);
  if (!names.length) return null;

  // Only the stub's mechanical bar is worth calling out — a real provider grading is the
  // expected case and does not need a warning.
  const stubGraded = names.filter((n) => state.dimensions[n].graded_by === "stub").length;

  return (
    <div className="rounded-[11px] border border-line-2 bg-surface-2/60 p-3">
      <div className="mb-2.5 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wide text-faint">
          {state.complete ? "Approved by grilling" : "Grill progress"}
        </span>
        {!state.complete && (
          <span className="font-mono text-[10px] text-faint">
            {names.length - state.outstanding.length}/{names.length}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        {names.map((name) => (
          <DimensionRow key={name} name={name} state={state.dimensions[name]} />
        ))}
      </div>

      {state.complete ? (
        <p className="mt-2.5 text-[11px] leading-snug text-faint">
          Approved because every dimension was answered or explicitly deferred — not by
          anyone setting a status.
          {stubGraded > 0 && (
            <> Graded offline: answers were recorded, their substance was not assessed.</>
          )}
        </p>
      ) : (
        <p className="mt-2.5 text-[11px] leading-snug text-faint">
          Answer the open dimensions in the grill — or defer one deliberately — and this
          PRD approves itself.
        </p>
      )}
    </div>
  );
}

function DimensionRow({ name, state }: { name: string; state: GrillDimensionState }) {
  const meta = OUTCOME_META[state.outcome] ?? OUTCOME_META.unanswered;
  const Icon = meta.icon;
  return (
    <div className="flex items-start gap-2 text-[12px]">
      <Icon size={13} className="mt-0.5 flex-none" style={{ color: meta.color }} />
      <span className="flex-none text-fg-2">{DIMENSION_LABEL[name] ?? name}</span>
      <span className="font-mono text-[10px] uppercase tracking-wide" style={{ color: meta.color }}>
        {meta.label}
      </span>
      {state.note && (
        <span className="min-w-0 flex-1 truncate text-[11px] text-faint" title={state.note}>
          {state.note}
        </span>
      )}
      {state.graded_by === "stub" && (
        <span
          title="Graded offline: an answer was recorded, its substance was not assessed."
          className="ml-auto flex-none rounded border border-line-2 px-1 font-mono text-[9px] uppercase text-faint"
        >
          offline
        </span>
      )}
    </div>
  );
}

/** The status control's replacement for a selectable `approved` — it explains why the
 *  option is absent rather than leaving a reader to wonder where it went. */
export function ApprovedIsEarned({ complete }: { complete: boolean }) {
  return (
    <div
      className={cn(
        "border-t border-line px-2 py-1.5 font-mono text-[9.5px] leading-snug",
        complete ? "text-[#5fd07a]" : "text-faint",
      )}
    >
      {complete
        ? "APPROVED — reached by finishing the grill"
        : "APPROVED is reached by finishing the grill"}
    </div>
  );
}
