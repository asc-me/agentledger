"""org_invites — emailed organization invitations (hosted SaaS)

AL-74b: the invite half of org onboarding. Like the org tables, this exists in
every deployment's schema but is only exercised in HOSTED_MODE.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_invites",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("invited_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("token", name="uq_org_invite_token"),
    )
    op.create_index("ix_org_invites_org_id", "org_invites", ["org_id"])
    op.create_index("ix_org_invites_email", "org_invites", ["email"])
    op.create_index("ix_org_invites_token", "org_invites", ["token"])
    op.create_index("ix_org_invites_status", "org_invites", ["status"])


def downgrade() -> None:
    op.drop_index("ix_org_invites_status", "org_invites")
    op.drop_index("ix_org_invites_token", "org_invites")
    op.drop_index("ix_org_invites_email", "org_invites")
    op.drop_index("ix_org_invites_org_id", "org_invites")
    op.drop_table("org_invites")
