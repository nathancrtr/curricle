"""The onboarding ledger and the factory-runs queue: store-level guarantees.

Two tenants from the first fixture (T5), the same as the progress suite: a
single-tenant fixture passes whether or not the scope does anything, because
it has nothing to leak toward. Everything here runs against the throwaway
Postgres of tests/pg.py, so every run also proves migration 0004 upgrades.
"""

import os
import unittest

import sqlalchemy as sa

from curricle import db

from pg import test_engine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
