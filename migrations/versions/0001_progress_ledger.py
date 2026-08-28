"""Tenants and the progress-event ledger.

The first migration carries the platform's two founding invariants into the
store itself. `tenants` is the identity table — written once at provisioning,
never derived; losing a row loses the account, so the events FK is RESTRICT
(a purge deletes events first, deliberately, in one transaction). The ledger
is append-only by convention with sequence carried by an identity id, because
the fold orders by id, never timestamp. `known_kind` is a CHECK rather than
application discipline: extending the event vocabulary is a migration, which
is exactly the ceremony a contract change deserves. Nothing here is
backfilled because nothing precedes it; browser-localStorage state arrives
later through the import CLI as ordinary events.

Revision ID: 0001
Revises:
"""

from alembic import op

from curricle import db

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    db.metadata.create_all(bind, tables=[db.tenants, db.progress_events])


def downgrade() -> None:
    op.drop_table("progress_events")
    op.drop_table("tenants")
