"""The onboarding ledger and the factory-runs queue: store-level guarantees,
then the fold that turns those rows into a wizard stop.

Two tenants from the first fixture (T5), the same as the progress suite: a
single-tenant fixture passes whether or not the scope does anything, because
it has nothing to leak toward. Everything here runs against the throwaway
Postgres of tests/pg.py, so every run also proves migration 0004 upgrades.
The fold tests need none of that — a pure function over tuples is tested
over tuples.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from curricle import db, onboarding, profile

from pg import test_engine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLOCK = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def ev(kind, course="greek-101", payload=None, at=CLOCK):
    """One ledger row as the fold sees it: (kind, course, payload, created_at)."""
    return (kind, course, payload or {}, at)


OUTLINE = {"plan": {"phases": [{"id": "p1", "title": "Phase 1"}]},
           "estimate_usd": "4.20"}


class OnboardingLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, "onboarding-a")
            cls.b = db.create_tenant(conn, "onboarding-b")

    def test_append_and_read_back_in_id_order(self):
        scope = db.for_tenant(self.a)
        with self.engine.begin() as conn:
            conn.execute(scope.onboarding_insert("profile_published", "", {}))
            conn.execute(scope.onboarding_insert(
                "scope_saved", "greek-101", {"topic": "koine"}))
            conn.execute(scope.onboarding_insert(
                "outline_requested", "greek-101", {}))
            rows = conn.execute(scope.onboarding_select()).all()
        self.assertEqual([r.kind for r in rows],
                         ["profile_published", "scope_saved", "outline_requested"])
        self.assertEqual([r.course for r in rows], ["", "greek-101", "greek-101"])
        self.assertEqual(rows[1].payload, {"topic": "koine"})
        self.assertEqual([r.id for r in rows], sorted(r.id for r in rows))

    def test_tenants_do_not_leak(self):
        scope_a, scope_b = db.for_tenant(self.a), db.for_tenant(self.b)
        with self.engine.begin() as conn:
            conn.execute(scope_b.onboarding_insert(
                "promoted", "b-only", {"course_id": "b-only"}))
            courses_a = [r.course for r in conn.execute(scope_a.onboarding_select())]
            courses_b = [r.course for r in conn.execute(scope_b.onboarding_select())]
        self.assertNotIn("b-only", courses_a)
        self.assertEqual(courses_b, ["b-only"])

    def test_unknown_kind_is_refused_by_the_database_too(self):
        # The CHECK constraint holds even if application validation is bypassed.
        with self.engine.connect() as conn:
            with self.assertRaises(sa.exc.IntegrityError):
                conn.execute(sa.insert(db.onboarding_events).values(
                    tenant_id=self.a, course="greek-101",
                    kind="vibes_published", payload={}))
            conn.rollback()


class FactoryRunsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, "runs-a")
            cls.b = db.create_tenant(conn, "runs-b")

    def test_a_queued_run_is_pending_and_scoped(self):
        scope_a, scope_b = db.for_tenant(self.a), db.for_tenant(self.b)
        with self.engine.begin() as conn:
            conn.execute(scope_a.runs_insert("greek-101", "noop", {}))
            conn.execute(scope_a.runs_insert(
                "greek-101", "outline", {"scope": "koine"}))
            conn.execute(scope_a.runs_insert("other-course", "build", {}))
            conn.execute(scope_b.runs_insert("greek-101", "outline", {}))
            rows = conn.execute(scope_a.runs_pending("greek-101")).all()
        self.assertEqual([r.stage for r in rows], ["noop", "outline"])
        # status defaults in the database; claimed_at waits for the worker.
        self.assertEqual([r.status for r in rows], ["queued", "queued"])
        self.assertIsNone(rows[0].claimed_at)

    def test_finished_runs_are_not_pending(self):
        # A claimed run is the control: pending spans queued *and* running,
        # because a run the worker is holding is exactly the one the wizard
        # has to show as "a machine's turn".
        scope = db.for_tenant(self.a)
        with self.engine.begin() as conn:
            conn.execute(scope.runs_insert("done-course", "noop", {}))
            conn.execute(scope.runs_insert("done-course", "outline", {}))
            conn.execute(sa.update(db.factory_runs)
                         .where(db.factory_runs.c.course == "done-course",
                                db.factory_runs.c.stage == "noop")
                         .values(status="done", finished_at=sa.func.now()))
            conn.execute(sa.update(db.factory_runs)
                         .where(db.factory_runs.c.course == "done-course",
                                db.factory_runs.c.stage == "outline")
                         .values(status="running", claimed_at=sa.func.now()))
            rows = conn.execute(scope.runs_pending("done-course")).all()
        self.assertEqual([(r.stage, r.status) for r in rows],
                         [("outline", "running")])
        self.assertIsNotNone(rows[0].claimed_at)

    def test_unknown_stage_and_status_are_refused_by_the_database(self):
        with self.engine.connect() as conn:
            with self.assertRaises(sa.exc.IntegrityError):
                conn.execute(sa.insert(db.factory_runs).values(
                    tenant_id=self.a, course="greek-101",
                    stage="hallucinate", payload={}))
            conn.rollback()
            with self.assertRaises(sa.exc.IntegrityError):
                conn.execute(sa.insert(db.factory_runs).values(
                    tenant_id=self.a, course="greek-101", stage="noop",
                    payload={}, status="vibing"))
            conn.rollback()


class DerivedRegistriesTest(unittest.TestCase):
    """T4: purge and export are derived from the classification, so a new
    scoped table joins them by existing — that is the whole point."""

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()

    def test_new_tables_are_registered(self):
        for name in ("onboarding_events", "factory_runs"):
            self.assertIn(name, db.TENANT_SCOPED)
            self.assertIn(name, db.EXPORTED)
            self.assertIn(name, db.PURGED)

    def test_export_and_purge_cover_the_new_tables(self):
        with self.engine.begin() as conn:
            victim = db.create_tenant(conn, "victim-onboarding")
            bystander = db.create_tenant(conn, "bystander-onboarding")
            for tenant in (victim, bystander):
                scope = db.for_tenant(tenant)
                conn.execute(scope.onboarding_insert("profile_published", "", {}))
                conn.execute(scope.runs_insert("greek-101", "noop", {}))

            export = db.export_tenant(conn, victim)
            self.assertEqual(set(export), db.EXPORTED)
            self.assertEqual(len(export["onboarding_events"]), 1)
            self.assertEqual(len(export["factory_runs"]), 1)

            counts = db.purge_tenant(conn, victim)
            self.assertEqual(counts["onboarding_events"], 1)
            self.assertEqual(counts["factory_runs"], 1)
            with self.assertRaises(db.UnknownTenant):
                db.tenant_id_for(conn, "victim-onboarding")

            # The bystander tenant keeps both of its rows.
            scope = db.for_tenant(bystander)
            self.assertEqual(
                len(conn.execute(scope.onboarding_select()).all()), 1)
            self.assertEqual(
                len(conn.execute(scope.runs_pending("greek-101")).all()), 1)


class FoldTest(unittest.TestCase):
    """O1: the current stop is a pure function of the rows, nothing else."""

    def test_every_transition_lands_where_the_design_says(self):
        # Folded over growing prefixes, so each row is checked in the state
        # its predecessors left — the fold's only real subject.
        steps = [
            (ev("scope_saved", payload={"topic": "koine"}), "outline", "waiting"),
            (ev("outline_requested"), "outline", "pending"),
            (ev("outline_failed", payload={"reason": "budget_exceeded"}),
             "outline", "failed"),
            (ev("outline_requested"), "outline", "pending"),
            (ev("outline_ready", payload=OUTLINE), "outline_gate", "waiting"),
            (ev("outline_rejected", payload={"note": "too fast"}),
             "outline_gate", "waiting"),
            (ev("outline_requested"), "outline", "pending"),
            (ev("outline_ready", payload=OUTLINE), "outline_gate", "waiting"),
            (ev("outline_approved", payload={"estimate_usd": "4.20"}),
             "build", "waiting"),
            (ev("build_requested"), "build", "pending"),
            (ev("build_failed", payload={"reason": "worker_error"}),
             "build", "failed"),
            (ev("build_requested"), "build", "pending"),
            (ev("build_ready"), "promote", "pending"),
            (ev("promote_failed", payload={"reason": "compile_failed"}),
             "promote", "failed"),
            (ev("promoted", payload={"course_id": "greek-101"}), "done", "waiting"),
        ]
        events = []
        for event, stage, status in steps:
            events.append(event)
            flow = onboarding.fold(events).flows["greek-101"]
            with self.subTest(kind=event[0], n=len(events)):
                self.assertEqual((flow.stage, flow.status), (stage, status))

    def test_a_reason_belongs_to_its_failure_and_to_nothing_else(self):
        failed = onboarding.fold([
            ev("scope_saved"),
            ev("outline_requested"),
            ev("outline_failed", payload={"reason": "compile_failed",
                                          "detail": "traceback for operators"}),
        ]).flows["greek-101"]
        self.assertEqual((failed.status, failed.reason), ("failed", "compile_failed"))
        # Retrying clears it: a stale key beside a live stage is a screen lying.
        retried = onboarding.fold([
            ev("scope_saved"),
            ev("outline_requested"),
            ev("outline_failed", payload={"reason": "compile_failed"}),
            ev("outline_requested"),
        ]).flows["greek-101"]
        self.assertEqual((retried.status, retried.reason), ("pending", None))

    def test_the_flow_keeps_the_payloads_the_screens_render(self):
        flow = onboarding.fold([
            ev("scope_saved", payload={"topic": "koine", "hours_per_week": 6}),
            ev("outline_requested"),
            ev("outline_ready", payload=OUTLINE),
            ev("outline_rejected", payload={"note": "start with the alphabet"}),
            ev("outline_requested"),
            ev("outline_ready", payload=OUTLINE),
            ev("outline_approved", payload={"estimate_usd": "4.20"}),
        ]).flows["greek-101"]
        self.assertEqual(flow.scope["topic"], "koine")
        self.assertEqual(flow.outline["estimate_usd"], "4.20")
        # O3: the approval carries the estimate the learner was shown.
        self.assertEqual(flow.approval, {"estimate_usd": "4.20"})
        self.assertEqual(flow.note, "start with the alphabet")

    def test_the_happy_path_ends_done_and_reopens_at_scope(self):
        st = onboarding.fold([
            ev("profile_published", course=""),
            ev("scope_saved", payload={"topic": "koine"}),
            ev("outline_requested"),
            ev("outline_ready", payload=OUTLINE),
            ev("outline_approved", payload={"estimate_usd": "4.20"}),
            ev("build_requested"),
            ev("build_ready"),
            ev("promoted", payload={"course_id": "greek-101"}),
        ])
        self.assertEqual(st.flows["greek-101"].stage, "done")
        self.assertEqual(st.flows["greek-101"].status, "waiting")
        self.assertIsNone(st.active())
        # A promoted flow re-enters at Stop 6 (design §4, Stop 10).
        self.assertEqual(st.current_stop(), "scope")

    def test_profile_published_flips_the_flag_and_the_stop(self):
        rows = [ev("scope_saved"), ev("outline_requested")]
        before = onboarding.fold(rows)
        self.assertFalse(before.profile_published)
        # Stop 1 outranks a live flow: an unpublished profile is the wizard's
        # first gate whatever else the ledger holds.
        self.assertEqual(before.current_stop(), "profile")
        after = onboarding.fold([ev("profile_published", course="")] + rows)
        self.assertTrue(after.profile_published)
        self.assertEqual(after.current_stop(), "outline")
        # profile_published touches no flow — it carries no course to touch.
        self.assertEqual(list(onboarding.fold(
            [ev("profile_published", course="")]).flows), [])

    def test_two_courses_are_independent_and_the_newest_live_one_is_active(self):
        st = onboarding.fold([
            ev("profile_published", course=""),
            ev("scope_saved", course="greek-101"),
            ev("outline_requested", course="greek-101"),
            ev("outline_ready", course="greek-101", payload=OUTLINE),
            ev("outline_approved", course="greek-101",
               payload={"estimate_usd": "4.20"}),
            ev("build_requested", course="greek-101"),
            ev("build_ready", course="greek-101"),
            ev("promoted", course="greek-101", payload={"course_id": "greek-101"}),
            ev("scope_saved", course="latin-201"),
            ev("outline_requested", course="latin-201"),
            ev("outline_failed", course="latin-201",
               payload={"reason": "budget_exceeded"}),
        ])
        self.assertEqual(list(st.flows), ["greek-101", "latin-201"])
        self.assertEqual(st.flows["greek-101"].stage, "done")
        self.assertEqual(st.active().course_id, "latin-201")
        self.assertEqual(st.current_stop(), "outline")
        self.assertEqual(st.flows["latin-201"].reason, "budget_exceeded")
        self.assertIsNone(st.flows["greek-101"].reason)

    def test_the_fold_ignores_the_clock(self):
        # Rows in id order, timestamps running backwards: ordering is by row
        # id, never timestamp, so the last row still wins.
        backwards = [
            ev("scope_saved", at=CLOCK),
            ev("outline_requested", at=CLOCK - timedelta(hours=1)),
            ev("outline_ready", payload=OUTLINE, at=CLOCK - timedelta(hours=2)),
            ev("outline_approved", payload={"estimate_usd": "4.20"},
               at=CLOCK - timedelta(days=3)),
        ]
        flow = onboarding.fold(backwards).flows["greek-101"]
        self.assertEqual((flow.stage, flow.status), ("build", "waiting"))
        # updated_at is display data: the last row's clock, whatever it says.
        self.assertEqual(flow.updated_at, CLOCK - timedelta(days=3))

    def test_the_stage_vocabulary_partitions_the_sequence(self):
        self.assertEqual(onboarding.HUMAN_STAGES | onboarding.WORKER_STAGES,
                         frozenset(onboarding.STAGE_SEQUENCE))
        self.assertFalse(onboarding.HUMAN_STAGES & onboarding.WORKER_STAGES)


class ValidateEventTest(unittest.TestCase):
    """Refuse, don't guess: no defaulting a missing reason to worker_error."""

    def refuses(self, kind, course, payload):
        with self.assertRaises(onboarding.InvalidOnboardingEvent):
            onboarding.validate_event(kind, course, payload)

    def test_unknown_kind(self):
        self.refuses("vibes_published", "greek-101", {})

    def test_profile_published_carries_no_course(self):
        self.refuses("profile_published", "greek-101", {})
        onboarding.validate_event("profile_published", "", {})

    def test_every_other_kind_needs_a_course(self):
        self.refuses("scope_saved", "", {"topic": "koine"})

    def test_failures_need_a_reason_from_the_vocabulary(self):
        self.refuses("outline_failed", "greek-101", {})
        self.refuses("build_failed", "greek-101", {"detail": "it broke"})
        self.refuses("promote_failed", "greek-101", {"reason": "it broke"})
        # A known reason, with operator detail alongside, is fine.
        onboarding.validate_event("outline_failed", "greek-101",
                                  {"reason": "worker_error", "detail": "Traceback…"})

    def test_the_outline_gate_payloads(self):
        self.refuses("outline_ready", "greek-101", {"estimate_usd": "4.20"})
        self.refuses("outline_ready", "greek-101", {"plan": {}})
        self.refuses("outline_approved", "greek-101", {})
        self.refuses("outline_rejected", "greek-101", {"note": "   "})
        self.refuses("outline_rejected", "greek-101", {})
        onboarding.validate_event("outline_approved", "greek-101",
                                  {"estimate_usd": "4.20"})

    def test_promoted_names_the_course_it_made(self):
        self.refuses("promoted", "greek-101", {})
        onboarding.validate_event("promoted", "greek-101",
                                  {"course_id": "greek-101"})


