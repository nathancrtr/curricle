"""Integration: the two mature courses must compile clean of errors.

These tests run against the sibling repos when present and skip otherwise —
the corpus is the compiler's real test suite (platform-design.md §8).
"""

import os
import sys
import unittest

from curricle.compiler import compile_course
from curricle.sidecar import load_sidecar

try:
    from corpuspaths import HAVE_RS, HAVE_TF, RS_ROOT, TF_ROOT
except ModuleNotFoundError:  # run as tests.test_corpus, without `discover`
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from corpuspaths import HAVE_RS, HAVE_TF, RS_ROOT, TF_ROOT

# The hub's exact checkable set (index.html), which the manifest must reproduce.
TF_HUB_IDS = [
    "p0-run", "p0-read", "p0-para",
    "u1", "u2", "u3", "u4", "u5", "u6", "u7", "p2-mail",
    "u8", "u9", "u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17",
    "u18", "u19", "u20", "u21", "u22",
]
TF_GREEK_IDS = ["g-alpha", "g-nouns", "g-verbs", "g-1john", "g-app", "g-mark"]


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class TestTextualFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sidecar = load_sidecar(os.path.join(TF_ROOT, "learning", "course.yaml"))
        cls.manifest, cls.issues = compile_course(TF_ROOT, sidecar)

    def test_compiles_without_errors(self):
        self.assertIsNotNone(self.manifest, [str(i) for i in self.issues])

    def test_progress_ids_match_the_hub_exactly(self):
        # Migration safety: localStorage state keyed by these ids must map 1:1.
        self.assertEqual(list(self.manifest.progress_ids()),
                         TF_HUB_IDS + TF_GREEK_IDS)

    def test_shape(self):
        self.assertEqual(len(self.manifest.phases), 7)
        self.assertEqual(len(self.manifest.units), 23)
        self.assertEqual(len(self.manifest.materials), 18)
        self.assertEqual(len(self.manifest.resources), 43)

    def test_every_phase_after_p0_has_goal_and_units(self):
        for p in self.manifest.phases:
            self.assertTrue(p.goal, f"{p.id} missing goal")
            self.assertTrue(p.entries, f"{p.id} has no entries")

    def test_track_goals_captured(self):
        with_goals = [p.id for p in self.manifest.phases
                      if p.checkpoint and p.checkpoint.track_goals]
        self.assertEqual(with_goals, ["p1", "p2", "p3", "p4", "p5"])

    def test_conditional_unit(self):
        u17 = self.manifest.unit("u17")
        self.assertIsNotNone(u17.condition)
        self.assertEqual(u17.condition.state, "pending")


@unittest.skipUnless(HAVE_RS, "rhyme-schemer repo not present")
class TestRhymeSchemer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sidecar = load_sidecar(os.path.join(RS_ROOT, "learning", "course.yaml"))
        cls.manifest, cls.issues = compile_course(RS_ROOT, sidecar)

    def test_compiles_without_errors(self):
        self.assertIsNotNone(self.manifest, [str(i) for i in self.issues])

    def test_shape(self):
        self.assertEqual(len(self.manifest.phases), 6)
        self.assertEqual(len(self.manifest.units), 16)   # u0..u15
        self.assertEqual(len(self.manifest.materials), 32)

    def test_version_history(self):
        self.assertEqual(self.manifest.course.version.rev, "1.2")
        self.assertEqual([v.rev for v in self.manifest.course.version_history], ["1.1"])

    def test_shared_widget_attaches_twice(self):
        # The rhyme-score sandbox belongs to u7 and also appears in u9.
        mats7 = {m.id for m in self.manifest.materials_for_unit("u7")}
        mats9 = {m.id for m in self.manifest.materials_for_unit("u9")}
        self.assertIn("w-sandbox", mats7)
        self.assertIn("w-sandbox", mats9)

    def test_capstone_resolves(self):
        self.assertEqual(self.manifest.course.capstone, "u15")
        self.assertEqual(self.manifest.unit("u15").phase, "p5")

