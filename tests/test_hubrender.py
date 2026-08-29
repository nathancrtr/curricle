"""The hub renderer's contracts, on a synthetic course.

tests/test_corpus.py pins the hub against textual-flow, but it skips when the
sibling repos are absent and — by design — it asserts about one course's data.
These tests own the renderer's *rules*, on a fixture built to contain the one
shape that keeps catching people out: a stepped unit whose steps are tracked
individually, sitting in the same payload as a true milestone. The two look
alike in the page and are not alike in the data, and every mutant below was
confirmed to survive the rest of the suite before this file existed.
"""

import json
import os
import re
import tempfile
import textwrap
import unittest

from curricle import hubrender
from curricle.compiler import compile_course
from curricle.hubrender import render_hub
from curricle.schema import Stage, Step, Track
from curricle.sidecar import (
    Sidecar, SidecarCourse, SidecarMaterial, SidecarMilestone, SidecarUnit,
)
# The WCAG helper and the two palettes, from the module that proves the
# helper against known values — a second copy here would be a second
# thing to trust.
from test_theme import DARK, LIGHT, _contrast

# u0 is a phase-body unit realized as two tracked steps; phase 1 holds a plain
# unit, a milestone, and another plain unit. The phase-0 quiz puts a "quiz"
# chip on that phase's last row, which is the exact configuration the corpus
# pin guards: a three-element step row carrying chips, immediately recognisable
# as a milestone row if you are reading the page rather than the payload.
CURRICULUM = textwrap.dedent("""\
    ## Phase 0 — Orientation (Week 0)

    **Goal:** Get going.

    - **Build:** setup.
    - **Read:** the readme.

    ## Phase 1 — Work (Weeks 1–3)

    **Goal:** Do the work.

    ### Unit 1 — The unit

    - **Build:** the thing.

    ### Unit 2 — More unit

    - **Build:** more thing.

    *Version 1.0 — 2026-01-01. Initial.*
    """)

MILESTONE_LABEL = "\U0001F4EE Contact milestone: say hi"


def make_manifest():
    root = tempfile.mkdtemp()
    learning = os.path.join(root, "learning")
    os.makedirs(os.path.join(learning, "interactive", "quizzes"))
    with open(os.path.join(learning, "curriculum.md"), "w") as f:
        f.write(CURRICULUM)
    with open(os.path.join(learning, "interactive", "quizzes", "p0.html"), "w") as f:
        f.write("<!doctype html>")
    sidecar = Sidecar(
        course=SidecarCourse(
            id="test-course", title="A title that is not the slug",
            mode="subject", hours_per_week=(1, 2),
            description="What this course is.",
        ),
        tracks=(Track(id="side", name="Side",
                      stages=(Stage(id="s1", label="one"),
                              Stage(id="s2", label="two"))),),
        units=(
            SidecarUnit(id="u0", num=0, phase_body=True,
                        steps=(Step(id="u0-a", label="first step"),
                               Step(id="u0-b", label="second step"))),
            SidecarUnit(id="u1", num=1, gloss="The first."),
            SidecarUnit(id="u2", num=2, gloss="The second."),
        ),
        milestones=(SidecarMilestone(id="m1", phase_num=1, kind="contact",
                                     label=MILESTONE_LABEL, after_unit="u1"),),
        materials=(SidecarMaterial(id="q-p0", kind="quiz", title="Phase 0 quiz",
                                   path="interactive/quizzes/p0.html",
                                   phase_num=0),),
    )
    mf, issues = compile_course(root, sidecar)
    assert mf is not None, [str(i) for i in issues]
    return mf


def payload(page: str, name: str):
    """The JSON assigned to `const <name>` in the emitted script."""
    m = re.search(r"const %s = (\[.*?\]);\n" % name, page, re.S)
    assert m, f"no `const {name} = [...]` in the page"
    return json.loads(m.group(1))


