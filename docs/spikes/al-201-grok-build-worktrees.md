# AL-201 spike — collision clusters → Grok Build parallel worktrees

**Goal:** decide whether AgentLedger's collision-aware clustering (AL-192) can drive Grok
Build's parallel-worktree execution — several agents building concurrently without merge
collisions — and whether their output can auto-capture touchpoints to sharpen the next round.
**Verdict: sound, phase it.** The two halves compose cleanly — AgentLedger decides *what can
run concurrently*, Grok Build *runs it in isolated worktrees* — and the streaming-json output
returns ground-truth touchpoints for free. Keep it an **optional, provider-neutral execution
backend**, not core.

Ground truth: `backend/app/services/collision.py` (`collision_clusters`) +
`GET /items/collision-clusters` already ship (AL-192). Grok Build capabilities per
[docs.x.ai/build](https://docs.x.ai/build) (2026-07).

## The two halves

**AgentLedger — `collision_clusters` (AL-192).** Partitions a set of items into connected
components over (actual-or-predicted) code touch-area overlap. Output per cluster:
`{items, areas, collides, predicted}`. The load-bearing invariant: **distinct clusters share
no touch-areas, so they are safe to run in parallel**; items *within* a cluster overlap and
belong to one worker.

**Grok Build — `--parallel` worktrees.** Grok Build spawns up to 8 sub-agents, **each in its
own git worktree/branch**, with headless `--output-format streaming-json` reporting files
modified, commands run, and results.

The fit is exact: **one non-colliding cluster → one worktree.**

## Handoff design

```
GET /items/collision-clusters?status=next          # AgentLedger: the divvy
  → clusters[]   (each non-colliding vs the others)
for each cluster (up to Grok Build's --parallel cap, default 8):
  grok -p "<cluster brief: items + their areas>" \
       --parallel --output-format streaming-json    # one worktree owns the cluster
  ← streaming-json { files_modified: [...], result: ... }
  → update_item(id, touchpoints=files_modified, status="review")   # capture + advance
```

- **Brief per cluster:** the cluster's items (id, title, description) + their `areas` as the
  expected blast radius. One worktree owns the whole cluster, so intra-cluster overlap is fine.
- **Cap:** clusters beyond the `--parallel` limit queue to the next wave; a finished worktree
  frees a slot and pulls the next non-colliding cluster — the reactive re-cluster from PRD-10's
  triage board (AL-191).

## Touchpoint auto-capture (closes the AL-192 loop)

Grok Build reports **files modified** per run; map it straight onto the item's touchpoints:

| Grok Build streaming-json | AgentLedger |
|---|---|
| `files_modified` (per worktree) | `update_item(id, touchpoints=[…])` — the **actual** touch-areas |
| result = success | `update_item(id, status="review")` |
| result = failure | `release_item(id)` — back to the queue |

Predicted areas drove the divvy; the *observed* files replace the prediction as ground truth,
so AL-192's learned model and the next round's clustering sharpen — collision-avoidance improves
over time with **zero manual tagging**. This is also the highest-value, lowest-risk slice on its
own (see phase 1).

## Phased path

1. **Parse-only (do first).** Don't orchestrate anything — run Grok Build as usual, parse its
   streaming-json, and write `touchpoints` back onto the item. Feeds the AL-192 learned model
   with no worktree orchestration and no coupling to the parallel runner.
2. **Single-cluster runner.** Hand *one* cluster to a `grok --parallel` run in a worktree;
   capture touchpoints on completion; open a branch/PR. Proves the brief + capture end to end.
3. **Wave orchestration.** Fan clusters across the worktree pool up to the cap, with the reactive
   re-cluster. This is the PRD-10 triage-board execution story.

## Risks / constraints

- **Provider-neutral.** Grok Build is one execution backend; keep it behind an adapter so Claude
  Code or a manual runner can slot in. Don't let the streaming-json shape leak past the parser.
- **0.1 beta.** The `--parallel` / streaming-json contract may change — isolate + version the
  parser.
- **Prediction cold-start (AL-192).** Early clusters lean on inference; a wrong prediction can
  put two colliding items in different worktrees. Mitigate: phase 1 seeds real touchpoints first,
  and require human tag-review above a confidence threshold before a `predicted` cluster is
  dispatched in parallel.
- **Collision ≠ conflict guarantee.** Shared *semantic* deps (a type, an interface, a migration)
  aren't always in the touch-areas. Treat collision clustering as conflict-*reduction*, not a
  guarantee — CI + review still gate every merge.

## Deliberately out of the spike

Building the orchestration (that's the phased work above); the AgentLedger side already exists
(`collision_clusters` + `GET /items/collision-clusters`). The immediate, low-risk win is
**phase 1** — touchpoint capture from streaming-json, which pays off even if the parallel runner
is never built.
