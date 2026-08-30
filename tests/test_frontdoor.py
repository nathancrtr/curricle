"""The front door: the page a prospective learner meets before anything else.

Two things are worth testing here and they are not the styling. First, the
card's arithmetic: the done-count, the total and the next-up label are
derived at render time, and the walk they are derived from has to be the
*same* walk the hub makes, or the front door quietly disagrees with the page
it links to. `webapp._program_ids` is pinned to `progress.summarize` id for
id below — not "same length", not "same count", the same ids in the same
order — because that is the drift that would surface as a number nobody can
explain.

Second, the waypath's "you are here" ring. It is drawn twice in this
codebase: server-side here as static HTML (the index carries no JavaScript at
all), and client-side by `theme.WAYPATH_JS` on every other surface. Two
implementations of one rule is a standing invitation to disagree, so the
Python side is exercised against a real course at zero progress, mid course
and complete, and the JS statement it mirrors is pinned beside it.
"""

import os
import re
import unittest

from curricle import db, progress, theme, webapp

from corpuspaths import HAVE_RS, HAVE_TF, RS_ROOT, TF_ROOT
from pg import test_engine
# The synthetic course with the shapes that catch people out — a stepped
# unit, a true milestone and a secondary track in one manifest. Building a
# second one here would be a second fixture to keep honest.
from test_hubrender import make_manifest

STONE = re.compile(r'<span class="wp-stone([^"]*)"></span>')
WAYPATH = re.compile(r'<div class="waypath"[^>]*>(.*?)</div>', re.S)


def stones(page: str) -> list[list[str]]:
    """The stone classes of every waypath on the page, path by path."""
    return [[" ".join(cls.split()) for cls in STONE.findall(path)]
            for path in WAYPATH.findall(page)]


def client(engine, roots: list[str], slug: str):
    """A test client for an app serving `roots` to a fresh tenant."""
    from fastapi.testclient import TestClient

    with engine.begin() as conn:
        db.create_tenant(conn, slug)
    return TestClient(webapp.create_app(roots, tenant_slug=slug,
                                        database_url=str(engine.url)))


class ProgramWalkTest(unittest.TestCase):
    """The front door's walk is `progress.summarize`'s walk, id for id."""

    def assert_walks_agree(self, manifest):
        ids = webapp._program_ids(manifest)
        state = progress.ProgressState()
        self.assertEqual(progress.summarize(manifest, state)["program_total"],
                         len(ids))
        # Marking the ids off in order, summarize must name each one in turn
        # as what comes next. Nothing weaker pins the *order*: two walks that
        # visit the same ids in different orders agree on every count and
        # still put the ring on the wrong stone.
        for i, pid in enumerate(ids):
            summary = progress.summarize(manifest, state)
            self.assertEqual(summary["next_up"], pid,
                             f"summarize's next_up at position {i} is "
                             f"{summary['next_up']!r}, the front door's is "
                             f"{pid!r} — the two walks have diverged")
            self.assertEqual(summary["program_done"], i)
            state.done[pid] = True
        done = progress.summarize(manifest, state)
        self.assertIsNone(done["next_up"])
        self.assertEqual(done["program_done"], len(ids))

    def test_agrees_on_the_synthetic_course(self):
        self.assert_walks_agree(make_manifest())

    @unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
    def test_agrees_on_textual_flow(self):
        self.assert_walks_agree(webapp.load_course(TF_ROOT).manifest)

    @unittest.skipUnless(HAVE_RS, "rhyme-schemer repo not present")
    def test_agrees_on_rhyme_schemer(self):
        self.assert_walks_agree(webapp.load_course(RS_ROOT).manifest)

    def test_the_secondary_tracks_are_the_only_thing_left_out(self):
        # The program track is the whole course minus the side tracks: the
        # front door counts what the hub's spine counts, and a track stepper
        # is not a step on the path.
        manifest = make_manifest()
        stage_ids = {s.id for t in manifest.tracks for s in t.stages}
        self.assertTrue(stage_ids)
        ids = webapp._program_ids(manifest)
        self.assertEqual(set(manifest.progress_ids()) - set(ids), stage_ids)

    def assert_every_id_is_named(self, manifest):
        # A card that cannot label its next-up id says nothing where the
        # whole point of the line is to say what comes next — and, worse,
        # falls through to the copy that claims the course is finished.
        labels = webapp._entry_labels(manifest)
        for pid in webapp._program_ids(manifest):
            self.assertTrue(labels.get(pid), f"no label for {pid!r}")

    @unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
    def test_every_program_id_in_textual_flow_can_be_named(self):
        self.assert_every_id_is_named(webapp.load_course(TF_ROOT).manifest)

    @unittest.skipUnless(HAVE_RS, "rhyme-schemer repo not present")
    def test_every_program_id_in_rhyme_schemer_can_be_named(self):
        self.assert_every_id_is_named(webapp.load_course(RS_ROOT).manifest)

    def test_every_program_id_can_be_named(self):
        manifest = make_manifest()
        self.assert_every_id_is_named(manifest)
        labels = webapp._entry_labels(manifest)
        self.assertEqual(labels["u0-a"], "first step")
        self.assertEqual(labels["m1"], "Contact milestone: say hi")
        self.assertTrue(labels["u1"].startswith("Unit 1 · "))


