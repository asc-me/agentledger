"""platform_config

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_config",
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("llm_mode", sa.String()),
        sa.Column("local_base_url", sa.String()),
        sa.Column("local_model", sa.String()),
        sa.Column("cloud_provider", sa.String()),
        sa.Column("cloud_model", sa.String()),
        sa.Column("github_connected", sa.Boolean()),
        sa.Column("github_account", sa.String()),
        sa.Column("github_repo", sa.String()),
        sa.Column("github_scope", sa.String()),
        sa.Column("gdrive_connected", sa.Boolean()),
        sa.Column("gdrive_account", sa.String()),
        sa.Column("gdrive_folder", sa.String()),
    )


def downgrade() -> None:
    op.drop_table("platform_config")
