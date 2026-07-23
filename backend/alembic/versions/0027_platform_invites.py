"""platform invites — org_invites gains kind/plan, org_id becomes nullable

AL-91: a second invite kind that authorizes a brand-new account to sign up and found
its OWN org (org_id NULL until that org exists), optionally pre-assigned a plan.
Existing rows are org invites, so `kind` backfills to 'org'.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "org_invites",
        sa.Column("kind", sa.String(), nullable=False, server_default="org"),
    )
    op.add_column("org_invites", sa.Column("plan", sa.String(), nullable=True))
    # A platform invite has no org yet.
    op.alter_column("org_invites", "org_id", existing_type=sa.String(), nullable=True)
    op.create_index("ix_org_invites_kind", "org_invites", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_org_invites_kind", "org_invites")
    # Platform invites can't be represented once org_id is NOT NULL again.
    op.execute("DELETE FROM org_invites WHERE kind = 'platform'")
    op.alter_column("org_invites", "org_id", existing_type=sa.String(), nullable=False)
    op.drop_column("org_invites", "plan")
    op.drop_column("org_invites", "kind")
