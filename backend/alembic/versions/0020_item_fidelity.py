"""items.fidelity — low- vs high-fidelity (needs-a-prototype) classification

AL-68: the grill technique's fidelity distinction, made first-class on tasks so
prototype-first work is trackable and prd_coverage can surface it. Existing rows
default to `low`.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("fidelity", sa.String(), nullable=False, server_default="low"))


def downgrade() -> None:
    op.drop_column("items", "fidelity")
