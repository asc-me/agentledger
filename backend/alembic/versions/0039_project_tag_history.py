"""Retired project tags, so keys rendered under them keep resolving (PRD-13 / AL-257).

One row per rename. Empty until something is actually retagged (AL-258 writes it), but
the resolution path reads it from the moment it exists, so it ships with resolution
rather than with the writer — a key rendered under an old tag must never depend on
which slice happened to land first.

`tag` is the primary key because tag reuse is forbidden per deployment. Two projects
holding `AL` at different times would make `AL-12` permanently ambiguous once both had
an item numbered 12, and no ordering by date can recover the intent.

Revision ID: 0039
Revises: 0038
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_tag_history",
        sa.Column("tag", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("held_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_tag_history_project_id", "project_tag_history", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_tag_history_project_id", table_name="project_tag_history")
    op.drop_table("project_tag_history")
