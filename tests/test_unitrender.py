"""The unit page and reader contracts, on a synthetic course (SPIKE).

What these pin: the unit page links every material its unit owns through
the right route (markdown through read/, HTML straight), the phase
checkpoint appears on units of a phase that has one, steps arrive as live
checkboxes, and the reader frames a lesson as the dialogue script it is
while climbing the right number of directories back to the hub.
"""

import os
import tempfile
import textwrap
import unittest

from curricle.compiler import compile_course
from curricle.schema import Step
from curricle.sidecar import (
    Sidecar, SidecarCourse, SidecarMaterial, SidecarUnit,
)
from curricle.unitrender import render_reader, render_unit

CURRICULUM = textwrap.dedent("""\
    ## Phase 0 — Orientation (Week 0)

    **Goal:** Get going.

    - **Build:** setup.
    - **Read:** the readme.

    ## Phase 1 — Work (Weeks 1–3)

    **Goal:** Do the work.

    ### Unit 1 — The unit

    - **Build:** the thing.

    *Version 1.0 — 2026-01-01. Initial.*
    """)


def make_manifest():
    root = tempfile.mkdtemp()
    learning = os.path.join(root, "learning")
    os.makedirs(os.path.join(learning, "interactive", "quizzes"))
    os.makedirs(os.path.join(learning, "interactive", "lessons"))
    with open(os.path.join(learning, "curriculum.md"), "w") as f:
        f.write(CURRICULUM)
    for rel in ("interactive/quizzes/p0.html",):
        with open(os.path.join(learning, rel), "w") as f:
            f.write("<!doctype html>")
    with open(os.path.join(learning, "interactive/lessons/u1.md"), "w") as f:
        f.write("# Lesson\n\nRun as dialogue.\n")
    sidecar = Sidecar(
        course=SidecarCourse(
            id="test-course", title="A test course",
            mode="subject", hours_per_week=(1, 2),
        ),
        units=(
            SidecarUnit(id="u0", num=0, phase_body=True,
                        steps=(Step(id="u0-a", label="first step"),
                               Step(id="u0-b", label="second step"))),
            SidecarUnit(id="u1", num=1, gloss="The first."),
        ),
        milestones=(),
        materials=(
            SidecarMaterial(id="q-p0", kind="quiz", title="Phase 0 quiz",
                            path="interactive/quizzes/p0.html", phase_num=0),
            SidecarMaterial(id="l-u1", kind="lesson", title="The lesson",
                            path="interactive/lessons/u1.md", unit="u1"),
        ),
    )
    mf, issues = compile_course(root, sidecar)
    assert mf is not None, [str(i) for i in issues]
    return mf


class TestUnitPage(unittest.TestCase):
    def setUp(self):
        self.mf = make_manifest()

    def test_markdown_material_links_through_the_reader(self):
        page = render_unit(self.mf, "u1", api="../api/events")
        self.assertIn('href="../read/interactive/lessons/u1.md"', page)
        self.assertIn("lesson", page)          # the chip says what it is

    def test_phase_checkpoint_appears_on_its_phase_units_only(self):
        with_cp = render_unit(self.mf, "u0", api="../api/events")
        without = render_unit(self.mf, "u1", api="../api/events")
        self.assertIn("Phase 0 checkpoint", with_cp)
        self.assertIn('href="../interactive/quizzes/p0.html"', with_cp)
        self.assertNotIn("checkpoint", without)

    def test_steps_render_as_checkboxes_and_feed_the_script(self):
        page = render_unit(self.mf, "u0", api="../api/events")
        self.assertIn('id="u0-a"', page)
        self.assertIn('"steps": ["u0-a", "u0-b"]', page)

    def test_the_page_posts_to_the_events_api(self):
        page = render_unit(self.mf, "u1", api="../api/events")
        self.assertIn('const API = "../api/events"', page)


class TestReader(unittest.TestCase):
    def setUp(self):
        self.mf = make_manifest()

    def test_lesson_gets_the_dialogue_banner_and_unit_crumb(self):
        m = next(m for m in self.mf.materials if m.id == "l-u1")
        page = render_reader(self.mf, "# L\n\nBody.", doc_title="The lesson",
                            material=m)
        self.assertIn("dialogue script", page)
        # read/interactive/lessons/u1.md sits three levels down
        self.assertIn('href="../../../index.html"', page)
        self.assertIn('href="../../../unit/u1.html"', page)

    def test_plain_document_renders_without_banner(self):
        page = render_reader(self.mf, "# Doc\n\nBody.", doc_title="Doc")
        self.assertNotIn("dialogue script", page)
        self.assertIn("<h1>Doc</h1>", page)
