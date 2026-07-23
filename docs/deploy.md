# Deploy runbook

How to deploy AgentLedger to the self-hosted LAN box, verify the exact revision
went live, and recover when a deploy goes wrong. This is the proven path — every
step here has been run in anger.

> The hosted (Railway) path is separate and tracked under the `railway` items;
> this runbook covers the current `rsync` + `docker compose` self-host deploy.

## What runs where

- **Target:** `ubuntu-srv` (LAN `192.168.50.81`), remapped ports because the box
  already runs another Postgres and had `:8000` busy — the **server's** `.env`
  sets `DB_PORT=5433`, `API_PORT=8001`, `WEB_PORT=8080`
  (`CORS_ORIGINS=http://192.168.50.81:8080,...`, stub providers).
- **Services:** `docker compose` — `db` (pgvector), `api`, `web` (nginx SPA).
- **Schema:** Alembic migrations run automatically on API startup (Postgres); the
  container comes up, migrates `0001 → head`, then serves.

## Deploy

From a clean working tree on the revision you want to ship:

```bash
# 1. Stamp the build with the git revision so /health can report it.
export GIT_SHA=$(git rev-parse --short HEAD)

# 2. Sync the tree to the server. ALWAYS exclude .env and sync (see invariants).
rsync -az --delete \
  --exclude .git --exclude .env --exclude sync \
  --exclude node_modules --exclude dist --exclude __pycache__ \
  --exclude .venv --exclude .serena \
  ./ ubuntu-srv:~/agentledger/

# 3. Build + restart on the server, passing the revision through to the images.
ssh ubuntu-srv "cd ~/agentledger && GIT_SHA=$GIT_SHA docker compose up -d --build"
```

Migrations apply on API startup, so a schema change ships with the same command.

## Invariants (violating these has broken a deploy)

- **`--exclude .env`** — there is no local `.env`, so a bare `rsync --delete`
  would DELETE the server's `.env`. Then compose reverts to default ports (5432
  conflicts with the box's other Postgres) **and** the persisted Postgres volume
  keeps the *old* password, so the API dies at startup with
  `password authentication failed for user "agentledger"` (exit 3; Python's
  block-buffered stdout hides the traceback). Never sync over the server `.env`.
- **`--exclude sync`** — the server's `~/agentledger/sync/` is a root-owned
  container-written mount; rsync fails `exit 23` (`mkdir ... Permission denied`)
  without this exclude.
- **Pass `GIT_SHA`** on both the local `export` and the remote `docker compose`
  so the build arg reaches the image — otherwise `/health` reports
  `git_sha: "unknown"`.

## Verify (release identity)

`/health` reports the exact running revision — always check it after a deploy:

```bash
ssh ubuntu-srv 'curl -s http://localhost:8001/health'
# {"status":"ok","service":"agentledger-api","version":"0.1.0","git_sha":"<sha>","db":"ok"}
```

- `git_sha` must match `git rev-parse --short HEAD` of what you deployed.
- `db: "ok"` confirms the API reached Postgres (readiness). `status` is `degraded`
  if the DB is unreachable — the API still answers 200 (liveness), so the
  container healthcheck tracks the process, not a DB blip.
- The web bundle's revision is at `http://localhost:8080/version.txt`.

Confirm the migration chain landed:

```bash
ssh ubuntu-srv 'cd ~/agentledger && docker compose exec -T db \
  psql -U agentledger -d agentledger -tc "SELECT version_num FROM alembic_version;"'
```

**Post-deploy note:** for the first few seconds after restart the API is warming;
an MCP/REST call may transient-fail once with an `internal` error whose hint says
"safe to retry once" — it is. Retrying succeeds.

## Recover

- **Server `.env` was clobbered / wrong ports:** recreate `~/agentledger/.env`
  with the remapped ports (`DB_PORT=5433 API_PORT=8001 WEB_PORT=8080` + the CORS
  origins and `POSTGRES_PASSWORD`) **before** `up`.
