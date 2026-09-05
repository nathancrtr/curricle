"""The scaffolding for looking at the wizard without spending.

Two tools, two contracts. `curricle.scripted` is the worker's canned model:
a transport with the SDK's signature that never reaches the network, a
designer that answers under the id the scope form minted, and two dials —
linger and fail — that wrap the real handler table in the ledger's own
vocabulary. `curricle.faces` is the gallery: every screen the wizard has,
rendered from synthetic state with no database, in both themes, with every
failure sentence the wording table knows reaching a page.

The end-to-end proof that the scripted worker lands on a served course is
`test_onboarding_flow`, which walks the wizard with the same transport.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from curricle import faces, onboarding, scripted, wizard, worker
from curricle.__main__ import main


class ScriptedSendTest(unittest.TestCase):
    def test_every_role_is_answered_and_logged_by_prompt_tag(self):
        send = scripted.ScriptedSend()
        for tag, role in scripted.BUILD_TAGS:
            text, usage = send("m", "sys", f"<learner_profile>\np\n</learner_profile>\n{tag}\nx\n</{tag[1:]}", 10)
            self.assertEqual(text, scripted.BUILD_RESPONSES[role])
            self.assertEqual(usage["input_tokens"], 100)
        send("m", "sys", "<course_id>\ntiny-demo\n</course_id>", 10)
        send("m", "sys", "<curriculum_md>\n# x\n</curriculum_md>", 10)
        self.assertEqual(send.roles()[-2:],
                         ["curriculum-designer", "resource-curator"])

    def test_the_designer_answers_under_the_id_and_title_the_prompt_names(self):
        prompt = ("<scope>\ntitle: Manifests, gently\nsubject: manifests\n</scope>\n\n"
                  "<course_id>\nmanifests-gently\n</course_id>")
        curriculum, sidecar, shelf = scripted.answer_as(prompt)
        self.assertIn("id: manifests-gently", sidecar)
        self.assertIn('title: "Manifests, gently"', sidecar)
        self.assertNotIn("tiny-demo", sidecar)
        self.assertTrue(curriculum.startswith("# Manifests, gently: Curriculum"))
        self.assertTrue(shelf.startswith("# Manifests, gently: Learning resources"))

    def test_without_a_prompt_to_read_the_script_keeps_its_own_name(self):
        _, sidecar, _ = scripted.answer_as("no tags at all")
        self.assertIn(f"id: {scripted.COURSE_ID}", sidecar)

    def test_the_module_holds_no_transport_that_could_reach_the_network(self):
        # By construction rather than by patching: nothing in the module
        # imports a client, so there is no send here that could be reached.
        import ast
        with open(scripted.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for client in ("anthropic", "httpx", "requests", "urllib", "socket"):
            self.assertNotIn(client, imported)


class DialsTest(unittest.TestCase):
    def setUp(self):
        self.ran: list[str] = []
        self.base = {"outline": lambda e, s, r: self.ran.append("outline") or ("outline_ready", {}),
                     "build": lambda e, s, r: self.ran.append("build") or ("build_ready", {})}
        self.slept: list[float] = []

    def handlers(self, **kw):
        return scripted.handlers(base=self.base, sleep=self.slept.append,
                                 log=io.StringIO(), **kw)

    def test_fail_stops_the_first_run_of_the_stage_and_only_that_one(self):
        h = self.handlers(fail=(("outline", "compile_failed"),))
        with self.assertRaises(worker.StageFailed) as cm:
            h["outline"](None, None, None)
        self.assertEqual(cm.exception.reason, "compile_failed")
        self.assertEqual(h["outline"](None, None, None), ("outline_ready", {}))
        self.assertEqual(h["build"](None, None, None), ("build_ready", {}))
        self.assertEqual(self.ran, ["outline", "build"])

    def test_linger_sleeps_before_every_stage(self):
        h = self.handlers(linger=7.5)
        h["outline"](None, None, None)
        h["build"](None, None, None)
        self.assertEqual(self.slept, [7.5, 7.5])

    def test_without_dials_the_handlers_are_transparent(self):
        h = self.handlers()
        self.assertEqual(h["outline"](None, None, None), ("outline_ready", {}))
        self.assertEqual(self.slept, [])

    def test_the_default_base_is_the_workers_own_table(self):
        self.assertEqual(set(scripted.handlers(log=io.StringIO())), set(worker.HANDLERS))

    def test_parse_fail_refuses_anything_outside_the_ledgers_vocabulary(self):
        self.assertEqual(scripted.parse_fail("build:interrupted"), ("build", "interrupted"))
        for bad in ("build", "scope:worker_error", "build:oops", "build:"):
            with self.subTest(bad=bad), self.assertRaises(scripted.BadFailSpec):
                scripted.parse_fail(bad)


class WorkCliTest(unittest.TestCase):
    """`python -m curricle work --scripted` rebinds the one seam and hands
    the wrapped handlers to the worker; the dials are refused without it."""

    def run_work(self, *argv):
        err = io.StringIO()
        with mock.patch("curricle.db.make_engine", return_value=object()), \
             mock.patch("curricle.worker.main", return_value=0) as run, \
             contextlib.redirect_stderr(err), \
             contextlib.redirect_stdout(io.StringIO()):
            code = main(["work", *argv])
        return code, run, err.getvalue()

    def tearDown(self):
        worker.RUNNER_FACTORY = self._factory

    def setUp(self):
        self._factory = worker.RUNNER_FACTORY

    def test_scripted_rebinds_the_runner_factory_and_wraps_the_handlers(self):
        code, run, err = self.run_work("--scripted", "--linger", "3",
                                       "--fail", "promote:interrupted")
        self.assertEqual(code, 0)
        self.assertIs(worker.RUNNER_FACTORY, scripted.runner_factory)
        handlers = run.call_args.kwargs["handlers"]
        self.assertEqual(set(handlers), set(worker.HANDLERS))
        self.assertIn("SCRIPTED", err)

    def test_a_plain_work_leaves_the_production_seam_alone(self):
        code, run, _ = self.run_work()
        self.assertEqual(code, 0)
        self.assertIs(worker.RUNNER_FACTORY, self._factory)
        self.assertIsNone(run.call_args.kwargs["handlers"])

    def test_the_dials_are_refused_without_scripted(self):
        code, run, err = self.run_work("--linger", "3")
        self.assertEqual(code, 2)
        self.assertFalse(run.called)
        self.assertIn("--scripted", err)

    def test_a_bad_fail_spec_is_refused_before_the_worker_starts(self):
        code, run, err = self.run_work("--scripted", "--fail", "build:nonsense")
        self.assertEqual(code, 2)
        self.assertFalse(run.called)
        self.assertIn("REASON", err)


class FacesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="curricle-faces-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.written = faces.write_all(cls.tmp)
        cls.faces = faces.faces()

    def page(self, name: str, dark: bool = False) -> str:
        with open(os.path.join(self.tmp, name + (".dark.html" if dark else ".html")),
                  encoding="utf-8") as f:
            return f.read()

    def test_every_face_lands_in_both_themes_with_an_index_and_a_viewer(self):
        names = {f.name for f in self.faces}
        self.assertEqual(len(names), len(self.faces))       # no two faces share a file
        self.assertEqual(len(self.written), 2 * len(names) + 2)
        self.assertIn('<html lang="en" data-theme="light">', self.page("welcome"))
        self.assertIn('<html lang="en" data-theme="dark">', self.page("welcome", dark=True))
        index = self.page("index")
        viewer = self.page("view")
        for name in names:
            self.assertIn(f'href="view.html#{name}"', index)
            self.assertIn(f'"{name}"', viewer)

    def test_every_failure_sentence_reaches_a_face(self):
        # O2's cross product, seen: one face per (stage, reason), and the
        # face prints the wording table's sentence for it. The promote
        # faces in particular had never been rendered before this (issue #61).
        for (stage, reason), sentence in onboarding.WORDING.items():
            with self.subTest(stage=stage, reason=reason):
                page = self.page(f"{stage}-failed-{reason.replace('_', '-')}")
                self.assertIn(sentence, page)

    def test_pending_faces_are_at_rest(self):
        for stage in onboarding.WORKER_STAGES:
            page = self.page(f"{stage}-pending")
            self.assertNotIn(wizard.STATUS_PATH, page)      # no poll
            self.assertNotIn("http-equiv", page)           # no refresh fallback
            self.assertIn("3 min", page)                    # elapsed, not a forecast

    def test_the_build_faces_draw_what_has_landed(self):
        # Two rings on the pending face — the masthead's on the build stop,
        # the panel's on the artifact being written — and one on the failed
        # face, where nothing is being written.
        pending = self.page("build-pending")
        self.assertIn("2 of 5 landed — writing the exercise", pending)
        self.assertEqual(pending.count("wp-stone here"), 2)
        failed = self.page("build-failed-worker-error")
        self.assertIn("2 of 5 landed and kept", failed)
        self.assertEqual(failed.count("wp-stone here"), 1)

    def test_the_filled_forms_and_the_review_carry_the_claims(self):
        self.assertIn(faces.CLAIMS["background"], self.page("form-1-filled"))
        self.assertNotIn(faces.CLAIMS["background"], self.page("form-1-empty"))
        self.assertIn(faces.CLAIMS["calibration"], self.page("review"))

    def test_the_gate_compiles_the_example_course_and_prints_the_number(self):
        gate = self.page("outline-gate")
        self.assertIn("Interpreters, end to end", gate)
        self.assertIn("1.37", gate)
        broken = self.page("outline-gate-broken")
        self.assertIn("cannot be read back", broken)
        self.assertNotIn("1.37", broken)       # no number to approve on a refused draft

    def test_the_landing_names_the_course_and_the_tenant(self):
        landing = self.page("landing")
        self.assertIn(faces.COURSE_ID, landing)
        self.assertIn(faces.TENANT, landing)


class FacesCliTest(unittest.TestCase):
    def test_faces_writes_where_it_is_told(self):
        tmp = tempfile.mkdtemp(prefix="curricle-faces-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "gallery")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = main(["faces", "--out", out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(out, "index.html")))
        self.assertIn("face(s)", buf.getvalue())
