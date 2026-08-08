"""Backfill `items.prd_id` values that froze a rendering instead of an id (GRPH-319).

`create_item` and `update_item` stored whatever PRD key the caller passed. Callers
before the AL→GRPH retag passed `PRD-12` — which *is* the frozen id — and callers after
it passed `GRPH-P12`, the live rendering. Both resolve fine on read, so nothing looked
wrong; but `prds.coverage` joins on the raw string, and it only ever matches one of them.
On the live database that hid 8 of PRD-12's 22 items, including shipped work.

The write path is fixed in `items._stored_prd_id`. This repairs the rows already written.

Deliberately narrow: a value that still names nothing is left exactly as it is. It is a
dangling reference either way, and the stored string is the only remaining evidence of
what the author meant — overwriting it with NULL would destroy the one clue needed to fix
it by hand.

`app.tagging` is imported rather than reimplemented here. It is pure parsing with no
model or schema coupling, so it cannot drift out from under this migration the way an
import of a service would.

Revision ID: 0047
Revises: 0046
"""
from alembic import op
import sqlalchemy as sa

from app import tagging

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    prd_ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM prds"))}
    # (project_id, number) -> frozen id, the same lookup `keys.resolve` rung 1 performs.
    by_number = {
        (r[0], r[1]): r[2]
        for r in conn.execute(sa.text("SELECT project_id, number, id FROM prds"))
    }
    tags = {r[0]: r[1] for r in conn.execute(sa.text("SELECT tag, id FROM projects"))}
    tags.update({
        r[0]: r[1]
        for r in conn.execute(sa.text("SELECT tag, project_id FROM project_tag_history"))
    })

    rows = conn.execute(sa.text(
        "SELECT id, prd_id FROM items WHERE prd_id IS NOT NULL AND prd_id <> ''"
    )).fetchall()

    for item_id, stored in rows:
        if stored in prd_ids:
            continue  # already a frozen id
        parsed = tagging.parse(stored)
        if not parsed or parsed[1] != "prd":
            continue
        tag, _kind, number = parsed
        project_id = tags.get(tag)
        resolved = by_number.get((project_id, number)) if project_id else None
        if resolved is None or resolved == stored:
            continue
        conn.execute(
            sa.text("UPDATE items SET prd_id = :prd WHERE id = :item"),
            {"prd": resolved, "item": item_id},
        )


def downgrade() -> None:
    """No-op. The pre-migration state is "some rows hold a rendering, some hold an id",
    and which was which is not recoverable — the rendering a row held was a function of
    when it was written. Re-deriving one would be inventing history, and the repaired
    value is correct under both the old and new read paths anyway."""
