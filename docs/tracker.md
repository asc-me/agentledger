# Tracker

The Tracker is the heart of AgentLedger: **one linear stream** of work items ordered by
priority and recency — no boards, no columns. It's the landing view.

## Item model

Each item has:

| Field | Notes |
| --- | --- |
| `id` | Human key, e.g. `AL-12` (auto-assigned `AL-<n>`) |
| `title`, `description` | Description is markdown |
| `status` | One of six states (below) |
| `tags` | Free-form list |
| `effort` | Points (integer) |
| `sort_order` | Drag-reorder position |
| `blocker` | Free text; shown as a red banner when set |
| `reporter` | Name / handle / avatar |
| `pr` | Optional PR metadata (number, branch, state, additions/deletions, checks) |
| `date` | Display date |

### States

`backlog` → `next` → `in_progress` → `review` → `done`, plus `blocked`. Each has a fixed
color used consistently across the app:

| State | Color |
| --- | --- |
| Backlog | `#8b949e` |
| Next | `#7ca2ff` |
| In Progress | `#c6f24e` |
| Review | `#e0b34a` |
| Done | `#5fd07a` |
| Blocked | `#ff6b6b` |

## Using it

- **Advance status** — click the status dot on a row (or in the detail panel) and pick a new
  state. Moving an item to **Done** triggers [auto-extraction](memory-and-chat.md#auto-extraction-on-done).
- **Reorder** — drag a row; the new order persists (`sort_order`).
- **Filter** — the quick-filter chips (All / per-state) narrow the stream; the top-bar search
  filters by title or id.
- **Detail panel** — click a row to slide in the detail: description, blocker, tags/effort,
  PR card, and **linked memory shards** (shards whose `item_id` matches).
- **New item** — the "New item" button opens a dialog (title, description, tags, effort);
  it drops into the backlog at the top of the stream.

## How it works

- Service: `backend/app/services/items.py` — `list_items`, `create_item`, `update_item`,
  `reorder_items`, `search_items`, `get_backlog`, `get_item_details`, `suggest_next`, and
  `_auto_extract_lessons` (fires on the transition to `done`).
- This service is shared by the REST routes **and** the MCP tools, so an agent's
  `create_item`/`update_item` is identical to the UI's.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/items` | List (optional `?status=` / `?project_id=`) |
| POST | `/api/items` | Create |
| PATCH | `/api/items/reorder` | Persist a new drag order (`{ordered_ids: [...]}`) |
| GET | `/api/items/{id}` | Fetch one |
| PATCH | `/api/items/{id}` | Update fields / advance status |

Front-end mutations use optimistic updates (TanStack Query) so status changes and drags feel
instant.

## Related

- Agents drive items through MCP: `create_item`, `update_item`, `search_items`,
  `get_backlog`, `get_item_details`, `suggest_next` — see [MCP tools](mcp.md).
- Completing an item can mint a memory shard — see [Memory & chat](memory-and-chat.md).
- Items can be linked to PRDs and to each other (typed links) — see [PRDs](prds.md) and
  [Links graph](links-graph.md).
