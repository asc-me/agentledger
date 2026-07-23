from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal, init_db
from app.version import __version__
from app.mcp_server import router as mcp_router
from app.routers import (
    agent,
    analytics,
    apikeys,
    auth,
    items,
    memory,
    platform,
    prds,
    projects,
    public,
    reports,
    requests,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.security.startup import check_security

    check_security()  # refuse/warn on a weak JWT secret before serving (AL-44)

    if settings.is_sqlite:
        # SQLite (tests / zero-infra dev): create tables directly.
        init_db()
    else:
        # Postgres: schema is owned by Alembic migrations.
        from app.migrate import run_migrations

        run_migrations()

    if settings.seed_on_start:
        from app.seed import seed

        db = SessionLocal()
        try:
            if seed(db):
                print("[seed] loaded AgentLedger prototype dataset")
        finally:
            db.close()

    # Apply any persisted platform LLM config so it drives the live providers.
    # Use the first existing project (there may be none on a freshly wiped DB).
    from sqlalchemy import select

    from app.models import Project
    from app.services.platform import apply_llm, get_config

    db = SessionLocal()
    try:
        first = db.scalars(select(Project).order_by(Project.name)).first()
        if first is not None:
            apply_llm(get_config(db, first.id))
    finally:
        db.close()
    yield


app = FastAPI(title="AgentLedger API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API under /api; MCP endpoint at /api/mcp.
API = "/api"
app.include_router(auth.router, prefix=API)
app.include_router(projects.router, prefix=API)
app.include_router(items.router, prefix=API)
app.include_router(requests.router, prefix=API)
app.include_router(memory.router, prefix=API)
app.include_router(apikeys.router, prefix=API)
app.include_router(agent.router, prefix=API)
app.include_router(prds.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(platform.router, prefix=API)
app.include_router(public.router, prefix=API)
app.include_router(reports.router, prefix=API)
app.include_router(mcp_router, prefix=API)


@app.get("/health")
def health():
    """Liveness + release identity. Always HTTP 200 while the process is up (so the
    container healthcheck tracks the API, not the DB); `db` reports readiness, and
    `version`+`git_sha` tell you exactly what revision is running (see docs/deploy.md)."""
    db_ok = True
    try:
        with SessionLocal() as s:
            s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — health must never raise
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "agentledger-api",
        "version": __version__,
        "git_sha": settings.git_sha,
        "db": "ok" if db_ok else "down",
    }
