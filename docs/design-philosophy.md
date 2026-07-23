# Design philosophy

AgentLedger is a tool that agents operate unattended. That single fact sets a
higher bar than a normal web app: when the primary user is a coding agent, the
*environment around it* — the tools, the errors, the guarantees — is the product.
A confusing error message isn't a rough edge; it's the app failing at its one job.

These are the principles the codebase is built to, distilled from the practice of
**harness engineering** — shaping the environment so a capable worker can recover
intent, operate the real system, respect authority, and prove the outcome. They
are not aspirations; each one is enforced by code and tests you can point at.

## 1. One source of truth, and the repo enforces it

Every capability has exactly one owner, and duplication is a bug we make
mechanically impossible rather than police by hand.

- **One service layer.** MCP tools, REST routers, and the web UI all call the same
  functions in `app/services/`. An agent's `create_item` and a human's click run
  identical code — there is one path to the database, so writes never need
  reconciliation. Adapters stay thin; domain logic lives in one place.
- **One owner per fact.** Item statuses, request types, and link relations are
  defined once in the service layer and *referenced* everywhere else (the MCP
  schema, the docs). When the same fact drifted across the tree (a tool count that
  read 5 / 11 / 26 / 27 in four places), we didn't just fix the copies — we added
  `test_docs_sync.py`, a ratchet that fails CI the moment docs and code disagree
  again. A weak pattern left in the tree becomes prompt material for the next
  agent, so the durable fix is a check, not a cleanup.

## 2. Capability and authority are separate contracts

An agent should act broadly in reversible spaces and be gated only where an action
is consequential — and that gate must be *enforced*, not merely displayed.

- **Scoped keys are real.** An API key is bounded by its declared scopes
  (read/write) **and** its owner's project memberships; it can never out-rank the
  human who minted it. A project-scoped key cannot reach another project's data,
  even by passing a different `project_id`. This is checked in one owner
  (`security/authz.py`) at every boundary, and the tests are *refusal* tests —
  they assert the wrong key is turned away, not just that the right one succeeds.
- **Every mutation is on the record.** The audit ledger (`events`) captures one row
  per accepted change — who (which key or user), what, when — written at the
  MCP and REST boundaries. Authority you can't audit is only half a contract; the
  Activity view makes "what did my agents do" answerable at a glance.

## 3. Tools are context; every result teaches the next step

An agent decides what to do next from what a tool hands back. So a tool result is
designed as context, and a failure is designed as a repair instruction.

- **Validate before dispatch.** Arguments are checked against each tool's declared
  schema before anything runs, so a bad call is an actionable `validation` error
  naming the missing field — never a stack trace or a silently-accepted junk value.
- **A typed error taxonomy with hints.** Failures carry a stable machine code
  (`not_found`, `validation`, `conflict`, `unauthorized`, `internal`) and, wherever
  possible, a `hint` naming the fix — "use search_items to find a valid id",
  "another agent holds the lease". An agent can branch on the code and know whether
  a retry could ever help, instead of parsing prose.
- **Receipts, not just acks.** Mutations echo the resulting state; `describe_code`
  returns the paths it touched so an agent can verify the effect without a second
  round-trip.

## 4. Prove the outcome in the real environment

A green check only proves its own assertion. We match the proof to the claim.

- **Two engines, always.** Production runs Postgres + pgvector; tests run fast on
  SQLite. But the vector-search path and the full Alembic migration chain only
  exist on Postgres, so CI runs the suite on **both** engines on every PR. This
  isn't ceremony: the Postgres job has caught real production defects a
  SQLite-only suite waved through — a vector index that silently dropped search
  results, and a test that passed only because of its ambient database.
- **The worker can operate the real system.** Anyone (human or agent) can boot the
  whole stack with one `docker compose up` and watch an agent's write appear live
  in the UI — the loop is observable end to end, not mocked.

## 5. The repository teaches the agent

The cheapest way to make the next run better is to put what a worker needs where
it will look for it.

- **A map, not a manual.** [`AGENTS.md`](../AGENTS.md) routes an agent to the
  operating loop, the invariants, and a per-task checklist (add-a-tool,
  add-a-migration, add-a-view) — small and navigable, with the deep detail one
  link away in these guides.
- **Lessons become infrastructure.** A correction that recurs shouldn't live in
  one chat. Completing an item auto-extracts its lessons into pgvector memory so a
  later agent recalls the decision instead of relearning it; a stable rule becomes
  a type, a check, or a routing doc — the earliest owner that can shape future work.

## Why this matters

Each principle makes the next change safer, and the effects compound: the
two-engine CI gated the authority work; operating the platform surfaced the
evidence that prioritized the error taxonomy; the audit ledger now watches all of
it. The goal is a system where a capable agent can do a whole job — and prove it —
with a person supplying direction and judgment, not acting as a relay.

See [Architecture](ARCHITECTURE.md) for how the pieces fit, and
[MCP tools](mcp.md) for the agent-facing surface these principles shape.
