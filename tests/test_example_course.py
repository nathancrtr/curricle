"""Integration: the shipped example course must compile clean.

`test_corpus.py` is the compiler's real integration suite, but it runs against
private sibling repos and skips when they are absent — which is the normal case
for everyone but the author, and a skipped suite reads as a pass. This module
covers the same ground against `examples/tinylang`, which is in the repository,
so a fresh clone still exercises the compiler end to end.

It also holds the example to a higher bar than the corpus: zero warnings, not
just zero errors. The example is what people copy, so anything the compiler is
willing to grumble about should not be in it.
"""

import os
import subprocess
import sys
import unittest

from curricle.compiler import compile_course
from curricle.sidecar import load_sidecar

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSE_ROOT = os.path.join(REPO_ROOT, "examples", "tinylang")
SIDECAR = os.path.join(COURSE_ROOT, "learning", "course.yaml")

# The exact progress-id enumeration, in order. Unlike the corpus pin this
# guards no real learner state — it is here because the ordering is a
# contract (units interleaved with their phase's milestones, tracks last)
# and a silent reordering is exactly the kind of change that should have to
# be typed out deliberately.
PROGRESS_IDS = [
    "p0-skeleton", "p0-repl", "p0-map",   # Phase 0's steps
    "u1", "u2", "m-errors",               # Phase 1, milestone after its anchor
    "u3", "u4",                           # Phase 2
    "t-regular", "t-cfg", "t-semantics",  # the theory track's ladder
]


class ExampleCourseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.issues = compile_course(COURSE_ROOT,
                                                  load_sidecar(SIDECAR))

    def test_compiles_without_errors(self):
        self.assertIsNotNone(self.manifest, [str(i) for i in self.issues])

    def test_compiles_without_warnings(self):
        # The example is the thing people copy. It gets no grumbles at all.
        self.assertEqual([str(i) for i in self.issues], [])

    def test_shape(self):
        self.assertEqual(len(self.manifest.phases), 3)
        self.assertEqual(len(self.manifest.units), 5)
        self.assertEqual(len(self.manifest.materials), 6)
        self.assertEqual(len(self.manifest.resources), 5)
        self.assertEqual(len(self.manifest.milestones), 1)
        self.assertEqual(len(self.manifest.tracks), 1)

    def test_progress_ids_are_pinned_and_ordered(self):
        self.assertEqual(list(self.manifest.progress_ids()), PROGRESS_IDS)

    def test_every_phase_has_a_goal_and_entries(self):
        for p in self.manifest.phases:
            self.assertTrue(p.goal, f"{p.id} missing goal")
            self.assertTrue(p.entries, f"{p.id} has no entries")

    def test_every_phase_has_a_checkpoint(self):
        for p in self.manifest.phases:
            self.assertIsNotNone(p.checkpoint, f"{p.id} has no checkpoint")

    def test_capstone_resolves(self):
        ids = {u.id for u in self.manifest.units}
        self.assertIn(self.manifest.course.capstone, ids)

    def test_exercises_every_material_kind_worth_demonstrating(self):
        # The example earns its place by being copyable, which means covering
        # the kinds someone will want an instance of to crib from.
        kinds = {m.kind for m in self.manifest.materials}
        self.assertEqual(kinds, {"lesson", "widget", "exercise", "quiz",
                                 "question-bank", "chapter"})

    def test_every_material_file_exists(self):
        content_root = os.path.join(COURSE_ROOT, "learning")
        for m in self.manifest.materials:
            self.assertTrue(os.path.exists(os.path.join(content_root, m.path)),
                            f"{m.id}: {m.path} does not exist")

    def test_the_exercise_carries_its_brief_as_task_md(self):
        # The house convention the renderers and the served reader assume.
        ex = next(m for m in self.manifest.materials if m.kind == "exercise")
        brief = os.path.join(COURSE_ROOT, "learning", ex.path, "task.md")
        self.assertTrue(os.path.exists(brief), f"missing {brief}")

    def test_the_curriculum_uses_every_reference_scheme(self):
        # Dangling refs are a compile error, so the schemes appearing at all
        # means they all resolved. This asserts they appear.
        with open(os.path.join(COURSE_ROOT, "learning", "curriculum.md"),
                  encoding="utf-8") as f:
            text = f.read()
        for scheme in ("res:", "unit:", "mat:", "repo:"):
            self.assertIn(f"]({scheme}", text, f"no {scheme} link in the example")


class ExampleExerciseTest(unittest.TestCase):
    """The starter must be a starter: shipped red, and solvable.

    Solvability is not something a test can assert cheaply — it was verified
    against a reference solution when the exercise was written. What this
    guards is the failure mode that actually happens: someone tidies the stub,
    fills in a `pass`, and the exercise silently becomes a no-op that passes on
    arrival with nothing left to do.
    """

    EX = os.path.join(COURSE_ROOT, "learning", "interactive",
                      "exercises", "unit-02-starter")

    def test_the_starter_tests_fail_against_the_stub(self):
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", self.EX],
            capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertNotEqual(proc.returncode, 0,
                            "the Unit 2 starter passes against its own stub — "
                            "the exercise has been solved in the repository")
        self.assertIn("NotImplementedError", proc.stderr)

    def test_the_starter_has_tests_to_fail(self):
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", self.EX, "-v"],
            capture_output=True, text=True, cwd=REPO_ROOT)
        # "Ran N tests" — a stub with no tests would also "fail" vacuously.
        self.assertRegex(proc.stderr, r"Ran (1[0-9]|[2-9][0-9]) tests")


if __name__ == "__main__":
    unittest.main()
