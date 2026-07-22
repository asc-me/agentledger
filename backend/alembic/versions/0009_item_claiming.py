"""items: assignee + agent claiming (claimed_by, claimed_at)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("assignee", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("claimed_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_column("claimed_at")
        batch.drop_column("claimed_by")
        batch.drop_column("assignee")
