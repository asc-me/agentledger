# Configuration

Configuration is via environment variables. In Docker, set them in `.env` (copy from
`.env.example`); locally, export them before running the API. The backend reads them through
`backend/app/config.py` (pydantic-settings).

## Database

| Var | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://agentledger:agentledger@localhost:5432/agentledger` | Use `sqlite:///./dev.db` for zero-infra dev. Postgres runs Alembic migrations; SQLite uses `create_all`. |

## Auth

| Var | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET` | dev placeholder | **Set a long random value in production** (≥ 32 bytes) |
| `ACCESS_TOKEN_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_DAYS` | `14` | Refresh token lifetime |

## AI providers

| Var | Default | Notes |
| --- | --- | --- |
| `CHAT_PROVIDER` | `stub` | `stub \| ollama \| anthropic` — switchable live in Settings |
| `EMBED_PROVIDER` | `stub` | `stub \| ollama \| openai` — deploy-time (must match `EMBED_DIM`) |
| `EMBED_DIM` | `384` | Vector dimension: stub 384, nomic-embed-text 768, OpenAI 1536 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` (Docker: `host.docker.internal`) | |
| `OLLAMA_CHAT_MODEL` | `llama3.1:8b` | |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | — | For OpenAI-compatible embeddings |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | |
| `ANTHROPIC_API_KEY` | — | Read by the `anthropic` SDK |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | |

See [AI providers](ai-providers.md) for the details (and why embeddings are deploy-time).

## App behavior

| Var | Default | Notes |
| --- | --- | --- |
| `SEED_ON_START` | `true` | Seed the demo dataset when the DB is empty |
| `PUBLIC_SUBMIT_ENABLED` | `true` | Allow the public feedback endpoints |
| `CORS_ORIGINS` | `http://localhost:8080,http://localhost:5173` | Comma-separated allowed origins |

## Docker Compose

`docker-compose.yml` reads these (all optional; defaults work):

| Var | Default |
| --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `agentledger` |
| `DB_PORT` | `5432` |
| `API_PORT` | `8000` |
| `WEB_PORT` | `8080` |

## Frontend

The dev server proxies `/api` to the backend; override the target with `VITE_API_PROXY`
(default `http://localhost:8000`). In the built image, nginx proxies `/api` and `/health` to
the `api` service.