- **Postgres password mismatch** (volume kept an old password): reset it over the
  local socket (no password needed there), non-destructive:
  ```bash
  ssh ubuntu-srv 'cd ~/agentledger && docker compose exec -T db \
    psql -U agentledger -d agentledger -c "ALTER USER agentledger WITH PASSWORD '\''agentledger'\'';"'
  ```
- **Silent API crash at startup:** stdout is block-buffered, so reproduce with the
  traceback visible:
  ```bash
  ssh ubuntu-srv 'cd ~/agentledger && docker compose run --rm -e PYTHONUNBUFFERED=1 \
    --no-deps api python -c "import app.main"'
  ```

## Rollback

Deploys are just a git revision + a rebuild, so rolling back is redeploying an
earlier one:

```bash
git checkout <previous-good-sha>
export GIT_SHA=$(git rev-parse --short HEAD)
rsync ... ubuntu-srv:~/agentledger/          # same excludes as above
ssh ubuntu-srv "cd ~/agentledger && GIT_SHA=$GIT_SHA docker compose up -d --build"
# verify /health git_sha now shows the rollback target
```

A **backward-incompatible migration** is the one thing a code rollback doesn't
undo — the DB stays migrated. Prefer additive, backward-compatible migrations so a
code rollback is always safe; if a destructive migration must ship, snapshot the
volume first (`docker compose exec db pg_dump ...`).

## Railway (hosted) — code readiness

The hosted multi-tenant offering runs on Railway. The application code is Railway-ready
(this is Phase 5, slice A); provisioning the actual project/services is a separate,
account-touching step (the remaining `railway` items). What the code already handles:

- **Two services, one repo.** `backend/railway.json` and `web/railway.json` declare a
  Dockerfile build + healthcheck per service. Create two Railway services with root
  directories `backend/` and `web/`; each picks up its `railway.json`.
- **`$PORT`.** Both images honor Railway's injected `$PORT` — the API via
  `uvicorn --port ${PORT:-8000}`, the web via nginx's envsubst template
  (`nginx.conf.template`, `listen ${PORT}`). Locally (`docker compose`) the defaults
  (8000 / 80) keep working unchanged.
- **`DATABASE_URL`.** Railway's Postgres hands out a `postgres://…` URL; config rewrites
  `postgres://` / `postgresql://` to the psycopg3 driver automatically — paste it as-is.
- **Web → API address.** Set `API_UPSTREAM` on the web service to the backend's private
  address (e.g. `${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000`); it defaults to `api:8000`
  for compose.
- **Migrations** run on API startup (same as self-host). Run a single API replica during
  a migration deploy to avoid two instances racing `upgrade head`.

### Required environment (backend service, hosted)

| Var | Notes |
|-----|-------|
| `HOSTED_MODE=true` | Turns on the org layer, quotas, and tighter tenant isolation. |
| `JWT_SECRET` | Long random string. `REQUIRE_STRONG_SECRET=true` refuses to boot on a weak one. |
| `SECRET_ENCRYPTION_KEY` | Required in hosted mode (encrypts BYOK provider keys); boot fails without it. |
| `DATABASE_URL` | From the Railway Postgres plugin (auto-normalized). |
| `PORT` | Injected by Railway. |
| `PLATFORM_ADMIN_EMAILS` | Comma-separated operator allowlist for manual plan assignment. |
| `APP_BASE_URL` | Public SPA origin, used to build org-invite links. |
| `SMTP_HOST` / `SMTP_*` | Invite email delivery (falls back to console/outbox if unset). |
| `REDIS_URL` | Optional; shared rate-limit store across replicas (in-process fallback otherwise). |
| `CORS_ORIGINS` | The web service's public origin(s). |
| `TRUSTED_PROXY=true` | Behind Railway's edge, so `X-Forwarded-For` is trustworthy. |

### `/data/sync`

Drive/filesystem sync is a self-host convenience. On Railway either leave it
unconfigured (it stays dormant with no Drive folder set) or attach a volume at
`/data/sync` if you want it — it is not required for the hosted app to run.
