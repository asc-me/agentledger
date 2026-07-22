"""code_refs — bridge tracker items/requests to code-graph paths

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "code_refs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id")),
        sa.Column("ref_type", sa.String(), nullable=False),
        sa.Column("ref_id", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("relation", sa.String()),
        sa.Column("created_at", TS),
        sa.UniqueConstraint("project_id", "ref_type", "ref_id", "path", "relation", name="uq_code_ref"),
    )
    op.create_index("ix_code_refs_path", "code_refs", ["project_id", "path"])
    op.create_index("ix_code_refs_ref", "code_refs", ["project_id", "ref_type", "ref_id"])


def downgrade() -> None:
    op.drop_index("ix_code_refs_ref", table_name="code_refs")
    op.drop_index("ix_code_refs_path", table_name="code_refs")
    op.drop_table("code_refs")
