"""Database layer: tables, tenancy invariants, and the one engine factory.

The tenancy rules (platform-design.md §7, inherited from job-radar) are
satisfied by construction from the first table:

- T1: tenant context is an ordinary argument. There is no default tenant;
  an unconfigured caller gets an exception, not tenant 0.
- T2: every table is classified TENANT_SCOPED or TENANT_LESS, asserted at
  import — this module refuses to load with an unclassified table. Scoped
  rows are reached only through TenantScope.
- T4: the purge and export registries are *derived* from the classification
  and asserted complete at import. A purge is unrepeatable (it deletes the
  tenants row), so nothing may be missable.
- T5 lives in the test suite: two tenants from the first fixture.

SQLAlchemy Core, no ORM — the generated SQL stays legible and the data-access
layer cannot quietly become a domain model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

# The progress-event vocabulary. The CHECK constraint makes the store refuse
# unknown kinds — the contract lives in the database, not in four writers'
# habits. Extend by migration, deliberately.
EVENT_KINDS = (
    "mark",              # {done: bool} on any progress id (unit/step/milestone/stage)
    "note",              # {text} on a unit — the curriculum view's per-unit note
    "resource_mark",     # {inhand: bool} on a resource key
    "resource_note",     # {text} on a resource key
    "checkpoint_result", # {score, total, misses[]} on a quiz material id
    "session_note",      # {text} free-form, subject_id may name a unit or ""
)

# The profile-evidence vocabulary. `assert` is the learner speaking in their
# own voice — accepted on arrival, because the human is the authority on
# themselves. `propose` is anything the system (or later, an agent) believes
# and must have ratified: the agent proposes, the human publishes.
PROFILE_EVENT_KINDS = ("assert", "propose", "accept", "reject", "retract")

# The onboarding vocabulary (onboarding-design.md §5): request/outcome pairs
# for the three worker stages, the human's verbs around the outline gate, and
# the terminal `promoted`. `promote_failed` and `promote_requested` complete
# the design doc's list rather than changing it — the promote stage ends in a
# compile gate that can refuse, ledger discipline says a failure is a row like
# any other, and a stage that can fail is a stage that can be asked for again.
# Without the request row, a retried promotion has nothing to move the flow
# off "failed", and the wizard would show a live run as a dead one (O1).
ONBOARDING_EVENT_KINDS = (
    "profile_published", "scope_saved",
    "outline_requested", "outline_ready", "outline_failed",
    "outline_approved", "outline_rejected",
    "build_requested", "build_ready", "build_failed",
    "promote_requested", "promote_failed", "promoted",
)

# What a queued run can ask for, and where it can be. `noop` is a real stage:
# slice 1 of the build order is provable with a no-op before any new role
# exists, and a stage the worker can run without spending a token stays useful
# long after as the end-to-end smoke test.
RUN_STAGES = ("noop", "outline", "build", "promote")
RUN_STATUSES = ("queued", "running", "done", "failed")

tenants = sa.Table(
    "tenants", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True),
              nullable=False, server_default=sa.func.now()),
)

progress_events = sa.Table(
    "progress_events", metadata,
    # BIGSERIAL: the fold orders by id, never by timestamp — rules that key
    # on sequence must survive clock skew (the job-radar eventlog lesson).
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.Integer,
              sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("course", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("subject_id", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True),
              nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(
        "kind IN " + repr(EVENT_KINDS), name="known_kind"),
    sa.Index("ix_progress_events_tenant_course", "tenant_id", "course"),
)

profile_events = sa.Table(
    "profile_events", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.Integer,
              sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("field", sa.Text, nullable=False),   # profile section (progress.FIELDS)
    sa.Column("key", sa.Text, nullable=False),     # claim identity within the field
    sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True),
              nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(
        "kind IN " + repr(PROFILE_EVENT_KINDS), name="known_profile_kind"),
    sa.Index("ix_profile_events_tenant", "tenant_id"),
)

token_ledger = sa.Table(
    "token_ledger", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.Integer,
              sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("stage", sa.Text, nullable=False),     # role name; every call has one
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("input_tokens", sa.Integer, nullable=False),
    sa.Column("output_tokens", sa.Integer, nullable=False),
    sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
    sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
    sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True),
              nullable=False, server_default=sa.func.now()),
    sa.Index("ix_token_ledger_tenant_stage", "tenant_id", "stage"),
)

onboarding_events = sa.Table(
    "onboarding_events", metadata,
    # Same identity-ordered sequence as the other two ledgers: the fold
    # orders by id, never timestamp.
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.Integer,
              sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
    # The course the event belongs to. `profile_published` happens before any
    # course exists and carries "" — a writer's rule (onboarding.py), not the
    # database's, because a nullable column would invite three-valued reads.
    sa.Column("course", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("created_at", sa.DateTime(timezone=True),
              nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(
        "kind IN " + repr(ONBOARDING_EVENT_KINDS), name="known_onboarding_kind"),
    sa.Index("ix_onboarding_events_tenant", "tenant_id"),
)

# The worker's queue. This shape is deliberately a procrastinate job's shape —
# the thin slice of the queue platform-design §6.1 already plans — so the
# later migration is "point the same callers at the real queue" rather than a
# redesign. `reason` holds a machine reason key, never prose: the wording
# table turns it into a sentence a human reads (O2).
factory_runs = sa.Table(
    "factory_runs", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.Integer,
              sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("course", sa.Text, nullable=False),
    sa.Column("stage", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("status", sa.Text, nullable=False, server_default="queued"),
    sa.Column("claimed_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("reason", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True),
              nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(
        "stage IN " + repr(RUN_STAGES), name="known_run_stage"),
    sa.CheckConstraint(
        "status IN " + repr(RUN_STATUSES), name="known_run_status"),
    sa.Index("ix_factory_runs_status", "status"),
)

# ---------------------------------------------------------------------------
# T2: classification, asserted at import
# ---------------------------------------------------------------------------

TENANT_SCOPED = frozenset({"progress_events", "profile_events", "token_ledger",
                           "onboarding_events", "factory_runs"})
TENANT_LESS = frozenset({"tenants"})

_all_tables = frozenset(metadata.tables)
_classified = TENANT_SCOPED | TENANT_LESS
assert _all_tables == _classified, (
    f"every table must be classified TENANT_SCOPED or TENANT_LESS; "
    f"unclassified: {sorted(_all_tables - _classified)}, "
    f"phantom: {sorted(_classified - _all_tables)}"
)
assert not (TENANT_SCOPED & TENANT_LESS)
for _name in TENANT_SCOPED:
    assert "tenant_id" in metadata.tables[_name].c, f"{_name} scoped without tenant_id"
for _name in TENANT_LESS:
    assert "tenant_id" not in metadata.tables[_name].c, (
        f"{_name} is TENANT_LESS but has a tenant_id column — a shared table "
        "with an unused tenant column is a table somebody eventually filters "
        "by mistake"
    )

# T4: purge and export are derived, not curated. With one scoped table the
# derivation is trivial; the assertion is the point — an unclassified or
# unregistered table cannot exist.
PURGED = frozenset(TENANT_SCOPED)
EXPORTED = frozenset(TENANT_SCOPED)
assert PURGED == TENANT_SCOPED and EXPORTED == TENANT_SCOPED


# ---------------------------------------------------------------------------
# Engine factory — the single seam runner, app, and tests share
# ---------------------------------------------------------------------------

ENV_URL = "CURRICLE_DATABASE_URL"


def database_url() -> str:
    url = os.environ.get(ENV_URL)
    if not url:
        raise RuntimeError(
            f"{ENV_URL} is not set. There is no default database — configure "
            "one explicitly (dev example: postgresql+psycopg:///curricle)."
        )
    return url


def make_engine(url: str | None = None) -> sa.Engine:
    return sa.create_engine(url or database_url())


# ---------------------------------------------------------------------------
# Tenants (T1: explicit, provisioned, never defaulted)
# ---------------------------------------------------------------------------

class UnknownTenant(LookupError):
    pass


def create_tenant(conn: sa.Connection, slug: str) -> int:
    row = conn.execute(
        sa.insert(tenants).values(slug=slug).returning(tenants.c.id)
    ).one()
    return row.id


def tenant_id_for(conn: sa.Connection, slug: str) -> int:
    row = conn.execute(
        sa.select(tenants.c.id).where(tenants.c.slug == slug)
    ).one_or_none()
    if row is None:
        raise UnknownTenant(
            f"no tenant with slug {slug!r} — provision it first "
            "(python -m curricle tenant create <slug>)"
        )
    return row.id


@dataclass(frozen=True)
class TenantScope:
    """The only path to tenant-scoped rows.

    Holds the tenant id it was built with; every statement it produces
    carries the predicate. Callers never spell `progress_events.c.tenant_id`
    themselves — the guard test enforces that outside this module.
    """

    tenant_id: int

    def events_select(self, course: str) -> sa.Select:
        return (
            sa.select(progress_events.c.id, progress_events.c.kind,
                      progress_events.c.subject_id, progress_events.c.payload,
                      progress_events.c.created_at)
            .where(progress_events.c.tenant_id == self.tenant_id,
                   progress_events.c.course == course)
            .order_by(progress_events.c.id)
        )

    def events_insert(self, course: str, kind: str, subject_id: str,
                      payload: dict) -> sa.Insert:
        return sa.insert(progress_events).values(
            tenant_id=self.tenant_id, course=course, kind=kind,
            subject_id=subject_id, payload=payload,
        )

    def profile_select(self) -> sa.Select:
        return (
            sa.select(profile_events.c.id, profile_events.c.kind,
                      profile_events.c.field, profile_events.c.key,
                      profile_events.c.payload, profile_events.c.created_at)
            .where(profile_events.c.tenant_id == self.tenant_id)
            .order_by(profile_events.c.id)
        )

    def profile_insert(self, kind: str, field: str, key: str,
                       payload: dict) -> sa.Insert:
        return sa.insert(profile_events).values(
            tenant_id=self.tenant_id, kind=kind, field=field,
            key=key, payload=payload,
        )

    def ledger_insert(self, stage: str, model: str, input_tokens: int,
                      output_tokens: int, cache_write_tokens: int,
                      cache_read_tokens: int, cost_usd) -> sa.Insert:
        return sa.insert(token_ledger).values(
            tenant_id=self.tenant_id, stage=stage, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_tokens=cache_read_tokens, cost_usd=cost_usd,
        )

    def ledger_stage_cost(self, stage: str) -> sa.Select:
        return sa.select(
            sa.func.coalesce(sa.func.sum(token_ledger.c.cost_usd), 0)
        ).where(token_ledger.c.tenant_id == self.tenant_id,
                token_ledger.c.stage == stage)

    def onboarding_select(self) -> sa.Select:
        return (
            sa.select(onboarding_events.c.id, onboarding_events.c.kind,
                      onboarding_events.c.course, onboarding_events.c.payload,
                      onboarding_events.c.created_at)
            .where(onboarding_events.c.tenant_id == self.tenant_id)
            .order_by(onboarding_events.c.id)
        )

    def onboarding_insert(self, kind: str, course: str,
                          payload: dict) -> sa.Insert:
        return sa.insert(onboarding_events).values(
            tenant_id=self.tenant_id, kind=kind, course=course,
            payload=payload,
        )

    def runs_insert(self, course: str, stage: str, payload: dict) -> sa.Insert:
        # No status: `queued` is the server default, so a request row cannot
        # be written into some other state by a caller's typo.
        return sa.insert(factory_runs).values(
            tenant_id=self.tenant_id, course=course, stage=stage,
            payload=payload,
        )

    def runs_pending(self, course: str) -> sa.Select:
        return (
            sa.select(factory_runs.c.id, factory_runs.c.stage,
                      factory_runs.c.status, factory_runs.c.claimed_at,
                      factory_runs.c.created_at)
            .where(factory_runs.c.tenant_id == self.tenant_id,
                   factory_runs.c.course == course,
                   factory_runs.c.status.in_(("queued", "running")))
            .order_by(factory_runs.c.id)
        )


def for_tenant(tenant_id: int) -> TenantScope:
    if not isinstance(tenant_id, int):
        raise TypeError(f"tenant_id must be an int, got {tenant_id!r}")
    return TenantScope(tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# The worker's queue, and the liveness other processes can see
# ---------------------------------------------------------------------------
#
# These are module-level rather than TenantScope methods because the worker
# has no tenant until it has a row: claiming is the one operation that
# *discovers* a tenant instead of being told one. T1 survives intact — the
# claimed row's `tenant_id` is an explicit value the caller then builds a
# scope from, and everything the stage touches afterwards goes through that
# scope. Nothing here reads a tenant from the environment or defaults one.

# `pg_advisory_lock(7231, 1)`: "one worker per database". Liveness is this
# lock and not a heartbeat table — it needs no schema, has no staleness
# window to tune, and dies with the process that held it, which is the only
# definition of "the worker is running" a welcome screen can trust.
WORKER_LOCK = (7231, 1)


def try_worker_lock(conn: sa.Connection) -> bool:
    """Take the worker lock, or report that somebody else holds it.

    Session-scoped: the lock outlives the transaction and is released when
    the connection's session ends, so the caller must hold this connection
    open for the worker's lifetime (and it must be a real session, not one
    handed back to a pool still holding the lock).
    """
    classid, objid = WORKER_LOCK
    return bool(conn.execute(
        sa.select(sa.func.pg_try_advisory_lock(classid, objid))).scalar())


def worker_alive(conn: sa.Connection) -> bool:
    """Is a worker holding the lock right now? The welcome screen's question."""
    classid, objid = WORKER_LOCK
    held = conn.execute(
        sa.text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND classid = cast(:classid AS oid) "
                "AND objid = cast(:objid AS oid)"),
        {"classid": classid, "objid": objid},
    ).scalar()
    return bool(held)


