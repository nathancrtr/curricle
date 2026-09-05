"""A `build_progress` kind for the onboarding ledger.

The build screen names the artifacts the learner approved and then, for
the eleven minutes it takes to write them, shows a clock and nothing else
— "there is no progress bar here … because this system would have to
invent both". The second half of that sentence was never true of the
count: the factory checkpoints the draft after every artifact, so which
ones have landed is a fact the worker holds, and a fact the worker holds
belongs in the ledger, where the screen can read it (O1) and where the
elapsed-never-forecast rule (design §3) has nothing to say against it.
That rule forbids estimates and percentages, not counts of finished
things.

So: one row per artifact as it lands, `build_progress{artifact}`, written
by the build stage between the checkpoint and the next role call. The
fold accumulates them into the flow's `landed` tuple, which an approval
resets — a retry after a failure keeps them, because the artifacts it
names are still on disk and the retry resumes rather than restarts. The
screen draws them as stones.

The same ceremony as 0005, for the same reason: the CHECK is the contract,
Postgres cannot widen one in place, and the lists here are spelled out so
this revision keeps meaning what it meant the day the next kind arrives.
Nothing is backfilled — no past build reported its artifacts as it went.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

BEFORE = (
    "profile_published", "scope_saved",
    "outline_requested", "outline_ready", "outline_failed",
    "outline_approved", "outline_rejected",
    "build_requested", "build_ready", "build_failed",
    "promote_requested", "promote_failed", "promoted",
)
AFTER = (
    "profile_published", "scope_saved",
    "outline_requested", "outline_ready", "outline_failed",
    "outline_approved", "outline_rejected",
    "build_requested", "build_progress", "build_ready", "build_failed",
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
    # A ledger holding progress rows cannot go back: the CHECK refuses the
    # downgrade rather than the migration deleting them to make room.
    _recreate_check(BEFORE)
