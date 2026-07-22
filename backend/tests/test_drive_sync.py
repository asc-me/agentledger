"""AL-01: two-way PRD <-> markdown-folder sync (filesystem backend)."""
from app.db import SessionLocal
from app.models import Prd
from app.services import drive_sync
from app.services import prds as prd_svc


def _project(client, auth):
    client.post("/api/projects", json={"name": "Sync"}, headers=auth)  # id: sync


def test_export_writes_files_with_front_matter(client, auth, tmp_path):
    _project(client, auth)
    db = SessionLocal()
    prd = prd_svc.create_prd(db, title="Spec One", project_id="sync", body="# Spec One\n\n## Goals\n- ship\n")
    rep = drive_sync.sync(db, "sync", root_dir=tmp_path)
    assert prd.id in rep["exported"]
    files = list((tmp_path / "PRDs").glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert f"agentledger_id: {prd.id}" in content and "## Goals" in content
    # Second sync with no changes is a no-op.
    assert drive_sync.sync(db, "sync", root_dir=tmp_path)["in_sync"] == 1
    db.close()


def test_editing_the_file_updates_the_prd(client, auth, tmp_path):
    _project(client, auth)
    db = SessionLocal()
    prd = prd_svc.create_prd(db, title="Editable", project_id="sync", body="# Editable\n\noriginal\n")
    drive_sync.sync(db, "sync", root_dir=tmp_path)  # export baseline
    fp = next((tmp_path / "PRDs").glob("*.md"))
    fp.write_text(fp.read_text().replace("original", "edited in the folder"))
    rep = drive_sync.sync(db, "sync", root_dir=tmp_path)
    assert prd.id in rep["updated_db"]
    db.expire_all()
    assert "edited in the folder" in db.get(Prd, prd.id).body  # pulled back into the DB
    db.close()


def test_new_file_imports_as_draft_prd_no_duplicate(client, auth, tmp_path):
    _project(client, auth)
    db = SessionLocal()
    d = tmp_path / "PRDs"
    d.mkdir(parents=True)
    (d / "manual-note.md").write_text("# Manual Idea\n\ndrafted in the folder\n")
    rep = drive_sync.sync(db, "sync", root_dir=tmp_path)
    assert len(rep["imported"]) == 1
    new_id = rep["imported"][0]
    p = db.get(Prd, new_id)
    assert p.title == "Manual Idea" and "drafted in the folder" in p.body
    # The file now carries the id, so a re-sync doesn't create a duplicate.
    assert f"agentledger_id: {new_id}" in (d / "manual-note.md").read_text()
    assert drive_sync.sync(db, "sync", root_dir=tmp_path)["imported"] == []
    db.close()


def test_conflict_is_flagged_not_clobbered(client, auth, tmp_path):
    _project(client, auth)
    db = SessionLocal()
    prd = prd_svc.create_prd(db, title="Contested", project_id="sync", body="# Contested\n\nbase\n")
    drive_sync.sync(db, "sync", root_dir=tmp_path)  # baseline
    # Change both sides differently since the last sync.
    prd_svc.update_prd(db, prd.id, body="# Contested\n\nDB edit\n")
    fp = next((tmp_path / "PRDs").glob("*.md"))
    fp.write_text(fp.read_text().replace("base", "folder edit"))
    rep = drive_sync.sync(db, "sync", root_dir=tmp_path)
    assert prd.id in rep["conflicts"]
    db.expire_all()
    assert "DB edit" in db.get(Prd, prd.id).body          # DB not clobbered
    assert "folder edit" in fp.read_text()                # file not clobbered
    db.close()


def test_sync_endpoint_requires_connection(client, auth, tmp_path, monkeypatch):
    _project(client, auth)
    from app.config import settings
    monkeypatch.setattr(settings, "sync_dir", str(tmp_path))

    assert client.post("/api/platform/gdrive/sync?project_id=sync", headers=auth).status_code == 400
    client.post("/api/platform/gdrive/connect?project_id=sync",
                json={"account": "me", "folder": "specs"}, headers=auth)
    r = client.post("/api/platform/gdrive/sync?project_id=sync", headers=auth)
    assert r.status_code == 200
    assert r.json()["prds_dir"].endswith("specs/PRDs")
