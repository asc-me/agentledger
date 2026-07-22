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

## The 18 tools

| Tool | Params | Does |
| --- | --- | --- |
| `get_context` | — | Orient: the key's project, scopes, project/tool counts. Call this first. |
| `list_projects` | — | All projects (`id`, `name`, `accent`, `description`) — ids for the `project_id` override |
| `next_cluster` | `agent_id`, `max_items`, `project_id` | **Claim a code-neighborhood at once** — the best ready item plus its related ready items, all assigned to you. |
| `related_work` | `id` | Items related to a task by shared touchpoints + typed links, best-first (read-only) |
| `claim_next` | `agent_id`, `lease_seconds`, `project_id` | **Atomically** claim the best ready item, assign it to you, move it to in_progress. Returns `{claimed, item}`. |
| `heartbeat` | `id`, `agent_id` | Extend the lease on an item you hold (so it isn't reclaimed while you work) |
| `release_item` | `id`, `agent_id`, `to_status` | Return a claimed item to the queue |
| `create_item` | `title`, `description`, `tags`, `touchpoints`, `effort`, `status`, `project_id` | Create a tracker item (returns its `project_id`) |
| `update_item` | `id`, `status`, `title`, `description`, `tags`, `touchpoints`, `effort`, `blocker`, `assignee`, `github_url` | Patch / advance an item |
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

### Dependency-aware prioritization

Readiness comes from the **dependency graph**, not just the free-text `blocker`: create a
`dependency` link (`link_items(a, b, type="dependency")` — *a depends on b*) and `a` stays
**blocked until `b` is done**. `claim_next` / `next_cluster` / `suggest_next` never hand out a
blocked item, and `get_backlog` ranks **ready-first**, then by a composite score — status,
**dependency fan-out** (items that unblock many rank higher), **request votes** rolled onto the
linked item, effort, and staleness. Each `get_backlog` row carries `ready`, `blocked_by`,
`unblocks`, `votes`, and `score`, so an agent can plan against the real graph.

### Code-locality clustering (pick up related work at once)

Give items **touchpoints** — the files/globs/modules they affect (`backend/app/routers/*`,
`web/src/lib/api.ts`, a symbol name) — on `create_item`/`update_item`. Two items relate when
their touchpoints overlap (exact, glob, or same directory), and sharing a touchpoint
**auto-creates a `code` link** between them. Then:

- `related_work(id)` shows the code-neighborhood around a task (shared touchpoints + link types),
  best-first — read-only.
- `next_cluster(agent_id, max_items)` **claims the whole neighborhood in one call**: the best ready
  item plus its related ready items, all assigned to you. This is how an agent pulls several
  pieces of related work simultaneously instead of context-switching.

### Task claiming (safe multi-agent loops)

Run an agent as a loop: `claim_next` **atomically** assigns the best ready item (unblocked
`backlog`/`next`, best-first) to you and flips it to `in_progress` — an optimistic
`claimed_by` guard means **two agents never claim the same item**. `agent_id` defaults to the
API key's name, so one key = one agent. While working, call `heartbeat(id)` to keep the lease;
if you go silent past `lease_seconds` (default 600) the item becomes reclaimable, so a crashed
agent's work is automatically freed and picked up by another. `release_item(id)` hands it back.
Completing is just `update_item(id, status="done")` (which also auto-extracts lessons to memory).

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
