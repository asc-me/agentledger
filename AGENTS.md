# AgentLedger — agent guide

AgentLedger is an agent-native dev tool: linear tracker + pgvector agent memory +
request triage + a code-structure graph, all operable by coding agents through
27 MCP tools (`POST /api/mcp`, JSON-RPC) that share one service layer with the
REST API and web UI. Local-Docker-first; stays fully offline by default (stub
embeddings/chat — real providers are opt-in env config).

This file is a map, not a manual. Deeper truth lives in [`docs/`](docs/README.md);
read the route for your task class, not the whole corpus.

## Operating loop

Every change, regardless of task class:

```bash
# Backend (from backend/; venv via `uv venv --python 3.12 .venv && uv pip install -e ".[dev]"`)
./.venv/bin/python -m pytest -q          # SQLite, ~45s. pytest is NOT on the host PATH.

# Backend against real Postgres+pgvector (what production runs — CI runs both):
docker run -d --name al-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=agentledger_test -p 5544:5432 pgvector/pgvector:pg16
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5544/agentledger_test" \
  ./.venv/bin/python -m pytest -q        # also proves the Alembic chain from empty

# Frontend (from web/):
pnpm test && pnpm typecheck              # build with `pnpm build`

# Full stack:
docker compose up --build                # web :8080, api :8000; starts EMPTY by design
```

CI (`.github/workflows/ci.yml`) runs all three on every PR. A change is not done
until both database engines pass — SQLite and Postgres have separate vector-search
implementations (`services/memory.py`, `services/code_graph.py`) and only the
Postgres run executes the real `<=>` SQL and migrations.

## Invariants (violating these is the review comment you'll get)

- **One service layer.** MCP tools, REST routers, and anything new call the same
  functions in `backend/app/services/`. Never duplicate domain logic in a router
  or tool handler.
- **Schema is owned by Alembic** on Postgres (`backend/alembic/versions/`,
  currently 0001–0016). SQLite/tests use `create_all`. Never edit an applied
  migration; add a new one.
- **AI providers only via `backend/app/providers/`** (`Embedder`/`ChatModel`/
  `Extractor` protocols, selected by `EMBED_PROVIDER`/`CHAT_PROVIDER`). Offline
  stub is the default; cloud deps stay lazy imports behind the `cloud` extra.
- **Frontend data access only via `web/src/lib/api.ts` + `queries.ts`**
  (TanStack Query). Query keys include the active project id.
- **Enums live in services** (`services/items.py:STATUSES`, `requests.py`,
  `links.py`, `code_graph.py`) — reference them; don't inline copies.

## Task classes

### Add or change an MCP tool
1. Tool entry in `backend/app/mcp_server.py` `TOOLS` (description states purpose,
   invariants, and return shape — match `claim_next`/`describe_code` style) +
   handler branch in `_call_tool` calling a service function.
2. **Every tool needs an `outputSchema`** (asserted by `test_api.py`).
3. Update the count assertions: `tests/test_api.py` (`len(names)`, `tool_count`
   ×2) and `tests/test_phase4.py` (`data["live"]`, `len(data["tools"])`).
4. Update the tool table in `docs/mcp.md`.
5. MCP round-trip test: POST a JSON-RPC `tools/call` envelope with an `X-API-Key`
   (see `test_api.py` for the pattern).

### Add a schema change (Postgres)
1. Edit models in `backend/app/models/__init__.py`.
2. `cd backend && ./.venv/bin/alembic revision --autogenerate -m "..."` — then
   **review the generated file**; the custom `EmbeddingType`/pgvector columns and
   raw-SQL indexes need hand-checking (autogen gets them wrong).
3. Verify the chain from empty: run the Postgres pytest command above (lifespan
   migrates on startup).
4. Vector indexes are **HNSW**, not ivfflat (migration 0016) — ivfflat built on
   empty tables silently loses recall.

### Add a view / frontend feature
Route in `web/src/App.tsx`, feature dir under `web/src/features/`, API methods in
`lib/api.ts` + hooks in `lib/queries.ts` (key on project id). Tests rendering a
view that touches `useProjectCtx` must wrap in `<ProjectProvider>` and mock
`api.projects`. Docs overlay: register the route in `features/docs/content.ts`.

### Work on providers / embeddings
`docs/ai-providers.md`. Changing `EMBED_DIM` requires DB reprovision AND note
that migrations 0001/0013 pin 384 in the column type — see AL-46.

## Routes into docs/

| Task | Read |
| --- | --- |
| Any first contact | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/data-model.md`](docs/data-model.md) |
| MCP tools | [`docs/mcp.md`](docs/mcp.md) |
| REST surface | [`docs/api-reference.md`](docs/api-reference.md) |
| Dev workflows | [`docs/development.md`](docs/development.md) |
| Providers/AI | [`docs/ai-providers.md`](docs/ai-providers.md) |
| Config/env | [`docs/configuration.md`](docs/configuration.md) |

## Deploy

Full runbook: **[`docs/deploy.md`](docs/deploy.md)** — the proven `rsync` +
`docker compose` self-host deploy, with verification, recovery, and rollback.
The essentials: stamp `GIT_SHA=$(git rev-parse --short HEAD)` and pass it through
to `docker compose up -d --build`; **always `rsync --exclude .env --exclude sync`**
(the server keeps its own `.env` with remapped ports, and `sync/` is a root-owned
mount); verify the exact revision went live via `/health` (`git_sha` + `db`).

## Tracker

This repo tracks its own work in AgentLedger (project `agentledger`). Current
priorities and the 2026-07 harness-review findings are items AL-40…AL-57 —
`get_backlog` / the Tracker view are the source of truth.
