# MCP tools

AgentLedger exposes a **Model Context Protocol** surface so agents can read and write project
context. The key property: **MCP tools call the same service layer as the web app**, so an
agent's writes are identical to a user's and appear instantly in the UI.

## Endpoint & protocol

- **`POST /api/mcp`** — JSON-RPC 2.0 over HTTP. Handles `initialize`, `tools/list`,
  `tools/call`, and the `notifications/initialized` notification. Single JSON responses (no
  SSE) keep it `curl`-friendly while remaining MCP Streamable-HTTP compatible for simple
  calls.
- **Auth** — a scoped **API key** via `X-API-Key: al_sk_…` or `Authorization: Bearer
  al_sk_…`. Create one in [Settings → API Keys](settings.md#api-keys-tab). Unauthenticated
  calls return `401`.
- **Project scope** — each key targets one **project** by default (the active project when
  you create it), so an agent's writes land in the right workspace. Tick *global* at creation
  to leave it unscoped. Any project-scoped tool call (`create_item`, `add_memory`,
  `search_items`, `search_memory`, `get_backlog`, `suggest_next`, `generate_digest`) also
  accepts an optional `project_id` argument that overrides the key's project for that call.
- **Metering** — every `tools/call` increments a per-tool counter (the `mcp_tool_stats`
  table) surfaced on the **MCP Tools** view.

## The 13 tools

| Tool | Params | Does |
| --- | --- | --- |
| `get_context` | — | Orient: the key's project, scopes, project/tool counts. Call this first. |
| `list_projects` | — | All projects (`id`, `name`, `accent`, `description`) — ids for the `project_id` override |
| `create_item` | `title`, `description`, `tags`, `effort`, `status`, `project_id` | Create a tracker item (returns its `project_id`) |
| `update_item` | `id`, `status`, `title`, `description`, `tags`, `effort`, `blocker` | Patch / advance an item |
| `search_items` | `query`, `tags`, `status`, `project_id` | Query the stream (query matches title, description, **and** tags) |
| `add_memory` | `text`, `scope`, `item_id`, `project_id` | Attach a memory shard |
| `search_memory` | `query`, `top_k`, `project_id` | Semantic search over shards (returns `item_id`, `source`) |
| `get_backlog` | `limit`, `project_id` | Prioritized backlog |
| `get_item_details` | `id` | Item + linked shards + linked requests |
| `suggest_next` | `project_id` | Best next item from state + memory |
| `link_items` | `a`, `b`, `type`, `reason` | Create a typed relationship |
| `extract_lessons` | `id` | Distill lessons from an item into memory |
| `generate_digest` | `project_id` | Compose a progress digest across the project |

`status` fields accept only `backlog · next · in_progress · review · done · blocked` (enforced in
the schema). Tool failures return `isError: true` with a machine-readable
`structuredContent.error.code` (`invalid_request` or `internal_error`) — never a raw HTTP 500.

### Built for agents

- **Typed results** — every tool returns `structuredContent` (a JSON object) alongside the
  text block, so you consume typed data instead of parsing JSON out of prose. List/search
  tools wrap their rows under `results`.
- **Annotations** — each tool carries `readOnlyHint` / `destructiveHint` / `idempotentHint`,
  so you can tell a safe read from a mutation.
- **Idempotent creates** — pass an `idempotency_key` to `create_item` / `add_memory` /
  `link_items`; a retried call with the same key returns the original resource, never a
  duplicate.
- **Pagination** — `search_items` and `get_backlog` take `limit` + `offset` and return
  `{results, total, limit, offset, has_more}`; `search_memory` returns `{results, returned,
  top_k}`.

## MCP Tools view

The **MCP Tools** view (`/mcp-tools`) is a live card grid of all tools: name, `LIVE` status,
**call count**, description, and params. The header shows `N tools live · total calls`,
matching the "MCP · 11 TOOLS LIVE" chip in the top bar. Data comes from
`GET /api/mcp/tools`.

## Examples

`tools/list`:

```bash
curl -s http://localhost:8000/api/mcp -H "X-API-Key: al_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`tools/call` — create an item (appears immediately in the Tracker):

```bash
curl -s http://localhost:8000/api/mcp -H "X-API-Key: al_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"create_item","arguments":{"title":"From an agent","effort":2}}}'
```

`search_memory` returns compact JSON the agent can chain:

```bash
… -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"search_memory","arguments":{"query":"pgvector self-host","top_k":3}}}'
```

Tool results come back as MCP `content` blocks (`{"content":[{"type":"text","text":"…"}]}`);
the text is JSON for structured tools. Tool errors return `isError: true` rather than a
JSON-RPC error.

## How it works

- `backend/app/mcp_server.py` — the endpoint, the `TOOLS` schema list, and `_call_tool`
  dispatch into `services/*`. `GET /api/mcp/tools` (in `routers/analytics.py`) exposes the
  schemas + live call counts.
- The same `services/items.py`, `services/memory.py`, `services/links.py`,
  `services/insights.py` power both MCP and the REST routes.

## Related

- [AI providers](ai-providers.md) — `search_memory`, `extract_lessons`, and `generate_digest`
  use the embedding/extraction providers.
- [Settings → API Keys](settings.md#api-keys-tab) — issuing agent credentials.
