"""The unit page and reader contracts, on a synthetic course.

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
from curricle.schema import (
    Condition, Grader, Stage, Step, Track, TriggerPhrase,
)
from curricle.sidecar import (
    Sidecar, SidecarCourse, SidecarMaterial, SidecarMilestone, SidecarUnit,
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
    os.makedirs(os.path.join(learning, "interactive", "chapters"))
    with open(os.path.join(learning, "interactive/chapters/u1.md"), "w") as f:
        f.write("# Chapter\n\nRead me.[^1]\n\n[^1]: A source.\n")
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
            SidecarMaterial(id="c-u1", kind="chapter", title="The chapter",
                            path="interactive/chapters/u1.md", unit="u1"),
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


class TestChapterOnUnitPage(unittest.TestCase):
    def setUp(self):
        self.mf = make_manifest()

    def test_chapter_is_the_start_panel_and_the_primary_action(self):
        page = render_unit(self.mf, "u1", api="../api/events")
        self.assertIn("Start here", page)
        self.assertIn('class="pill primary" href="../read/interactive/chapters/u1.md">'
                      "Read the chapter", page)
        self.assertLess(page.index("The chapter"), page.index("The lesson"))

    def test_chapter_contributes_its_own_tag(self):
        self.assertIn("chapter", self.mf.tags_for_unit("u1"))
        self.assertIn("lesson", self.mf.tags_for_unit("u1"))


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

    def test_chapter_gets_its_own_banner_not_the_dialogue_one(self):
        m = next(m for m in self.mf.materials if m.id == "c-u1")
        page = render_reader(self.mf, "# C\n\nBody.[^1]\n\n[^1]: Src.",
                             doc_title="The chapter", material=m)
        self.assertIn("This is the unit's chapter.", page)
        self.assertNotIn("dialogue script", page)
        self.assertIn('<section class="footnotes">', page)

    def test_a_chapter_figure_resolves_from_the_chapter_directory(self):
        m = next(m for m in self.mf.materials if m.id == "c-u1")
        page = render_reader(self.mf, "# C\n\n![A graph](figures/g.svg)\n",
                             doc_title="The chapter", material=m)
        # read/interactive/chapters/u1.md is three deep; the figure is served
        # by the content route at interactive/chapters/figures/g.svg
        self.assertIn('<img src="../../../interactive/chapters/figures/g.svg" alt="A graph">', page)
        self.assertIn("<figcaption>A graph</figcaption>", page)

    def test_plain_document_renders_without_banner(self):
        page = render_reader(self.mf, "# Doc\n\nBody.", doc_title="Doc")
        self.assertNotIn("dialogue script", page)
        self.assertIn("<h1>Doc</h1>", page)

    def test_a_material_document_flows_back_to_its_unit(self):
        m = next(m for m in self.mf.materials if m.id == "l-u1")
        page = render_reader(self.mf, "# L\n\nBody.", doc_title="The lesson",
                             material=m)
        self.assertIn("Unit 1 — The unit", page)


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
        self.assertIn('href="u2.html">'
                      '<b class="dir">Next</b>Unit 2 — The deep end', self.u1)
        self.assertNotIn("Previous", self.u1)        # nothing before u1
        self.assertIn('href="u1.html">'
                      '<b class="dir">Previous</b>Unit 1 — First steps', self.u2)

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


# --- the walk (a unit that owns one of everything) ---------------------------

WALK_CURRICULUM = textwrap.dedent("""\
    ## Phase 1 — Work (Weeks 1–3)

    **Goal:** Do the work.

    ### Unit 1 — First steps

    - **Build:** the thing, in `thing/`.
    - **Read:** [Alpha](res:alpha), the first chapter; then [Beta](res:beta).
    - **Concepts:** the one idea; why the second follows; the *third* as a choice.
    - **Side track:** finish stage one.
    - **Exercise:** [the starter](mat:x-u1) — make its tests pass.
    - **Milestone:** `thing/` committed with tests.
    - **Key insight:** it was a loop all along.
    - **Caveat to carry forward:** the second idea is contested.

    ### Unit 2 — The deep end

    - **Build:** more thing.
    - **Read:** [Beta](res:beta), the rest of it.
    - **Concepts:** one only.

    ### — Phase 1 Checkpoint —
    Everything works end to end.

    *Version 1.0 — 2026-01-01. Initial.*
    """)


def make_walk_manifest():
    from curricle.schema import Resource
    root = tempfile.mkdtemp()
    learning = os.path.join(root, "learning")
    for d in ("lessons", "chapters", "widgets", "exercises/u1-starter", "quizzes"):
        os.makedirs(os.path.join(learning, "interactive", d))
    with open(os.path.join(learning, "curriculum.md"), "w") as f:
        f.write(WALK_CURRICULUM)
    files = {"interactive/lessons/u1.md": "# Lesson\n",
             "interactive/chapters/u1.md": "# Chapter\n",
             "interactive/widgets/w.html": "<!doctype html>",
             "interactive/quizzes/p1.html": "<!doctype html>",
             "interactive/quizzes/bank.md": "# Bank\n",
             "interactive/exercises/u1-starter/task.md": "# Task\n"}
    for rel, text in files.items():
        with open(os.path.join(learning, rel), "w") as f:
            f.write(text)
    sidecar = Sidecar(
        course=SidecarCourse(
            id="walk", title="Walk", mode="subject", hours_per_week=(1, 2),
            trigger_phrases=(
                TriggerPhrase(say="Teach me Unit 2 interactively.",
                              note="a guide exists for Unit 1."),
                TriggerPhrase(say="Quiz me on Phase 3.",
                              note="draws from the checkpoint quiz."),
            ),
        ),
        tracks=(Track(id="side", name="Side", cadence="an hour a week",
                      stages=(Stage(id="s1", label="one"),),
                      row_labels=("Side track",)),),
        resources=(
            Resource(key="alpha", title="Alpha", url="https://example.org/alpha"),
            Resource(key="beta", title="Beta", url="https://example.org/beta"),
        ),
        units=(SidecarUnit(id="u1", num=1), SidecarUnit(id="u2", num=2)),
        milestones=(SidecarMilestone(
            id="m-side", phase_num=1, kind="side-quest", label="Polish the errors",
            detail="One afternoon, optional.", after_unit="u1"),),
        materials=(
            SidecarMaterial(id="c-u1", kind="chapter", title="The chapter",
                            path="interactive/chapters/u1.md", unit="u1"),
            SidecarMaterial(id="l-u1", kind="lesson", title="The lesson",
                            path="interactive/lessons/u1.md", unit="u1",
                            blurb="A conversation that asks rather than tells."),
            SidecarMaterial(id="w-u1", kind="widget", title="The widget",
                            path="interactive/widgets/w.html", unit="u1"),
            SidecarMaterial(id="x-u1", kind="exercise", title="The starter",
                            path="interactive/exercises/u1-starter", unit="u1",
                            grader=Grader(type="unit-test", runner="python",
                                          command="python -m unittest discover x")),
            SidecarMaterial(id="q-p1", kind="quiz", title="Phase 1 quiz",
                            path="interactive/quizzes/p1.html", phase_num=1),
            SidecarMaterial(id="bank", kind="question-bank", title="Question bank",
                            path="interactive/quizzes/bank.md"),
        ),
    )
    mf, issues = compile_course(root, sidecar)
    assert mf is not None, [str(i) for i in issues]
    return mf, issues


class TestTheWalk(unittest.TestCase):
    """The unit page places rows by role and materials by kind, in the
    order a learner needs them: start, work, read, know, tracks, the
    assistant, the browser, done. Authoring order is not page order."""

    @classmethod
    def setUpClass(cls):
        cls.mf, cls.issues = make_walk_manifest()
        cls.u1 = render_unit(cls.mf, "u1", api="../api/events")
        cls.u2 = render_unit(cls.mf, "u2", api="../api/events")

    def _order(self, page, *needles):
        idx = [page.index(n) for n in needles]
        self.assertEqual(idx, sorted(idx), needles)

    def test_sections_come_in_walking_order_not_authoring_order(self):
        # The curriculum authored Exercise after the track row and the
        # Caveat last; the page puts the work together and the caveat as
        # its own field after the vocabulary sections.
        self._order(self.u1, "Start here", "<h2>The work</h2>",
                    '<b class="lbl">Build</b>', '<b class="lbl">Exercise</b>',
                    "<h2>Read</h2>", "<h2>Concepts</h2>", "Side track",
                    "Caveat to carry forward", "With your assistant",
                    "<h2>Try it</h2>", "<h2>Done means</h2>",
                    '<b class="lbl">Milestone</b>', 'id="mark"',
                    "Phase 1 checkpoint", "Polish the errors",
                    '<b class="dir">Next</b>')

    def test_the_chapter_holds_the_only_primary_pill(self):
        self.assertEqual(self.u1.count("pill primary"), 1)
        self.assertIn('href="../read/interactive/chapters/u1.md">Read the chapter',
                      self.u1)
        # the mark is a secondary pill at the bottom, not the top action
        self.assertIn('<button class="pill" id="mark"', self.u1)
        self.assertLess(self.u1.index("<h2>Done means</h2>"), self.u1.index('id="mark"'))

    def test_without_a_chapter_the_readings_start_with_the_first_named(self):
        self.assertIn("Start here", self.u2)
        self.assertIn("<h2>The readings</h2>", self.u2)
        self.assertIn('class="pill primary" href="https://example.org/beta"'
                      ' target=_blank rel=noopener>Read Beta', self.u2)
        self.assertNotIn("<h2>Read</h2>", self.u2)     # the start panel is it

    def test_exercise_material_attaches_to_its_row_with_the_grader_command(self):
        self.assertIn('<div class="exercise panel">', self.u1)
        self.assertIn("python -m unittest discover x", self.u1)
        self.assertIn('href="../read/interactive/exercises/u1-starter/task.md"', self.u1)
        self.assertLess(self.u1.index('<b class="lbl">Exercise</b>'),
                        self.u1.index('<div class="exercise panel">'))
        self.assertLess(self.u1.index('<div class="exercise panel">'),
                        self.u1.index("<h2>Read</h2>"))

    def test_concepts_split_on_semicolons_into_a_list(self):
        self.assertIn('<ul class="know">', self.u1)
        self.assertIn("<li>The one idea</li>", self.u1)
        self.assertIn("<li>The <i>third</i> as a choice.</li>", self.u1)
        # a single concept stays prose
        self.assertNotIn('<ul class="know">', self.u2)
        self.assertIn("one only", self.u2)

    def test_track_row_is_headed_by_its_track_name_and_cadence(self):
        self.assertIn("<h2>Side track <span class=\"trackline\">· an hour a week</span></h2>",
                      self.u1)
        self.assertIn("Finish stage one.", self.u1)       # capitalised as a field
        self.assertIn("The second idea is contested.", self.u1)   # a course's own label, likewise

    def test_lesson_is_offered_as_the_sentence_that_runs_it(self):
        self.assertIn('<span class="say">Teach me Unit 1 interactively.</span>', self.u1)
        self.assertIn('href="../read/interactive/lessons/u1.md">See the script.</a>', self.u1)
        self.assertIn("a conversation that asks rather than tells", self.u1)
        self.assertNotIn("Read the lesson guide", self.u1)
        # the lesson is not a card
        self.assertNotIn('<span class="chip">lesson</span>', self.u1)

    def test_a_unit_without_a_guide_still_gets_the_row(self):
        self.assertIn("Teach me Unit 2 interactively.", self.u2)
        self.assertIn("improvises one from the curriculum", self.u2)

    def test_quiz_phrase_retargets_to_this_phase_and_names_the_bank(self):
        self.assertIn('<span class="say">Quiz me on Phase 1.</span>', self.u1)
        self.assertNotIn("Phase 3", self.u1)
        self.assertIn('href="../interactive/quizzes/p1.html">Phase 1 quiz</a> in conversation',
                      self.u1)
        self.assertIn('href="../read/interactive/quizzes/bank.md">question bank</a>', self.u1)

    def test_quiz_phrase_is_offered_only_where_a_quiz_exists(self):
        mf = make_flow_manifest()      # a course with a teach phrase, no quiz
        page = render_unit(mf, "u1", api="../api/events")
        self.assertIn("With your assistant", page)
        self.assertNotIn("Quiz me", page)

    def test_widget_is_a_card_under_try_it(self):
        self.assertIn('<span class="chip acc">widget</span>', self.u1)
        self.assertIn("Open the widget", self.u1)

    def test_side_quest_after_this_unit_lands_before_the_way_on(self):
        self.assertIn("Before you go on, optional: Polish the errors", self.u1)
        self.assertIn("One afternoon, optional.", self.u1)
        self.assertNotIn("Polish the errors", self.u2)

    def test_a_read_row_that_links_the_chapter_warns(self):
        # The page leads with the chapter; a Read row that also opens with
        # it says the same thing twice. The walk fixture keeps its Read row
        # clean, so no warning; a course that links the chapter gets one.
        self.assertFalse(any("own chapter" in i.message for i in self.issues))
        mf = make_manifest()   # no chapter link in its Read row either
        self.assertIsNotNone(mf)
