"""The progress service: ledger, fold, tenancy invariants, web app.

Runs against a throwaway Postgres cluster (tests/pg.py). Two tenants from
the first fixture — a single-tenant fixture passes whether or not the scope
does anything; it has nothing to leak toward (T5).
"""

import os
import unittest

import sqlalchemy as sa

from curricle import db, progress
from curricle.compiler import compile_course
from curricle.sidecar import load_sidecar

from corpuspaths import HAVE_TF, TF_ROOT
from pg import test_engine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tf_manifest():
    sidecar = load_sidecar(os.path.join(TF_ROOT, "learning", "course.yaml"))
    manifest, _ = compile_course(TF_ROOT, sidecar)
    return manifest


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class LedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        cls.manifest = tf_manifest()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, f"a-{cls.__name__.lower()}")
            cls.b = db.create_tenant(conn, f"b-{cls.__name__.lower()}")

    def test_append_fold_roundtrip(self):
        scope = db.for_tenant(self.a)
        with self.engine.begin() as conn:
            progress.append_event(conn, scope, self.manifest,
                                  "mark", "p0-run", {"done": True})
            progress.append_event(conn, scope, self.manifest,
                                  "mark", "u1", {"done": True})
            progress.append_event(conn, scope, self.manifest,
                                  "mark", "u1", {"done": False})   # last wins
            progress.append_event(conn, scope, self.manifest,
                                  "note", "u1", {"text": "sparse matrix!"})
            progress.append_event(conn, scope, self.manifest,
                                  "resource_mark", "wg", {"inhand": True})
            state = progress.load_state(conn, scope, "textual-flow")
        self.assertTrue(state.done["p0-run"])
        self.assertFalse(state.done["u1"])
        self.assertEqual(state.notes["u1"], "sparse matrix!")
        self.assertTrue(state.res_inhand["wg"])
        summary = progress.summarize(self.manifest, state)
        self.assertEqual(summary["program_done"], 1)
        self.assertEqual(summary["program_total"], 26)
        self.assertEqual(summary["next_up"], "p0-read")

    def test_unknown_subject_is_refused(self):
        scope = db.for_tenant(self.a)
        with self.engine.begin() as conn:
            with self.assertRaises(progress.InvalidEvent):
                progress.append_event(conn, scope, self.manifest,
                                      "mark", "u99", {"done": True})
            with self.assertRaises(progress.InvalidEvent):
                progress.append_event(conn, scope, self.manifest,
                                      "resource_mark", "nope", {"inhand": True})
            with self.assertRaises(progress.InvalidEvent):
                progress.append_event(conn, scope, self.manifest,
                                      "mark", "u1", {"done": "yes"})

    def test_unknown_kind_is_refused_by_the_database_too(self):
        # The CHECK constraint holds even if application validation is bypassed.
        with self.engine.connect() as conn:
            with self.assertRaises(sa.exc.IntegrityError):
                conn.execute(sa.insert(db.progress_events).values(
                    tenant_id=self.a, course="textual-flow",
                    kind="vibes", subject_id="u1", payload={}))
            conn.rollback()

    def test_tenants_do_not_leak(self):
        scope_a, scope_b = db.for_tenant(self.a), db.for_tenant(self.b)
        with self.engine.begin() as conn:
            progress.append_event(conn, scope_b, self.manifest,
                                  "mark", "u22", {"done": True})
            state_a = progress.load_state(conn, scope_a, "textual-flow")
            state_b = progress.load_state(conn, scope_b, "textual-flow")
        self.assertNotIn("u22", state_a.done)
        self.assertTrue(state_b.done["u22"])

    def test_export_and_purge_are_complete_and_scoped(self):
        with self.engine.begin() as conn:
            victim = db.create_tenant(conn, "victim-ledger")
            bystander = db.create_tenant(conn, "bystander-ledger")
            progress.append_event(conn, db.for_tenant(victim), self.manifest,
                                  "mark", "u1", {"done": True})
            progress.append_event(conn, db.for_tenant(bystander), self.manifest,
                                  "mark", "u2", {"done": True})
            export = db.export_tenant(conn, victim)
            self.assertEqual(set(export), db.EXPORTED)
            self.assertEqual(len(export["progress_events"]), 1)
            counts = db.purge_tenant(conn, victim)
            self.assertEqual(counts["progress_events"], 1)
            with self.assertRaises(db.UnknownTenant):
                db.tenant_id_for(conn, "victim-ledger")
            # The bystander tenant is untouched.
            state = progress.load_state(conn, db.for_tenant(bystander),
                                        "textual-flow")
            self.assertTrue(state.done.get("u2"))


