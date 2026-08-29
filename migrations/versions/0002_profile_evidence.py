"""The profile-evidence ledger.

Phase 2's founding table: profile claims as append-only events, same house
pattern as the progress ledger — sequence by identity id, a pure fold, any
stored profile document a projection. The kind vocabulary encodes the
review discipline in the store itself: `assert` is the learner speaking in
their own voice (accepted on arrival — the human is the authority on
themselves); `propose` is anything the system believes about the learner
and must have ratified before it renders; accept/reject/retract are the
ratification verbs. The evidence tier (attested/demonstrated/thin) lives in
the payload rather than a column because the fold, not SQL, is the reader —
if a query ever needs to filter by tier, that is the migration where it
becomes a column. `field` is validated in the application (the vocabulary
is expected to grow with the profile model); `kind` is CHECKed here because
the review discipline must hold even against a bypassed app layer.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

from curricle import db

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    db.metadata.create_all(bind, tables=[db.profile_events])


def downgrade() -> None:
    op.drop_table("profile_events")
