# Settings & profile

**Settings** (`/settings`, or the top-bar user menu) is a tabbed view; **Profile**
(`/profile`, from the user menu) shows the current user and their access.

## AI Providers tab

Switches the **chat & extraction** provider — takes effect immediately.

- Pick a mode: **Offline stub** (default, deterministic, no external services), **Local
  (Ollama)**, or **Cloud (Claude)**.
- Local mode exposes the Ollama base URL + chat model; cloud mode exposes the Claude model.
- **Save** persists to `platform_config` and reapplies to the live provider (the in-memory
  settings are updated and the provider cache is reset).

> The **embedding** provider is deliberately a **deploy-time** setting, not switchable here —
> changing it changes the pgvector column dimension. See [AI providers](ai-providers.md).

## Integrations tab

### GitHub

- **Connect** stores account + repo (and shows scope) **for this project**. **Disconnect** clears it.
- The tab shows the **inbound issues webhook** URL (`…/api/public/github/webhook`) with a
  copy button. Point a GitHub *Issues* webhook at it and **opened issues become tracker
  items** (rate-limited; real deployments add HMAC signature verification).
- **Repo → project routing:** the webhook reads the payload's `repository.full_name` and
  creates the item **in the project that has that repo connected** (falling back to the
  default project). Each created item is **linked back** to the originating issue via
  `github_url`, shown as a GitHub chip on the tracker row.
- **Note:** connection state and the inbound webhook are fully wired. **Outbound** sync
  (opening real GitHub issues, two-way PR sync) requires a connected token/OAuth and is out
  of scope for the local slice — `POST /api/platform/github/create-issue` creates the local
  item and reports `pushed_to_github: false`.

### Google Drive

A connect form (account + folder) that stores connection config. **Live import/sync is not
wired in the local slice** (no third-party OAuth); the layout below is the **intended design**
for when sync ships.

**Folder structure.** The connection is per-project, so the folder you pick *is* that project's
root. AgentLedger organizes it into typed subfolders (created on first sync):

```
<connected folder>/
├── PRDs/          Each PRD mirrored as "AL-PRD-1 — Title.md" (front-matter carries id/status/version)
├── Digests/       Generated progress digests, dated: "2026-07-21 — digest.md"
├── Exports/       Data snapshots — memory shards & items as JSON
└── Attachments/   Feedback screenshots, by request id
```

Only these known subfolders are managed; anything else in the root is left untouched.

**Manually-added files.** The design is a two-way, folder-as-source-of-truth sync:

- Drop a `.md` file into **`PRDs/`** → it's imported as a new **draft PRD** on the next sync,
  taking its title from the first `# heading` (or the file name). This is the same import path
  the [PRD page](prds.md) exposes via **Import a .md file** — Drive just automates it.
- Editing a file that mirrors an existing PRD updates that PRD and snapshots a new version;
  a conflicting edit on both sides is flagged rather than silently overwritten (last-writer
  never clobbers).
- Files placed **outside** the known subfolders (or with unrecognized extensions) are ignored,
  so the folder is safe to use for your own notes.
- Deleting a mirrored file does **not** delete the PRD (archival is explicit) — it just detaches
  the mirror.

Until sync ships, use **PRDs → Import a .md file** to bring markdown in directly.

## Project tab

Edit the active project's **name**, **description**, and flags:

- **Share global memory across projects**
- **Auto-extract lessons on item completion** (drives [auto-extraction](memory-and-chat.md#auto-extraction-on-done))
- **Expose MCP tools for this project**

Saved via `PATCH /api/projects/{id}`.

## Members tab

Lists the project's members with their **role** (owner/admin/member) and **access**
(write/read/none), from the `memberships` table.

## API Keys tab

Manage scoped keys used to authenticate agents to the [MCP endpoint](mcp.md):

- **Create** a key — the plaintext (`al_sk_…`) is shown **once**; copy it immediately. Only a
  SHA-256 hash is stored.
- **Revoke** a key with the trash icon.

## Profile (`/profile`)

Your account card (name, handle, email, avatar) and **project access** — each project you
belong to with your role and access level. Reachable from the top-bar user menu.

## How it works

- Config: the `platform_config` table (Alembic migration `0004`), one row per project.
- Service: `backend/app/services/platform.py` — `get_config`, `update_config` (applies LLM
  settings to the live provider), and the GitHub/Drive connect/disconnect helpers.
- Routers: `backend/app/routers/platform.py`, plus project/member routes in
  `projects.py` and `GET /api/auth/me/memberships`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET / PATCH | `/api/platform` | Read / update platform + provider config |
| POST | `/api/platform/github/connect` · `/disconnect` | GitHub connection state |
| POST | `/api/platform/github/create-issue` | Mirror an item as an issue (local; honest stub) |
| POST | `/api/platform/gdrive/connect` · `/disconnect` | Drive connection state |
| PATCH | `/api/projects/{id}` | Update project config |
| GET | `/api/projects/{id}/members` | List members |
| GET / POST / DELETE | `/api/api-keys` … | Manage API keys |
| GET | `/api/auth/me/memberships` | The current user's project access (Profile) |