class WordingTest(unittest.TestCase):
    def test_no_machine_reason_without_a_human_sentence(self):
        """O2: every (worker stage, reason) pair has a sentence, and a test
        fails when one doesn't. The full cross product is required precisely
        so that no pair can be quietly considered inapplicable."""
        for stage in sorted(onboarding.WORKER_STAGES):
            for reason in onboarding.REASONS:
                with self.subTest(stage=stage, reason=reason):
                    self.assertIn((stage, reason), onboarding.WORDING)
                    self.assertTrue(onboarding.WORDING[(stage, reason)].strip())

    def test_the_table_says_nothing_else(self):
        # A human stage has no machine reason to word, so an entry for one is
        # a sign the vocabulary drifted.
        self.assertEqual(
            set(onboarding.WORDING),
            {(s, r) for s in onboarding.WORKER_STAGES for r in onboarding.REASONS})


class ProfileGateTest(unittest.TestCase):
    def test_an_empty_profile_is_missing_every_required_field(self):
        self.assertEqual(onboarding.profile_gate_missing(profile.fold([])),
                         onboarding.REQUIRED_PROFILE_FIELDS)

    def test_one_claim_per_required_field_opens_the_gate(self):
        st = profile.fold([
            ("assert", f, f"{f}-01", {"text": f"A claim about {f}.",
                                      "tier": "attested"})
            for f in onboarding.REQUIRED_PROFILE_FIELDS
        ])
        self.assertEqual(onboarding.profile_gate_missing(st), ())

    def test_the_other_fields_are_not_gated(self):
        # An empty subject_adapters is an omitted prompt line, not a blocker.
        st = profile.fold([
            ("assert", f, f"{f}-01", {"text": "x.", "tier": "attested"})
            for f in ("background", "style", "pacing")
        ] + [("assert", "meta", "description", {"text": "x.", "tier": "attested"})])
        self.assertEqual(onboarding.profile_gate_missing(st), ("calibration",))


