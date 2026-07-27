# AL-81 spike — local↔cloud sync: the hard half (bidirectional items, claims, offline)

**Goal:** settle the claim-authority + conflict model for mutable, contended state (items,
claims, memory, PRDs) before anyone builds bidirectional sync, and lay out a phased path.
**Verdict: don't build general bidirectional sync for v1.** The MCP proxy (AL-138) already
delivers the online hybrid with a *single* authority (the cloud), so the two-writer problem
never arises while connected. The only thing bidirectional buys is **offline mutation** — and
that's best served by a **read-only offline mirror first**, with guarded read-write deferred
until there's real demand. This note settles the model so the phased build is unambiguous.

Grounding: what shipped — one-way code-graph sync (AL-137/139), privacy/purge (AL-137 D8),
and the **MCP proxy** (AL-138: graph-local, everything-else→cloud). The precedent to reuse for
conflict detection is the Drive/filesystem sync (`SyncState` + "flag when both sides changed").

## What the proxy already solved, and what's left

**Solved (online).** With AL-138, a linked local instance forwards every item/claim/memory/PRD
call to the cloud in real time. There is **exactly one writer** (the cloud), so claims, edits,
and the ledger have one authority and **no conflict**. The code graph is the *other* direction
(local-authoritative, one-way push) and is also conflict-free by construction (derived,
content-hashed, LWW-per-path).

**Left (offline).** The hard half is only reached when the local instance mutates items **while
disconnected** and must reconcile on reconnect — now there are two writers. Everything below is
about *that* window.

## Per-entity conflict model

| Entity | Why it's hard | Recommendation |
|---|---|---|
| **Claims** (`claimed_by`/`claimed_at`, lease-based) | Leases assume one authoritative clock/server; two writers can both "own" an item. | **Claiming is disabled while disconnected** (read-only mirror). For guarded read-write: a local claim is provisional and **always yields to the cloud** on reconcile (namespaced, never wins a contested lease). |
| **Items** (status/title/description) | Concurrent edits to the same field. | **Per-field last-writer-wins**, but carry a "changed since last sync" flag on both sides (the `SyncState` precedent). When *both* sides changed the *same* field, don't silently LWW — **surface a conflict** for the human to resolve. |
| **PRDs** | Mutable but already **versioned** (`PrdVersion`). | Easiest: a conflict becomes a **new version**, not a lost edit. Fold the offline edit in as a version and let the author reconcile. |
| **Events** (append-only ledger) | Offline events must merge without rewriting history. | **Append-with-origin**; dedup by (actor, ts, action, target) + the existing idempotency keys. Never rewrite or renumber — the ledger only grows. |
| **Tenant/identity** | A local self-host runs with the org layer inert; `org_id`/memberships and local users/keys must map to hosted identities. | **Prerequisite for any item sync:** the link credential's org stamps `org_id` server-side (as the code-graph ingest already does, AL-137 D3); local identities resolve to hosted ones at the boundary. Sync must never become a tenant-isolation hole (AL-76/AL-95). |

## Phased path

1. **Read-only offline mirror (do first if offline is requested).** Cache the dev's slice
   (their assigned items + the code graph) locally for **reads** while disconnected; every
   *write* still requires connectivity and goes through the proxy. Needs **none** of the merge
   machinery above — no claim reconciliation, no item merge, no conflict UX. Highest value,
   lowest risk; covers "work on the plane, read what I have."
2. **Guarded read-write.** Allow a **bounded** set of offline mutations — status transitions and
   comments, *not* arbitrary edits or claims — with the per-entity model above: claims yield to
   cloud, items per-field LWW with conflict surfacing, PRDs as new versions, events appended.
   Reconcile on reconnect with a visible conflict list.
3. **Full bidirectional.** The general two-writer merge across all fields. Only if demand proves
   it out — the conflict UX and correctness cost is high and, given the proxy, the online case
   (the common one) doesn't need it.

## Recommendation

Ship nothing here yet. The **online hybrid (proxy) is the primary use case and it's done.**
When offline is actually asked for, build **phase 1 (read-only mirror)** — it's a caching layer,
not a sync algorithm. Treat phase 2 as opt-in and demand-driven; do **not** build guarded
read-write speculatively. If phase 2 lands, the model above is the contract.

## Deliberately out of the spike

- Implementation (this is a design note; the phased builds are separate items).
- A general CRDT/OT merge engine — overkill for a backlog tool; the per-entity rules above are
  simpler and match how humans actually reconcile a tracker.
- The code-graph direction — already solved one-way (AL-137/139), not part of the hard half.
