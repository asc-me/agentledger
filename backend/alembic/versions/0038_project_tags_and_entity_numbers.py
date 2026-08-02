"""Project tags + per-entity numbers; seed the legacy key table (PRD-13 / AL-255).

Before this, every item, request, and PRD on an instance was numbered from ONE global
sequence behind a hardcoded prefix — `AL-`, `R-`, `PRD-` — so a project's tickets carried
the product's abbreviation rather than the project's, and the id said nothing about which
project owned it.

This splits display from identity. `projects.tag` holds the prefix; `number` holds the
sequence; the key a human sees is RENDERED from the two. Stored ids are left exactly as
they are and are never rewritten again — which is the point: twelve columns across ten
tables hold an entity id and only three are enforced foreign keys, so a design that moved
ids would be hand-correcting nine unchecked columns on every rename, forever.

Tags are DERIVED from each project's current name, not hardcoded. A migration cannot know
the projects on any given deployment, and hardcoding this instance's would corrupt every
other one. On the instance this was written for, "AgentLedger" derives to `AL`, so every
existing key renders identically to before and the backfill is invisible. Choosing a
different tag later is an ordinary retag through the UI — one UPDATE — which is precisely
the operation this design exists to make cheap.

The derivation is deliberately a FROZEN COPY of `app.tagging.derive` rather than an import.
An applied migration must never change behaviour retroactively: if the live derivation is
tuned later, already-migrated deployments must keep the tags they were given.

Revision ID: 0038
Revises: 0037
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

TAG_MIN, TAG_MAX = 2, 4
_TAG_RE = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")
_LEGACY_RE = re.compile(r"^([A-Za-z]+)-0*(\d+)$")

# (table, entity_type) — the three kinds that carry a human-facing key.
_ENTITIES = [("items", "item"), ("requests", "request"), ("prds", "prd")]


def _derive(name: str) -> str:
    """Frozen copy of app.tagging.derive — see the module docstring."""
    tokens: list[str] = []
    for part in (p for p in re.split(r"[^A-Za-z0-9]+", name or "") if p):
        tokens.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", part) or [part])
    if len(tokens) >= 2:
        base = "".join(t[0] for t in tokens)
    elif tokens:
        base = tokens[0]
    else:
        base = ""
    base = re.sub(r"^[0-9]+", "", base.upper())[:TAG_MAX]
    if len(base) < TAG_MIN:
        base = (base + "PJ")[:TAG_MAX]
    return base


def _variants(base: str):
    yield base
    for n in range(2, 1000):
        suffix = str(n)
        cand = (base[: max(1, TAG_MAX - len(suffix))] + suffix)[:TAG_MAX]
        if _TAG_RE.match(cand):
            yield cand


def upgrade() -> None:
    bind = op.get_bind()

    # ---- projects.tag ------------------------------------------------------------
    # Added nullable so the backfill can run, then tightened. Ordered by id so the
    # derivation is deterministic: re-running against the same data gives the same tags.
    op.add_column("projects", sa.Column("tag", sa.String(), nullable=True))

    taken: set[str] = set()
    rows = bind.execute(sa.text("SELECT id, name FROM projects ORDER BY id")).fetchall()
    for pid, name in rows:
        for candidate in _variants(_derive(name or pid)):
            if candidate not in taken:
                taken.add(candidate)
                bind.execute(
                    sa.text("UPDATE projects SET tag = :t WHERE id = :i"), {"t": candidate, "i": pid}
                )
                print(f"  [tags] {pid!r} ({name!r}) -> {candidate}", flush=True)
                break

    op.alter_column("projects", "tag", nullable=False)
    op.create_unique_constraint("uq_project_tag", "projects", ["tag"])

    # ---- number on items / requests / prds ----------------------------------------
    # The number is the digits already in the stored id, so nothing is renumbered and
    # the gaps a shared counter left behind are preserved. Sparse history is accurate.
    for table, _kind in _ENTITIES:
        op.add_column(table, sa.Column("number", sa.Integer(), nullable=True))

        for eid, in bind.execute(sa.text(f"SELECT id FROM {table}")).fetchall():  # noqa: S608
            m = _LEGACY_RE.match((eid or "").strip())
            if m:
                bind.execute(
                    sa.text(f"UPDATE {table} SET number = :n WHERE id = :i"),  # noqa: S608
                    {"n": int(m.group(2)), "i": eid},
                )

        # An id that didn't parse (hand-inserted, or from a fork with another scheme)
        # still needs a number. Give it one past the project's high-water mark rather
        # than failing the migration on data we can't interpret.
        unparsed = bind.execute(
            sa.text(f"SELECT id, project_id FROM {table} WHERE number IS NULL")  # noqa: S608
        ).fetchall()
        for eid, pid in unparsed:
            nxt = bind.execute(
                sa.text(f"SELECT COALESCE(MAX(number), 0) + 1 FROM {table} WHERE project_id = :p"),  # noqa: S608
                {"p": pid},
            ).scalar()
            bind.execute(
                sa.text(f"UPDATE {table} SET number = :n WHERE id = :i"),  # noqa: S608
                {"n": nxt, "i": eid},
            )
            print(f"  [numbers] {table}.{eid!r} had no parseable number -> {nxt}", flush=True)

        op.alter_column(table, "number", nullable=False)
        op.create_unique_constraint(f"uq_{_kind}_number", table, ["project_id", "number"])

    # ---- legacy_entity_keys --------------------------------------------------------
    # Every id issued BEFORE this migration, kept resolvable forever. Seeded here because
    # this is the last moment the old ids are authoritative. Never appended to again:
    # everything minted afterwards resolves by grammar or by tag history.
    op.create_table(
        "legacy_entity_keys",
        sa.Column("old_key", sa.String(), primary_key=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
    )
    op.create_index("ix_legacy_entity_keys_entity_id", "legacy_entity_keys", ["entity_id"])
    op.create_index("ix_legacy_entity_keys_project_id", "legacy_entity_keys", ["project_id"])

    seeded = 0
    for table, kind in _ENTITIES:
        for eid, pid in bind.execute(
            sa.text(f"SELECT id, project_id FROM {table}")  # noqa: S608
        ).fetchall():
            bind.execute(
                sa.text(
                    "INSERT INTO legacy_entity_keys (old_key, entity_type, entity_id, project_id)"
                    " VALUES (:k, :t, :e, :p)"
                ),
                {"k": eid, "t": kind, "e": eid, "p": pid},
            )
            seeded += 1
    print(f"  [legacy-keys] seeded {seeded} pre-tag id(s)", flush=True)


def downgrade() -> None:
    op.drop_table("legacy_entity_keys")
    for table, kind in _ENTITIES:
        op.drop_constraint(f"uq_{kind}_number", table, type_="unique")
        op.drop_column(table, "number")
    op.drop_constraint("uq_project_tag", "projects", type_="unique")
    op.drop_column("projects", "tag")