class AppendAndLoadTest(unittest.TestCase):
    """T5: the writer and the fold over a real ledger, two tenants."""

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, "fold-a")
            cls.b = db.create_tenant(conn, "fold-b")

    def test_round_trip_is_scoped_to_its_tenant(self):
        scope_a, scope_b = db.for_tenant(self.a), db.for_tenant(self.b)
        with self.engine.begin() as conn:
            onboarding.append_event(conn, scope_a, "profile_published", "")
            onboarding.append_event(conn, scope_a, "scope_saved", "greek-101",
                                    {"topic": "koine"})
            onboarding.append_event(conn, scope_a, "outline_requested", "greek-101")
            onboarding.append_event(conn, scope_b, "scope_saved", "latin-201",
                                    {"topic": "cicero"})
            state_a = onboarding.load_state(conn, scope_a)
            state_b = onboarding.load_state(conn, scope_b)

        self.assertTrue(state_a.profile_published)
        self.assertEqual(list(state_a.flows), ["greek-101"])
        self.assertEqual(state_a.current_stop(), "outline")
        self.assertEqual(state_a.flows["greek-101"].status, "pending")
        self.assertIsNotNone(state_a.flows["greek-101"].updated_at)

        # B has a scope and no published profile: a different tenant, a
        # different stop, from the same code.
        self.assertFalse(state_b.profile_published)
        self.assertEqual(list(state_b.flows), ["latin-201"])
        self.assertEqual(state_b.current_stop(), "profile")

    def test_the_writer_refuses_before_the_row_exists(self):
        scope = db.for_tenant(self.a)
        with self.engine.begin() as conn:
            with self.assertRaises(onboarding.InvalidOnboardingEvent):
                onboarding.append_event(conn, scope, "build_failed", "greek-101",
                                        {"detail": "no reason given"})
            rows = conn.execute(scope.onboarding_select()).all()
        self.assertNotIn("build_failed", [r.kind for r in rows])


class ScopeGuardTest(unittest.TestCase):
    def test_scoped_tables_are_only_touched_via_db_module(self):
        """T2's guard, for the two tables 0004 adds: a helper nothing forces
        you to use is a suggestion."""
        allowed = {"db.py"}
        offenders = []
        pkg = os.path.join(HERE, "curricle")
        for fn in sorted(os.listdir(pkg)):
            if not fn.endswith(".py") or fn in allowed:
                continue
            with open(os.path.join(pkg, fn), encoding="utf-8") as f:
                source = f.read()
            for table in ("onboarding_events", "factory_runs"):
                if table in source:
                    offenders.append((fn, table))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