@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class TestHubParity(unittest.TestCase):
    """The generated hub must expose exactly the original hub's checkable ids."""

    def test_generated_hub_matches_original_ids(self):
        import json
        import re
        from curricle.hubrender import render_hub

        sidecar = load_sidecar(os.path.join(TF_ROOT, "learning", "course.yaml"))
        manifest, _ = compile_course(TF_ROOT, sidecar)
        gen = render_hub(manifest)

        payload = re.search(r"const PHASES = (\[.*?\]);\nconst TRACKS = (\[.*?\]);\n",
                            gen, re.S)
        phases = json.loads(payload.group(1))
        tracks = json.loads(payload.group(2))
        gen_ids = [u[0] for p in phases for u in p["units"]]
        gen_greek = [s[0] for t in tracks for s in t["stages"]]
        self.assertEqual(gen_ids, TF_HUB_IDS)
        self.assertEqual(gen_greek, TF_GREEK_IDS)
        self.assertIn('const KEY = "tf-progress"', gen)
        # The p0 milestone step carries the phase-quiz chip, as the original does.
        p0_rows = phases[0]["units"]
        self.assertEqual(p0_rows[-1], ["p0-para",
                         "Milestone paragraph: in, out, where the humans sit", ["quiz"]])


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class TestCurriculumViewParity(unittest.TestCase):
    """The generated curriculum view keeps the original's state contract."""

    @classmethod
    def setUpClass(cls):
        import json
        import re
        from curricle.currender import render_curriculum
        sidecar = load_sidecar(os.path.join(TF_ROOT, "learning", "course.yaml"))
        manifest, _ = compile_course(TF_ROOT, sidecar)
        cls.gen = render_curriculum(manifest)
        cls.payload = json.loads(
            re.search(r"const PHASES = (\[.*?\]);\nconst HUB_IDS", cls.gen, re.S).group(1))
        cls.hub_ids = json.loads(
            re.search(r"const HUB_IDS = (\[.*?\]);", cls.gen).group(1))

    def test_storage_keys_are_legacy(self):
        self.assertIn('const KEY = "tf-progress"', self.gen)
        self.assertIn('const NOTES_KEY = "tf-curriculum-notes"', self.gen)

    def test_meter_ids_are_the_program_track(self):
        self.assertEqual(self.hub_ids, TF_HUB_IDS)

    def test_stepped_unit_replaces_composite_mapping(self):
        entries = [e for p in self.payload for e in p["entries"]]
        u0 = next(e for e in entries if e["id"] == "u0")
        self.assertEqual([s[0] for s in u0["steps"]], ["p0-run", "p0-read", "p0-para"])

    def test_milestone_renders_as_entry(self):
        entries = [e for p in self.payload for e in p["entries"]]
        ms = next(e for e in entries if e["id"] == "p2-mail")
        self.assertEqual(ms["tags"], ["contact"])

    def test_key_insight_rows_carry_key_class(self):
        entries = [e for p in self.payload for e in p["entries"]]
        u1 = next(e for e in entries if e["id"] == "u1")
        row = next(r for r in u1["rows"] if r[0] == "Key insight")
        self.assertEqual(row[2], "key")
        self.assertIn("<i>sparse matrix with an opinionated schema</i>", row[1])

    def test_checkpoint_track_goals_render(self):
        p1 = self.payload[1]
        self.assertEqual(p1["checkpoint"]["goals"][0][0], "Koine Greek")


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class TestResourcesViewParity(unittest.TestCase):
    """The generated resources view keeps the original's state contract."""

    @classmethod
    def setUpClass(cls):
        import json
        import re
        from curricle.resrender import render_resources
        sidecar = load_sidecar(os.path.join(TF_ROOT, "learning", "course.yaml"))
        manifest, _ = compile_course(TF_ROOT, sidecar)
        cls.gen = render_resources(manifest)
        cls.tiers = json.loads(
            re.search(r"const TIERS = (\[.*?\]);\n\nlet state", cls.gen, re.S).group(1))

    def test_storage_key_is_legacy(self):
        self.assertIn('const KEY = "tf-resources"', self.gen)

    def test_tier1_core_path_matches_original(self):
        # The original page's TIER1_IDS, in order — the in-hand meter contract.
        t1 = [e["id"] for g in self.tiers[0]["groups"] for e in g["entries"]]
        self.assertEqual(t1, ["wg", "mink", "gurry", "carlson", "parker",
                              "handbook", "camps", "decker", "step", "metzger"])

    def test_tier_shapes(self):
        counts = [sum(len(g["entries"]) for g in t["groups"]) for t in self.tiers]
        self.assertEqual(counts, [10, 13, 16, 4])
        self.assertTrue(self.tiers[2]["compact"])       # tier 3 is the dense one

    def test_urn_url_renders_linkless(self):
        entries = [e for t in self.tiers for g in t["groups"] for e in g["entries"]]
        metzger = next(e for e in entries if e["id"] == "metzger")
        self.assertEqual(metzger["links"], [])


if __name__ == "__main__":
    unittest.main()
