import os

# Must be set before app modules import settings.
os.environ["DATABASE_URL"] = "sqlite:///./.pytest.db"
os.environ["SEED_ON_START"] = "true"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    # The spam limiter keeps in-process state; clear it so tests don't leak counts.
    from app.services import spam

    spam._hits.clear()
    yield


@pytest.fixture()
def client():
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(engine)  # start clean; lifespan re-creates + seeds
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


@pytest.fixture()
def auth(client):
    r = client.post(
        "/api/auth/login", json={"email": "alex@ascme-labs.com", "password": "agentledger"}
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
