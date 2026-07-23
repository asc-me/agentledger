import { Check, Sparkles, X } from "lucide-react";

import { useProjectCtx } from "@/features/ProjectContext";
import { useCandidateShards, useReviewShard } from "@/lib/queries";
import type { Shard } from "@/lib/types";

/** AL-49: the review queue. Agent-written memory enters as a candidate and only
 *  reaches the trusted retrieval path once a human publishes it here. */
export function MemoryReviewView() {
  const { activeId } = useProjectCtx();
  const { data: candidates, isLoading } = useCandidateShards(activeId);
  const { publish, reject } = useReviewShard();

  if (isLoading || !candidates) {
    return <div className="flex h-full items-center justify-center text-[13px] text-muted">Loading…</div>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-none items-center gap-4 border-b border-line px-5 py-4">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight">Memory review</h1>
          <p className="mt-0.5 text-[12.5px] text-muted">
            Agent-written memory is a candidate until you publish it. Only published shards surface in
            search — so an unverified note never becomes ground truth for the next agent.
          </p>
        </div>
        <div className="ml-auto font-mono text-[10.5px] text-faint">{candidates.length} PENDING</div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {candidates.length === 0 ? (
          <div className="mt-16 text-center text-[13px] text-muted">
            Nothing to review. Agent-proposed lessons and notes will queue here for your approval.
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-2.5">
            {candidates.map((s) => (
              <CandidateCard
                key={s.id}
                shard={s}
                onPublish={() => publish.mutate(s.id)}
                onReject={() => reject.mutate(s.id)}
                busy={publish.isPending || reject.isPending}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function CandidateCard({
  shard,
  onPublish,
  onReject,
  busy,
}: {
  shard: Shard;
  onPublish: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-[12px] border border-line-2 bg-surface-2 p-3.5">
      <div className="mb-2 flex items-center gap-2">
        <Sparkles size={13} className="text-[#a78bfa]" />
        <span className="font-mono text-[10.5px] text-faint">{shard.origin || "agent"}</span>
        {shard.source && <span className="font-mono text-[10.5px] text-faint">· {shard.source}</span>}
        <span className="ml-auto rounded border border-[#3a2f1a] bg-[rgba(224,179,74,0.08)] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-[#e0b34a]">
          candidate
        </span>
      </div>
      <p className="mb-3 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{shard.text}</p>
      <div className="flex items-center gap-2">
        <button
          onClick={onPublish}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#1c2620] bg-[rgba(95,208,122,0.08)] px-2.5 py-1.5 text-[12px] font-medium text-st-done transition-colors hover:bg-[rgba(95,208,122,0.14)] disabled:opacity-50"
        >
          <Check size={13} /> Publish
        </button>
        <button
          onClick={onReject}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[12px] text-muted transition-colors hover:border-line-hover hover:text-ink disabled:opacity-50"
        >
          <X size={13} /> Reject
        </button>
      </div>
    </div>
  );
}
