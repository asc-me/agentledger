import * as React from "react";

import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

/**
 * The project tag field, shared by both creation surfaces (PRD-13 / AL-260).
 *
 * A tag is the short prefix a project's item, request, and PRD keys render with —
 * `GRPH-12`, `GRPH-R33`, `GRPH-P4`. It is set at creation and changeable afterwards.
 *
 * Neither derivation nor the availability rule is reimplemented here. Both are server
 * calls, because a second implementation in TypeScript would drift from the one that
 * actually assigns and enforces the tag — and the availability rule in particular is
 * not guessable from the client: it excludes tags this deployment previously held and
 * prefixes reserved by ids issued before tags existed.
 */
export type TagStatus =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "ok" }
  | { kind: "unavailable"; reason: string };

export function useTagField(name: string) {
  const [tag, setTagRaw] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const [status, setStatus] = React.useState<TagStatus>({ kind: "idle" });

  function setTag(next: string) {
    setTouched(true);
    setTagRaw(next.toUpperCase().slice(0, 4));
  }

  function reset() {
    setTagRaw("");
    setTouched(false);
    setStatus({ kind: "idle" });
  }

  // Suggest from the name until the user takes over the field. Once they've typed a
  // tag, the name no longer overwrites it — otherwise editing the name would silently
  // discard a deliberate choice.
  React.useEffect(() => {
    if (touched || !name.trim()) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .tagSuggestion(name.trim())
        .then((r) => {
          if (!cancelled) setTagRaw(r.tag);
        })
        .catch(() => {
          /* a failed suggestion just leaves the field empty; the server derives on submit */
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [name, touched]);

  React.useEffect(() => {
    if (!tag) {
      setStatus({ kind: "idle" });
      return;
    }
    let cancelled = false;
    setStatus({ kind: "checking" });
    const t = setTimeout(() => {
      api
        .tagCheck(tag)
        .then((r) => {
          if (cancelled) return;
          setStatus(r.available ? { kind: "ok" } : { kind: "unavailable", reason: r.reason });
        })
        .catch(() => {
          if (!cancelled) setStatus({ kind: "idle" });
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [tag]);

  return { tag, setTag, status, reset, blocked: status.kind === "unavailable" };
}

export function TagField({
  tag,
  setTag,
  status,
}: {
  tag: string;
  setTag: (v: string) => void;
  status: TagStatus;
}) {
  return (
    <div>
      <label
        htmlFor="project-tag"
        className="mb-1.5 block font-mono text-[10px] uppercase tracking-wide text-faint"
      >
        Tag
      </label>
      <Input
        id="project-tag"
        value={tag}
        onChange={(e) => setTag(e.target.value)}
        placeholder="e.g. GRPH"
        maxLength={4}
        aria-invalid={status.kind === "unavailable"}
        className="font-mono uppercase"
      />
      <p className="mt-1.5 font-mono text-[10px] text-faint" role="status">
        {status.kind === "unavailable" ? (
          <span className="text-danger">{status.reason}</span>
        ) : tag ? (
          <>
            Keys look like <span className="text-fg-2">{tag}-12</span>,{" "}
            <span className="text-fg-2">{tag}-R33</span>, <span className="text-fg-2">{tag}-P4</span>
          </>
        ) : (
          "2–4 letters or digits, starting with a letter"
        )}
      </p>
    </div>
  );
}
