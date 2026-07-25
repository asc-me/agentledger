"""items.evidence — proof-on-done receipts

AL-53: an item carries evidence receipts (test-run summary, URL, screenshot ref,
deployed-health check) so a completion claim can be matched to its proof.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("evidence", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "evidence")
