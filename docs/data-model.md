# Data model

SQLAlchemy models live in `backend/app/models/__init__.py`. The Postgres schema is owned by
Alembic; SQLite (tests / zero-infra dev) uses `create_all`.

## Entities

| Table | Key | Purpose |
| --- | --- | --- |
| `users` | `id` (`u1`, `u_…`) | Account: name, handle, email, avatar, initials, password hash |
| `projects` | `id` (`core`) | Project: name, accent, visibility, description, flags (`share_global_memory`, `auto_extract`, `mcp_enabled`, `embed_model`) |
| `memberships` | `id` | User ↔ project with `role` (owner/admin/member) + `access` (write/read/none) |
| `items` | `id` (`AL-12`) | Tracker item: title, description, `status`, tags, effort, `sort_order`, blocker, reporter, `pr` (JSON), date |
| `memory_shards` | `id` (`m1`, `m_…`) | Shard: text, `scope`, source, optional `item_id`, `embedding` (vector), `fresh` |
| `requests` | `id` (`R-31`) | Triage: type, title, by, votes, status, `linked_to` |
| `links` | `id` | Typed edge: `a`, `b`, `type` (dependency/code/semantic/tag), `confidence`, `reason` |
| `prds` | `id` (`PRD-1`) | PRD: title, status, version, body (markdown), `linked` (item ids), updated |
| `prd_versions` | `id` | Immutable snapshot: `prd_id`, version, date, note, body |
| `milestones` | `id` | Roadmap entry: `phase` (mvp/post/later), title, tag, `done`, `sort_order` |
| `mcp_tool_stats` | `tool` | Per-tool MCP call count |
| `platform_config` | `project_id` | Per-project LLM mode + provider config + GitHub/Drive connection state |
| `api_keys` | `id` | Scoped agent key: name, prefix, `hashed_key` (SHA-256), scopes, last used |

## Relationships

```
users ─< memberships >─ projects
projects ─< items, requests, links, prds, milestones, memory_shards, platform_config
items ─< memory_shards (item_id)          # item-scoped shards / lessons
items <─ requests (linked_to)             # a request linked to an item
items <─ prds.linked (id list, JSON)      # PRD ↔ items
prds  ─< prd_versions
users ─< api_keys
```

## Notes

- **Embeddings** — `memory_shards.embedding` is a real pgvector `vector(EMBED_DIM)` on
  Postgres (with an ivfflat cosine index) and JSON on SQLite, via a dialect-aware
  `EmbeddingType`. `EMBED_DIM` must match the [embedding provider](ai-providers.md).
- **Human ids** — items (`AL-<n>`), requests (`R-<n>`), and PRDs (`PRD-<n>`) use readable
  ids computed from the max existing number.
- **PRD versions** — the latest snapshot stores the full body; older seeded snapshots keep
  their note/date only. New snapshots (via the editor) always store the body.
- **Links** — `a`/`b` are plain id strings (items or requests), not foreign keys, so an edge
  can span either kind.

## Migrations

```
0001 initial      users, projects, memberships, items, memory_shards, requests, links, api_keys
                  (+ CREATE EXTENSION vector + ivfflat index)
0002 prds         prds, prd_versions
0003 roadmap_mcp  milestones, mcp_tool_stats
0004 platform     platform_config
```
