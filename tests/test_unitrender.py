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
from curricle.currender import render_curriculum
from curricle.schema import Condition, Step, TriggerPhrase
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

    def test_a_material_document_flows_back_to_its_unit(self):
        m = next(m for m in self.mf.materials if m.id == "l-u1")
        page = render_reader(self.mf, "# L\n\nBody.", doc_title="The lesson",
                             material=m)
        self.assertIn("Back to Unit 1 — The unit", page)


# --- the flowing unit page (fuller synthetic course) -------------------------

FLOW_CURRICULUM = textwrap.dedent("""\
    ## Phase 1 — Work (Weeks 1–3)

    **Goal:** Do the work.

    ### Unit 1 — First steps

    - **Build:** the thing.
    - **Milestone:** `thing/` committed with tests.
    - **Interactive:** lesson `interactive/lessons/u1.md`.

    ### Unit 2 — The deep end

    - **Build:** more thing.

    ### — Phase 1 Checkpoint —
    Everything works end to end.

    *Version 1.0 — 2026-01-01. Initial.*
    """)


def make_flow_manifest():
    root = tempfile.mkdtemp()
    learning = os.path.join(root, "learning")
    os.makedirs(os.path.join(learning, "interactive", "lessons"))
    with open(os.path.join(learning, "curriculum.md"), "w") as f:
        f.write(FLOW_CURRICULUM)
    with open(os.path.join(learning, "interactive/lessons/u1.md"), "w") as f:
        f.write("# Lesson\n")
    sidecar = Sidecar(
        course=SidecarCourse(
            id="flow", title="Flow", mode="subject", hours_per_week=(1, 2),
            trigger_phrases=(TriggerPhrase(
                say="Teach me Unit 2 interactively."),),
        ),
        units=(
            SidecarUnit(id="u1", num=1),
            SidecarUnit(id="u2", num=2, depends_on=("u1",),
                        note="Runs long; that is the point.",
                        condition=Condition(on="library card", state="pending")),
        ),
        materials=(
            SidecarMaterial(id="l-u1", kind="lesson", title="The lesson",
                            path="interactive/lessons/u1.md", unit="u1"),
        ),
    )
    mf, issues = compile_course(root, sidecar)
    assert mf is not None, [str(i) for i in issues]
    return mf


class TestFlowingUnitPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = make_flow_manifest()
        cls.u1 = render_unit(cls.mf, "u1", api="../api/events")
        cls.u2 = render_unit(cls.mf, "u2", api="../api/events")

    def test_phase_goal_appears_under_the_masthead(self):
        self.assertIn("Phase 1 — Work.", self.u1)
        self.assertIn("Do the work.", self.u1)

    def test_milestone_row_gets_the_deliverable_treatment(self):
        self.assertIn('class="row deliver"', self.u1)

    def test_authored_interactive_row_is_not_rendered(self):
        # The materials section is that row, derived; the authored path
        # dump never reaches the page.
        self.assertNotIn("<b class=\"lbl\">Interactive</b>", self.u1)

    def test_context_says_what_the_unit_builds_on_and_what_gates_it(self):
        self.assertIn("Builds on", self.u2)
        self.assertIn('href="../unit/u1.html">Unit 1 — First steps</a>',
                      self.u2)
        self.assertIn("gated · pending", self.u2)
        self.assertIn("waits on library card", self.u2)

    def test_sidecar_note_is_rendered(self):
        self.assertIn("Runs long; that is the point.", self.u2)
        self.assertNotIn("Runs long", self.u1)

    def test_prev_next_walk_the_course_order(self):
        self.assertIn('href="u2.html">Unit 2 — The deep end →', self.u1)
        self.assertNotIn("← Unit", self.u1)          # nothing before u1
        self.assertIn('href="u1.html">← Unit 1 — First steps', self.u2)

    def test_checkpoint_prose_lands_on_the_phase_closing_unit_only(self):
        self.assertIn("this unit closes the phase", self.u2)
        self.assertIn("Everything works end to end.", self.u2)
        self.assertNotIn("Everything works end to end.", self.u1)

    def test_reader_retargets_the_trigger_phrase_to_this_unit(self):
        m = next(m for m in self.mf.materials if m.id == "l-u1")
        page = render_reader(self.mf, "# L\n", doc_title="The lesson",
                             material=m)
        self.assertIn("Teach me Unit 1 interactively.", page)
        self.assertNotIn("Teach me Unit 2 interactively.", page)


class TestDerivedInteractiveRow(unittest.TestCase):
    def test_curriculum_derives_the_row_from_materials(self):
        mf = make_manifest()   # u1 owns a lesson, authors no Interactive row
        page = render_curriculum(mf, api="api/events", unit_pages=True)
        self.assertIn('lesson — <a href=\\"read/interactive/lessons/'
                      'u1.md\\">The lesson</a>', page)

    def test_an_authored_row_suppresses_derivation(self):
        mf = make_flow_manifest()   # u1 authors an Interactive row
        page = render_curriculum(mf, api="api/events", unit_pages=True)
        # The authored row's text is present, the derived link form absent.
        self.assertIn("interactive/lessons/u1.md", page)
        self.assertNotIn("lesson — <a", page)
