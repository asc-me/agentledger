"""prds + prd_versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "prds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String()),
        sa.Column("version", sa.String()),
        sa.Column("body", sa.Text()),
        sa.Column("linked", sa.JSON()),
        sa.Column("updated", sa.String()),
        sa.Column("created_at", TS),
        sa.Column("updated_at", TS),
    )
    op.create_table(
        "prd_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prd_id", sa.String(), sa.ForeignKey("prds.id")),
        sa.Column("version", sa.String()),
        sa.Column("date", sa.String()),
        sa.Column("note", sa.String()),
        sa.Column("body", sa.Text()),
        sa.Column("created_at", TS),
    )


def downgrade() -> None:
    op.drop_table("prd_versions")
    op.drop_table("prds")