def claim_next_run(conn: sa.Connection) -> sa.Row | None:
    """Take the oldest queued run, marking it running. None when idle.

    `FOR UPDATE SKIP LOCKED` inside the caller's transaction is what makes
    the claim a claim: a row another session is already holding is passed
    over rather than waited on, so a second worker (or a stray script) can
    never hand the same run out twice. The row must stay locked until the
    caller commits, which is why this takes a connection and not an engine.
    """
    row = conn.execute(
        sa.select(factory_runs.c.id, factory_runs.c.tenant_id,
                  factory_runs.c.course, factory_runs.c.stage,
                  factory_runs.c.payload)
        .where(factory_runs.c.status == "queued")
        .order_by(factory_runs.c.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    conn.execute(
        sa.update(factory_runs).where(factory_runs.c.id == row.id)
        .values(status="running", claimed_at=sa.func.now())
    )
    return row


def finish_run(conn: sa.Connection, run_id: int, status: str,
               reason: str | None = None) -> None:
    """End a claimed run. `reason` is a machine key, never a sentence."""
    assert status in ("done", "failed"), (
        f"a run finishes done or failed, not {status!r} — the queued/running "
        "states belong to the claim, not to its outcome")
    conn.execute(
        sa.update(factory_runs).where(factory_runs.c.id == run_id)
        .values(status=status, finished_at=sa.func.now(), reason=reason)
    )


# ---------------------------------------------------------------------------
# T4 in motion: export and purge over the derived registries
# ---------------------------------------------------------------------------

def export_tenant(conn: sa.Connection, tenant_id: int) -> dict[str, list[dict]]:
    """Everything the tenant owns, as plain rows keyed by table name."""
    out: dict[str, list[dict]] = {}
    for name in sorted(EXPORTED):
        table = metadata.tables[name]
        rows = conn.execute(
            sa.select(table).where(table.c.tenant_id == tenant_id)
            .order_by(table.c.id)
        ).mappings().all()
        out[name] = [dict(r) for r in rows]
    return out


def purge_tenant(conn: sa.Connection, tenant_id: int) -> dict[str, int]:
    """Delete everything the tenant owns, then the tenant row, one transaction.

    Rows-then-identity order: if this is interrupted, the tenants row still
    names the owner of whatever remains, so the purge is re-runnable.
    """
    counts: dict[str, int] = {}
    for name in sorted(PURGED):
        table = metadata.tables[name]
        result = conn.execute(
            sa.delete(table).where(table.c.tenant_id == tenant_id)
        )
        counts[name] = result.rowcount
    conn.execute(sa.delete(tenants).where(tenants.c.id == tenant_id))
    return counts
