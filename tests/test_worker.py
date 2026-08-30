"""The worker: what it claims, what it records, and who can see it running.

Everything here runs against the throwaway Postgres of tests/pg.py, because
the three things worth testing about a worker are all database behaviour:
`FOR UPDATE SKIP LOCKED` claiming, the atomicity of an outcome with its run
row, and an advisory lock two other sessions can observe. A fake queue would
prove none of them.

Two tenants per fixture (T5), and the handlers assert the scope they are
handed — the worker has no tenant of its own, so T1 here means the claimed
row's `tenant_id` and nothing else reaching the stage.

The queue is global by construction (the worker claims across tenants), so
each fixture retires whatever another module left queued or running before
asserting anything about order. That is a property of the table, not a wart
in the tests: a run left queued anywhere is a run this worker would take,
and one left running is one its startup sweep would fail.
"""

import contextlib
import io
import unittest

import sqlalchemy as sa

from curricle import db, onboarding, worker

from pg import test_engine

OUTLINE = {"plan": {"phases": [{"id": "p1", "title": "Phase 1"}]},
           "estimate_usd": "4.20"}


def session(engine):
    """A connection that is a real session rather than a pooled one.

    Session-scoped advisory locks outlive a rollback, and returning a
    connection to the pool only rolls it back — so a lock taken on a pooled
    connection would ride it into the next borrower. Detaching makes close()
    end the session, which is the property the worker depends on.
    """
    conn = engine.connect()
    conn.detach()
    return conn


