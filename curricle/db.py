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

# ---------------------------------------------------------------------------
# T2: classification, asserted at import
# ---------------------------------------------------------------------------

TENANT_SCOPED = frozenset({"progress_events", "profile_events"})
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


def for_tenant(tenant_id: int) -> TenantScope:
    if not isinstance(tenant_id, int):
        raise TypeError(f"tenant_id must be an int, got {tenant_id!r}")
    return TenantScope(tenant_id=tenant_id)


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
