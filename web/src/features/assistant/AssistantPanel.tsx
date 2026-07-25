import { ArrowUp, Check, Sparkles, User as UserIcon, X } from "lucide-react";
import * as React from "react";

import { api } from "@/lib/api";
import { Markdown } from "@/lib/markdown";
import type { AssistantProvider, ProposedAction } from "@/lib/types";

/** AL-175: the in-app assistant, scoped to one item or PRD. Streams a turn over SSE and
 *  surfaces the writes it proposes as approve/reject cards — nothing mutates until you
 *  approve (the AL-177 propose-then-approve guarantee). */
type Msg = { role: "user" | "assistant"; content: string; proposed: ProposedAction[] };

export function AssistantPanel({
  entityType,
  entityId,
  projectId,
}: {
  entityType: "item" | "prd";
  entityId: string;
  projectId: string;
}) {
  const [threadId, setThreadId] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<Msg[]>([]);
  const [providers, setProviders] = React.useState<AssistantProvider[]>([]);
  const [provider, setProvider] = React.useState<string>("");
  const [draft, setDraft] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Load the model catalog + the most recent thread for this entity (if any).
  React.useEffect(() => {
    let alive = true;
    api.assistantProviders(projectId).then((r) => alive && setProviders(r.providers)).catch(() => {});
    api.assistantThreads(projectId, entityType, entityId).then(async (threads) => {
      if (!alive || threads.length === 0) return;
      const t = threads[0];
      setThreadId(t.id);
      setProvider(t.provider);
      const detail = await api.getAssistantThread(t.id);
      if (!alive) return;
      setMessages(detail.messages
        .filter((m) => m.role !== "tool")
        .map((m) => ({ role: m.role as "user" | "assistant", content: m.content, proposed: m.proposed_actions })));
    }).catch(() => {});
    return () => { alive = false; };
  }, [projectId, entityType, entityId]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, streaming]);

  async function ensureThread(): Promise<string> {
    if (threadId) return threadId;
    const t = await api.createAssistantThread({
      project_id: projectId, entity_type: entityType, entity_id: entityId, provider: provider || undefined });
    setThreadId(t.id);
    setProvider(t.provider);
    return t.id;
  }

  async function send() {
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft("");
    setMessages((m) => [...m, { role: "user", content: text, proposed: [] },
                              { role: "assistant", content: "", proposed: [] }]);
    setStreaming(true);
    const patchLast = (fn: (m: Msg) => Msg) =>
      setMessages((m) => m.map((msg, i) => (i === m.length - 1 ? fn(msg) : msg)));
    try {
      const id = await ensureThread();
      await api.assistantStream(id, text, {
        onDelta: (d) => patchLast((m) => ({ ...m, content: m.content + d })),
        onProposed: (a) => patchLast((m) => ({ ...m, proposed: [...m.proposed, a] })),
        onError: (msg) => patchLast((m) => ({ ...m, content: m.content + `\n\n_Error: ${msg}_` })),
      });
    } finally {
      setStreaming(false);
    }
  }

  async function decide(mi: number, pi: number, approve: boolean) {
    const action = messages[mi].proposed[pi];
    const res = approve ? await api.applyAction(action.id) : await api.rejectAction(action.id);
    setMessages((m) => m.map((msg, i) => i !== mi ? msg : {
      ...msg,
      proposed: msg.proposed.map((p, j) => j !== pi ? p : { ...p, status: res.status as ProposedAction["status"] }),
    }));
  }

  async function pickProvider(id: string) {
    setProvider(id);
    const tid = threadId ?? (await ensureThread());
    const p = providers.find((x) => x.id === id);
    await api.setThreadModel(tid, id, p?.chat_model ?? "");
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-none items-center gap-2 pb-2">
        <Sparkles size={13} className="text-[#a78bfa]" />
        <span className="text-[12px] font-medium text-fg-2">Assistant</span>
        <select
          value={provider}
          onChange={(e) => pickProvider(e.target.value)}
          className="ml-auto rounded-md border border-line-2 bg-surface-2 px-2 py-1 text-[11px] text-muted"
        >
          {providers.length === 0 && <option value="">no provider configured</option>}
          {providers.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.configured}>
              {p.label}{p.configured ? "" : " (configure in Settings)"}
            </option>
          ))}
        </select>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <p className="mt-6 text-center text-[12.5px] text-faint">
            Brainstorm or review this {entityType}. The assistant can propose changes — you approve them.
          </p>
        )}
        {messages.map((m, mi) => (
          <div key={mi} className="flex gap-2">
            <div className="mt-0.5 flex-none">
              {m.role === "user"
                ? <UserIcon size={13} className="text-faint" />
                : <Sparkles size={13} className="text-[#a78bfa]" />}
            </div>
            <div className="min-w-0 flex-1">
              {m.role === "assistant"
                ? <div className="text-[13px] leading-relaxed text-fg-2"><Markdown source={m.content || "…"} /></div>
                : <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{m.content}</p>}
              {m.proposed.map((a, pi) => (
                <div key={a.id} className="mt-2 rounded-[10px] border border-[#3a2f1a] bg-[rgba(224,179,74,0.06)] p-2.5">
                  <div className="mb-1 flex items-center gap-1.5">
                    <span className="font-mono text-[9px] uppercase tracking-wide text-[#e0b34a]">proposed · {a.tool}</span>
                  </div>
                  <p className="text-[12px] text-fg-2">{a.summary}</p>
                  {a.status === "pending" ? (
                    <div className="mt-2 flex items-center gap-2">
                      <button onClick={() => decide(mi, pi, true)}
                        className="inline-flex items-center gap-1 rounded-lg border border-[#1c2620] bg-[rgba(95,208,122,0.1)] px-2 py-1 text-[11.5px] text-st-done hover:bg-[rgba(95,208,122,0.16)]">
                        <Check size={12} /> Approve
                      </button>
                      <button onClick={() => decide(mi, pi, false)}
                        className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-[11.5px] text-muted hover:text-ink">
                        <X size={12} /> Reject
                      </button>
                    </div>
                  ) : (
                    <div className="mt-1.5 font-mono text-[10px] uppercase tracking-wide text-faint">{a.status}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-none items-end gap-2 pt-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          rows={2}
          placeholder={`Ask about this ${entityType}, or propose a change…`}
          className="min-h-0 flex-1 resize-none rounded-[10px] border border-line-2 bg-surface-2 px-3 py-2 text-[12.5px] text-fg-2 outline-none focus:border-line-hover"
        />
        <button
          onClick={send}
          disabled={streaming || !draft.trim()}
          className="flex-none rounded-lg bg-accent p-2 text-ink disabled:opacity-40"
        >
          <ArrowUp size={15} />
        </button>
      </div>
    </div>
  );
}
