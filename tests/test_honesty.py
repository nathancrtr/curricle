"""What the pages claim must be true of the app the reader is looking at.

Every case here started as a defect where a rendered surface stated something
the running app made false: a resources page metering a shelf that does not
exist, footers promising localStorage on a server-backed page, the hub
linking documents the server refuses to serve, and a milestone whose glyph
was a stray period. They are gathered in one file because they are one rule —
the page may only say what is true in the mode it is rendered for — and
because the fork is nearly always `api`, which no single renderer's test file
owns.

The fixture is deliberately not the corpus: textual-flow has a shelf and
rhyme-schemer has none, so the empty branch is only reachable there by
luck of what someone has transcribed. Here both shapes are built on purpose,
and neither depends on a sibling repo being checked out.
"""

import json
import os
import re
import tempfile
import unittest

from curricle import theme
from curricle.compiler import compile_course
from curricle.currender import render_curriculum
from curricle.hubrender import render_hub
from curricle.resrender import render_resources
from curricle.schema import Docs, Resource, ResourceTier, Step
from curricle.sidecar import Sidecar, SidecarCourse, SidecarMilestone, SidecarUnit
# The curriculum text and the brace-matched JS reader live with the hub's
# tests; a second copy of either would be a second thing to keep true.
from test_hubrender import CURRICULUM, js_function_body

# The corpus's document layout, which is the one that hurts: the course text
# lives under learning/ — the directory the app serves content from — and two
# of the five documents sit above it, where a served page cannot reach them.
DOCS = Docs(readme="learning/README.md",
            resources_doc="learning/learning-resources.md",
            curriculum_doc="learning/curriculum.md",
            review="REVIEW.md",
            exploration="exploration/")

SHELF = (Resource(key="r1", title="A book worth reading",
                  url="https://example.org/book", tier=1,
                  formats=("text",), free=True,
                  why_this_one="It is the one that covers the whole path."),)
TIERS = (ResourceTier(num=1, name="The core path",
                      role="Worked through substantially, in course order."),)


def make_manifest(*, resources=(), resource_tiers=(), docs=DOCS):
    root = tempfile.mkdtemp()
    # The curriculum goes where the docs say it goes: that directory is the
    # content root, and where the other documents sit relative to it is the
    # whole question the documents panel has to answer.
    curriculum = os.path.join(root, docs.curriculum_doc or "learning/curriculum.md")
    os.makedirs(os.path.dirname(curriculum))
    with open(curriculum, "w") as f:
        f.write(CURRICULUM)
    sidecar = Sidecar(
        course=SidecarCourse(
            id="test-course", title="A course", mode="subject",
            hours_per_week=(1, 2), docs=docs,
        ),
        units=(
            SidecarUnit(id="u0", num=0, phase_body=True,
                        steps=(Step(id="u0-a", label="first step"),
                               Step(id="u0-b", label="second step"))),
            SidecarUnit(id="u1", num=1, gloss="The first."),
            SidecarUnit(id="u2", num=2, gloss="The second."),
        ),
        milestones=(SidecarMilestone(id="m1", phase_num=1, kind="contact",
                                     label="Contact milestone: say hi",
                                     after_unit="u1"),),
        resources=resources, resource_tiers=resource_tiers,
    )
    mf, issues = compile_course(root, sidecar)
    assert mf is not None, [str(i) for i in issues]
    return mf


def footer(page: str) -> str:
    """The page's footer copy, whitespace collapsed."""
    m = re.search(r"<footer>(.*?)</footer>", page, re.S)
    assert m, "no <footer> on the page"
    return " ".join(m.group(1).split())


class TestFootersSayWhereProgressActuallyGoes(unittest.TestCase):
    """The trust-relevant sentence, and the only one that forks on `api`.

    Served, a learner's marks are rows in the tenant's append-only ledger and
    the front door on the same instance promises "progress kept for you".
    Telling that learner the record lives in this browser's localStorage
    invites them to treat two years of work as a cache they may clear. A
    standalone file genuinely is localStorage and keeps saying so, which is
    why this is a fork and not a rewrite.
    """

    @classmethod
    def setUpClass(cls):
        cls.mf = make_manifest(resources=SHELF, resource_tiers=TIERS)
        cls.renderers = (("hub", render_hub),
                         ("curriculum", render_curriculum),
                         ("resources", render_resources))

    def test_a_served_page_never_claims_localstorage(self):
        for name, render in self.renderers:
            with self.subTest(page=name):
                text = footer(render(self.mf, api="api/events"))
                self.assertIn("kept for you on the server", text)
                self.assertNotIn("localStorage", text)

    def test_a_standalone_page_still_says_localstorage(self):
        for name, render in self.renderers:
            with self.subTest(page=name):
                text = footer(render(self.mf))
                self.assertIn("this browser's localStorage", text)
                self.assertNotIn("server", text)


