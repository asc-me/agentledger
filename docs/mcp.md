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
- **Metering** — every `tools/call` increments a per-tool counter (the `mcp_tool_stats`
  table) surfaced on the **MCP Tools** view.

## The 11 tools

| Tool | Params | Does |
| --- | --- | --- |
| `create_item` | `title`, `description`, `tags`, `effort`, `status` | Create a tracker item |
| `update_item` | `id`, `status`, `title`, `description`, `blocker` | Patch / advance an item |
| `search_items` | `query`, `status` | Query the linear stream |
| `add_memory` | `text`, `scope`, `item_id` | Attach a memory shard |
| `search_memory` | `query`, `top_k` | Semantic search over shards |
| `get_backlog` | `limit` | Prioritized backlog |
| `get_item_details` | `id` | Item + linked shards + linked requests |
| `suggest_next` | — | Best next item from state + memory |
| `link_items` | `a`, `b`, `type`, `reason` | Create a typed relationship |
| `extract_lessons` | `id` | Distill lessons from an item into memory |
| `generate_digest` | — | Compose a progress digest across the project |

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
