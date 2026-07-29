import { Check, Layers, RotateCcw, Sparkles, X } from "lucide-react";

import { cn } from "@/lib/cn";
import { useProjectCtx } from "@/features/ProjectContext";
import {
  useAutoActions,
  useCandidateClusters,
  useCandidateShards,
  usePromoteCluster,
  useReviewShard,
  useScoredCandidates,
  useUndoAutoShard,
} from "@/lib/queries";
import type { ReviewSuggestion, ScoredCandidate, Shard, ShardCluster } from "@/lib/types";

/** AL-49: the review queue. Agent-written memory enters as a candidate and only
 *  reaches the trusted retrieval path once a human publishes it here.
 *  AL-50: recurring near-duplicate candidates are grouped so a lesson that keeps
 *  recurring can be promoted once as a principle. */
export function MemoryReviewView() {
  const { activeId } = useProjectCtx();
  const { data: candidates, isLoading } = useCandidateShards(activeId);
  const { data: clusters } = useCandidateClusters(activeId);
  const { data: scored } = useScoredCandidates(activeId);
  const { data: autoActions } = useAutoActions(activeId);
  const { publish, reject } = useReviewShard();
  const promoteCluster = usePromoteCluster();
  const undoAuto = useUndoAutoShard();

  if (isLoading || !candidates) {
    return <div className="flex h-full items-center justify-center text-[13px] text-muted">Loading…</div>;
  }

  const clustered = new Set((clusters ?? []).flatMap((c) => [c.representative.id, ...c.members.map((m) => m.id)]));
  const scoreById = new Map((scored ?? []).map((s) => [s.shard.id, s]));
  // Loose candidates ordered most-actionable first (highest suggestion confidence).
  const loose = candidates
    .filter((s) => !clustered.has(s.id))
    .sort((a, b) => (scoreById.get(b.id)?.confidence ?? 0) - (scoreById.get(a.id)?.confidence ?? 0));

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
        <div className="mx-auto flex max-w-3xl flex-col gap-2.5">
          {candidates.length === 0 ? (
            <div className="py-16 text-center text-[13px] text-muted">
              Nothing to review. Agent-proposed lessons and notes will queue here for your approval.
            </div>
          ) : (
            <>
              {(clusters ?? []).map((c) => (
                <ClusterCard
                  key={c.representative.id}
                  cluster={c}
                  onPromote={() =>
                    promoteCluster.mutate({
                      publishId: c.representative.id,
                      rejectIds: c.members.map((m) => m.id),
                    })
                  }
                  busy={promoteCluster.isPending}
                />
              ))}
              {loose.map((s) => (
                <CandidateCard
                  key={s.id}
                  shard={s}
                  score={scoreById.get(s.id)}
                  onPublish={() => publish.mutate(s.id)}
                  onReject={() => reject.mutate(s.id)}
                  busy={publish.isPending || reject.isPending}
                />
              ))}
            </>
          )}
          {autoActions && autoActions.length > 0 && (
            <AutoActionsLane
              shards={autoActions}
              onUndo={(id) => undoAuto.mutate(id)}
              busy={undoAuto.isPending}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** AL-227: memories the scorer published or rejected without a human. Shown so no
 *  auto-action is silent — each can be pulled back into the review queue. */
function AutoActionsLane({
  shards,
  onUndo,
  busy,
}: {
  shards: Shard[];
  onUndo: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center gap-2 px-0.5">
        <Sparkles size={12} className="text-[#a78bfa]" />
        <span className="font-mono text-[10.5px] uppercase tracking-wide text-faint">
          Recent auto-actions · {shards.length}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {shards.map((s) => {
          const rejected = s.status === "rejected";
          return (
            <div
              key={s.id}
              className="flex items-start gap-2.5 rounded-[10px] border border-line-2 bg-surface-2/60 px-3 py-2"
            >
              <span
                className={cn(
                  "mt-0.5 shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide",
                  rejected
                    ? "border-[rgba(255,107,107,0.3)] bg-[rgba(255,107,107,0.08)] text-st-blocked"
                    : "border-[#1c2620] bg-[rgba(95,208,122,0.1)] text-st-done",
                )}
              >
                auto-{rejected ? "rejected" : "published"}
              </span>
              <p className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2" title={s.text}>
                {s.text}
              </p>
              {s.auto_confidence != null && (
                <span className="mt-0.5 shrink-0 font-mono text-[10px] text-faint">
                  {Math.round(s.auto_confidence * 100)}%
                </span>
              )}
              <button
                onClick={() => onUndo(s.id)}
                disabled={busy}
                title="Return to the review queue"
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] text-muted transition-colors hover:border-line-hover hover:text-ink disabled:opacity-50"
              >
                <RotateCcw size={11} /> Undo
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// AL-151: advisory review suggestion — colour + label per suggestion category.
const SUGGESTION_META: Record<ReviewSuggestion, { label: string; className: string }> = {
  accept: { label: "suggest publish", className: "border-[#1c2620] bg-[rgba(95,208,122,0.1)] text-st-done" },
  reject: { label: "suggest reject", className: "border-[rgba(255,107,107,0.3)] bg-[rgba(255,107,107,0.08)] text-st-blocked" },
  review: { label: "needs a look", className: "border-line-2 bg-surface-3 text-muted" },
};

function CandidateCard({
  shard,
  score,
  onPublish,
  onReject,
  busy,
}: {
  shard: Shard;
  score?: ScoredCandidate;
  onPublish: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const meta = score ? SUGGESTION_META[score.suggestion] : null;
  return (
    <div className="rounded-[12px] border border-line-2 bg-surface-2 p-3.5">
      <div className="mb-2 flex items-center gap-2">
        <Sparkles size={13} className="text-[#a78bfa]" />
        <span className="font-mono text-[10.5px] text-faint">{shard.origin || "agent"}</span>
        {shard.source && <span className="font-mono text-[10.5px] text-faint">· {shard.source}</span>}
        {meta && (
          <span
            title={score ? `${Math.round(score.confidence * 100)}% confidence` : undefined}
            className={cn(
              "ml-auto rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide",
              meta.className,
            )}
          >
            {meta.label}
          </span>
        )}
        <span
          className={cn(
            "rounded border border-[#3a2f1a] bg-[rgba(224,179,74,0.08)] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-[#e0b34a]",
            !meta && "ml-auto",
          )}
        >
          candidate
        </span>
      </div>
      <p className="mb-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{shard.text}</p>
      {score && score.reasons.length > 0 && (
        <p className="mb-3 text-[11.5px] text-faint">Why: {score.reasons.join(" · ")}</p>
      )}
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

/** AL-50: a recurring lesson — several near-duplicate candidates. Promote the
 *  representative as the principle and drop the duplicates in one action. */
function ClusterCard({
  cluster,
  onPromote,
  busy,
}: {
  cluster: ShardCluster;
  onPromote: () => void;
  busy: boolean;
}) {
  const { representative: rep, members, size } = cluster;
  return (
    <div className="rounded-[12px] border border-[rgba(224,179,74,0.35)] bg-[rgba(224,179,74,0.04)] p-3.5">
      <div className="mb-2 flex items-center gap-2">
        <Layers size={13} className="text-[#e0b34a]" />
        <span className="font-mono text-[10.5px] font-medium text-[#e0b34a]">
          RECURRING · appeared {size}×
        </span>
        <span className="font-mono text-[10.5px] text-faint">{rep.origin || "agent"}</span>
      </div>
      <p className="mb-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{rep.text}</p>
      {members.length > 0 && (
        <details className="mb-3 text-[12px] text-muted">
          <summary className="cursor-pointer select-none text-faint">
            {members.length} similar duplicate{members.length > 1 ? "s" : ""}
          </summary>
          <ul className="mt-1.5 flex flex-col gap-1 border-l border-line pl-3">
            {members.map((m) => (
              <li key={m.id} className="whitespace-pre-wrap leading-relaxed">{m.text}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="flex items-center gap-2">
        <button
          onClick={onPromote}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#1c2620] bg-[rgba(95,208,122,0.08)] px-2.5 py-1.5 text-[12px] font-medium text-st-done transition-colors hover:bg-[rgba(95,208,122,0.14)] disabled:opacity-50"
        >
          <Check size={13} /> Publish as principle{members.length > 0 ? ` · drop ${members.length}` : ""}
        </button>
      </div>
    </div>
  );
}
