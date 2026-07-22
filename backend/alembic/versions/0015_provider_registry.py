"""platform_config: provider registry (active_chat_provider + providers JSON)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("platform_config") as batch:
        batch.add_column(sa.Column("active_chat_provider", sa.String(), nullable=True))
        batch.add_column(sa.Column("providers", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("platform_config") as batch:
        batch.drop_column("providers")
        batch.drop_column("active_chat_provider")
