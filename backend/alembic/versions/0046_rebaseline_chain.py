"""Baselines form an append-only chain (AL-241 / PRD-12).

Rebaselining is the deliberate, recorded act of declaring new frozen intent for an
in-flight PRD. It exists because specs legitimately change mid-delivery — but *learning*,
*scope change*, and *laundering* are content-identical when you only look at the end
state. "We discovered the spec was wrong" and "we edited the spec to match what we built"
produce the same diff. Only sequencing and a stated reason tell them apart, which is why
`supersedes_id`, `rebaseline_reason_type` and `rebaseline_reason` are all mandatory on
anything after the first baseline.

`supersedes_id` is NULL on a first baseline — it supersedes nothing — and points at the
prior row afterwards. Nothing ever updates or deletes a baseline: N+1 is a new row, so a
rebaseline can never erase the record it is superseding. That is the whole point.

Existing baselines (PRD-12 v1.0 is the only one) get NULL and empty strings, which reads
correctly: they are chain heads that superseded nothing.

Revision ID: 0046
Revises: 0045
"""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prd_versions", sa.Column("supersedes_id", sa.Integer(), nullable=True))
    op.add_column("prd_versions", sa.Column("rebaseline_reason_type", sa.String(),
                                            nullable=False, server_default=""))
    op.add_column("prd_versions", sa.Column("rebaseline_reason", sa.Text(),
                                            nullable=False, server_default=""))
    op.add_column("prd_versions", sa.Column("requested_by", sa.String(),
                                            nullable=False, server_default=""))
    op.create_foreign_key("fk_prd_versions_supersedes", "prd_versions", "prd_versions",
                          ["supersedes_id"], ["id"])
    # A rebaseline that has been requested but not yet earned. Non-null means the PRD is
    # being re-interrogated, which a UI needs to tell apart from a first-time review.
    op.add_column("prds", sa.Column("pending_rebaseline", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("prds", "pending_rebaseline")
    op.drop_constraint("fk_prd_versions_supersedes", "prd_versions", type_="foreignkey")
    op.drop_column("prd_versions", "requested_by")
    op.drop_column("prd_versions", "rebaseline_reason")
    op.drop_column("prd_versions", "rebaseline_reason_type")
    op.drop_column("prd_versions", "supersedes_id")
