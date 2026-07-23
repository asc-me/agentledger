"""organizations + org_memberships + projects.org_id — hosted SaaS org layer

AL-74: the SaaS Organization layer. Tables exist in every deployment's schema but
are inert unless HOSTED_MODE is on; self-host rows keep projects.org_id = NULL.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "org_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_membership"),
    )
    op.create_index("ix_org_memberships_org_id", "org_memberships", ["org_id"])
    op.create_index("ix_org_memberships_user_id", "org_memberships", ["user_id"])

    op.add_column(
        "projects",
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=True),
    )
    op.create_index("ix_projects_org_id", "projects", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_org_id", "projects")
    op.drop_column("projects", "org_id")
    op.drop_index("ix_org_memberships_user_id", "org_memberships")
    op.drop_index("ix_org_memberships_org_id", "org_memberships")
    op.drop_table("org_memberships")
    op.drop_table("organizations")
