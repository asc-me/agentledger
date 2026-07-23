"""users.token_version — revocation epoch for server-side logout

AL-59: embedded in each JWT as `tv` and checked on decode, so logout /
password-change can invalidate every outstanding access + refresh token by
bumping this counter. Existing rows default to 0.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
