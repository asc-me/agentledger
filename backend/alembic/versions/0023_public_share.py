"""platform_config.public_share_enabled + share_token — opt-in public sharing

AL-73: public endpoints accepted an arbitrary project_id unauthenticated, leaking
data across tenants. Gate them behind a per-project opt-in addressed by an
unguessable share token. Existing rows default to not-shared (NULL token).

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "platform_config",
        sa.Column("public_share_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("platform_config", sa.Column("share_token", sa.String(), nullable=True))
    op.create_unique_constraint("uq_platform_config_share_token", "platform_config", ["share_token"])


def downgrade() -> None:
    op.drop_constraint("uq_platform_config_share_token", "platform_config", type_="unique")
    op.drop_column("platform_config", "share_token")
    op.drop_column("platform_config", "public_share_enabled")
