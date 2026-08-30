"""The onboarding ledger and the factory-runs queue.

`onboarding_events` is the third ledger and the same discipline as the first
two: append-only, tenant-scoped, sequence carried by an identity id because
the fold orders by id and never by timestamp. What it buys is invariant O1 —
the wizard's current screen is a pure function of the ledgers, so navigation
can reach exactly the stops a fold says are open and no screen keeps state
of its own. The vocabulary is CHECKed here rather than trusted to the
writers, for the same reason `known_kind` is: growing the state machine
should cost a migration. It records only *that* something happened; the
profile stop's content still comes from the profile fold, because a claim
duplicated into a second ledger is a projection waiting to disagree.

`factory_runs` exists because L1 holds — no LLM on a request path, ever — so
the generation stages belong to a worker process. The web app writes request
rows and reads outcome rows; it never runs a stage itself. The table's shape
(stage, payload, status, claimed_at, finished_at, reason) is deliberately a
procrastinate job's shape: platform-design §6.1 already plans a real queue
with multi-tenancy, and this is a thin slice of it rather than a rival, so
that migration path is "point the same callers at the real queue" and not a
redesign. `reason` is a machine key, never a sentence — the human wording
lives in a table the tests hold complete (O2). Nothing is backfilled: an
existing tenant has simply never onboarded, which the empty fold already
says correctly.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

from curricle import db

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    db.metadata.create_all(bind, tables=[db.onboarding_events, db.factory_runs])


def downgrade() -> None:
    op.drop_table("factory_runs")
    op.drop_table("onboarding_events")
