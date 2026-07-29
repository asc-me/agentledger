"""sync_link — instance-wide cloud link (web-managed)

AL-141: a singleton row holding the self-hosted instance's cloud link — target URL, an
encrypted `sync`-scoped credential, and an optional org label. Web counterpart of the
`agentledger link` CLI; when present it overrides the env SYNC_CLOUD_URL/SYNC_API_KEY.

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_link",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("cloud_url", sa.String(), nullable=False, server_default=""),
        sa.Column("api_key_enc", sa.String(), nullable=False, server_default=""),
        sa.Column("org", sa.String(), nullable=False, server_default=""),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_link")
