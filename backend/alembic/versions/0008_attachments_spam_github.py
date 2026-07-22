"""attachments, spam-protection config, item github_url

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content_type", sa.String()),
        sa.Column("size", sa.Integer()),
        sa.Column("data", sa.LargeBinary()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    with op.batch_alter_table("requests") as batch:
        batch.add_column(sa.Column("attachment_ids", sa.JSON(), nullable=True))
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("github_url", sa.String(), nullable=False, server_default=""))
    with op.batch_alter_table("platform_config") as batch:
        batch.add_column(sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="20"))
        batch.add_column(sa.Column("turnstile_sitekey", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("turnstile_secret", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("platform_config") as batch:
        batch.drop_column("turnstile_secret")
        batch.drop_column("turnstile_sitekey")
        batch.drop_column("rate_limit_per_min")
    with op.batch_alter_table("items") as batch:
        batch.drop_column("github_url")
    with op.batch_alter_table("requests") as batch:
        batch.drop_column("attachment_ids")
    op.drop_table("attachments")
