import { Check, Loader2 } from "lucide-react";
import * as React from "react";

import { TYPE_META } from "@/lib/meta";
import { publicApi } from "@/lib/publicApi";
import type { DuplicateHit, RequestType } from "@/lib/types";

import type { FeedbackConfig } from "./config";

/**
 * Self-contained, themeable feedback widget. Runs unauthenticated against the
 * public endpoints — used both standalone (/embed/feedback) and in the generator
 * preview. Does its own live duplicate detection before submit.
 */
export function FeedbackWidget({ config }: { config: FeedbackConfig }) {
  const types = config.types.length ? config.types : (["feedback"] as RequestType[]);
  const [type, setType] = React.useState<RequestType>(types[0]);
  const [title, setTitle] = React.useState("");
  const [detail, setDetail] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [dups, setDups] = React.useState<DuplicateHit[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [doneRef, setDoneRef] = React.useState<string | null>(null);

  // Live duplicate detection, debounced on the title.
  React.useEffect(() => {
    if (title.trim().length < 4) {
      setDups([]);
      return;
    }
    const t = setTimeout(async () => {
      setDups(await publicApi.duplicates(title.trim(), config.projectId));
    }, 350);
    return () => clearTimeout(t);
  }, [title, config.projectId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || submitting) return;
    setSubmitting(true);
    try {
      const res = await publicApi.submit({
        type,
        title: title.trim(),
        detail: detail.trim(),
        email: email.trim(),
        project_id: config.projectId,
      });
      setDoneRef(res.request.id);
    } catch {
      setDoneRef("error");
    } finally {
      setSubmitting(false);
    }
  }

  const style = {
    "--fb-accent": config.accent,
    "--fb-radius": `${config.radius}px`,
  } as React.CSSProperties;

  if (doneRef && doneRef !== "error") {
    return (
      <div style={style} className="w-full max-w-md">
        <div
          className="flex flex-col items-center gap-3 border border-line-2 bg-surface-3 p-8 text-center"
          style={{ borderRadius: "var(--fb-radius)" }}
        >
          <span
            className="flex h-11 w-11 items-center justify-center rounded-full"
            style={{ background: "var(--fb-accent)" }}
          >
            <Check size={22} className="text-bg" />
          </span>
          <div className="text-[15px] font-semibold">Thanks — we got it.</div>
          <div className="font-mono text-[12px] text-muted">Tracked as {doneRef}</div>
        </div>
      </div>
    );
  }

  return (
    <div style={style} className="w-full max-w-md">
      <form
        onSubmit={submit}
        className="flex flex-col gap-3 border border-line-2 bg-surface-3 p-5"
        style={{ borderRadius: "var(--fb-radius)" }}
      >
        <div>
          <h2 className="text-[15px] font-semibold">Send feedback</h2>
          <p className="text-[12px] text-muted">Found a bug or have an idea? Tell us.</p>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {types.map((t) => {
            const active = t === type;
            const m = TYPE_META[t];
            return (
              <button
                key={t}
                type="button"
                onClick={() => setType(t)}
                className="rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-wide transition-colors"
                style={{
                  borderRadius: "var(--fb-radius)",
                  color: active ? m.color : "#8b949e",
                  background: active ? m.bg : "transparent",
                  borderColor: active ? m.border : "#1e242a",
                }}
              >
                {m.label}
              </button>
            );
          })}
        </div>

        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Summary"
          className="h-9 border border-line-2 bg-surface-2 px-3 text-[13px] outline-none focus:border-line-hover"
          style={{ borderRadius: "var(--fb-radius)" }}
        />

        {dups.length > 0 && (
          <div
            className="border border-[rgba(224,179,74,0.3)] bg-[rgba(224,179,74,0.06)] p-2.5"
            style={{ borderRadius: "var(--fb-radius)" }}
          >
            <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-[#e0b34a]">
              Possibly already reported
            </div>
            <div className="flex flex-col gap-1">
              {dups.slice(0, 3).map((d) => (
                <div key={`${d.kind}-${d.id}`} className="flex items-center gap-2 text-[12px]">
                  <span className="font-mono text-[10px] text-faint">{d.id}</span>
                  <span className="min-w-0 flex-1 truncate text-fg-2">{d.title}</span>
                  <span className="font-mono text-[10px] text-[#e0b34a]">{Math.round(d.score * 100)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <textarea
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          placeholder="Details (optional)"
          rows={3}
          className="resize-none border border-line-2 bg-surface-2 px-3 py-2 text-[13px] outline-none focus:border-line-hover"
          style={{ borderRadius: "var(--fb-radius)" }}
        />

        {config.showEmail && (
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email (optional)"
            type="email"
            className="h-9 border border-line-2 bg-surface-2 px-3 text-[13px] outline-none focus:border-line-hover"
            style={{ borderRadius: "var(--fb-radius)" }}
          />
        )}

        {doneRef === "error" && (
          <p className="text-[12px] text-st-blocked">Something went wrong. Please try again.</p>
        )}

        <button
          type="submit"
          disabled={!title.trim() || submitting}
          className="flex h-9 items-center justify-center gap-2 font-semibold text-bg transition-opacity disabled:opacity-50"
          style={{ background: "var(--fb-accent)", borderRadius: "var(--fb-radius)" }}
        >
          {submitting && <Loader2 size={14} className="animate-spin" />}
          Send feedback
        </button>
      </form>
    </div>
  );
}
