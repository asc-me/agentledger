"""AL-192: collision-aware clustering — actual/predicted touch-areas, non-colliding clusters."""
import types

import pytest

from app.db import SessionLocal
from app.services import code_graph, collision
from app.services import items as items_svc
from app.services import links as links_svc


@pytest.fixture()
def db(client):
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _item(db, title, touchpoints=None, desc=""):
    return items_svc.create_item(db, title=title, description=desc, project_id="core",
                                 touchpoints=touchpoints or [])


def _no_code_hits(monkeypatch):
    monkeypatch.setattr(code_graph, "search_code", lambda db, q, pid, top_k=5: [])


def test_touch_areas_prefers_actual_touchpoints(db):
    it = _item(db, "Widget", touchpoints=["backend/app/widget.py"])
    areas, src = collision.touch_areas(db, it, "core")
    assert areas == ["backend/app/widget.py"] and src == "actual"


def test_predict_uses_code_map_inference_above_threshold(db, monkeypatch):
    monkeypatch.setattr(code_graph, "search_code", lambda db, q, pid, top_k=5: [
        (types.SimpleNamespace(path="backend/app/sync.py"), 0.9),
        (types.SimpleNamespace(path="backend/app/weak.py"), 0.05)])  # below min-sim
    it = _item(db, "Fix the sync engine")
    areas, src = collision.touch_areas(db, it, "core")
    assert src == "predicted"
    assert "backend/app/sync.py" in areas and "backend/app/weak.py" not in areas


def test_predict_uses_linked_item_touchpoints_as_learned_signal(db, monkeypatch):
    _no_code_hits(monkeypatch)  # learned signal only
    known = _item(db, "Known area", touchpoints=["backend/app/auth.py"])
    fresh = _item(db, "Fresh ticket")  # no touchpoints
    links_svc.create_link(db, a=fresh.id, b=known.id, type_="dependency", project_id="core")
    areas, src = collision.touch_areas(db, fresh, "core")
    assert src == "predicted" and "backend/app/auth.py" in areas


def test_clusters_group_overlapping_and_split_independent(db, monkeypatch):
    _no_code_hits(monkeypatch)
    a = _item(db, "A", touchpoints=["backend/app/pay.py"])
    b = _item(db, "B", touchpoints=["backend/app/pay.py"])   # collides with A
    c = _item(db, "C", touchpoints=["web/src/cart.tsx"])     # independent
    clusters = collision.collision_clusters(db, [a, b, c], "core")

    ab = next(cl for cl in clusters if a.id in cl["items"])
    assert set(ab["items"]) == {a.id, b.id} and ab["collides"] is True and ab["predicted"] is False
    solo = next(cl for cl in clusters if c.id in cl["items"])
    assert solo["items"] == [c.id] and solo["collides"] is False
    assert clusters[0]["items"] == ab["items"]  # largest cluster first


def test_glob_or_directory_overlap_counts_as_collision(db, monkeypatch):
    _no_code_hits(monkeypatch)
    a = _item(db, "A", touchpoints=["backend/app/routers/items.py"])
    b = _item(db, "B", touchpoints=["backend/app/routers/*.py"])  # glob covers A
    clusters = collision.collision_clusters(db, [a, b], "core")
    assert len(clusters) == 1 and set(clusters[0]["items"]) == {a.id, b.id}


def test_predicted_cluster_is_flagged(db, monkeypatch):
    # both items lack touchpoints; a shared inferred path groups them, flagged predicted
    monkeypatch.setattr(code_graph, "search_code",
                        lambda db, q, pid, top_k=5: [(types.SimpleNamespace(path="backend/app/x.py"), 0.8)])
    a = _item(db, "infer A")
    b = _item(db, "infer B")
    clusters = collision.collision_clusters(db, [a, b], "core")
    assert len(clusters) == 1 and clusters[0]["collides"] and clusters[0]["predicted"] is True


def test_endpoint_returns_clusters_and_requires_auth(client, auth, monkeypatch):
    from app.services import code_graph as cg
    monkeypatch.setattr(cg, "search_code", lambda db, q, pid, top_k=5: [])

    a = client.post("/api/items", json={"title": "Pay A", "project_id": "core",
                    "touchpoints": ["backend/app/billing.py"]}, headers=auth).json()
    b = client.post("/api/items", json={"title": "Pay B", "project_id": "core",
                    "touchpoints": ["backend/app/billing.py"]}, headers=auth).json()

    assert client.get("/api/items/collision-clusters?project_id=core").status_code == 401
    r = client.get("/api/items/collision-clusters?project_id=core", headers=auth)
    assert r.status_code == 200
    pay = next(cl for cl in r.json()["clusters"] if a["id"] in cl["items"])
    assert {a["id"], b["id"]} <= set(pay["items"]) and pay["collides"] is True