def js_function_body(page: str, name: str) -> str:
    """The source between the braces of `function <name>(...) {...}`.

    Extracted by brace matching rather than by regex, because the mutant this
    guards against does not delete a line — it hoists one out of the function
    to run once at load, which a whole-page substring search cannot see.
    """
    start = page.index(f"function {name}(")
    opened = page.index("{", start)
    depth, i = 1, opened + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(page[i], 0)
        i += 1
    return page[opened + 1:i - 1]


class TestProgramTrackPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = make_manifest()
        cls.page = render_hub(cls.mf)
        cls.phases = payload(cls.page, "PHASES")

    def test_only_true_milestones_carry_the_kind_marker(self):
        # The trap: a milestone row and a step row look the same on the page,
        # so it is tempting to give every row a uniform four-element shape.
        # Doing that breaks the corpus pin on p0's last row, which protects
        # stored progress ids. Rows stay heterogeneous, and the marker is the
        # thing that says which is which.
        rows = [row for p in self.phases for row in p["units"]]
        marked = {row[0] for row in rows if len(row) == 4 and row[3] == "m"}
        milestones = {m.id for m in self.mf.milestones}
        self.assertEqual(marked, milestones)
        self.assertEqual(marked, {"m1"})
        # And nothing else grew a fourth element — steps least of all.
        self.assertEqual([len(row) for row in rows], [3, 3, 3, 4, 3])

    def test_a_stepped_units_last_step_carries_chips_and_stays_three_long(self):
        # The corpus asserts this exact equality against textual-flow's
        # "p0-para" row; here it is on synthetic data, so it holds whether or
        # not the sibling repos are checked out.
        self.assertEqual(self.phases[0]["units"][-1],
                         ["u0-b", "second step", ["quiz"]])

    def test_the_milestone_label_sheds_its_leading_pictograph(self):
        row = next(r for p in self.phases for r in p["units"] if r[0] == "m1")
        self.assertEqual(row[1], "Contact milestone: say hi")
        # …and the raw glyph reaches no part of the page, payload or markup.
        self.assertNotIn("\U0001F4EE", self.page)

    def test_the_payload_assignments_stay_adjacent(self):
        # PHASES and TRACKS are read as one regex over consecutive lines by
        # tests/test_corpus.py. A comment slipped between them is invisible
        # here and fatal there.
        self.assertRegex(self.page,
                         r"const PHASES = \[.*?\];\nconst TRACKS = \[.*?\];\n")

    def test_phases_are_numbered_for_the_spine_badges(self):
        self.assertEqual([p["num"] for p in self.phases], ["0", "1"])
        self.assertEqual([p["name"] for p in self.phases],
                         ["Orientation", "Work"])


