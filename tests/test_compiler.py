import os
import tempfile
import textwrap
import unittest

from curricle.compiler import compile_course
from curricle.sidecar import (
    Sidecar, SidecarCourse, SidecarMaterial, SidecarMilestone, SidecarUnit,
)
from curricle.schema import Grader, Step, Track, Stage

CURRICULUM = textwrap.dedent("""\
    ## Phase 0 — Orientation (Week 0)

    **Goal:** Get going.

    - **Build:** setup.
    - **Read:** the readme.

    ## Phase 1 — Work (Weeks 1–3)

    **Goal:** Do the work.

    ### Unit 1 — The unit

    - **Build:** the thing.
    - **Milestone:** thing built.

    ### Unit 2 — More unit

    - **Build:** more thing.

    ### — Phase 1 Checkpoint —
    Done with work. **Side by now:** halfway.

    *Version 1.0 — 2026-01-01. Initial.*
    """)


def make_course_dir():
    root = tempfile.mkdtemp()
    learning = os.path.join(root, "learning")
    os.makedirs(os.path.join(learning, "interactive", "lessons"))
    with open(os.path.join(learning, "curriculum.md"), "w") as f:
        f.write(CURRICULUM)
    with open(os.path.join(learning, "interactive", "lessons", "unit-01.md"), "w") as f:
        f.write("# Lesson\n")
    return root


def base_sidecar(**overrides):
    kw = dict(
        course=SidecarCourse(
            id="test", title="Test", mode="subject", hours_per_week=(1, 2),
        ),
        tracks=(Track(id="side", name="Side", stages=(Stage(id="s1", label="one"),),
                      checkpoint_labels=("Side by now",)),),
        units=(
            SidecarUnit(id="u0", num=0, phase_body=True,
                        steps=(Step(id="u0-a", label="a"), Step(id="u0-b", label="b"))),
            SidecarUnit(id="u1", num=1, gloss="The first."),
            SidecarUnit(id="u2", num=2, gloss="The second."),
        ),
        milestones=(SidecarMilestone(id="m1", phase_num=1, kind="contact",
                                     label="Say hi", after_unit="u1"),),
        materials=(SidecarMaterial(id="l-u01", kind="lesson", title="L1",
                                   path="interactive/lessons/unit-01.md", unit="u1"),),
    )
    kw.update(overrides)
    return Sidecar(**kw)


class TestCompile(unittest.TestCase):
    def setUp(self):
        self.root = make_course_dir()

    def test_clean_compile(self):
        mf, issues = compile_course(self.root, base_sidecar())
        self.assertIsNotNone(mf, [str(i) for i in issues])
        self.assertFalse(issues.has_errors)
        # Phase-body unit realized with steps; milestone after its anchor.
        self.assertEqual(mf.phases[0].entries, ("u0",))
        self.assertEqual(mf.phases[1].entries, ("u1", "m1", "u2"))
        # Progress ids: steps replace the stepped unit; stages appended.
        self.assertEqual(mf.progress_ids(),
                         ("u0-a", "u0-b", "u1", "m1", "u2", "s1"))
        # Checkpoint track goal attributed via checkpoint_labels.
        cp = mf.phases[1].checkpoint
        self.assertEqual(cp.track_goals, (("side", "halfway."),))
        self.assertEqual(cp.prose, "Done with work.")

    def test_missing_material_path_is_error(self):
        sc = base_sidecar(materials=(
            SidecarMaterial(id="l-x", kind="lesson", title="X",
                            path="interactive/lessons/nope.md", unit="u1"),))
        mf, issues = compile_course(self.root, sc)
        self.assertIsNone(mf)
        self.assertTrue(any("path does not exist" in i.message for i in issues))

    def test_dangling_unit_ref_is_error(self):
        sc = base_sidecar(materials=(
            SidecarMaterial(id="l-x", kind="lesson", title="X",
                            path="interactive/lessons/unit-01.md", unit="u9"),))
        mf, issues = compile_course(self.root, sc)
        self.assertIsNone(mf)
        self.assertTrue(any("does not resolve" in i.message for i in issues))

    def test_sidecar_unit_without_md_counterpart_is_error(self):
        sc = base_sidecar(units=(
            SidecarUnit(id="u0", num=0, phase_body=True),
            SidecarUnit(id="u1", num=1),
            SidecarUnit(id="u2", num=2),
            SidecarUnit(id="u9", num=9),))
        mf, issues = compile_course(self.root, sc)
        self.assertIsNone(mf)
        self.assertTrue(any("no such unit" in i.message for i in issues))

    def test_duplicate_id_is_error(self):
        sc = base_sidecar(milestones=(
            SidecarMilestone(id="u1", phase_num=1, kind="contact", label="dupe"),))
        mf, issues = compile_course(self.root, sc)
        self.assertIsNone(mf)
        self.assertTrue(any("id used by both" in i.message for i in issues))

    def test_unregistered_file_warns(self):
        extra = os.path.join(self.root, "learning", "interactive", "lessons", "stray.md")
        with open(extra, "w") as f:
            f.write("stray\n")
        mf, issues = compile_course(self.root, base_sidecar())
        self.assertIsNotNone(mf)
        self.assertTrue(any("unregistered file" in i.message for i in issues))

    def test_derived_quiz_chip_on_last_unit(self):
        sc = base_sidecar(materials=(
            SidecarMaterial(id="l-u01", kind="lesson", title="L1",
                            path="interactive/lessons/unit-01.md", unit="u1"),
            SidecarMaterial(id="q-p1", kind="quiz", title="Q1",
                            path="interactive/lessons/unit-01.md", phase_num=1),))
        mf, issues = compile_course(self.root, sc)
        self.assertIsNotNone(mf)
        self.assertIn("quiz", mf.tags_for_unit("u2"))       # last unit of p1
        self.assertNotIn("quiz", mf.tags_for_unit("u1"))
        self.assertEqual(mf.phases[1].checkpoint.quiz, "q-p1")

    def test_grader_types_are_enforced(self):
        with self.assertRaises(Exception):
            Grader(type="vibes")


if __name__ == "__main__":
    unittest.main()
