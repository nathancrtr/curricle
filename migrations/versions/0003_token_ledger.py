"""The token ledger.

Every LLM call the factory makes writes one row here, attributed to a
tenant and a stage (the role name) — invariant L2 made durable. Costs are
computed at write time from models.yaml's price list and stored, because a
ledger records what a call cost when it happened, not what it would cost
under today's prices; re-deriving costs from a mutable price list would
rewrite history. Budgets read this table: spend-so-far per (tenant, stage)
against the configured ceiling, checked before a call, so a runaway loop
stops at the ledger, not at the invoice.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

from curricle import db

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    db.metadata.create_all(bind, tables=[db.token_ledger])


def downgrade() -> None:
    op.drop_table("token_ledger")
