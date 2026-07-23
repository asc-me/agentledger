# API reference

All endpoints are under `/api` (proxied by the web tier and served directly by the API).
Interactive OpenAPI docs are at **`/docs`**.

**Auth legend:** **JWT** = `Authorization: Bearer <access-jwt>` · **MCP** = API key via
`X-API-Key` / `Authorization: Bearer al_sk_…` · **public** = no auth (rate-limited).

## Health

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/health` | none |

## Auth

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | none | Email + password → access + refresh tokens |
| POST | `/api/auth/register` | none | Create a user → tokens |
| POST | `/api/auth/refresh` | none | Refresh token → new tokens |
| GET | `/api/auth/me` | JWT | Current user |
| GET | `/api/auth/me/memberships` | JWT | Current user's project access |

## Projects

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/projects` | JWT | List projects |
| PATCH | `/api/projects/{id}` | JWT | Update project config |
| GET | `/api/projects/{id}/members` | JWT | List members (role/access) |

## Items (tracker)

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/items` (`?status=`, `?project_id=`) | JWT |
| POST | `/api/items` | JWT |
| PATCH | `/api/items/reorder` | JWT |
| GET | `/api/items/{id}` | JWT |
| PATCH | `/api/items/{id}` | JWT |

## Requests

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/requests` (`?type=`) | JWT |
| POST | `/api/requests` | JWT |
| POST | `/api/requests/{id}/vote` | JWT |
| POST | `/api/requests/{id}/link` | JWT |

## Memory & agent chat

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/memory/shards` | JWT |
| POST | `/api/memory/shards` | JWT |
| PATCH | `/api/memory/shards/{id}` | JWT |
| POST | `/api/memory/search` | JWT |
| POST | `/api/memory/backfill` | JWT |
| GET | `/api/memory/export` | JWT |
| POST | `/api/memory/import` | JWT |
| POST | `/api/agent/chat` | JWT |
| POST | `/api/agent/chat/stream` | JWT (SSE) |
| POST | `/api/agent/code` | JWT |
| POST | `/api/agent/code/stream` | JWT (SSE) |
| GET | `/api/agent/code/map` | JWT |
| GET | `/api/agent/code/neighbors` | JWT |
| GET | `/api/agent/code/for` | JWT — code linked to an item/request (work→code) |
| POST | `/api/agent/code/link` | JWT — link an item/request to a code path |
| POST | `/api/agent/code/unlink` | JWT |

`/api/agent/code` is the code-graph consumer: it grounds the configured ChatModel in the
code structure the coding agent described via MCP (`search_code` + `code_neighbors`), so the
connected LLM can answer "what depends on X" from real edges — never from a checkout it
doesn't have. Returns `{reply, nodes:[{node, score}]}`; the `/stream` variant emits a `nodes`
SSE event, then `delta`s, then `done`. Body is `{message, project_id?}`.

## PRDs

| Method | Path | Auth |
| --- | --- | --- |
| GET / POST | `/api/prds` | JWT |
| GET / PATCH | `/api/prds/{id}` | JWT |
| GET / POST | `/api/prds/{id}/versions` | JWT |
| POST | `/api/prds/{id}/link` | JWT |
| POST | `/api/prds/{id}/ai` | JWT |

## Analytics

| Method | Path | Auth | Returns |
| --- | --- | --- | --- |
| GET | `/api/dashboard` | JWT | Aggregated project health |
| GET | `/api/roadmap` | JWT | Phases + milestones + progress |
| GET | `/api/links` | JWT | Typed links |
| GET | `/api/mcp/tools` | JWT | Tool schemas + live call counts |

## Platform & integrations

| Method | Path | Auth |
| --- | --- | --- |
| GET / PATCH | `/api/platform` | JWT |
| POST | `/api/platform/github/connect` · `/disconnect` · `/create-issue` | JWT |
| POST | `/api/platform/gdrive/connect` · `/disconnect` | JWT |

## API keys

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/api-keys` | JWT |
| POST | `/api/api-keys` | JWT (plaintext returned once) |
| DELETE | `/api/api-keys/{id}` | JWT |

## Reports (upstream feedback)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/reports/upstream` | JWT | Whether upstream reporting is on + where reports go |
| POST | `/api/reports/upstream` | JWT | Forward a user-initiated AgentLedger issue report upstream |

## MCP

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/mcp` | MCP | JSON-RPC 2.0 — `initialize` / `tools/list` / `tools/call` |

See [MCP tools](mcp.md) for the tool catalog.

## Public (unauthenticated)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/public/requests` | Submit feedback + return duplicates |
| GET | `/api/public/duplicates` | Live duplicate check (`?q=&project_id=`) |
| GET | `/api/public/roadmap` | Read-only roadmap (for the share link) |
| POST | `/api/public/github/webhook` | Inbound GitHub issue → tracker item |

All public endpoints share a per-IP sliding-window rate limit (20/60s).
