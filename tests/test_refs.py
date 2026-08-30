"""The reference schemes: parsing, per-medium resolution, compile refusal.

Rule 4 of the schema spec: content links by reference (`res:` / `unit:` /
`mat:` / `repo:`), each renderer resolves for its medium, and the compiler
refuses a dangling target. These tests pin all three halves.
"""

import os
import tempfile
import textwrap
import unittest

from curricle.compiler import compile_course
from curricle.inlinemd import inline_html
from curricle.refs import RefResolver, find_refs, split_ref
from curricle.sidecar import Sidecar, SidecarCourse, SidecarMaterial, SidecarUnit
from curricle.schema import Resource

CURRICULUM = textwrap.dedent("""\
    ## Phase 1 — Work (Weeks 1–3)

    **Goal:** Do the work.

    ### Unit 1 — The unit

    - **Build:** the thing.
    - **Read:** [The Book](res:book) ch. 1; then [the primer](res:primer).
    - **Concepts:** see [Unit 2](unit:u2) and [the lesson](mat:l-u01);
      background in [the readme](repo:README.md).
    - **Milestone:** thing built.

    ### Unit 2 — More unit

    - **Build:** more thing.

    *Version 1.0 — 2026-01-01. Initial.*
    """)


def make_course_dir(curriculum: str = CURRICULUM) -> str:
    root = tempfile.mkdtemp()
    learning = os.path.join(root, "learning")
    os.makedirs(os.path.join(learning, "interactive", "lessons"))
    with open(os.path.join(learning, "curriculum.md"), "w") as f:
        f.write(curriculum)
    with open(os.path.join(learning, "interactive", "lessons", "unit-01.md"), "w") as f:
        f.write("# Lesson\n")
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write("# Readme\n")
    return root


def base_sidecar(**overrides) -> Sidecar:
    kw = dict(
        course=SidecarCourse(
            id="test", title="Test", mode="subject", hours_per_week=(1, 2),
        ),
        units=(SidecarUnit(id="u1", num=1), SidecarUnit(id="u2", num=2)),
        materials=(
            SidecarMaterial(id="l-u01", kind="lesson", title="L1",
                            path="interactive/lessons/unit-01.md", unit="u1"),
        ),
        resources=(
            Resource(key="book", title="The Book", url="https://example.org/book"),
            Resource(key="primer", title="The Primer", url="urn:isbn:978-0-00"),
        ),
    )
    kw.update(overrides)
    return Sidecar(**kw)


def compile_ok(root: str, sidecar: Sidecar):
    mf, issues = compile_course(root, sidecar)
    assert mf is not None, [str(i) for i in issues]
    return mf


class TestFindRefs(unittest.TestCase):
    def test_finds_only_linked_refs(self):
        text = ("See [W&G](res:wg) and [Unit 8](unit:u8); bare res:loose "
                "in prose is prose, and [a URL](https://x.example) is not a ref.")
        self.assertEqual(find_refs(text),
                         [("res", "wg"), ("unit", "u8")])

    def test_split_ref(self):
        self.assertEqual(split_ref("mat:t-alphabet"), ("mat", "t-alphabet"))
        self.assertIsNone(split_ref("https://x.example"))
        self.assertIsNone(split_ref("res:"))
        self.assertIsNone(split_ref("plain.md"))


class TestResolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = make_course_dir()
        cls.mf = compile_ok(cls.root, base_sidecar())

    def test_res_with_fetchable_url_is_external(self):
        r = RefResolver(self.mf)
        self.assertEqual(r.resolve("res:book"),
                         ("https://example.org/book", True))

    def test_res_with_identifier_url_lands_on_the_shelf(self):
        r = RefResolver(self.mf, to_root="../")
        self.assertEqual(r.resolve("res:primer"),
                         ("../learning-resources.html#res-primer", False))

    def test_unit_served_vs_standalone(self):
        self.assertEqual(RefResolver(self.mf).resolve("unit:u2"),
                         ("unit/u2.html", False))
        self.assertEqual(
            RefResolver(self.mf, served=False).resolve("unit:u2"),
            ("curriculum.html#u-u2", False))

    def test_mat_markdown_reads_in_the_reader_when_served(self):
        self.assertEqual(
            RefResolver(self.mf, to_root="../").resolve("mat:l-u01"),
            ("../read/interactive/lessons/unit-01.md", False))
        self.assertEqual(
            RefResolver(self.mf, served=False).resolve("mat:l-u01"),
            ("interactive/lessons/unit-01.md", False))

    def test_repo_served_vs_standalone(self):
        self.assertEqual(RefResolver(self.mf).resolve("repo:README.md"),
                         ("repo/README.md", False))
        # Standalone pages sit in the content root (learning/), so the
        # honest relative path climbs out of it.
        self.assertEqual(
            RefResolver(self.mf, served=False).resolve("repo:README.md"),
            ("../README.md", False))

    def test_non_ref_and_dangling_return_none(self):
        r = RefResolver(self.mf)
        self.assertIsNone(r.resolve("https://x.example"))
        self.assertIsNone(r.resolve("res:nope"))


class TestInlineWithRefs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mf = compile_ok(make_course_dir(), base_sidecar())

    def test_ref_link_resolves(self):
        out = inline_html("Read [The Book](res:book) ch. 1.",
                          resolver=RefResolver(self.mf))
        self.assertIn('<a href="https://example.org/book" target="_blank" '
                      'rel="noopener">The Book</a>', out)

    def test_without_resolver_a_ref_degrades_to_its_label(self):
        out = inline_html("Read [The Book](res:book) ch. 1.")
        self.assertNotIn("<a", out)
        self.assertIn("Read The Book ch. 1.", out)

    def test_plain_urls_unaffected(self):
        out = inline_html("[x](https://x.example)", resolver=None)
        self.assertIn('href="https://x.example"', out)


class TestCompileRefs(unittest.TestCase):
    def test_valid_refs_compile_clean_of_errors(self):
        mf, issues = compile_course(make_course_dir(), base_sidecar())
        self.assertIsNotNone(mf, [str(i) for i in issues])

    def test_dangling_res_is_error(self):
        bad = CURRICULUM.replace("res:book", "res:ghost")
        mf, issues = compile_course(make_course_dir(bad), base_sidecar())
        self.assertIsNone(mf)
        self.assertTrue(any("res:ghost names no resource" in i.message
                            for i in issues))

    def test_dangling_mat_and_unit_are_errors(self):
        bad = (CURRICULUM.replace("mat:l-u01", "mat:ghost")
                         .replace("unit:u2", "unit:u99"))
        mf, issues = compile_course(make_course_dir(bad), base_sidecar())
        self.assertIsNone(mf)
        messages = [i.message for i in issues]
        self.assertTrue(any("mat:ghost names no material" in m for m in messages))
        self.assertTrue(any("unit:u99 names no unit" in m for m in messages))

    def test_missing_repo_file_is_error(self):
        bad = CURRICULUM.replace("repo:README.md", "repo:GHOST.md")
        mf, issues = compile_course(make_course_dir(bad), base_sidecar())
        self.assertIsNone(mf)
        self.assertTrue(any("repo:GHOST.md does not exist" in i.message
                            for i in issues))

    def test_repo_escape_is_error(self):
        bad = CURRICULUM.replace("repo:README.md", "repo:../secrets")
        mf, issues = compile_course(make_course_dir(bad), base_sidecar())
        self.assertIsNone(mf)
        self.assertTrue(any("escapes the repo" in i.message for i in issues))

    def test_authored_interactive_row_warns(self):
        cur = CURRICULUM.replace(
            "- **Milestone:** thing built.",
            "- **Interactive:** lesson `interactive/lessons/unit-01.md`.\n"
            "- **Milestone:** thing built.")
        mf, issues = compile_course(make_course_dir(cur), base_sidecar())
        self.assertIsNotNone(mf, [str(i) for i in issues])
        self.assertTrue(any("authored Interactive row" in i.message
                            for i in issues))


if __name__ == "__main__":
    unittest.main()
