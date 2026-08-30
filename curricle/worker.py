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

A run takes exactly two transactions, and the split is the important part.
The first claims the row and commits it `running` — so the claim is a fact
the moment it is made, visible to anything that looks, and a stage that then
falls over cannot be handed out again by a rollback. The handler runs with
no transaction open at all, because a stage is minutes of model calls and
holding a row lock across them would be a database problem waiting to
happen. The second appends the outcome event and finishes the run row
together: *that* pair is the invariant worth an atom, since an outcome the
ledger records but the queue thinks is still going (or the reverse) is drift
nobody can reconstruct afterwards. What is not covered — and never was — is
whatever a handler wrote while it ran: `token_ledger` rows are committed by
the runner as the money is spent, which is exactly right for a spend record,
and no rollback here un-spends them.

The cost of committing the claim early is a run that can be left `running`
by a worker that dies mid-stage. Nothing sweeps that automatically at
runtime, because a worker cannot tell the difference between a peer's live
run and a dead one's wreckage — but at startup it can: the advisory lock
proves no other worker is alive, so every `running` row is wreckage, and it
is failed with reason `interrupted`. Deliberately *not* re-run: an automatic
retry after a crash re-spends real money on the learner's behalf without
being asked. The human sees an honest failure and a retry button.

T1 runs through all of it: the tenant comes from the claimed row and from
nowhere else. The worker serves every tenant and has no ambient one;
`db.for_tenant(run.tenant_id)` is the only scope a handler ever sees.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

import sqlalchemy as sa
import yaml

from . import coursehome, db, factory, llm, onboarding, profile
from .compiler import compile_course
from .sidecar import load_sidecar

# A handler runs one claimed stage. It returns the outcome to append to the
# onboarding ledger, or None (nothing to record — the noop stage).
#   handler(engine, scope, run) -> tuple[event_kind, payload] | None
# `run` is the claimed row (id, tenant_id, course, stage, payload).
Handler = Callable[[sa.Engine, db.TenantScope, sa.Row],
                   "tuple[str, dict] | None"]

# How a stage builds the thing that spends money. A seam, not a setting:
# tests hand back a Runner whose transport is scripted, and the process that
# serves web requests never reaches this module at all. Production has
# exactly one answer and it is the default.
RUNNER_FACTORY = llm.Runner


