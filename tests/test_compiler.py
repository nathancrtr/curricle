import contextlib
import io
import os
import tempfile
import textwrap
import unittest

from curricle import theme
from curricle.__main__ import main
from curricle.compiler import compile_course
from curricle.sidecar import (
    Sidecar, SidecarCourse, SidecarMaterial, SidecarMilestone, SidecarUnit,
)
from curricle.schema import Grader, Resource, Step, Track, Stage

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

    def test_a_figures_directory_is_a_chapters_assets_not_a_material(self):
        figs = os.path.join(self.root, "learning", "interactive", "chapters", "figures")
        os.makedirs(figs)
        with open(os.path.join(figs, "graph.svg"), "w") as f:
            f.write("<svg/>\n")
        mf, issues = compile_course(self.root, base_sidecar())
        self.assertIsNotNone(mf)
        self.assertFalse(any("figures" in i.message for i in issues), [str(i) for i in issues])

    def test_read_row_linking_the_units_chapter_warns(self):
        # The unit page leads with the chapter; a Read row that also points
        # at it says the same thing twice (docs/chapter-pattern.md).
        ch = os.path.join(self.root, "learning", "interactive", "chapters")
        os.makedirs(ch)
        with open(os.path.join(ch, "u1.md"), "w") as f:
            f.write("# Chapter\n")
        cur = os.path.join(self.root, "learning", "curriculum.md")
        with open(cur) as f:
            text = f.read()
        text = text.replace("- **Build:** the thing.",
                            "- **Build:** the thing.\n"
                            "- **Read:** [this unit's chapter](mat:c-u1) first, then the readme.", 1)
        with open(cur, "w") as f:
            f.write(text)
        mats = base_sidecar().materials + (
            SidecarMaterial(id="c-u1", kind="chapter", title="C1",
                            path="interactive/chapters/u1.md", unit="u1"),)
        mf, issues = compile_course(self.root, base_sidecar(materials=mats))
        self.assertIsNotNone(mf, [str(i) for i in issues])
        hits = [i for i in issues if "own chapter" in i.message]
        self.assertEqual(len(hits), 1, [str(i) for i in issues])
        self.assertEqual(hits[0].where, "unit u1 [Read]")

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


class TestResourceUrlSchemes(unittest.TestCase):
    """The chokepoint that keeps a model-written `href` from being a script.

    A resource URL is prose a model wrote from a learner's scope, and it is
    rendered as an anchor on the outline gate — the trust screen, on the
    origin that after promotion also carries the tenant's event APIs. The
    rule lives here rather than in the three renderers because a compile is
    what every one of those surfaces is downstream of: the gate compiles the
    draft fresh, the worker refuses before `outline_ready`, and `factory
    promote` aborts on a dirty compile.
    """

    def setUp(self):
        self.root = make_course_dir()

    def compile_with(self, url=None, links=()):
        res = Resource(key="r1", title="R", url=url or (links[0][1] if links else ""),
                       links=tuple(links))
        return compile_course(self.root, base_sidecar(resources=(res,)))

    def errors(self, issues):
        return [i.message for i in issues if i.level == "error"]

    def test_http_https_and_urn_are_the_shelf_vocabulary(self):
        for url in ("https://example.org/book", "http://example.org/book",
                    "urn:isbn:9783438060105"):
            with self.subTest(url=url):
                mf, issues = self.compile_with(url)
                self.assertIsNotNone(mf, self.errors(issues))

    def test_a_dangerous_scheme_is_refused(self):
        for url in ("javascript:alert(1)", "data:text/html,<script>x</script>",
                    "vbscript:msgbox", "JavaScript:alert(1)"):
            with self.subTest(url=url):
                mf, issues = self.compile_with(url)
                self.assertIsNone(mf)
                self.assertTrue(any("scheme" in m for m in self.errors(issues)),
                                self.errors(issues))

    def test_a_scheme_a_browser_would_reassemble_is_refused(self):
        r"""Browsers strip whitespace and control characters before parsing.

        `java\nscript:` is `javascript:` by the time it is clicked, so it has
        to be `javascript:` by the time it is checked — a rule matching the
        raw text would wave this through as a relative path.
        """
        for url in ("java\nscript:alert(1)", "java\tscript:alert(1)",
                    "  javascript:alert(1)", "java\rscript:alert(1)"):
            with self.subTest(url=repr(url)):
                mf, issues = self.compile_with(url)
                self.assertIsNone(mf, "a browser would run this")

    def test_a_relative_path_stays_legal(self):
        """textual-flow shelves this repo's own `../exploration/`.

        It is not a scheme problem: a relative path resolves against whoever
        is serving the page — a dead link at worst, never a script — and the
        corpus has a real one, so refusing it would be refusing a course
        that has always compiled.
        """
        mf, issues = self.compile_with(links=[["exploration/", "../exploration/"]])
        self.assertIsNotNone(mf, self.errors(issues))

    def test_a_protocol_relative_url_is_refused(self):
        """The one schemeless shape that is still a destination."""
        mf, issues = self.compile_with("//evil.example/x")
        self.assertIsNone(mf)
        self.assertTrue(any("protocol-relative" in m for m in self.errors(issues)))

    def test_every_link_is_checked_not_only_the_primary(self):
        """`links` is what the shelf renders; checking `url` alone would
        leave every row after the first clickable."""
        mf, issues = self.compile_with(links=[
            ["Publisher", "https://example.org/book"],
            ["Mirror", "javascript:alert(1)"],
        ])
        self.assertIsNone(mf)
        self.assertEqual(len(self.errors(issues)), 1, self.errors(issues))
        self.assertIn("'Mirror'", self.errors(issues)[0])

    def test_one_bad_url_reported_once_not_once_per_alias(self):
        """`url` defaults to `links[0]`, so a naive walk names it twice."""
        mf, issues = self.compile_with("javascript:alert(1)")
        self.assertEqual(len(self.errors(issues)), 1, self.errors(issues))


