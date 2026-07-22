/** Unauthenticated client for the public feedback endpoints (embed widget). */
import type { DuplicateHit, PublicSubmitResponse } from "./types";

export interface PublicSubmitBody {
  type: string;
  title: string;
  detail?: string;
  email?: string;
  project_id?: string;
  source_url?: string;
  meta?: Record<string, unknown>;
}

export const publicApi = {
  async duplicates(q: string, projectId = ""): Promise<DuplicateHit[]> {
    const params = new URLSearchParams({ q });
    if (projectId) params.set("project_id", projectId);
    const res = await fetch(`/api/public/duplicates?${params.toString()}`);
    if (!res.ok) return [];
    return res.json();
  },

  async submit(body: PublicSubmitBody): Promise<PublicSubmitResponse> {
    const res = await fetch("/api/public/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`submit failed: ${res.status}`);
    return res.json();
  },
};