class TestServerAndStandalone(unittest.TestCase):
    """The two renders differ in what may be linked to, and nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.mf = make_manifest()
        cls.standalone = render_hub(cls.mf)
        cls.served = render_hub(cls.mf, api="api/events",
                                initial={"u0-a": True})

    def test_sibling_pills_render_only_in_server_mode(self):
        # A standalone file may sit beside no curriculum at all; a dead
        # primary button is worse than no button.
        self.assertIn('<a class="pill" href="curriculum.html">', self.served)
        self.assertIn('<a class="pill" href="learning-resources.html">', self.served)
        self.assertNotIn('href="curriculum.html"', self.standalone)
        self.assertNotIn('href="learning-resources.html"', self.standalone)

    def test_the_resume_pill_exists_in_both_and_starts_hidden(self):
        for label, page in (("served", self.served),
                            ("standalone", self.standalone)):
            with self.subTest(mode=label):
                self.assertIn('<a class="pill primary" id="resume" href="#" hidden>',
                              page)

    def test_the_continue_action_forks_on_whether_there_is_an_api(self):
        # The fork itself is taken in the browser, so this pins the emitted
        # source: server mode deep-links into the curriculum at the next
        # entry, a standalone file jumps down its own page to the next row.
        # Degrading the server arm to the local one is the mutant — it leaves
        # every other test in the suite green and quietly removes the action
        # the hub was rebuilt around.
        for label, page in (("served", self.served),
                            ("standalone", self.standalone)):
            with self.subTest(mode=label):
                body = js_function_body(page, "refresh")
                self.assertIn(
                    "r.href = API ? `curriculum.html#u-${encodeURIComponent(nextId)}`",
                    body)
                self.assertIn(": `#${encodeURIComponent(nextId)}`;", body)

    def test_the_api_and_initial_constants_carry_the_fold(self):
        self.assertIn('const API = "api/events"', self.served)
        self.assertIn('"u0-a": true', self.served)
        self.assertIn("const API = null", self.standalone)


class TestLiveElements(unittest.TestCase):
    """Things the page recomputes, pinned inside the function that recomputes.

    Per-phase counts and the single hot row are the spine's whole mechanic.
    Both are cheap to break by hoisting them to load time — the page still
    renders, still looks right on arrival, and simply stops responding. The
    brace-matched extraction is what makes the hoist visible.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = render_hub(make_manifest())
        cls.refresh = js_function_body(cls.page, "refresh")

    def test_per_phase_counts_are_written_by_refresh(self):
        self.assertIn("phaseEls[i].count.textContent = `${d} of ${p.units.length}`",
                      self.refresh)

    def test_the_hot_row_is_reassigned_by_refresh(self):
        self.assertIn('rows[id].classList.toggle("next", id === nextId)',
                      self.refresh)

    def test_the_holding_phase_is_marked_by_refresh(self):
        self.assertIn('phaseEls[i].div.classList.toggle("current"', self.refresh)


class TestTheHotMilestoneRow(unittest.TestCase):
    """The one place two tinted backgrounds meet.

    A milestone that is also the next row wears both `.ms` and `.next`. The
    green fill wins the cascade, so the hot row's ring is drawn on
    --good-soft rather than on --panel, and it is a different contrast
    question with a different answer. DIRECTION.md's composed round retired
    the project's last contrast exception on purpose; re-introducing one by
    cascade accident would undo that silently, which is the worst way for it
    to happen.
    """

    RULE = re.compile(r"\.unit\.ms\.next\s*\{[^}]*?border-color:\s*var\((--[\w-]+)\)")

    def test_the_ring_is_retinted_for_the_green_ground(self):
        m = self.RULE.search(hubrender.STYLE)
        self.assertIsNotNone(
            m, "no `.unit.ms.next { border-color: var(--…) }` rule: the hot "
               "milestone row falls back to .unit.next's --accent, which "
               "computes 2.82 on --good-soft, under the 3.0 non-text floor")
        token = m.group(1)
        for name, palette in (("light", LIGHT), ("dark", DARK)):
            with self.subTest(palette=name):
                ratio = _contrast(palette[token], palette["--good-soft"])
                self.assertGreaterEqual(
                    round(ratio, 2), 3.0,
                    f"{token} on --good-soft is {ratio:.2f} in the {name} "
                    "palette, under the 3.0 floor for a meaningful border")


class TestPageChrome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = make_manifest()
        cls.page = render_hub(cls.mf)

    def test_h1_is_the_course_title_and_the_slug_is_demoted(self):
        # "test-course" as a page title reads as infrastructure.
        self.assertIn("<h1>A title that is not the slug</h1>", self.page)
        self.assertIn('<p class="courseid">test-course</p>', self.page)
        self.assertNotIn("<h1>test-course</h1>", self.page)

    def test_the_tab_title_is_the_course_title_too(self):
        self.assertIn("<title>A title that is not the slug — course hub</title>",
                      self.page)

    def test_the_program_track_is_a_spine_not_a_grid(self):
        # The layout the operator asked for: one column, phases in walking
        # order. `.cols` was the masonry container that got overruled.
        self.assertIn('<div class="spine" id="phases"></div>', self.page)
        self.assertNotIn('class="cols"', self.page)


if __name__ == "__main__":
    unittest.main()
