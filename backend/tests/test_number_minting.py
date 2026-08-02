"""Per-project number minting under a project lock (PRD-13 / AL-259).

Replaces the single global counter, where every project's tickets shared one sequence
and a project's next number depended on what unrelated projects had done.

The concurrency test is the reason this file exists. The old counter had the same race
— read max, add one, write — and it never bit because nothing created two items at once.
This product is aimed squarely at parallel agent fleets, so it will.
"""
import pytest
from sqlalchemy import event, text

from app.db import SessionLocal, engine
from app.services import keys

_IS_SQLITE = engine.url.drivername.startswith("sqlite")


def _mk_project(client, auth, name: str) -> str:
    r = client.post("/api/projects", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_mint_returns_the_rendered_key_and_its_number(client, auth):
    project_id = _mk_project(client, auth, "Mint Test")
    with SessionLocal() as db:
        stored_id, number = keys.mint(db, project_id, "item")
    assert number == 1
    assert stored_id.endswith("-1")


def test_each_kind_counts_separately_within_a_project(client, auth):
    """Items, requests, and PRDs each keep their own sequence — today's behaviour, just
    project-scoped instead of global."""
    project_id = _mk_project(client, auth, "Kinds Apart")
    with SessionLocal() as db:
        assert keys.mint(db, project_id, "item")[1] == 1
        assert keys.mint(db, project_id, "request")[1] == 1
        assert keys.mint(db, project_id, "prd")[1] == 1


def test_mint_skips_a_stored_id_another_project_already_owns(client, auth):
    """A tag can equal a prefix from the pre-tag era, and numbering was GLOBAL back
    then — so the id this project would render may already be another project's primary
    key. Mint has to walk forward rather than raise an IntegrityError."""
    from app.models import Item, Project

    owner = _mk_project(client, auth, "Zulu")
    claimant = _mk_project(client, auth, "Zeta Yankee")

    with SessionLocal() as db:
        tag = db.get(Project, claimant).tag
        squatted = f"{tag}-1"  # exactly what `claimant` would mint first
        db.add(Item(id=squatted, number=1, project_id=owner, title="squatter"))
        db.commit()

        stored_id, number = keys.mint(db, claimant, "item")

    assert stored_id != squatted
    assert number == 2, "the number advances past the taken id"


def test_numbering_is_independent_across_projects(client, auth):
    a, b = _mk_project(client, auth, "Indy One"), _mk_project(client, auth, "Indy Two")
    with SessionLocal() as db:
        for _ in range(3):
            keys.mint(db, a, "item")
        assert keys.mint(db, b, "item")[1] == 1, "b must not inherit a's position"


# ---- the lock ---------------------------------------------------------------------
def _capture_for_update(fn):
    seen: list[str] = []

    def before(conn, cursor, statement, params, ctx, many):
        if "FOR UPDATE" in statement.upper():
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return seen


@pytest.mark.skipif(_IS_SQLITE, reason="row locks are a Postgres concern")
def test_mint_really_takes_a_row_lock_on_postgres(client, auth):
    """Pins that the lock is issued rather than assumed. Without it the race below is
    only ever won by luck."""
    project_id = _mk_project(client, auth, "Locked Down")
    seen = _capture_for_update(
        lambda: client.post(
            "/api/items", json={"title": "locked", "project_id": project_id}, headers=auth
        )
    )
    assert seen, "mint must emit SELECT … FOR UPDATE on Postgres"


@pytest.mark.skipif(not _IS_SQLITE, reason="the SQLite branch")
def test_no_for_update_is_emitted_on_sqlite(client, auth):
    """SQLAlchemy silently DROPS `FOR UPDATE` on SQLite rather than failing, so relying
    on a portable-looking lock would leave one of the two engines we ship unprotected
    with nothing to show for it. The branch is explicit; this pins that."""
    project_id = _mk_project(client, auth, "No Lock Here")
    seen = _capture_for_update(
        lambda: client.post(
            "/api/items", json={"title": "unlocked", "project_id": project_id}, headers=auth
        )
    )
    assert seen == []


@pytest.mark.skipif(_IS_SQLITE, reason="SQLite serializes writers; no concurrency to test")
def test_concurrent_creates_never_mint_a_duplicate_number(client, auth):
    """THE test this slice exists for.

    `max(number) + 1` is read-then-write. Eight agents creating work in the same project
    at the same moment must produce eight distinct numbers and eight distinct ids — the
    lock removes the race rather than recovering from it, and the (project_id, number)
    unique constraint is the backstop if it is ever bypassed.
    """
    from concurrent.futures import ThreadPoolExecutor

    project_id = _mk_project(client, auth, "Thundering Herd")

    def create(n: int) -> str:
        with SessionLocal() as db:
            from app.services import items as items_svc

            return items_svc.create_item(db, title=f"concurrent {n}", project_id=project_id).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(create, range(8)))

    assert len(set(ids)) == 8, f"duplicate stored ids: {ids}"
    with engine.connect() as conn:
        numbers = [
            r[0]
            for r in conn.execute(
                text("SELECT number FROM items WHERE project_id = :p"), {"p": project_id}
            ).fetchall()
        ]
    assert sorted(numbers) == list(range(1, 9)), numbers


@pytest.mark.skipif(_IS_SQLITE, reason="Postgres-only unique constraint check")
def test_the_unique_constraint_is_the_backstop(client, auth):
    """If minting is ever bypassed, the database still refuses a duplicate number."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Item

    project_id = _mk_project(client, auth, "Backstop")
    with SessionLocal() as db:
        db.add(Item(id="BSTOP-X1", number=7, project_id=project_id, title="first"))
        db.commit()
        db.add(Item(id="BSTOP-X2", number=7, project_id=project_id, title="dup"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
