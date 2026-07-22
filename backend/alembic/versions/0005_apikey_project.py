"""api_keys.project_id — scope agent keys to a project

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("project_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_api_keys_project", "projects", ["project_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_constraint("fk_api_keys_project", type_="foreignkey")
        batch.drop_column("project_id")