@unittest.skipUnless(HAVE_TF and HAVE_RS, "corpus repos not present")
class FrontDoorShapeTest(unittest.TestCase):
    """The page renders in all three shapes it can be asked for."""

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()

    def test_no_courses_configured(self):
        page = client(self.engine, [], "frontdoor-none").get("/")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("No courses are configured yet", page.text)
        # No course, no promise about picking anything up.
        self.assertNotIn("Pick up where you left off.", page.text)
        self.assertEqual(stones(page.text), [])

    def test_one_course_takes_the_singular_lede(self):
        page = client(self.engine, [TF_ROOT], "frontdoor-one").get("/")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Your course is ready when you are.", page.text)
        self.assertIn('href="/c/textual-flow/"', page.text)
        self.assertEqual(len(stones(page.text)), 1)

    def test_two_courses_take_the_plural_lede(self):
        page = client(self.engine, [TF_ROOT, RS_ROOT],
                      "frontdoor-two").get("/")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Pick up where you left off.", page.text)
        self.assertIn('href="/c/textual-flow/"', page.text)
        self.assertIn('href="/c/rhyme-schemer/"', page.text)
        self.assertEqual(len(stones(page.text)), 2)

    def test_the_page_carries_the_design_system_and_no_script(self):
        page = client(self.engine, [TF_ROOT], "frontdoor-shell").get("/")
        self.assertIn(theme.TOKENS_CSS, page.text)          # both palettes
        self.assertIn('class="wordmark"', page.text)
        self.assertIn('href="/profile"', page.text)
        self.assertIn(theme.greeting(0).split()[0], page.text)   # "Good …"
        # The index is server-rendered through and through; the ring below is
        # static HTML precisely so this stays true.
        self.assertNotIn("<script", page.text)


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class WaypathAgreementTest(unittest.TestCase):
    """The static stones say what `theme.WAYPATH_JS` would say."""

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        cls.manifest = webapp.load_course(TF_ROOT).manifest
        cls.ids = webapp._program_ids(cls.manifest)
        cls.client = client(cls.engine, [TF_ROOT], "frontdoor-waypath")
        with cls.engine.begin() as conn:
            cls.tenant = db.tenant_id_for(conn, "frontdoor-waypath")
        cls.scope = db.for_tenant(cls.tenant)

    def mark(self, ids):
        with self.engine.begin() as conn:
            for pid in ids:
                progress.append_event(conn, self.scope, self.manifest,
                                      "mark", pid, {"done": True})

    def assert_path(self, expected_done: int):
        """One stone per program id, lit through `expected_done`, ring next."""
        path, = stones(self.client.get("/").text)
        self.assertEqual(len(path), len(self.ids))
        self.assertEqual([i for i, cls in enumerate(path) if "lit" in cls],
                         list(range(expected_done)))
        here = [i for i, cls in enumerate(path) if "here" in cls]
        if expected_done == len(self.ids):
            # Complete: `waypath()` is passed no nextId, so no stone rings.
            self.assertEqual(here, [])
        else:
            self.assertEqual(here, [expected_done],
                             "the ring belongs to the first undone stone, "
                             "and to nothing else")
            self.assertNotIn("lit", path[expected_done])
        return path

    def test_ring_tracks_the_first_undone_stone_from_zero_to_complete(self):
        # Zero progress: the whole path is laid, ahead of you, with the ring
        # on the first stone. This is the state the direction cares most about.
        page = self.client.get("/").text
        self.assertIn("steps</b>, ready when you are", page)
        self.assertIn("Begin →", page)
        self.assert_path(0)

        # Mid course: the ring walks with you, and the copy counts honestly.
        self.mark(self.ids[:3])
        page = self.client.get("/").text
        self.assertIn(f"<b>3 of {len(self.ids)}</b> done · next up:", page)
        self.assertIn("Continue →", page)
        self.assert_path(3)

        self.mark(self.ids[3:9])
        self.assert_path(9)

        # Complete: no ring anywhere, and the copy stops asking for anything.
        self.mark(self.ids[9:])
        page = self.client.get("/").text
        self.assertIn(f"<b>Complete.</b> All {len(self.ids)} steps walked.",
                      page)
        self.assertIn("Revisit →", page)
        self.assert_path(len(self.ids))

    def test_the_js_rule_the_static_stones_mirror(self):
        # If the client-side rule moves, this fails next to the tests that
        # claim the two agree — which is the only warning the static copy
        # will ever get, since no test can run both.
        rule = next(line for line in theme.WAYPATH_JS.splitlines()
                    if "s.className" in line)
        self.assertIn('"wp-stone"', rule)
        self.assertIn('" lit"', rule)
        self.assertIn('" here"', rule)
        self.assertIn("id === nextId", rule)


