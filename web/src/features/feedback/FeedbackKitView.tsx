import { Check, Copy } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";
import { TYPE_META } from "@/lib/meta";
import type { RequestType } from "@/lib/types";

import { FeedbackWidget } from "./FeedbackWidget";
import { ALL_TYPES, DEFAULT_CONFIG, toParams, type FeedbackConfig } from "./config";

const ACCENTS = ["#c6f24e", "#7ca2ff", "#a78bfa", "#5fd07a", "#ff8f8f", "#e0b34a"];
const RADII = [4, 8, 12, 20];

/** Feedback Kit — configure a themeable embeddable widget, preview it live,
 *  and copy the embed snippet. (Phase 2.) */
export function FeedbackKitView() {
  const [cfg, setCfg] = React.useState<FeedbackConfig>(DEFAULT_CONFIG);
  const [copied, setCopied] = React.useState(false);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const embedUrl = `${origin}/embed/feedback?${toParams(cfg)}`;
  const snippet = `<iframe src="${embedUrl}"\n  width="440" height="520" style="border:0;color-scheme:dark"\n  title="Feedback"></iframe>`;

  function toggleType(t: RequestType) {
    setCfg((c) => ({
      ...c,
      types: c.types.includes(t) ? c.types.filter((x) => x !== t) : [...c.types, t],
    }));
  }

  async function copy() {
    await navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-none border-b border-line px-5 py-4">
        <h1 className="text-[18px] font-semibold tracking-tight">Feedback Kit</h1>
        <p className="mt-0.5 text-[12.5px] text-muted">
          A themeable, embeddable feedback widget with built-in duplicate detection. Configure, preview, and copy the snippet.
        </p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 overflow-y-auto p-6 lg:grid-cols-[320px_1fr]">
        {/* Config panel */}
        <div className="flex flex-col gap-5">
          <Section label="Accent">
            <div className="flex flex-wrap gap-2">
              {ACCENTS.map((a) => (
                <button
                  key={a}
                  onClick={() => setCfg((c) => ({ ...c, accent: a }))}
                  className={cn(
                    "h-7 w-7 rounded-full border-2",
                    cfg.accent === a ? "border-fg" : "border-transparent",
                  )}
                  style={{ background: a }}
                  aria-label={a}
                />
              ))}
            </div>
          </Section>

          <Section label="Corner radius">
            <div className="flex gap-1.5">
              {RADII.map((r) => (
                <button
                  key={r}
                  onClick={() => setCfg((c) => ({ ...c, radius: r }))}
                  className={cn(
                    "rounded-md border px-3 py-1.5 font-mono text-[11px] transition-colors",
                    cfg.radius === r
                      ? "border-line-hover bg-surface-3 text-fg"
                      : "border-line-2 bg-surface-2 text-muted hover:text-fg-2",
                  )}
                >
                  {r}px
                </button>
              ))}
            </div>
          </Section>

          <Section label="Enabled types">
            <div className="flex flex-wrap gap-1.5">
              {ALL_TYPES.map((t) => {
                const on = cfg.types.includes(t);
                return (
                  <button
                    key={t}
                    onClick={() => toggleType(t)}
                    className="rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-wide transition-colors"
                    style={{
                      color: on ? TYPE_META[t].color : "#5c656e",
                      background: on ? TYPE_META[t].bg : "transparent",
                      borderColor: on ? TYPE_META[t].border : "#1e242a",
                    }}
                  >
                    {TYPE_META[t].label}
                  </button>
                );
              })}
            </div>
          </Section>

          <Section label="Options">
            <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-fg-2">
              <input
                type="checkbox"
                checked={cfg.showEmail}
                onChange={(e) => setCfg((c) => ({ ...c, showEmail: e.target.checked }))}
              />
              Collect email
            </label>
          </Section>

          <Section label="Embed snippet">
            <div className="relative">
              <pre className="overflow-x-auto rounded-lg border border-line-2 bg-surface-2 p-3 pr-10 font-mono text-[11px] leading-relaxed text-muted-2">
                {snippet}
              </pre>
              <button
                onClick={copy}
                className="absolute right-2 top-2 rounded-md border border-line-2 bg-surface-3 p-1.5 text-muted hover:text-fg"
                title="Copy"
              >
                {copied ? <Check size={13} className="text-accent" /> : <Copy size={13} />}
              </button>
            </div>
          </Section>
        </div>

        {/* Live preview */}
        <div className="flex flex-col">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-faint">Live preview</div>
          <div className="flex flex-1 items-start justify-center rounded-[14px] border border-dashed border-line-2 bg-surface/40 p-8">
            <FeedbackWidget key={JSON.stringify(cfg)} config={cfg} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-faint">{label}</div>
      {children}
    </div>
  );
}