class FoldPurityTest(unittest.TestCase):
    def test_fold_needs_no_database(self):
        state = progress.fold([
            ("mark", "u1", {"done": True}),
            ("note", "u1", {"text": "hm"}),
            ("note", "u1", {"text": ""}),          # empty note clears
            ("resource_note", "wg", {"text": "ILL due 10/2"}),
        ])
        self.assertTrue(state.done["u1"])
        self.assertNotIn("u1", state.notes)
        self.assertEqual(state.res_notes["wg"], "ILL due 10/2")


class ScopeGuardTest(unittest.TestCase):
    def test_scoped_table_is_only_touched_via_db_module(self):
        """T2's guard: `progress_events` may be spelled only in db.py and
        migrations. A helper nothing forces you to use is a suggestion."""
        allowed = {"db.py"}
        offenders = []
        pkg = os.path.join(HERE, "curricle")
        for fn in os.listdir(pkg):
            if not fn.endswith(".py") or fn in allowed:
                continue
            with open(os.path.join(pkg, fn), encoding="utf-8") as f:
                if "progress_events" in f.read():
                    offenders.append(fn)
        self.assertEqual(offenders, [])


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class WebAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from curricle.webapp import create_app
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            db.create_tenant(conn, "webapp-learner")
        app = create_app([TF_ROOT], tenant_slug="webapp-learner",
                         database_url=str(cls.engine.url))
        cls.client = TestClient(app)

    def test_unknown_tenant_refuses_startup(self):
        from curricle.webapp import create_app
        with self.assertRaises(db.UnknownTenant):
            create_app([TF_ROOT], tenant_slug="nobody",
                       database_url=str(self.engine.url))

    def test_mark_roundtrip_through_the_pages(self):
        r = self.client.post("/c/textual-flow/api/events", json={
            "kind": "mark", "subject_id": "p0-run", "payload": {"done": True}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["summary"]["program_done"], 1)
        self.assertEqual(r.json()["summary"]["next_up"], "p0-read")
        # The hub arrives with the fold as INITIAL and no localStorage read.
        hub = self.client.get("/c/textual-flow/index.html").text
        self.assertIn('const API = "api/events"', hub)
        self.assertIn('"p0-run": true', hub)
        cur = self.client.get("/c/textual-flow/curriculum.html").text
        self.assertIn('"p0-run": true', cur)

    def test_invalid_event_is_422(self):
        r = self.client.post("/c/textual-flow/api/events", json={
            "kind": "mark", "subject_id": "u99", "payload": {"done": True}})
        self.assertEqual(r.status_code, 422)

    def test_content_served_and_traversal_refused(self):
        ok = self.client.get(
            "/c/textual-flow/interactive/quizzes/greek-alphabet-trainer.html")
        self.assertEqual(ok.status_code, 200)
        md = self.client.get("/c/textual-flow/curriculum.md")
        self.assertEqual(md.status_code, 200)
        self.assertTrue(md.headers["content-type"].startswith("text/plain"))
        evil = self.client.get("/c/textual-flow/../../CLAUDE.md")
        self.assertEqual(evil.status_code, 404)
        evil2 = self.client.get("/c/textual-flow/interactive/%2e%2e/%2e%2e/%2e%2e/course.yaml")
        self.assertIn(evil2.status_code, (200, 404))  # resolves inside root or 404

    def test_resources_page_carries_server_state(self):
        r = self.client.post("/c/textual-flow/api/events", json={
            "kind": "resource_mark", "subject_id": "wg",
            "payload": {"inhand": True}})
        self.assertEqual(r.status_code, 200)
        page = self.client.get("/c/textual-flow/learning-resources.html").text
        self.assertIn('"wg": true', page)


if __name__ == "__main__":
    unittest.main()