# The same course as `base_sidecar()`, on disk: the CLI loads its sidecar from
# a file, so the in-memory constructors can't stand in for it.
SIDECAR_YAML = textwrap.dedent("""\
    sidecar_version: 1
    course:
      id: test
      title: Test
      mode: subject
      hours_per_week: [1, 2]
    tracks:
    - id: side
      name: Side
      stages:
      - {id: s1, label: one}
      checkpoint_labels: ["Side by now"]
    units:
    - id: u0
      num: 0
      phase_body: true
      steps:
      - {id: u0-a, label: a}
      - {id: u0-b, label: b}
    - {id: u1, num: 1, gloss: The first.}
    - {id: u2, num: 2, gloss: The second.}
    milestones:
    - {id: m1, phase_num: 1, kind: contact, label: Say hi, after_unit: u1}
    materials:
    - {id: l-u01, kind: lesson, title: L1,
       path: interactive/lessons/unit-01.md, unit: u1}
    """)


class TestCliWriters(unittest.TestCase):
    """`--out` paths whose directory does not exist yet.

    The README's quickstart renders the pages beside the course, and someone
    following it points `--out` at `build/` in a fresh clone. Opening the path
    without making its parent turned both into a FileNotFoundError from inside
    the CLI, which is the CLI's job to prevent, not the reader's.
    """

    def setUp(self):
        self.root = make_course_dir()
        with open(os.path.join(self.root, "learning", "course.yaml"), "w") as f:
            f.write(SIDECAR_YAML)
        self.out_root = tempfile.mkdtemp()

    def run_cli(self, argv):
        # "wrote …" on stdout, issues on stderr: neither belongs in a run.
        noise = io.StringIO()
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            return main(argv), noise.getvalue()

    def test_compile_makes_the_parent_directory_of_out(self):
        out = os.path.join(self.out_root, "nested", "deeper", "manifest.yaml")
        code, log = self.run_cli(["compile", self.root, "--out", out])
        self.assertEqual(code, 0, log)
        self.assertTrue(os.path.exists(out), log)

    def test_the_renderers_make_the_parent_directory_of_out(self):
        for command, name in (("hub", "index.html"),
                              ("curriculum", "curriculum.html"),
                              ("resources", "learning-resources.html")):
            with self.subTest(command=command):
                out = os.path.join(self.out_root, command, "pages", name)
                code, log = self.run_cli([command, self.root, "--out", out])
                self.assertEqual(code, 0, log)
                self.assertTrue(os.path.exists(out), log)

    def test_theme_writes_what_the_served_route_serves(self):
        # The materials link `../../theme.css`; the app serves theme.style("")
        # there, and a static render has to be able to put the same bytes on
        # disk or a widget opened from a rendered hub comes up unstyled.
        out = os.path.join(self.out_root, "nested", "theme.css")
        code, log = self.run_cli(["theme", "--out", out])
        self.assertEqual(code, 0, log)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), theme.style(""))


if __name__ == "__main__":
    unittest.main()
