# PRD-14 acceptance walk

The zero-browser install, run for real rather than asserted in unit tests (AL-286).
Re-run this after changing `start.sh`, `bootstrap.py`, or either gate.

Run it in an **isolated compose project** so it never attaches to a real instance's
volume — the compose project name is pinned to `agentledger`, and a machine that has
done local development already has `agentledger_agentledger_pgdata` with data in it.

```bash
COMPOSE="docker compose -p gb-acceptance" \
  DB_PORT=5455 API_PORT=8011 WEB_PORT=8091 \
  PROJECT_NAME="Acceptance Repo" ./start.sh
```

## What must happen

| # | Step | Expected |
| --- | --- | --- |
| 1 | `./start.sh` on a virgin instance | stack up, operator + project + key provisioned, MCP config printed |
| 2 | `get_context` with the printed key | resolves the project, `empty: true` |
| 3 | `describe_code` then `search_code` | nodes upserted; the matching path ranks first |
| 4 | `add_memory` then `search_memory` | **published**, and the write comes back — no `include_candidates`, no human |
| 5 | `create_item` then `update_item` → done | key renders under the derived tag (`AR-1`) |
| 6 | `setup_project` | `complete: true` |
| 7 | re-run `./start.sh` | provisions nothing, re-prints config |
| 8 | `HOSTED_MODE=true graphban init` | refuses, names the reason |
| 9 | `SEED_ON_START=true graphband init` | refuses, names the reason |
| 10 | `create_project` while unlinked | allowed |
| 11 | `graphban link …` then `create_project` | refused — "linked to a cloud org" |
| 12 | open the web UI | trusted publishes labelled `no review`, undoable |

Tear down without touching anything real:

```bash
docker compose -p gb-acceptance down -v
```

## Two defects this walk found

Both are the kind only a real run surfaces: each component was correct in isolation and
the composition was not.

**`start.sh` wrote the MCP credential into `~/.graphban/config.json`** — the file
`graphban link` owns, which stores the **cloud sync** credential under the same `api_key`
name. On a machine that had linked, this both destroyed the link and left `graphban sync`
pushing with the wrong credential. It now writes `~/.graphban/mcp.json`.

**A bootstrapped project could not read back its own memory.** D1 made `review` the
default (right for an existing project) and D3 created a project (right on its own), but
together they meant the zero-browser install stopped at the first memory the agent wrote:
it landed as a candidate, `search_memory` returned nothing, and there was no human to
publish it. Projects created by this script now start in `trusted` mode — an explicit
request for an agent-driven instance, on a brand-new project with no corpus to poison,
with every publish labelled and undoable. Existing projects are untouched.