class StageFailed(RuntimeError):
    """A stage refusing in the ledger's own vocabulary.

    `reason` is a REASONS key, which is what makes this different from any
    other exception a handler can raise: `_reason_of` takes it at its word
    and the wizard has a sentence ready for it. Everything without one is a
    `worker_error`, honestly recorded as the bug it is.
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def _noop(engine: sa.Engine, scope: db.TenantScope, run: sa.Row) -> None:
    """The stage that proves the machinery without spending a token.

    Slice 1 of the build order runs end to end before any role exists
    (design §10), and a stage the worker can run for free stays useful long
    after as the smoke test for everything around it.
    """
    return None


def _outline(engine: sa.Engine, scope: db.TenantScope,
             run: sa.Row) -> tuple[str, dict]:
    """Stop 7: draft this course's outline, and price building phase 1 of it.

    Everything the stage needs comes from the claimed row's tenant (T1): the
    scope out of that tenant's onboarding fold, the profile out of that
    tenant's evidence fold, and a runner whose spend is metered against that
    tenant's ledger. The worker has no tenant of its own to fall back on.

    One short read, and then no transaction at all. The draft is minutes of
    model calls, and `run_once` has already committed the claim precisely so
    that nothing here has to hold a row lock across them; the outcome this
    returns is what the second transaction records. A worker that dies in
    the middle leaves a `running` row for the next one's startup sweep,
    which fails it honestly as `interrupted` rather than re-spending.

    The plan and the estimate are computed here rather than at the gate
    because they are what the gate is a gate *on*: the learner approves a
    number, and O3 says the row carries the number they were shown.
    """
    with engine.begin() as conn:
        flow = onboarding.load_state(conn, scope).flows.get(run.course)
        prof = profile.load_profile(conn, scope)
    if flow is None or not flow.scope:
        # Not a stage failure in the ledger's sense — it is a run enqueued
        # for a course nobody scoped, which is a bug in whoever enqueued it.
        raise StageFailed("worker_error",
                          f"no saved scope for course {run.course!r}")

    # Asked before the runner is built, so an unconfigured courses home
    # fails the run before it can spend anything. There is no default home
    # and this is not the place to invent one.
    draft_dir = os.path.join(coursehome.courses_dir(), run.course,
                             ".draft-onboarding")
    runner = RUNNER_FACTORY(engine, scope)
    try:
        factory.build_outline(runner, prof, run.course, flow.scope, draft_dir,
                              note=run.payload.get("note") or flow.note)
    except llm.BudgetExceeded as exc:
        # The runner refuses in money's vocabulary; the ledger has a key for
        # it and the wizard has a sentence. Wrapped rather than re-raised
        # bare, because `BudgetExceeded` carries no reason of its own.
        raise StageFailed("budget_exceeded", str(exc)) from exc

    # The draft was already compiled clean by the stage that wrote it; this
    # is the same compile again for the manifest itself, which is what the
    # plan is derived from. A refusal here would mean the two disagreed.
    try:
        sidecar = load_sidecar(os.path.join(draft_dir, factory.OUTLINE_FILES[1]))
        manifest, issues = compile_course(draft_dir, sidecar)
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        # The same set the outline stage's own validator guards with: the
        # sidecar loader raises through what it cannot turn into a finding.
        raise StageFailed("compile_failed",
                          f"{type(exc).__name__}: {exc}") from exc
    if manifest is None:
        raise StageFailed("compile_failed",
                          "\n".join(str(i) for i in issues if i.level == "error"))

    try:
        plan = factory.default_build_plan(manifest)
    except ValueError as exc:
        # An outline that compiles and still has no phase 1, or a phase 1
        # with no units in it: a shape this system accepts from the compiler
        # and cannot build from. That is the outline being wrong, not the
        # worker breaking, so it is worded as such and the retry is offered.
        raise StageFailed("validation_failed", str(exc)) from exc
    estimate = factory.estimate_build_cost(runner.config, plan)
    return "outline_ready", {"plan": plan, "estimate_usd": f"{estimate:.2f}"}


HANDLERS: dict[str, Handler] = {"noop": _noop, "outline": _outline}

# What a stage says in the ledger when it fails — because its handler
# raised, because the outcome it returned was refused, or because the worker
# running it was interrupted. A stage without an entry here has no failure
# vocabulary yet, so a failure of it is recorded on the run row alone.
FAILURE_KINDS = {
    "outline": "outline_failed",
    "build": "build_failed",
    "promote": "promote_failed",
}


def run_once(engine: sa.Engine,
             handlers: dict[str, Handler] | None = None) -> bool:
    """Claim and run at most one queued run. True if there was one.

    Two transactions, per the module docstring: the claim commits before the
    stage starts, and the outcome event and the finished run row commit
    together afterwards. The handler runs between them with nothing open.
    """
    handlers = HANDLERS if handlers is None else handlers
    with engine.begin() as conn:            # transaction 1: the claim
        run = db.claim_next_run(conn)
        if run is None:
            return False
        # T1: the tenant is this row's, never an ambient one. The worker
        # process has no tenant of its own to fall back to.
        scope = db.for_tenant(run.tenant_id)
        superseded = _superseded(conn, scope, run)

    if superseded:
        # The fold treats `promoted` as absorbing, so a late outcome could
        # not resurrect a finished course anyway — but the fold protects the
        # screen, and this protects the budget. A run for a course that is
        # already published has nothing left to buy.
        with engine.begin() as conn:
            db.finish_run(conn, run.id, "done", "superseded")
        return True

    handler = handlers.get(run.stage)
    if handler is None:
        # No handler is not a stage failure: the stage never started, so its
        # vocabulary never applied and there is nothing truthful to append.
        # The run row carries the reason for an operator, and the wizard's
        # wording table has a sentence for the day one of these reaches a
        # learner.
        with engine.begin() as conn:
            db.finish_run(conn, run.id, "failed", "unknown_stage")
        return True

    try:
        outcome = handler(engine, scope, run)
    except Exception as exc:
        # Nothing is re-raised: one stage falling over is a row, not the end
        # of the worker.
        _record_failure(engine, scope, run, _reason_of(exc), str(exc))
        return True

    try:
        with engine.begin() as conn:        # transaction 2: outcome + finish
            if outcome is not None:
                kind, payload = outcome
                onboarding.append_event(conn, scope, kind, run.course, payload)
            db.finish_run(conn, run.id, "done")
    except (onboarding.InvalidOnboardingEvent, TypeError, ValueError) as exc:
        # A handler that returns an outcome the ledger refuses — a malformed
        # payload, or something that isn't a (kind, payload) pair at all — is
        # a bug in the handler, and it is treated exactly like a handler that
        # raised: the invalid outcome is not recorded, the stage's failure
        # is, and the run ends failed rather than being tried forever. (The
        # first two are the same class; both are named because the shapes a
        # handler can get wrong are the point of catching here.)
        _record_failure(engine, scope, run, "worker_error", str(exc))
    return True


def _record_failure(engine: sa.Engine, scope: db.TenantScope, run: sa.Row,
                    reason: str, detail: str) -> None:
    """One transaction: the stage's failure event, and the finished row.

    A stage with no entry in FAILURE_KINDS has no failure vocabulary yet, so
    its failure is recorded on the run row alone — the ledger says nothing
    rather than something it cannot mean.
    """
    with engine.begin() as conn:
        kind = FAILURE_KINDS.get(run.stage)
        if kind is not None:
            onboarding.append_event(conn, scope, kind, run.course,
                                    {"reason": reason, "detail": detail[:500]})
        db.finish_run(conn, run.id, "failed", reason)


def sweep_interrupted(engine: sa.Engine) -> int:
    """Fail every run still `running`, as the wreckage of a dead worker.

    Only ever safe to call while holding the worker lock: the lock is the
    proof that no other worker is alive, and therefore that a `running` row
    is nobody's live claim. The runs are failed, never re-run — a crash that
    silently re-spends the learner's money is worse than a failure they can
    see and retry.
    """
    with engine.begin() as conn:
        stale = db.stale_runs(conn)
        for run in stale:
            scope = db.for_tenant(run.tenant_id)
            kind = FAILURE_KINDS.get(run.stage)
            if kind is not None:
                onboarding.append_event(
                    conn, scope, kind, run.course,
                    {"reason": "interrupted",
                     "detail": "the worker holding this run did not survive "
                               "to report it"})
            db.finish_run(conn, run.id, "failed", "interrupted")
    return len(stale)


def _superseded(conn: sa.Connection, scope: db.TenantScope,
                run: sa.Row) -> bool:
    """Has this run's course already been promoted?"""
    flow = onboarding.load_state(conn, scope).flows.get(run.course)
    return flow is not None and flow.stage == "done"


