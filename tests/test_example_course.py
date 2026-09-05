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
import re
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


class ExampleBankTest(unittest.TestCase):
    """The shipped bank must meet the contract its own author role states.

    `roles/bank-author.md` asks for "5–7 items per unit, all three tags
    represented per unit", and `factory.validate_bank` checks none of that —
    it checks the shape of an item, not the shape of a section, because a
    validator that refused a thin section would be refusing a model's output
    on a house rule the model can only approximate.

    So the bar is kept here instead, where it belongs. This bank is the
    example people copy, and its Phase 0 section is literally the exemplar
    every first build is shown (`curricle/exemplars/bank-section.md`) — a
    thin section here does not merely set a bad example, it teaches one, to
    every course this factory ever writes. It was thin: one application item
    in the whole bank, and none at all in three of the five sections.
    """

    BANK = os.path.join(COURSE_ROOT, "learning", "interactive", "quizzes",
                        "question-bank.md")
    ITEM = re.compile(r"^\*\*(\d+)\.(\d+) \(([RAW])\)\*\* ")

    @classmethod
    def setUpClass(cls):
        cls.sections = {}
        heading = None
        with open(cls.BANK, encoding="utf-8") as f:
            for line in f:
                if line.startswith("## "):
                    heading = line[3:].strip()
                    cls.sections[heading] = []
                match = cls.ITEM.match(line)
                if match:
                    cls.sections[heading].append(match.groups())

    def test_the_bank_has_a_section_per_unit_and_the_phase_body(self):
        manifest, _ = compile_course(COURSE_ROOT, load_sidecar(SIDECAR))
        self.assertEqual(len(self.sections), len(manifest.units))

    def test_every_section_carries_five_to_seven_items(self):
        for heading, items in self.sections.items():
            with self.subTest(section=heading):
                self.assertGreaterEqual(len(items), 5)
                self.assertLessEqual(len(items), 7)

    def test_every_section_represents_all_three_tags(self):
        # Application is the one that goes missing, because it is the one
        # that takes work: a scenario with real numbers in it, not a
        # question about the material.
        for heading, items in self.sections.items():
            with self.subTest(section=heading):
                self.assertEqual({tag for _, _, tag in items}, {"R", "A", "W"})

    def test_items_are_numbered_within_their_section_from_one(self):
        for heading, items in self.sections.items():
            with self.subTest(section=heading):
                self.assertEqual([m for _, m, _ in items],
                                 [str(n) for n in range(1, len(items) + 1)])
                self.assertEqual(len({n for n, _, _ in items}), 1)

    def test_every_item_carries_its_answer_and_its_teaching_note(self):
        # The bank is drawn from live by a tutor that has to teach a miss,
        # so an item without a note is an item that can only mark.
        with open(self.BANK, encoding="utf-8") as f:
            blocks = f.read().split("\n\n")
        items = [b for b in blocks if self.ITEM.match(b)]
        self.assertEqual(len(items), sum(len(v) for v in self.sections.values()))
        for block in items:
            with self.subTest(item=block.split("**")[1]):
                self.assertIn("\n**Answer:** ", block)
                self.assertIn("\n**Note:** ", block)

    def test_the_shipped_exemplar_is_this_bank_first_section(self):
        # The other direction from `test_nothing_has_drifted_from_tinylang`:
        # that one asks whether the exemplar still matches the bank, this one
        # asks whether the section it was cut from is still the first one —
        # so re-curating from a *different* section, which would quietly
        # change what every first build is taught, has to be deliberate.
        with open(os.path.join(REPO_ROOT, "curricle", "exemplars",
                               "bank-section.md"), encoding="utf-8") as f:
            exemplar = f.read()
        with open(self.BANK, encoding="utf-8") as f:
            body = f.read()
        first = body.index("## ")
        self.assertTrue(body[first:].startswith(exemplar.rstrip()))


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
