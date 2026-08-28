import unittest

from curricle.mdparse import parse_curriculum

FIXTURE = """\
# Test course — curriculum

Preamble prose that the parser must preserve but not interpret.

## Phase 0 — Orientation (Week 0)

**Goal:** Get running.

- **Build:** Nothing yet. Run the tests.
- **Read:** the repo `README.md`.

> **Check yourself:** Why vowels?
>
> <details><summary>Answer</summary>
>
> Because spelling lies.
> </details>

---

## Phase 1 — Foundations (Weeks 1–5)

**Goal:** Build the base.

### Unit 1 — First things

- **Build:** A parser for the thing,
  continued on a second line.
- **Read:** Book ch. 1.
- **Key insight:** The thing is a *matrix*.
- **Greek track:** alphabet drills.

### Unit 2 — Second things

- **Build:** More.

### — Phase 1 Checkpoint —
You can do the base. **Greek by now:** the alphabet is boring.

---

## Phase 2 — Frontiers (Weeks 6+)

**Goal:** Onward.

### Unit 3 — Last things

- **Build:** Everything else.

*Version 1.0 — 2026-01-01. Initial.*

*Version 1.1 — 2026-02-02: revised against review.*
"""


class TestParseCurriculum(unittest.TestCase):
    def setUp(self):
        self.doc = parse_curriculum(FIXTURE)

    def test_phase_structure(self):
        nums = [p.num for p in self.doc.phases]
        self.assertEqual(nums, [0, 1, 2])
        self.assertEqual(self.doc.phases[0].weeks, (0, 0))     # "(Week 0)"
        self.assertEqual(self.doc.phases[1].weeks, (1, 5))     # range
        self.assertEqual(self.doc.phases[2].weeks, (6, None))  # "(Weeks 6+)"
        self.assertEqual(self.doc.phases[1].goal, "Build the base.")

    def test_phase_body_unit(self):
        p0 = self.doc.phases[0]
        self.assertEqual([r.label for r in p0.body_rows], ["Build", "Read"])
        self.assertIsNotNone(p0.body_check)
        self.assertEqual(p0.body_check.q, "Why vowels?")
        self.assertEqual(p0.body_check.ans, "Because spelling lies.")

    def test_unit_rows_with_continuation(self):
        u1 = self.doc.phases[1].units[0]
        self.assertEqual(u1.title, "First things")
        build = u1.rows[0]
        self.assertEqual(build.content,
                         "A parser for the thing, continued on a second line.")
        self.assertEqual([r.label for r in u1.rows],
                         ["Build", "Read", "Key insight", "Greek track"])

    def test_checkpoint_inline_labels(self):
        cp = self.doc.phases[1].checkpoint
        self.assertEqual(cp.prose, "You can do the base.")
        self.assertEqual(cp.labeled_lines,
                         [("Greek by now", "the alphabet is boring.")])

    def test_version_history(self):
        self.assertEqual([v[0] for v in self.doc.versions], ["1.0", "1.1"])
        self.assertEqual(self.doc.versions[1][1], "2026-02-02")

    def test_preamble_preserved_not_parsed(self):
        self.assertTrue(any("Preamble prose" in line for line in self.doc.preamble))


if __name__ == "__main__":
    unittest.main()
