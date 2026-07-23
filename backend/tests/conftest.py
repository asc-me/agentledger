import os

# Must be set before app modules import settings. setdefault so CI can point the
# suite at Postgres (DATABASE_URL=postgresql+psycopg://...) to exercise the real
# Alembic chain and pgvector `<=>` search path; local runs default to SQLite.
os.environ.setdefault("DATABASE_URL", "sqlite:///./.pytest.db")
os.environ["SEED_ON_START"] = "true"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    # The spam limiter keeps in-process state; clear it so tests don't leak counts.
    from app.services import spam

    spam._hits.clear()
    yield


def _drop_schema():
    from sqlalchemy import text

    from app.db import Base, engine

    Base.metadata.drop_all(engine)
    if not engine.url.drivername.startswith("sqlite"):
        # alembic_version isn't in Base.metadata; drop it too or the lifespan's
        # `upgrade head` would think the (now-dropped) schema is still current.
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture()
def client():
    from app.main import app

    _drop_schema()  # start clean; lifespan re-creates (SQLite) / re-migrates (Postgres) + seeds
    with TestClient(app) as c:
        yield c
    _drop_schema()


@pytest.fixture()
def auth(client):
    r = client.post(
        "/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "agentledger"}
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
