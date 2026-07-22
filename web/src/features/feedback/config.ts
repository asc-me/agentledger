import type { RequestType } from "@/lib/types";

export interface FeedbackConfig {
  accent: string; // hex incl. #
  radius: number; // px
  types: RequestType[];
  showEmail: boolean;
  projectId: string;
}

export const ALL_TYPES: RequestType[] = ["bug", "feature", "enhancement", "feedback"];

export const DEFAULT_CONFIG: FeedbackConfig = {
  accent: "#c6f24e",
  radius: 10,
  types: ALL_TYPES,
  showEmail: true,
  projectId: "", // filled with the active project by the Feedback Kit; empty → server default
};

/** Serialize config to the query params the /embed/feedback route reads. */
export function toParams(cfg: FeedbackConfig): string {
  const p = new URLSearchParams();
  p.set("accent", cfg.accent.replace("#", ""));
  p.set("radius", String(cfg.radius));
  p.set("types", cfg.types.join(","));
  p.set("email", cfg.showEmail ? "1" : "0");
  p.set("project", cfg.projectId);
  return p.toString();
}

export function fromParams(search: URLSearchParams): FeedbackConfig {
  const accent = search.get("accent");
  const radius = search.get("radius");
  const types = search.get("types");
  return {
    accent: accent ? `#${accent.replace("#", "")}` : DEFAULT_CONFIG.accent,
    radius: radius ? Number(radius) : DEFAULT_CONFIG.radius,
    types: types
      ? (types.split(",").filter((t) => ALL_TYPES.includes(t as RequestType)) as RequestType[])
      : DEFAULT_CONFIG.types,
    showEmail: search.get("email") !== "0",
    projectId: search.get("project") ?? DEFAULT_CONFIG.projectId,
  };
}
