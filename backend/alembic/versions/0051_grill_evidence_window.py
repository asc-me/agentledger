"""Scope a rebaseline's grill to answers given AFTER it was requested (GRPH-322).

`request_rebaseline` cleared the dimension verdicts and left the transcript — correct,
since the transcript is append-only history. But `classify_grill` then read the WHOLE
transcript, re-graded the previous grill's answers, and promoted straight back to
`approved`. PRD-12 reached v1.2 on a classification pass with no new input, every
dimension citing the last answer of the v1.0 grill.

That defeats the property `request_rebaseline` exists for: *"'we edited the spec to match
what we built' has to survive being questioned."* It did not have to — the previous
conversation answered on its behalf, and rebaselining is precisely where laundering is the
named risk (see 0046).

`grill_from_seq` is the boundary. The transcript stays whole; only the evidence window
moves, the same distinction `baseline_at_claim` draws between what happened and what a
judgement may rest on.

Existing rows default to 0 — the whole transcript, which is right for any PRD that has
never rebaselined and is the honest reading for one that has: those answers WERE the
evidence at the time, and rewriting the window backwards would fabricate a history of
interrogation that did not happen.

Revision ID: 0051
Revises: 0050
"""
from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prds", sa.Column("grill_from_seq", sa.Integer(), nullable=False,
                                    server_default="0"))


def downgrade() -> None:
    op.drop_column("prds", "grill_from_seq")
