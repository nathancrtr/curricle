"""A `promote_requested` kind for the onboarding ledger.

The vocabulary 0004 froze had request/outcome pairs for the outline and
build stages but only outcomes for promote — `promote_failed` and
`promoted`. That reads fine until a promotion fails: the wizard's retry
button queues a run, and no row exists that can move the flow off
promote/failed, so the screen goes on saying "failed" while the worker is
busy. Under O1 the screen is a pure function of the ledger, which means the
fix belongs in the ledger and nowhere else — a projection that "knows" a
retry is in flight is exactly the kind of second source of truth this
system doesn't keep.

So: one more kind, and the house ceremony for it. The CHECK is the contract,
so growing it costs a migration; the constraint has to be dropped and
recreated because Postgres has no way to widen one in place. The lists here
are spelled out rather than read from `db.ONBOARDING_EVENT_KINDS` on
purpose: a migration is a snapshot of what this revision did, and one that
follows a live constant would silently mean something different on the day
the next kind is added. Nothing is backfilled — no past row could have been
a `promote_requested`.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

BEFORE = (
    "profile_published", "scope_saved",
    "outline_requested", "outline_ready", "outline_failed",
    "outline_approved", "outline_rejected",
    "build_requested", "build_ready", "build_failed",
    "promote_failed", "promoted",
)
AFTER = (
    "profile_published", "scope_saved",
    "outline_requested", "outline_ready", "outline_failed",
    "outline_approved", "outline_rejected",
    "build_requested", "build_ready", "build_failed",
    "promote_requested", "promote_failed", "promoted",
)


def _recreate_check(kinds: tuple[str, ...]) -> None:
    op.drop_constraint("known_onboarding_kind", "onboarding_events",
                       type_="check")
    op.create_check_constraint("known_onboarding_kind", "onboarding_events",
                               "kind IN " + repr(kinds))


def upgrade() -> None:
    _recreate_check(AFTER)


def downgrade() -> None:
    # A database holding rows of the kind being un-taught cannot go back;
    # the CHECK refuses the downgrade rather than the migration deleting
    # somebody's ledger rows to make room for itself.
    _recreate_check(BEFORE)
