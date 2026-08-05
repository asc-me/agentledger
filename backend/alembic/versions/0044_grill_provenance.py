"""Who answered the grill, and which provider set the bar (AL-299 / PRD-15 D3).

Approval is derived from the grill, so a baseline is only as trustworthy as what stands
behind it. Two facts a reader needs and could not previously recover:

- **Where an answer came from** — typed by a person in an authenticated session, or
  relayed by an agent from what a person told it in chat. Both are legitimate and neither
  blocks; the relayed path is what keeps the coding-agent loop frictionless.
- **Which provider graded the dimensions** — a real model, or the offline stub whose bar
  is mechanical (`stub`), or the author themselves for an explicit deferral (`author`).

That second one carries the weight. On the shipped default configuration, `approved`
means "four answers were recorded", not "four questions were answered well". Without
`graded_by` on the record, a stub-graded baseline and a model-graded one are
indistinguishable to anyone reading them later.

Existing rows get empty strings, which reads correctly as "recorded before provenance
was tracked" rather than asserting something untrue about them.

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grill_turns", sa.Column("via", sa.String(), nullable=False, server_default=""))
    op.add_column("grill_turns", sa.Column("actor", sa.String(), nullable=False, server_default=""))
    op.add_column("grill_dimensions",
                  sa.Column("graded_by", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("grill_dimensions", "graded_by")
    op.drop_column("grill_turns", "actor")
    op.drop_column("grill_turns", "via")
