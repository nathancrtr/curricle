"""The course factory: validators, metering, budgets, the build — no network.

The fake transport returns canned artifacts; the smoke tests (an exercise's
tests must fail against its stub, a widget must be offline) run for real.
"""

import json
import os
import tempfile
import textwrap
import unittest
from decimal import Decimal

from curricle import db, factory, profile
from curricle.llm import BudgetExceeded, Runner, load_models_config, load_role

from pg import test_engine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS = os.path.dirname(HERE)
ML_ROOT = os.path.join(REPOS, "learning", "ml-ai")


GOOD_QUIZ = json.dumps([
    {"q": f"Question {i}?", "options": [
        {"text": "right", "correct": True, "why": "because"},
        {"text": "wrong a", "correct": False, "why": "misconception a"},
        {"text": "wrong b", "correct": False, "why": "misconception b"},
        {"text": "wrong c", "correct": False, "why": "misconception c"},
    ]} for i in range(10)
])

GOOD_EXERCISE = json.dumps({
    "slug": "unit-03-bpe",
    "task_md": "# BPE\nBuild it.",
    "stub_name": "bpe.py",
    "stub": textwrap.dedent('''\
        def merge(tokens, pair):
            """Merge every adjacent occurrence of pair."""
            raise NotImplementedError
        '''),
    "test_name": "test_bpe.py",
    "test": textwrap.dedent('''\
        import unittest
        from bpe import merge

        class TestMerge(unittest.TestCase):
            def test_merges_adjacent_pair(self):
                # classic trap: overlapping pairs merge left-to-right
                self.assertEqual(merge(["a", "b", "b"], ("a", "b")), ["ab", "b"])

        if __name__ == "__main__":
            unittest.main()
        '''),
})


class ValidatorTest(unittest.TestCase):
    def test_quiz_rules(self):
        self.assertEqual(len(factory.validate_quiz(GOOD_QUIZ)), 10)
        bad = json.loads(GOOD_QUIZ)
        bad[3]["options"][1]["correct"] = True     # two correct answers
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_quiz(json.dumps(bad))
        bad = json.loads(GOOD_QUIZ)
        bad[0]["options"][2]["why"] = ""           # a throwaway distractor
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_quiz(json.dumps(bad))

    def test_quiz_strips_code_fence(self):
        fenced = "```json\n" + GOOD_QUIZ + "\n```"
        self.assertEqual(len(factory.validate_quiz(fenced)), 10)

    def test_widget_offline_rule(self):
        ok = "<!DOCTYPE html><html><body><script>let x=1;</script></body></html>"
        self.assertTrue(factory.validate_widget(ok))
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_widget(ok.replace(
                "<script>", '<script src="https://cdn.example.com/x.js"></script><script>'))
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_widget("<div>not a document</div>")

    def test_exercise_smoke_runs_tests_against_stub(self):
        with tempfile.TemporaryDirectory() as d:
            data = factory.validate_exercise(GOOD_EXERCISE, workdir=d)
            self.assertEqual(data["slug"], "unit-03-bpe")
        # Tests that pass against the stub test nothing — refused.
        passing = json.loads(GOOD_EXERCISE)
        passing["test"] = passing["test"].replace(
            'self.assertEqual(merge(["a", "b", "b"], ("a", "b")), ["ab", "b"])',
            "self.assertTrue(True)")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(factory.ValidationFailed):
                factory.validate_exercise(json.dumps(passing), workdir=d)

    def test_lesson_and_bank(self):
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_lesson("# Short\nno pauses here" + "x" * 3000)
        good = "# Lesson\n" + "context " * 400 + "\n> PAUSE.\nmore"
        self.assertIn("PAUSE", factory.validate_lesson(good))
        bank = ("## Module 3 — Tokenization\n\n**3.1 (R)** What is BPE?\n"
                "**Answer:** Byte-pair encoding.\n**Note:** Merges by frequency.")
        self.assertTrue(factory.validate_bank(bank))
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_bank("just prose")

    def test_quiz_shell_rendering(self):
        shell = ("<title>Phase 1 Checkpoint</title>\n<script>\n"
                 "const QUIZ_DATA = [\n  {q: 'old'}\n];\n</script>")
        out = factory.render_quiz_html(shell, json.loads(GOOD_QUIZ), 2, 1)
        self.assertIn("Phase 2 Checkpoint", out)
        self.assertIn("Question 0?", out)
        self.assertNotIn("'old'", out)


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.tenant = db.create_tenant(conn, "factory-runner")
        cls.scope = db.for_tenant(cls.tenant)
        cls.config = load_models_config()

    def test_roles_load_and_map_to_models(self):
        for name in ("lesson-writer", "quiz-author", "exercise-author",
                     "widget-builder", "bank-author"):
            role = load_role(name)
            self.assertTrue(role.system)
            self.assertIn(self.config.model_for_role(name), self.config.prices)

    def test_call_is_metered(self):
        def fake_send(model, system, prompt, max_tokens):
            return "output", {"input_tokens": 1000, "output_tokens": 500,
                              "cache_write_tokens": 0, "cache_read_tokens": 0}
        runner = Runner(self.engine, self.scope, self.config, send=fake_send)
        result = runner.run_role("quiz-author", "prompt")
        # opus-5: 1000 in * $5/M + 500 out * $25/M = $0.005 + $0.0125
        self.assertEqual(result.cost_usd, Decimal("0.0175"))
        self.assertEqual(runner.spent("quiz-author"), Decimal("0.017500"))

    def test_budget_refusal(self):
        def expensive(model, system, prompt, max_tokens):
            return "x", {"input_tokens": 900_000, "output_tokens": 20_000,
                         "cache_write_tokens": 0, "cache_read_tokens": 0}
        with self.engine.begin() as conn:
            t = db.create_tenant(conn, "factory-budget")
        runner = Runner(self.engine, db.for_tenant(t), self.config,
                        send=expensive)
        runner.run_role("widget-builder", "p")     # $4.50+$0.50 = $5.00 spent
        with self.assertRaises(BudgetExceeded):
            runner.run_role("widget-builder", "p")


