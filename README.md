# AgentLedger

**Agent memory. Linear execution.**

An agent-native dev tool: a skinny **linear tracker** + persistent **agent memory**
(pgvector semantic search) + feature/bug **request triage** + a **PRD editor**, with
native **MCP tools** so agents read and write project context through the *same code
path* as the web app.

**Local-Docker-first.** The whole product runs offline with `docker compose up` — no
API keys, no external services required. Cloud/local LLM providers and integrations are
opt-in. A hosted multi-tenant service is a later, additive layer.

> Built from the `AgentLedger.dc.html` design prototype. Design tokens (dark-only, lime
> `#c6f24e` / purple `#a78bfa`, IBM Plex) and the optional demo dataset mirror the prototype.
> **Full documentation is in [`docs/`](docs/README.md)** — product overview, per-feature
> guides, architecture, API reference, and the phase-by-phase implementation plan.
> Coding agents (and contributors) start at [`AGENTS.md`](AGENTS.md) — operating loop,
> invariants, and per-task-class checklists.

## What's built

| Area | Included |
| --- | --- |
| **Tracker** | Single linear stream · 6 states · drag-reorder · inline status · detail panel · quick filters |
| **Agent / Memory** | Memory shards, **semantic search** (pgvector), re-embed on edit, import/export, **auto-extraction** of lessons on `done`, **streaming** agent chat (SSE) |
| **Requests** | Triage queue · votes · link-to-item · **public embeddable feedback form** + **auto-duplicate detection** |
| **PRDs** | List + editor with **live markdown preview**, version history + **diff**, AI commands (expand / risks / summarize), item links |
| **Links** | Interactive force-directed graph of typed relationships (dependency / code / semantic / tag) |
| **Dashboard** | KPI tiles, status distribution, request breakdown, recent activity |
| **Roadmap** | MVP → Post-MVP → Later with progress; shareable read-only public link |
| **MCP Tools** | **11 live tools** with per-tool call metering, params, and descriptions |
| **Feedback Kit** | Themeable embeddable widget generator (accent / radius / types) with live preview + copy-paste snippet |
| **Settings / Profile** | AI provider switch, GitHub/Drive connection config, project config, members, API keys; profile + project access |
| **MCP** | `create_item` · `update_item` · `search_items` · `add_memory` · `search_memory` · `get_backlog` · `get_item_details` · `suggest_next` · `link_items` · `extract_lessons` · `generate_digest` |
| **Auth** | JWT login (users/roles/memberships) + scoped API keys for agents |
| **Integrations** | Inbound **GitHub issues webhook** → tracker items (live); GitHub/Drive connection config |

## Quick start (Docker — one command)

```bash
cp .env.example .env      # optional; defaults work with zero external services
docker compose up --build
```

- Web app → http://localhost:8080
- API → http://localhost:8000  (`/health`, OpenAPI at `/docs`)
- Public roadmap → http://localhost:8080/embed/roadmap
- Embeddable feedback widget → http://localhost:8080/embed/feedback

On first boot the API creates the pgvector extension and runs Alembic migrations; the database
starts **empty**. Open the web app, **Create an account**, then **Create your first project**.

To explore a populated app instead, set `SEED_ON_START=true` before the first `docker compose
up` — it loads a demo dataset (9 items, 5 requests, 5 memory shards, 3 PRDs with history, a
typed link graph, a roadmap, MCP call counts, and platform config; seeded users share the
password `agentledger`). See [Getting started](docs/getting-started.md).

## AI providers (F1)

Every AI capability sits behind a provider interface. The **default is a deterministic,
offline stub** so nothing external is needed. Switch the **chat / extraction** provider
live from **Settings → AI Providers**, or via env:

| | Chat / extraction | Embeddings |
| --- | --- | --- |
| **stub** (default) | deterministic, offline | deterministic hashed vector |
| **local** | Ollama (`llama3.1`) | Ollama (`nomic-embed-text`) |
| **cloud** | Anthropic Claude (`claude-opus-4-8`) | OpenAI-compatible `/v1/embeddings` |

`CHAT_PROVIDER` switches live (chat + auto-extraction + streaming). `EMBED_PROVIDER` is a
**deploy-time** setting — changing it changes the vector dimension, so set `EMBED_DIM` to
match (nomic-embed-text=768, OpenAI text-embedding-3-small=1536), reprovision the DB, then
`POST /api/memory/backfill`. See `.env.example`. The `anthropic` SDK is an optional
`cloud` pip extra (lazily imported); stub and Ollama need no extra dependency.

## Using the MCP tools

Issue a scoped API key (Settings → API Keys, or `POST /api/api-keys`), then call the MCP
endpoint over JSON-RPC 2.0:

```bash
curl -s http://localhost:8000/api/mcp \
  -H "X-API-Key: al_sk_..." -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"create_item","arguments":{"title":"From an agent","effort":2}}}'
```

`tools/list` returns all 11 tools; every call is metered and shows up on the **MCP Tools**
page. The created item appears immediately in the web Tracker — agents and the UI share
one service layer.

## Embeddable widgets & webhooks

- **Feedback widget** — `GET /embed/feedback?accent=…&radius=…&types=bug,feature` (public,
  themeable, live duplicate detection). Configure + copy the iframe snippet in **Feedback Kit**.
- **Public roadmap** — `GET /embed/roadmap` (read-only). "Copy public link" in the Roadmap view.
- **GitHub issues webhook** — `POST /api/public/github/webhook` turns opened issues into
  tracker items (rate-limited; real deployments add HMAC verification).

## Local development (without Docker)

**Backend**
```bash
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
export DATABASE_URL="sqlite:///./dev.db"     # zero-infra; create_all + seed on boot
# …or Postgres (runs Alembic migrations):
# export DATABASE_URL="postgresql+psycopg://agentledger:agentledger@localhost:5432/agentledger"
uvicorn app.main:app --reload
pytest            # 49 tests
```

**Frontend**
```bash
cd web
pnpm install
pnpm dev          # http://localhost:5173, proxies /api -> :8000
pnpm test         # vitest
pnpm typecheck
```

## Schema migrations

Postgres schema is owned by **Alembic** (`backend/alembic/`). Migrations run automatically
on API startup; SQLite (tests / zero-infra dev) uses `create_all`. Evolve the schema with:

```bash
cd backend && alembic revision --autogenerate -m "describe change" && alembic upgrade head
```

## Testing

- **Backend**: `cd backend && pytest` — 49 tests (auth, items/reorder, memory search,
  all 11 MCP tools + metering, requests + public feedback + dedup, PRDs + versions + AI,
  dashboard/roadmap/links, platform provider switch, GitHub webhook). Runs on SQLite, offline.
- **Frontend**: `cd web && pnpm test` — Vitest + Testing Library (tracker interactions,
  memory search, feedback dedup, markdown/diff).

## Layout

```
backend/   FastAPI app; services shared by REST + MCP; provider abstraction; Alembic; tests
web/       Vite + React 19 + TS SPA; Tailwind v4 tokens; TanStack Query; shadcn-style UI
docker-compose.yml   postgres(pgvector) + api + web
docs/      PRD · IMPLEMENTATION_PLAN.md · ARCHITECTURE.md
```

## License

[Functional Source License 1.1 (Apache 2.0 future license)](LICENSE.md) — see also
[Product overview → Licensing](docs/product-overview.md#licensing--business-model).

Free to use, modify, and self-host for personal, internal, and development purposes. You may
**not** make it available to others as a commercial product or service that competes with it
(reselling it or offering it as a hosted/SaaS service). Each released version automatically
converts to Apache-2.0 two years after its release.

© 2026 Ascme Labs.
