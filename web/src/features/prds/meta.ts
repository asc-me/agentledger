import type { PrdStatus } from "@/lib/types";

export const PRD_STATUS_META: Record<PrdStatus, { label: string; color: string }> = {
  draft: { label: "Draft", color: "#8b949e" },
  review: { label: "Review", color: "#e0b34a" },
  approved: { label: "Approved", color: "#5fd07a" },
};

export const PRD_STATUS_ORDER: PrdStatus[] = ["draft", "review", "approved"];
