import type { PrdStatus } from "@/lib/types";

export const PRD_STATUS_META: Record<PrdStatus, { label: string; color: string }> = {
  draft: { label: "Draft", color: "#8b949e" },
  review: { label: "Review", color: "#e0b34a" },
  approved: { label: "Approved", color: "#5fd07a" },
};

export const PRD_STATUS_ORDER: PrdStatus[] = ["draft", "review", "approved"];

/** What a person may actually choose (PRD-15). `approved` stays in PRD_STATUS_ORDER —
 *  it is still a real status that has to render — but it is REACHED by finishing the
 *  grill, never picked, so it is absent here. */
export const PRD_SETTABLE_STATUSES: PrdStatus[] = ["draft", "review"];