@unittest.skipUnless(os.path.isdir(ML_ROOT), "ml-ai course not present")
class BuildPhaseTest(unittest.TestCase):
    """End-to-end build against the real ml-ai manifest, fake transport."""

    @classmethod
    def setUpClass(cls):
        from curricle.compiler import compile_course
        from curricle.sidecar import load_sidecar
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            t = db.create_tenant(conn, "factory-build")
        cls.scope = db.for_tenant(t)
        cls.manifest, _ = compile_course(
            ML_ROOT, load_sidecar(os.path.join(ML_ROOT, "course.yaml")))

    def test_build_quiz_and_exercise_into_draft(self):
        responses = {"quiz-author": GOOD_QUIZ, "exercise-author": GOOD_EXERCISE}

        def fake_send(model, system, prompt, max_tokens):
            # Route by which role's system prompt this is.
            role = ("quiz-author" if "checkpoint-quiz questions" in system
                    else "exercise-author")
            self.assertIn("Learner Profile", prompt)      # calibration present
            return responses[role], {"input_tokens": 10, "output_tokens": 10,
                                     "cache_write_tokens": 0,
                                     "cache_read_tokens": 0}

        runner = Runner(self.engine, self.scope, send=fake_send)
        with tempfile.TemporaryDirectory() as content_root:
            os.makedirs(os.path.join(content_root, "interactive/quizzes"))
            # A quiz shell must exist in the (temp) content root.
            import shutil
            shutil.copy(
                os.path.join(ML_ROOT, "interactive/quizzes/phase-1-checkpoint.html"),
                os.path.join(content_root, "interactive/quizzes/phase-1-checkpoint.html"))
            spec = factory.BuildSpec(phase_id="p2", exercise_unit="u3",
                                     quiz=True, bank=False)
            report = factory.build_phase(
                runner, self.manifest, profile.ProfileState(),
                content_root, spec)
            roles = {a.role for a in report.artifacts}
            self.assertEqual(roles, {"quiz-author", "exercise-author"})
            quiz_path = os.path.join(
                report.draft_dir, "quizzes/phase-2-checkpoint.html")
            self.assertTrue(os.path.exists(quiz_path))
            with open(quiz_path) as f:
                self.assertIn("Question 0?", f.read())
            self.assertTrue(os.path.exists(os.path.join(
                report.draft_dir, "exercises/unit-03-bpe/task.md")))


if __name__ == "__main__":
    unittest.main()