class TestTheEmptyShelf(unittest.TestCase):
    """A manifest with no resources gets a page, not a broken meter.

    Every piece of the shelf's furniture states something false when there is
    nothing on it, and the worst of them blamed the reader: "Nothing matches
    this filter." over a filter nobody had touched.
    """

    @classmethod
    def setUpClass(cls):
        cls.empty = render_resources(make_manifest(), api="api/events")
        cls.stocked = render_resources(
            make_manifest(resources=SHELF, resource_tiers=TIERS),
            api="api/events")

    def test_the_page_says_there_is_no_shelf(self):
        self.assertIn("No shelf yet.", self.empty)

    def test_none_of_the_shelfs_furniture_is_drawn(self):
        for lie in ('id="ticks"',            # the waypath, over nothing
                    'id="count"',            # "core path: 0 of 0 in hand"
                    "0 tiers",               # the crumb
                    "Nothing matches this filter.",
                    'id="f-free"', 'id="f-need"'):
            with self.subTest(absent=lie):
                self.assertNotIn(lie, self.empty)

    def test_there_is_nothing_to_wire_so_no_script_is_emitted(self):
        # Not tidiness: the shelf's script wires filter buttons by id and
        # would throw on the first line that finds none.
        self.assertNotIn("<script", self.empty)

    def test_a_stocked_shelf_is_untouched(self):
        for kept in ('id="ticks"', 'id="count"', "1 tiers",
                     "Nothing matches this filter.", "<script"):
            with self.subTest(present=kept):
                self.assertIn(kept, self.stocked)
        self.assertNotIn("No shelf yet.", self.stocked)


class TestTheHubOffersOnlyWhatExists(unittest.TestCase):
    """A dead primary button is worse than none — DIRECTION.md's rule.

    It is why the sibling pills are server-mode-only, and a course with no
    resource entries is the same situation one level down: the page resolves,
    and there is nothing on it.
    """

    def test_the_resources_pill_needs_a_shelf_to_point_at(self):
        stocked = make_manifest(resources=SHELF, resource_tiers=TIERS)
        empty = make_manifest()
        self.assertIn('href="learning-resources.html"',
                      render_hub(stocked, api="api/events"))
        self.assertNotIn('href="learning-resources.html"',
                         render_hub(empty, api="api/events"))

    def test_the_curriculum_pill_is_unaffected(self):
        # Every course has a curriculum; only the shelf can be empty.
        self.assertIn('href="curriculum.html"',
                      render_hub(make_manifest(), api="api/events"))


class TestTheDocumentsPanel(unittest.TestCase):
    """Links that 404 on the instance rendering them are not links.

    Content is served from the curriculum doc's directory and the app refuses
    anything resolving outside it, so a document kept above that root is
    unreachable — verified 404 on a served instance for both of
    textual-flow's. A standalone render sits in the course repo, where the
    same relative paths do resolve, and keeps them.
    """

    ITEM = re.compile(r'<li><a href="([^"]+)">([^<]+)</a>')

    @classmethod
    def setUpClass(cls):
        cls.mf = make_manifest()
        cls.served = cls.ITEM.findall(render_hub(cls.mf, api="api/events"))
        cls.standalone = cls.ITEM.findall(render_hub(cls.mf))

    def test_served_drops_everything_above_the_content_root(self):
        self.assertEqual([href for href, _ in self.served],
                         ["curriculum.md", "learning-resources.md", "README.md"])

    def test_standalone_keeps_them_all(self):
        self.assertEqual([href for href, _ in self.standalone],
                         ["curriculum.md", "learning-resources.md", "README.md",
                          "../REVIEW.md", "../exploration/"])

    def test_hrefs_are_derived_from_the_manifest_not_assumed(self):
        # The old panel hard-coded five filenames, so a course keeping its
        # docs anywhere else got five links to nowhere in either mode.
        mf = make_manifest(docs=Docs(curriculum_doc="course/curriculum.md",
                                     readme="course/HOWTO.md"))
        self.assertEqual(self.ITEM.findall(render_hub(mf, api="api/events")),
                         [("curriculum.md", "curriculum.md"),
                          ("HOWTO.md", "HOWTO.md")])

    def test_link_text_is_a_name_not_a_path(self):
        # The manifest carries no titles for documents (schema.Docs is five
        # optional path strings), so the file's own name is the most human
        # thing available — but "../" is navigation, not a name.
        for href, text in self.standalone:
            with self.subTest(href=href):
                self.assertNotIn("../", text)
        self.assertIn(("../exploration/", "exploration/"), self.standalone)


class TestTheMilestoneGutter(unittest.TestCase):
    """The curriculum's number column, where a milestone has no number.

    The hub draws this row with the product's one drawn glyph; the curriculum
    printed "·", which reads as a stray period beside the label. Same row,
    same drawing.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = render_curriculum(make_manifest())
        cls.entries = [e for p in json.loads(
            re.search(r"const PHASES = (\[.*?\]);\nconst HUB_IDS",
                      cls.page, re.S).group(1)) for e in p["entries"]]

    def test_the_milestone_carries_the_flag_and_the_units_carry_numbers(self):
        ms = next(e for e in self.entries if e["id"] == "m1")
        self.assertEqual(ms["num"], theme.FLAG_SVG)
        self.assertEqual([e["num"] for e in self.entries if e["id"] != "m1"],
                         ["00", "01", "02"])

    def test_no_entry_falls_back_to_the_stray_period(self):
        self.assertNotIn("·", [e["num"] for e in self.entries])

    def test_only_the_milestone_is_marked_as_one(self):
        # The marker is what the expand control reads to know it is not
        # looking at a unit.
        self.assertEqual({e["id"] for e in self.entries if e.get("ms")}, {"m1"})

    def test_the_expand_control_does_not_call_a_milestone_a_unit(self):
        # A milestone's detail holds the note box and nothing else, so
        # "Full unit" was wrong twice over.
        self.assertIn(
            'const TOGGLE = e => e.ms ? ["Note", "Hide note"] '
            ': ["Full unit", "Hide unit"];', self.page)
        # …and the label is re-read on every open, not fixed at render time.
        self.assertIn('.textContent = TOGGLE(e)[on ? 1 : 0]',
                      js_function_body(self.page, "openEntry"))


if __name__ == "__main__":
    unittest.main()
