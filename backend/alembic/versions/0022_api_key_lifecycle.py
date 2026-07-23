"""api_keys.expires_at + revoked — key lifecycle

AL-72: API keys were create-and-delete only, never expiring. Add an optional
expiry and a soft revoke flag, both checked in verify_api_key. Existing rows get
NULL expiry (non-expiring) and revoked=false.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "revoked")
    op.drop_column("api_keys", "expires_at")
