"""items.prd_id + prd_section — spec-to-task traceability

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("prd_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("prd_section", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_column("prd_section")
        batch.drop_column("prd_id")