def _rects(svg: str) -> list[dict[str, str]]:
    """Every <rect> in an SVG, as attribute dicts, in document order."""
    return [dict(re.findall(r'([a-z-]+)="([^"]*)"', attrs))
            for attrs in re.findall(r"<rect ([^>]*?)/>", svg)]


class WordmarkTest(unittest.TestCase):
    """The mark is the waypath in miniature — so it is checked against it.

    Not against a transcription of it: every number below is read out of
    `theme.BASE_CSS`, because the failure this closes is the mark being left
    behind when the path moves. It happened once — the lit stone kept
    `--accent` through the contrast fix that lit every other waypath with
    `--accent-strong` (#16) — and it is invisible from the wordmark's own
    line, which spells a token that still exists and still looks coral.
    """

    def setUp(self):
        self.lit, self.ring, self.unlit = _rects(webapp.WORDMARK)
        self.stone = dict(re.findall(
            r"([a-z-]+):([^;]+);",
            re.search(r"\.wp-stone \{([^}]*)\}", theme.BASE_CSS).group(1)))

    def test_the_lit_stone_takes_the_token_the_path_lights_with(self):
        lit_rule = re.search(r"\.wp-stone\.lit \{([^}]*)\}", theme.BASE_CSS).group(1)
        token = re.search(r"var\((--[a-z-]+)\)", lit_rule).group(1)
        self.assertEqual(self.lit["fill"], f"var({token})")
        self.assertEqual(self.unlit["fill"], self.stone["background"].strip())

    def test_the_stones_are_the_path_s_lozenge_scaled(self):
        # The chosen stone is a 2:1 lozenge with fully rounded ends. Circles
        # were the rejected fork; a mark drawn in the rejected shape is a
        # different drawing from the path it claims to miniaturize.
        ratio = float(self.stone["width"].removesuffix("px")) / float(
            self.stone["height"].removesuffix("px"))
        for name, stone in (("lit", self.lit), ("unlit", self.unlit)):
            with self.subTest(stone=name):
                w, h = float(stone["width"]), float(stone["height"])
                self.assertEqual(w / h, ratio)
                self.assertEqual(float(stone["rx"]) * 2, h)

    def test_the_ring_is_a_hollow_lit_stone(self):
        # `.wp-stone.here` is an inset ring in the lit color: same footprint
        # as a stone, drawn hollow. The SVG says it with a centered stroke,
        # so the rect is inset by half the stroke on every side.
        stroke = float(self.ring["stroke-width"])
        self.assertEqual(self.ring["fill"], "none")
        self.assertEqual(self.ring["stroke"], self.lit["fill"])
        self.assertEqual(float(self.ring["width"]) + stroke, float(self.lit["width"]))
        self.assertEqual(float(self.ring["height"]) + stroke, float(self.lit["height"]))

    def test_the_mark_fits_its_viewbox(self):
        w, h = re.search(r'viewBox="0 0 (\d+) (\d+)"', webapp.WORDMARK).groups()
        right = float(self.unlit["x"]) + float(self.unlit["width"])
        self.assertEqual(right, float(w))
        self.assertEqual(float(self.lit["height"]), float(h))


# Every module on a request path. L1 is a property of the serving process
# rather than of one file, so this list grows by one line each time `serve`
# gains a module — the wizard joins it here.
GUARDED_MODULES = ("webapp.py",)


class InvariantL1Test(unittest.TestCase):
    def test_the_request_path_cannot_reach_the_model(self):
        # L1: no LLM on a request path, ever. The front door made this module
        # bigger; it did not make it a caller. `factory` is guarded beside
        # `llm` because the generation stages reach the model through it, and
        # both of them now belong to the worker process instead.
        pkg = os.path.dirname(webapp.__file__)
        for name in GUARDED_MODULES:
            with open(os.path.join(pkg, name), encoding="utf-8") as f:
                source = f.read()
            for forbidden in ("llm", "factory"):
                with self.subTest(module=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