def _reason_of(exc: Exception) -> str:
    """The machine reason key a failed stage reports.

    A handler that means something specific says so by carrying a `reason`;
    anything else is a worker error. A key the ledger's vocabulary has never
    heard of would be refused by `append_event`, which would leave the
    failure unrecorded — so an unknown key is treated as the bug it is: the
    failure is still recorded, under the honest reason, with the handler's
    own words in `detail`.
    """
    reason = getattr(exc, "reason", None)
    return reason if reason in onboarding.REASONS else "worker_error"


def main(engine: sa.Engine, poll: float = 2.0, once: bool = False) -> int:
    """Hold the worker lock, clear the last worker's wreckage, and drain.

    One worker per database, enforced by the advisory lock rather than by
    hoping: a second `work` process refuses to start rather than racing the
    first for claims it would mostly skip anyway. Holding the lock is also
    what makes the startup sweep safe to do — see sweep_interrupted.
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

        # The lock is held, so nothing else is running a stage anywhere in
        # this database: whatever is still `running` belongs to a worker that
        # died, and it is failed rather than quietly retried.
        interrupted = sweep_interrupted(engine)
        if interrupted:
            print(f"swept {interrupted} interrupted run(s) from a previous "
                  "worker", file=sys.stderr)

        while True:
            worked = run_once(engine)
            if once:
                return 0
            if not worked:
                time.sleep(poll)
