"""items.touchpoints — code-locality for related-work clustering

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("touchpoints", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_column("touchpoints")
