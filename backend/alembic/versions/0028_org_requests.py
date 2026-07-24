"""org_requests — requests to found an additional organization (hosted SaaS)

AL-92: every account gets one org; founding another needs an operator-approved request
(one-time, `consumed` when spent) or a standing plan entitlement (enterprise tier).

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_note", sa.String(), nullable=True),
    )
    op.create_index("ix_org_requests_user_id", "org_requests", ["user_id"])
    op.create_index("ix_org_requests_status", "org_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_org_requests_status", "org_requests")
    op.drop_index("ix_org_requests_user_id", "org_requests")
    op.drop_table("org_requests")
