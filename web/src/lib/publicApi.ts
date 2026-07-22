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
  attachment_ids?: string[];
  turnstile_token?: string;
  hp?: string;
}

export const publicApi = {
  async duplicates(q: string, projectId = ""): Promise<DuplicateHit[]> {
    const params = new URLSearchParams({ q });
    if (projectId) params.set("project_id", projectId);
    const res = await fetch(`/api/public/duplicates?${params.toString()}`);
    if (!res.ok) return [];
    return res.json();
  },

  async uploadAttachment(file: File): Promise<{ id: string; url: string } | null> {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/public/attachments", { method: "POST", body: form });
    if (!res.ok) return null;
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
