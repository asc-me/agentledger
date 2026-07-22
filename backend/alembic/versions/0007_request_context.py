"""requests: detail, source_url, meta — capture feedback context

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("requests") as batch:
        batch.add_column(sa.Column("detail", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("source_url", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("requests") as batch:
        batch.drop_column("meta")
        batch.drop_column("source_url")
        batch.drop_column("detail")
