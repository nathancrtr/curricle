"""The worker: claim a queued run, run its stage, append the outcome.

L1 says no LLM on a request path, ever, so the onboarding stages that talk
to a model do not run inside `serve`. They run here, in `python -m curricle
work` — "a separate process beside `serve`, sharing the database and nothing
else" (onboarding-design.md §6). The web app writes request rows and reads
outcome rows; it never imports the model runner, and a grep guard keeps it
honest.

This is deliberately the thin slice of the queue platform-design §6.1
already plans, not a rival to it: one process, one claim at a time, and no
retry scheduling at all — the wizard's retry button *is* the scheduler. A
failed stage is simply requested again, which is a row, which is the fold's
business rather than this module's.

Two rules hold the ledger and the queue together. First, a claim, its
stage, and its outcome share one transaction, so a run row and the ledger
can never disagree about what happened — an outcome without a finished run
is the sort of drift nobody can reconstruct afterwards. Second, T1: the
tenant comes from the claimed row and from nowhere else. The worker serves
every tenant and has no ambient one; `db.for_tenant(run.tenant_id)` is the
only scope a handler ever sees.
"""

from __future__ import annotations

import sys
import time
from typing import Callable

import sqlalchemy as sa

from . import db, onboarding

# A handler runs one claimed stage. It returns the outcome to append to the
# onboarding ledger, or None (nothing to record — the noop stage).
#   handler(engine, scope, run) -> tuple[event_kind, payload] | None
# `run` is the claimed row (id, tenant_id, course, stage, payload).
Handler = Callable[[sa.Engine, db.TenantScope, sa.Row],
                   "tuple[str, dict] | None"]


def _noop(engine: sa.Engine, scope: db.TenantScope, run: sa.Row) -> None:
    """The stage that proves the machinery without spending a token.

    Slice 1 of the build order runs end to end before any role exists
    (design §10), and a stage the worker can run for free stays useful long
    after as the smoke test for everything around it.
    """
    return None


HANDLERS: dict[str, Handler] = {"noop": _noop}

# What a stage says in the ledger when its handler raises. A stage without
# an entry here has no failure vocabulary yet, so a failure of it is recorded
# on the run row alone — see run_once.
FAILURE_KINDS = {
    "outline": "outline_failed",
    "build": "build_failed",
    "promote": "promote_failed",
}


def run_once(engine: sa.Engine,
             handlers: dict[str, Handler] | None = None) -> bool:
    """Claim and run at most one queued run. True if there was one.

    Everything happens inside the claim's transaction, including the stage
    itself: the run row stays locked while its handler works, so the outcome
    event and the finished run row commit together or not at all.
    """
    handlers = HANDLERS if handlers is None else handlers
    with engine.begin() as conn:
        run = db.claim_next_run(conn)
        if run is None:
            return False
        # T1: the tenant is this row's, never an ambient one. The worker
        # process has no tenant of its own to fall back to.
        scope = db.for_tenant(run.tenant_id)

        if _superseded(conn, scope, run):
            # The fold treats `promoted` as absorbing, so a late outcome
            # could not resurrect a finished course anyway — but the fold
            # protects the screen, and this protects the budget. A run for a
            # course that is already published has nothing left to buy.
            db.finish_run(conn, run.id, "done", "superseded")
            return True

        handler = handlers.get(run.stage)
        if handler is None:
            # No handler is not a stage failure: the stage never started, so
            # its vocabulary never applied and there is nothing truthful to
            # append. The run row carries the reason for an operator, and
            # the wizard's wording table has a sentence for the day one of
            # these reaches a learner.
            db.finish_run(conn, run.id, "failed", "unknown_stage")
            return True

        try:
            outcome = handler(engine, scope, run)
        except Exception as exc:
            reason = _reason_of(exc)
            failure_kind = FAILURE_KINDS.get(run.stage)
            if failure_kind is not None:
                onboarding.append_event(
                    conn, scope, failure_kind, run.course,
                    {"reason": reason, "detail": str(exc)[:500]})
            db.finish_run(conn, run.id, "failed", reason)
            # Nothing is re-raised: one stage falling over is a row, not the
            # end of the worker.
            return True

        if outcome is not None:
            kind, payload = outcome
            onboarding.append_event(conn, scope, kind, run.course, payload)
        db.finish_run(conn, run.id, "done")
        return True


def _superseded(conn: sa.Connection, scope: db.TenantScope,
                run: sa.Row) -> bool:
    """Has this run's course already been promoted?"""
    flow = onboarding.load_state(conn, scope).flows.get(run.course)
    return flow is not None and flow.stage == "done"


def _reason_of(exc: Exception) -> str:
    """The machine reason key a failed stage reports.

    A handler that means something specific says so by carrying a `reason`;
    anything else is a worker error. A key the ledger's vocabulary has never
    heard of would be refused by `append_event` — and refusing there would
    roll back the claim and hand the same run out forever — so an unknown
    key is treated as the bug it is: the failure is still recorded, under
    the honest reason, with the handler's own words in `detail`.
    """
    reason = getattr(exc, "reason", None)
    return reason if reason in onboarding.REASONS else "worker_error"


def main(engine: sa.Engine, poll: float = 2.0, once: bool = False) -> int:
    """Hold the worker lock and drain the queue until killed.

    One worker per database, enforced by the advisory lock rather than by
    hoping: a second `work` process refuses to start rather than racing the
    first for claims it would mostly skip anyway.
    """
    # Detached from the pool on purpose. The lock is session-scoped, so this
    # has to be a session that ends when the worker does — a connection
    # returned to the pool is only rolled back, and an advisory lock would
    # ride it into the next borrower.
    lock_conn = engine.connect()
    lock_conn.detach()
    with lock_conn:
        if not db.try_worker_lock(lock_conn):
            print("another worker holds the lock", file=sys.stderr)
            return 1
        # The lock is not transactional: committing here ends the read and
        # leaves the worker holding the lock, rather than sitting idle in a
        # transaction for its whole life.
        lock_conn.commit()

        while True:
            worked = run_once(engine)
            if once:
                return 0
            if not worked:
                time.sleep(poll)