class WorkerFixture(unittest.TestCase):
    """Two tenants and an empty queue. No tests of its own."""

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, f"worker-{cls.__name__}-a")
            cls.b = db.create_tenant(conn, f"worker-{cls.__name__}-b")
            conn.execute(sa.update(db.factory_runs)
                         .where(db.factory_runs.c.status.in_(("queued",
                                                              "running")))
                         .values(status="done", finished_at=sa.func.now()))

    def runs(self, tenant_id: int):
        """This tenant's run rows, in id order, whatever their status."""
        with self.engine.begin() as conn:
            return conn.execute(
                sa.select(db.factory_runs)
                .where(db.factory_runs.c.tenant_id == tenant_id)
                .order_by(db.factory_runs.c.id)).all()

    def ledger(self, tenant_id: int, course: str):
        """(kind, payload) for one tenant's course, in ledger order."""
        scope = db.for_tenant(tenant_id)
        with self.engine.begin() as conn:
            return [(r.kind, r.payload)
                    for r in conn.execute(scope.onboarding_select())
                    if r.course == course]

    def enqueue(self, tenant_id: int, course: str, stage: str,
                payload: dict | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(db.for_tenant(tenant_id)
                         .runs_insert(course, stage, payload or {}))

    def strand(self, tenant_id: int, course: str, stage: str) -> None:
        """A run left `running` — what a worker that died mid-stage leaves."""
        with self.engine.begin() as conn:
            conn.execute(db.for_tenant(tenant_id).runs_insert(course, stage, {}))
            conn.execute(sa.update(db.factory_runs)
                         .where(db.factory_runs.c.tenant_id == tenant_id,
                                db.factory_runs.c.course == course,
                                db.factory_runs.c.status == "queued")
                         .values(status="running", claimed_at=sa.func.now()))


class ClaimTest(WorkerFixture):
    def test_queued_runs_are_claimed_in_id_order_and_finished(self):
        seen = []

        def record(engine, scope, run):
            # T1: the scope a handler works through is the claimed row's
            # tenant, never an ambient one — the worker has none.
            self.assertEqual(scope.tenant_id, run.tenant_id)
            seen.append((scope.tenant_id, run.course, run.stage))
            return None

        self.enqueue(self.a, "greek-101", "noop")
        self.enqueue(self.b, "latin-201", "noop")

        handlers = {"noop": record}
        self.assertTrue(worker.run_once(self.engine, handlers))
        self.assertTrue(worker.run_once(self.engine, handlers))
        # Nothing left: an idle worker says so rather than inventing work.
        self.assertFalse(worker.run_once(self.engine, handlers))

        self.assertEqual(seen, [(self.a, "greek-101", "noop"),
                                (self.b, "latin-201", "noop")])
        for tenant, course in ((self.a, "greek-101"), (self.b, "latin-201")):
            row, = [r for r in self.runs(tenant) if r.course == course]
            self.assertEqual((row.status, row.reason), ("done", None))
            self.assertIsNotNone(row.claimed_at)
            self.assertIsNotNone(row.finished_at)

    def test_a_noop_run_records_nothing_in_the_ledger(self):
        # The stage that proves the machinery has no outcome to append: a
        # ledger row for it would be a row about the worker, not the learner.
        self.enqueue(self.a, "noop-course", "noop")
        self.assertTrue(worker.run_once(self.engine))
        self.assertEqual(self.ledger(self.a, "noop-course"), [])


class DispatchTest(WorkerFixture):
    def test_an_unknown_stage_fails_the_run_and_says_nothing_in_the_ledger(self):
        # `outline` has a failure kind, and it still gets no event: no
        # handler means the stage never started, so its vocabulary never
        # applied. That is a different thing from a stage that ran and broke,
        # and the ledger should not blur them.
        self.enqueue(self.a, "unhandled", "outline")
        self.assertTrue(worker.run_once(self.engine, {"noop": worker._noop}))

        row, = [r for r in self.runs(self.a) if r.course == "unhandled"]
        self.assertEqual((row.status, row.reason), ("failed", "unknown_stage"))
        self.assertEqual(self.ledger(self.a, "unhandled"), [])
        # O2: unworded reasons are the failure mode this pins against.
        self.assertIn(("outline", "unknown_stage"), onboarding.WORDING)

    def test_a_raising_handler_becomes_the_stages_failure_event(self):
        def boom(engine, scope, run):
            raise RuntimeError("the model hung up: " + "x" * 900)

        self.enqueue(self.a, "broken", "outline")
        self.assertTrue(worker.run_once(self.engine, {"outline": boom}))

        row, = [r for r in self.runs(self.a) if r.course == "broken"]
        self.assertEqual((row.status, row.reason), ("failed", "worker_error"))
        (kind, payload), = self.ledger(self.a, "broken")
        self.assertEqual(kind, "outline_failed")
        self.assertEqual(payload["reason"], "worker_error")
        # Operator detail, truncated: a traceback is not a screen's business.
        self.assertTrue(payload["detail"].startswith("the model hung up"))
        self.assertEqual(len(payload["detail"]), 500)

    def test_a_handler_that_names_its_reason_is_taken_at_its_word(self):
        class Refused(RuntimeError):
            reason = "budget_exceeded"

        self.enqueue(self.b, "expensive", "build")
        def raise_refused(engine, scope, run):
            raise Refused("stage budget spent")
        self.assertTrue(worker.run_once(self.engine, {"build": raise_refused}))

        row, = [r for r in self.runs(self.b) if r.course == "expensive"]
        self.assertEqual((row.status, row.reason), ("failed", "budget_exceeded"))
        (kind, payload), = self.ledger(self.b, "expensive")
        self.assertEqual((kind, payload["reason"]),
                         ("build_failed", "budget_exceeded"))

    def test_a_reason_outside_the_vocabulary_is_recorded_as_a_worker_error(self):
        # A key the ledger has never heard of would be refused by
        # append_event, and refusing inside the claim's transaction would
        # roll the claim back and hand the same run out forever. The failure
        # is recorded under the honest reason instead, with the handler's own
        # words kept in `detail` for whoever has to fix the handler.
        class Odd(RuntimeError):
            reason = "vibes"

        self.enqueue(self.b, "odd", "build")
        def raise_odd(engine, scope, run):
            raise Odd("something the vocabulary cannot say")
        self.assertTrue(worker.run_once(self.engine, {"build": raise_odd}))

        row, = [r for r in self.runs(self.b) if r.course == "odd"]
        self.assertEqual((row.status, row.reason), ("failed", "worker_error"))
        (_, payload), = self.ledger(self.b, "odd")
        self.assertEqual(payload["reason"], "worker_error")
        self.assertIn("vocabulary cannot say", payload["detail"])

    def test_an_outcome_and_its_run_row_commit_together(self):
        def ready(engine, scope, run):
            self.assertEqual(scope.tenant_id, self.a)
            return "outline_ready", OUTLINE

        self.enqueue(self.a, "planned", "outline", {"topic": "koine"})
        self.assertTrue(worker.run_once(self.engine, {"outline": ready}))

        row, = [r for r in self.runs(self.a) if r.course == "planned"]
        self.assertEqual((row.status, row.reason), ("done", None))
        (kind, payload), = self.ledger(self.a, "planned")
        self.assertEqual(kind, "outline_ready")
        self.assertEqual(payload["estimate_usd"], "4.20")

    def test_an_outcome_the_ledger_refuses_fails_the_run_and_frees_the_queue(self):
        # The poison pill. A handler that returns a payload the ledger won't
        # accept used to raise out of the claim's own transaction, rolling
        # the claim back — the run went straight back to `queued` and the
        # worker spent the rest of its life re-claiming it. Now the claim is
        # already committed and a refused outcome is the handler's bug: the
        # run ends failed, the invalid outcome is not recorded, and the queue
        # moves on.
        def malformed(engine, scope, run):
            return "outline_ready", {"plan": "not-a-dict",
                                     "estimate_usd": "4.20"}

        self.enqueue(self.a, "poison", "outline")
        self.enqueue(self.a, "after-poison", "noop")
        handlers = {"outline": malformed, "noop": worker._noop}
        self.assertTrue(worker.run_once(self.engine, handlers))

        row, = [r for r in self.runs(self.a) if r.course == "poison"]
        self.assertEqual((row.status, row.reason), ("failed", "worker_error"))
        # The stage's failure is recorded the way any other failure is; what
        # is not recorded is the outcome the ledger refused.
        (kind, payload), = self.ledger(self.a, "poison")
        self.assertEqual((kind, payload["reason"]),
                         ("outline_failed", "worker_error"))
        self.assertIn("plan", payload["detail"])

        # The queue proceeds: the next run is claimed, not the poisoned one.
        self.assertTrue(worker.run_once(self.engine, handlers))
        after, = [r for r in self.runs(self.a) if r.course == "after-poison"]
        self.assertEqual(after.status, "done")

    def test_the_claim_is_committed_before_the_stage_starts(self):
        # The two-transaction shape, seen from outside: while the handler
        # works, another session already sees the run as `running`. Under one
        # transaction it would have seen `queued` (and a stage's minutes of
        # model calls would have held a row lock the whole time).
        seen = []

        def look(engine, scope, run):
            with engine.connect() as other:
                seen.append(other.execute(
                    sa.select(db.factory_runs.c.status)
                    .where(db.factory_runs.c.id == run.id)).scalar())
            return None

        self.enqueue(self.a, "watched", "noop")
        self.assertTrue(worker.run_once(self.engine, {"noop": look}))
        self.assertEqual(seen, ["running"])
        row, = [r for r in self.runs(self.a) if r.course == "watched"]
        self.assertEqual(row.status, "done")

    def test_a_promoted_course_supersedes_its_queued_runs(self):
        def never(engine, scope, run):
            raise AssertionError("a promoted course has nothing left to buy")

        scope = db.for_tenant(self.a)
        with self.engine.begin() as conn:
            onboarding.append_event(conn, scope, "scope_saved", "finished",
                                    {"topic": "koine"})
            onboarding.append_event(conn, scope, "promoted", "finished",
                                    {"course_id": "finished"})
        self.enqueue(self.a, "finished", "build")
        self.assertTrue(worker.run_once(self.engine, {"build": never}))

        row, = [r for r in self.runs(self.a) if r.course == "finished"]
        self.assertEqual((row.status, row.reason), ("done", "superseded"))
        # No outcome event: the run bought nothing, so it reports nothing.
        self.assertEqual([k for k, _ in self.ledger(self.a, "finished")],
                         ["scope_saved", "promoted"])


class LivenessTest(WorkerFixture):
    def test_the_lock_is_what_other_processes_see(self):
        with session(self.engine) as observer:
            self.assertFalse(db.worker_alive(observer))

            with session(self.engine) as holder:
                self.assertTrue(db.try_worker_lock(holder))
                self.assertTrue(db.worker_alive(observer))
                # One worker per database: the second asks and is refused,
                # rather than racing the first for claims.
                with session(self.engine) as rival:
                    self.assertFalse(db.try_worker_lock(rival))

            # Liveness dies with the session — no staleness window to tune.
            self.assertFalse(db.worker_alive(observer))


class MainTest(WorkerFixture):
    def test_once_processes_a_single_run_and_returns_zero(self):
        self.enqueue(self.a, "once-course", "noop")
        self.enqueue(self.a, "second-course", "noop")
        self.assertEqual(worker.main(self.engine, once=True), 0)

        statuses = [(r.course, r.status) for r in self.runs(self.a)]
        self.assertEqual(statuses, [("once-course", "done"),
                                    ("second-course", "queued")])

    def test_once_on_an_empty_queue_still_returns_zero(self):
        self.assertEqual(worker.main(self.engine, once=True), 0)

    def test_a_second_worker_refuses_to_start(self):
        with session(self.engine) as holder:
            self.assertTrue(db.try_worker_lock(holder))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(worker.main(self.engine, once=True), 1)
        self.assertIn("another worker holds the lock", err.getvalue())

    def test_main_leaves_no_lock_behind(self):
        # The worker's lock connection is detached from the pool, so the
        # session really ends when main returns; a pooled connection would
        # carry the lock into the next borrower and the next worker would
        # refuse to start for no reason.
        self.assertEqual(worker.main(self.engine, once=True), 0)
        with self.engine.connect() as conn:
            self.assertFalse(db.worker_alive(conn))


class SkipLockedTest(WorkerFixture):
    def test_a_claimed_row_is_passed_over_never_waited_on(self):
        self.enqueue(self.a, "first", "noop")
        self.enqueue(self.b, "second", "noop")

        with self.engine.connect() as one, self.engine.connect() as two:
            first = db.claim_next_run(one)          # holds the row's lock
            second = db.claim_next_run(two)         # must skip it
            self.assertEqual(first.course, "first")
            self.assertEqual(second.course, "second")
            self.assertNotEqual(first.id, second.id)
            # T1 again, at the claim: each row carries its own tenant.
            self.assertEqual((first.tenant_id, second.tenant_id),
                             (self.a, self.b))

            # With both rows held, a third session finds nothing rather than
            # blocking on somebody else's claim.
            with self.engine.connect() as three:
                self.assertIsNone(db.claim_next_run(three))

            one.rollback()
            two.rollback()

        # Rolled back, the claims never happened: the rows are queued again.
        with self.engine.begin() as conn:
            statuses = conn.execute(
                sa.select(db.factory_runs.c.status)
                .where(db.factory_runs.c.id.in_([first.id, second.id]))).all()
        self.assertEqual([s.status for s in statuses], ["queued", "queued"])


class SweepTest(WorkerFixture):
    """What the next worker does with a dead one's claims."""

    def test_a_stranded_run_is_failed_at_startup_and_the_queue_proceeds(self):
        self.strand(self.a, "abandoned", "build")
        self.enqueue(self.a, "next-up", "noop")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(worker.main(self.engine, once=True), 0)
        self.assertIn("swept 1 interrupted run(s)", err.getvalue())

        stranded, = [r for r in self.runs(self.a) if r.course == "abandoned"]
        self.assertEqual((stranded.status, stranded.reason),
                         ("failed", "interrupted"))
        self.assertIsNotNone(stranded.finished_at)
        (kind, payload), = self.ledger(self.a, "abandoned")
        self.assertEqual((kind, payload["reason"]),
                         ("build_failed", "interrupted"))
        # O2: the reason the sweep invents has a sentence like any other.
        self.assertIn(("build", "interrupted"), onboarding.WORDING)
        # Failed, never re-run: a crash must not re-spend the learner's money
        # unasked. Retrying is theirs to ask for.
        self.assertEqual(
            [r.status for r in self.runs(self.a) if r.course == "abandoned"],
            ["failed"])
        # And the sweep is not the end of the worker: it goes on to claim.
        nxt, = [r for r in self.runs(self.a) if r.course == "next-up"]
        self.assertEqual(nxt.status, "done")

    def test_a_stage_with_no_failure_vocabulary_is_swept_on_the_row_alone(self):
        # `noop` has no `*_failed` kind, so the ledger says nothing about it
        # rather than saying something it cannot mean.
        self.strand(self.b, "abandoned-noop", "noop")
        self.assertEqual(worker.sweep_interrupted(self.engine), 1)

        row, = [r for r in self.runs(self.b) if r.course == "abandoned-noop"]
        self.assertEqual((row.status, row.reason), ("failed", "interrupted"))
        self.assertEqual(self.ledger(self.b, "abandoned-noop"), [])

    def test_an_empty_sweep_touches_nothing(self):
        self.assertEqual(worker.sweep_interrupted(self.engine), 0)


if __name__ == "__main__":
    unittest.main()
