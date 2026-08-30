"""The course factory: validators, metering, budgets, the build — no network.

The fake transport returns canned artifacts; the smoke tests (an exercise's
tests must fail against its stub, a widget must be offline) run for real.
"""

import json
import os
import re
import tempfile
import textwrap
import unittest
from decimal import Decimal

import sqlalchemy as sa

from curricle import db, factory, llm, profile
from curricle.llm import (
    BudgetExceeded, FactoryConfigMissing, Runner, load_models_config, load_role,
)

from corpuspaths import HAVE_ML, ML_ROOT
from pg import test_engine


GOOD_QUIZ = json.dumps([
    {"q": f"Question {i}?", "options": [
        {"text": "right", "correct": True, "why": "because"},
        {"text": "wrong a", "correct": False, "why": "misconception a"},
        {"text": "wrong b", "correct": False, "why": "misconception b"},
        {"text": "wrong c", "correct": False, "why": "misconception c"},
    ]} for i in range(10)
])

GOOD_EXERCISE = json.dumps({
    "slug": "unit-03-bpe",
    "task_md": "# BPE\nBuild it.",
    "stub_name": "bpe.py",
    "stub": textwrap.dedent('''\
        def merge(tokens, pair):
            """Merge every adjacent occurrence of pair."""
            raise NotImplementedError
        '''),
    "test_name": "test_bpe.py",
    "test": textwrap.dedent('''\
        import unittest
        from bpe import merge

        class TestMerge(unittest.TestCase):
            def test_merges_adjacent_pair(self):
                # classic trap: overlapping pairs merge left-to-right
                self.assertEqual(merge(["a", "b", "b"], ("a", "b")), ["ab", "b"])

        if __name__ == "__main__":
            unittest.main()
        '''),
})


# The outline fixtures: a two-unit course small enough to read and real
# enough to compile, standing in for what curriculum-designer emits.
GOOD_CURRICULUM = """\
# Tiny Demo: Curriculum

A two-unit course, for one learner, at four hours a week.

## Phase 1 — Foundations (Weeks 1–2)

<!-- resource keys: primer -->

**Goal:** Read a manifest and say what it claims.

### Unit 1 — What a manifest is
- **Build:** Write a three-line sidecar by hand and compile it.
- **Read:** [The Manifest Primer](res:primer), the opening chapter.

### Unit 2 — What the compiler refuses
- **Build:** Break the sidecar on purpose and read the finding it raises.
- **Concepts:** refusal over guessing; why every finding names a place.

### — Phase 1 Checkpoint —
You can write a sidecar that compiles and explain one thing it refuses.

---

*Curriculum v1.0 — 2026-08-30: initial version.*
"""

GOOD_SIDECAR = """\
sidecar_version: 1

course:
  id: tiny-demo
  title: Tiny demo
  mode: subject
  hours_per_week: [4, 4]
  docs:
    curriculum_doc: learning/curriculum.md
    resources_doc: learning/learning-resources.md
  capstone: u2
  description: A two-unit course about manifests.

resource_tiers:
- num: 1
  name: Core path
  role: Worked through in curriculum order.

resources:
- key: primer
  tier: 1
  title: The Manifest Primer
  cite: "A. Author · 2026"
  formats: [TEXT]
  cost: free
  free: true
  links:
  - ["Read online", "https://example.invalid/primer"]
  why_this_one: The one text that argues for refusal rather than asserting it.

units:
- id: u1
  num: 1
  gloss: A manifest is a claim about a course, checkable by a compiler.
- id: u2
  num: 2
  gloss: The compiler refuses rather than guesses.
  depends_on: [u1]
"""

# Same sidecar, plus a unit no curriculum header claims: a compile error with
# a `where` the designer can act on, and nothing the curator did wrong.
BROKEN_SIDECAR = GOOD_SIDECAR + """\
- id: u9
  num: 9
  gloss: A unit that exists only in the sidecar.
"""

# `hours_per_week` as a scalar: the loader subscripts it and raises TypeError
# rather than returning a where-bearing Issue. A finding, not a traceback.
CRASHING_SIDECAR = GOOD_SIDECAR.replace("hours_per_week: [4, 4]",
                                        "hours_per_week: 4")

GOOD_SHELF = """\
# Tiny Demo: Learning resources

**Tier 1** is the core path, worked through in curriculum order.

---

## Tier 1 — Core path

### The Manifest Primer
*A. Author · 2026 · free*
→ <https://example.invalid/primer>

The one text that argues for refusal rather than asserting it, which is the
argument this whole course rests on.

---

*Resources v1.0 — 2026-08-30.*
"""

# A shelf that disagrees with the sidecar in both directions at once.
WRONG_SHELF = GOOD_SHELF.replace(
    "### The Manifest Primer\n*A. Author · 2026 · free*\n"
    "→ <https://example.invalid/primer>",
    "### Some Other Book\n*B. Author · 2026 · free*\n"
    "→ <https://example.invalid/other>")


def designer_json(curriculum=GOOD_CURRICULUM, sidecar=GOOD_SIDECAR):
    return json.dumps({"curriculum_md": curriculum, "course_yaml": sidecar})


SCOPE = {"subject": "Course manifests", "title": "Tiny demo",
         "mode": "subject", "hours_per_week": 4, "cadence": "weekday evenings",
         "done_looks_like": "I can write a sidecar that compiles.",
         "out_of_scope": ["writing a compiler of my own"],
         "prior_exposure": "I have read one manifest."}


class ValidatorTest(unittest.TestCase):
    def test_quiz_rules(self):
        self.assertEqual(len(factory.validate_quiz(GOOD_QUIZ)), 10)
        bad = json.loads(GOOD_QUIZ)
        bad[3]["options"][1]["correct"] = True     # two correct answers
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_quiz(json.dumps(bad))
        bad = json.loads(GOOD_QUIZ)
        bad[0]["options"][2]["why"] = ""           # a throwaway distractor
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_quiz(json.dumps(bad))

    def test_quiz_strips_code_fence(self):
        fenced = "```json\n" + GOOD_QUIZ + "\n```"
        self.assertEqual(len(factory.validate_quiz(fenced)), 10)

    def test_widget_offline_rule(self):
        ok = "<!DOCTYPE html><html><body><script>let x=1;</script></body></html>"
        self.assertTrue(factory.validate_widget(ok))
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_widget(ok.replace(
                "<script>", '<script src="https://cdn.example.com/x.js"></script><script>'))
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_widget("<div>not a document</div>")

    def test_exercise_smoke_runs_tests_against_stub(self):
        with tempfile.TemporaryDirectory() as d:
            data = factory.validate_exercise(GOOD_EXERCISE, workdir=d)
            self.assertEqual(data["slug"], "unit-03-bpe")
        # Tests that pass against the stub test nothing — refused.
        passing = json.loads(GOOD_EXERCISE)
        passing["test"] = passing["test"].replace(
            'self.assertEqual(merge(["a", "b", "b"], ("a", "b")), ["ab", "b"])',
            "self.assertTrue(True)")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(factory.ValidationFailed):
                factory.validate_exercise(json.dumps(passing), workdir=d)

    def test_lesson_and_bank(self):
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_lesson("# Short\nno pauses here" + "x" * 3000)
        good = "# Lesson\n" + "context " * 400 + "\n> PAUSE.\nmore"
        self.assertIn("PAUSE", factory.validate_lesson(good))
        bank = ("## Module 3 — Tokenization\n\n**3.1 (R)** What is BPE?\n"
                "**Answer:** Byte-pair encoding.\n**Note:** Merges by frequency.")
        self.assertTrue(factory.validate_bank(bank))
        with self.assertRaises(factory.ValidationFailed):
            factory.validate_bank("just prose")

    def test_quiz_shell_rendering(self):
        shell = ("<title>Phase 1 Checkpoint</title>\n<script>\n"
                 "const QUIZ_DATA = [\n  {q: 'old'}\n];\n</script>")
        out = factory.render_quiz_html(shell, json.loads(GOOD_QUIZ), 2, 1)
        self.assertIn("Phase 2 Checkpoint", out)
        self.assertIn("Question 0?", out)
        self.assertNotIn("'old'", out)


# Where each house exemplar came from, relative to tinylang's `interactive/`.
# Whole copies, so the parity test asserts equality; the bank section is a
# slice of its source and the quiz shell a dialect rename of its own.
HOUSE_SOURCES = {
    "lesson.md": "lessons/unit-01-lexer.md",
    "widget.html": "widgets/token-stream.html",
    "exercise/task.md": "exercises/unit-02-starter/task.md",
    "exercise/pratt.py": "exercises/unit-02-starter/pratt.py",
    "exercise/test_pratt.py": "exercises/unit-02-starter/test_pratt.py",
}

# tinylang's checkpoint page names its quiz data `QUESTIONS` and spells an
# option `{t, ok, why}`; `validate_quiz` emits `{text, correct, why}` and
# `render_quiz_html` looks for `const QUIZ_DATA`. The house shell is that page
# with these six renames applied and nothing else changed — recorded here so
# the parity test can recompute it, which is the drift guard the whole-copy
# files get from plain equality.
QUIZ_DIALECT = (
    (r"\bQUESTIONS\b", "QUIZ_DATA"),
    (r"\bopts\b", "options"),
    (r"\bo\.t\b", "o.text"),
    (r"\bo\.ok\b", "o.correct"),
    (r"\bt: ", "text: "),
    (r"\bok: ", "correct: "),
)


def tinylang_material(rel):
    path = os.path.join(llm.home(), "examples", "tinylang", "learning",
                        "interactive", rel)
    with open(path, encoding="utf-8") as f:
        return f.read()


class HouseExemplarTest(unittest.TestCase):
    """The shipped exemplar set: what a course's *first* build is shown.

    Every lookup in `build_phase` reaches for the course's own earlier
    materials and a new course has none, so each falls back here. Two things
    have to hold: the set is usable by the code that consumes it (the shell
    must render, the widget must survive the widget validator), and it has not
    drifted from the tinylang materials it was curated from.
    """

    def test_every_kind_returns_text_and_an_unknown_one_refuses(self):
        for kind in ("lesson", "widget", "quiz", "bank"):
            self.assertTrue(factory.house_exemplar(kind).strip(), kind)
        with self.assertRaises(KeyError):
            factory.house_exemplar("podcast")

    def test_the_exercise_comes_back_in_the_native_blob_format(self):
        blob = factory.house_exercise_exemplar()
        for fn in ("pratt.py", "task.md", "test_pratt.py"):
            self.assertIn(f"--- {fn} ---", blob)
        self.assertIn("NotImplementedError", blob)       # it ships red, as tinylang's does

    def test_the_quiz_shell_is_a_shell_the_renderer_can_swap(self):
        shell = factory.house_exemplar("quiz")
        self.assertIn("const QUIZ_DATA", shell)
        out = factory.render_quiz_html(shell, json.loads(GOOD_QUIZ), 1, 1)
        self.assertIn("Question 0?", out)
        self.assertNotIn("Why are lexing and parsing two stages", out)
        # And the block the quiz-author is shown is the questions, not the page.
        self.assertIn("const QUIZ_DATA", factory._quiz_exemplar(shell))

    def test_the_widget_would_survive_its_own_validator(self):
        widget = factory.house_exemplar("widget")
        # An exemplar the widget validator would refuse is an exemplar that
        # teaches the role to write refusable widgets.
        self.assertIsNone(factory.EXTERNAL_REF_RE.search(widget))
        self.assertTrue(factory.validate_widget(widget))

    def test_the_bank_section_is_one_section(self):
        section = factory.house_exemplar("bank")
        self.assertTrue(section.startswith("## "))
        self.assertEqual(section.count("\n## "), 0)

    def test_nothing_has_drifted_from_tinylang(self):
        for name, source in HOUSE_SOURCES.items():
            with open(os.path.join(factory.EXEMPLARS_DIR, name),
                      encoding="utf-8") as f:
                self.assertEqual(f.read(), tinylang_material(source), name)

        bank = tinylang_material("quizzes/question-bank.md")
        self.assertIn(factory.house_exemplar("bank"), bank)

        renamed = tinylang_material("quizzes/phase-1-checkpoint.html")
        for pattern, replacement in QUIZ_DIALECT:
            renamed = re.sub(pattern, replacement, renamed)
        self.assertEqual(factory.house_exemplar("quiz"), renamed)


class ConfigLocationTest(unittest.TestCase):
    """Where the factory reads `models.yaml` and `roles/` from.

    They live at the checkout root because they are operator-editable
    configuration, which makes the factory a checkout-mode feature: an
    installed curricle has the compiler and the web app but no role contracts.
    That is a supported outcome, not a bug — so it has to fail *legibly*
    rather than as a FileNotFoundError from inside a YAML parse.
    """

    def setUp(self):
        self._saved = os.environ.get("CURRICLE_HOME")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CURRICLE_HOME", None)
        else:
            os.environ["CURRICLE_HOME"] = self._saved

    def test_defaults_to_the_checkout_root(self):
        os.environ.pop("CURRICLE_HOME", None)
        self.assertEqual(llm.home(), llm.REPO_ROOT)
        self.assertTrue(os.path.isfile(llm.models_path()))
        self.assertTrue(os.path.isdir(llm.roles_dir()))

    def test_curricle_home_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CURRICLE_HOME"] = tmp
            # Resolved per call, not pinned at import: setting it late works.
            self.assertEqual(llm.home(), tmp)
            self.assertEqual(llm.models_path(), os.path.join(tmp, "models.yaml"))

    def test_a_home_holding_a_real_config_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "roles"))
            with open(os.path.join(llm.models_path()), encoding="utf-8") as f:
                real = f.read()
            with open(os.path.join(tmp, "models.yaml"), "w", encoding="utf-8") as f:
                f.write(real)
            with open(os.path.join(tmp, "roles", "quiz-author.md"), "w",
                      encoding="utf-8") as f:
                f.write("---\nname: quiz-author\n---\nA stand-in contract.\n")
            os.environ["CURRICLE_HOME"] = tmp
            self.assertEqual(load_role("quiz-author").system,
                             "A stand-in contract.")
            self.assertTrue(load_models_config().tiers)

    def test_missing_models_yaml_says_what_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CURRICLE_HOME"] = tmp
            with self.assertRaises(FactoryConfigMissing) as caught:
                load_models_config()
        message = str(caught.exception)
        self.assertIn("models.yaml", message)
        self.assertIn("CURRICLE_HOME", message)

    def test_missing_role_names_the_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CURRICLE_HOME"] = tmp
            with self.assertRaises(FactoryConfigMissing) as caught:
                load_role("quiz-author")
        self.assertIn("quiz-author", str(caught.exception))


class OutlineRolesTest(unittest.TestCase):
    """The two outline roles, and the tags their prompts are assembled from.

    `curriculum-designer` and `resource-curator` are read by the outline
    build, which interpolates the sections named here by name. The tag
    assertions are a cheap drift guard in both directions: rename a section in
    the prompt assembly without rewording the contract (or the reverse) and
    the model is briefed on inputs it never receives.
    """

    @classmethod
    def setUpClass(cls):
        cls.config = load_models_config()

    def test_contracts_load(self):
        for name in ("curriculum-designer", "resource-curator"):
            role = load_role(name)
            self.assertEqual(role.name, name)
            self.assertTrue(role.system)

    def test_they_run_on_the_top_tier_at_the_default_budget(self):
        top = self.config.tiers["premium"]
        default = Decimal(str(self.config.budgets["default"]))
        for name in ("curriculum-designer", "resource-curator"):
            self.assertEqual(self.config.model_for_role(name), top)
            self.assertEqual(self.config.budget_for_stage(name), default)
            # The tier mapping lives in models.yaml alone; a contract that
            # named a model or a price would be a second place to change.
            # The whole file, frontmatter included — a model named in
            # `mission:` is as much a second place as one in the body.
            with open(os.path.join(llm.roles_dir(), f"{name}.md"),
                      encoding="utf-8") as f:
                text = f.read()
            for leak in (*self.config.tiers.values(), *self.config.prices):
                self.assertNotIn(leak, text)

    def test_bodies_name_their_prompt_sections(self):
        designer = load_role("curriculum-designer").system
        curator = load_role("resource-curator").system
        for tag in ("<learner_profile>", "<scope>", "<compiler_findings>",
                    "<reviewer_note>"):
            self.assertIn(tag, designer)
            self.assertIn(tag, curator)
        for tag in ("<course_id>", "<exemplar_course>"):
            self.assertIn(tag, designer)
        for tag in ("<curriculum_md>", "<resource_shelf>",
                    "<exemplar_resources>"):
            self.assertIn(tag, curator)


class FakeOutlineSend:
    """A scripted transport for the two outline roles.

    Routing is by prompt tag rather than by the contract's wording: the
    prompt assembly is what this suite is pinning, and `<course_id>` goes to
    exactly one role. Every call is logged, so "the curator never ran" is an
    assertion rather than an inference.
    """

    def __init__(self, designer, curator=None, usage=None):
        self.designer = designer
        self.curator = curator
        self.usage = usage or {"input_tokens": 100, "output_tokens": 200,
                               "cache_write_tokens": 0, "cache_read_tokens": 0}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model, system, prompt, max_tokens):
        role = ("curriculum-designer" if "<course_id>" in prompt
                else "resource-curator")
        assert "<learner_profile>" in prompt          # calibration is the point
        self.calls.append((role, prompt))
        reply = self.designer if role == "curriculum-designer" else self.curator
        text = reply(prompt) if callable(reply) else reply
        return text, dict(self.usage)

    def roles(self):
        return [role for role, _ in self.calls]

    def prompts(self, role):
        return [p for r, p in self.calls if r == role]


def on_rewrite(first, rewritten):
    """The same role, answering differently once it has been given findings."""
    return lambda prompt: rewritten if "<compiler_findings>" in prompt else first


def compile_draft(draft_dir):
    from curricle.compiler import compile_course
    from curricle.sidecar import load_sidecar
    return compile_course(draft_dir,
                          load_sidecar(os.path.join(draft_dir, "learning",
                                                    "course.yaml")))


class BuildOutlineTest(unittest.TestCase):
    """The outline stage: the compiler is the validator, one rewrite, no network.

    Each test gets its own tenant so the token ledger it asserts against
    holds only its own rows.
    """

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()

    def setUp(self):
        with self.engine.begin() as conn:
            self.tenant = db.create_tenant(conn, f"outline-{self.id()}")
        self.scope = db.for_tenant(self.tenant)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.draft = os.path.join(self.tmp.name, "tiny-demo", ".draft-onboarding")

    def build(self, send, note=None):
        runner = Runner(self.engine, self.scope, send=send)
        return factory.build_outline(runner, profile.ProfileState(), "tiny-demo",
                                     SCOPE, self.draft, note=note)

    def ledger_stages(self):
        with self.engine.begin() as conn:
            return conn.execute(
                sa.select(db.token_ledger.c.stage)
                .where(db.token_ledger.c.tenant_id == self.tenant)
            ).scalars().all()

    def paths(self):
        return [os.path.join(self.draft, rel) for rel in factory.OUTLINE_FILES]

    def test_happy_path_writes_a_draft_that_compiles(self):
        send = FakeOutlineSend(designer_json(), GOOD_SHELF)
        report = self.build(send)

        self.assertEqual(report.draft_dir, self.draft)
        self.assertEqual(report.files, list(factory.OUTLINE_FILES))
        self.assertEqual(report.retried, ())
        for path in self.paths():
            self.assertTrue(os.path.exists(path), path)
        manifest, issues = compile_draft(self.draft)
        self.assertIsNotNone(manifest, [str(i) for i in issues])
        self.assertEqual(manifest.course.id, "tiny-demo")
        self.assertEqual([u.id for u in manifest.units], ["u1", "u2"])

        # L2: every call metered, under a stage label that is the role name.
        self.assertEqual(sorted(self.ledger_stages()),
                         ["curriculum-designer", "resource-curator"])
        self.assertEqual(sorted(report.costs), ["curriculum-designer",
                                                "resource-curator"])
        self.assertIn("100in/200out", report.costs["curriculum-designer"])

    def test_the_designer_runs_before_the_curator_and_hands_it_the_curriculum(self):
        send = FakeOutlineSend(designer_json(), GOOD_SHELF)
        self.build(send)
        self.assertEqual(send.roles(), ["curriculum-designer", "resource-curator"])
        designer_prompt = send.prompts("curriculum-designer")[0]
        for tag in ("<scope>", "<course_id>", "<exemplar_course>"):
            self.assertIn(tag, designer_prompt)
        self.assertIn("Crafting Interpreters", designer_prompt)   # tinylang
        curator_prompt = send.prompts("resource-curator")[0]
        for tag in ("<scope>", "<curriculum_md>", "<resource_shelf>",
                    "<exemplar_resources>"):
            self.assertIn(tag, curator_prompt)
        self.assertIn("resource keys: primer", curator_prompt)
        self.assertNotIn("<reviewer_note>", curator_prompt)
        # The shelf list is the exact titles and URLs the curator must
        # reproduce — the whole reason agreement is checkable rather than
        # guessed at.
        self.assertIn("primer — The Manifest Primer — "
                      "https://example.invalid/primer", curator_prompt)

    def test_the_curator_gets_the_shelf_list_and_not_the_sidecar(self):
        # The curator needs keys, titles and URLs; nothing else in course.yaml
        # is its business, and a shelf it could quote the sidecar into would
        # be agreement by copying rather than by contract.
        send = FakeOutlineSend(designer_json(), GOOD_SHELF)
        self.build(send)
        curator_prompt = send.prompts("resource-curator")[0]
        self.assertNotIn("<course_yaml>", curator_prompt)
        for sidecar_only in ("sidecar_version", "why_this_one", "curriculum_doc",
                             "resource_tiers"):
            self.assertNotIn(sidecar_only, curator_prompt)
        # The designer, by contrast, is shown a whole sidecar.
        self.assertIn("sidecar_version", send.prompts("curriculum-designer")[0])

    def test_a_reviewer_note_reaches_both_roles(self):
        send = FakeOutlineSend(designer_json(), GOOD_SHELF)
        self.build(send, note="Too many weeks — I have four, not eight.")
        for _, prompt in send.calls:
            self.assertIn("<reviewer_note>", prompt)
            self.assertIn("I have four, not eight", prompt)

    def test_compile_errors_buy_exactly_one_rewrite(self):
        send = FakeOutlineSend(
            on_rewrite(designer_json(sidecar=BROKEN_SIDECAR), designer_json()),
            GOOD_SHELF)
        report = self.build(send)

        self.assertEqual(report.retried, ("curriculum-designer",))
        self.assertEqual(send.roles(), ["curriculum-designer", "resource-curator",
                                        "curriculum-designer"])
        findings = send.prompts("curriculum-designer")[1]
        self.assertIn("<compiler_findings>", findings)
        self.assertIn("sidecar declares num 9", findings)
        manifest, _ = compile_draft(self.draft)
        self.assertIsNotNone(manifest)
        # One line per role, totalling both of the designer's calls.
        self.assertIn("200in/400out", report.costs["curriculum-designer"])

    def test_a_second_failure_refuses_and_keeps_nothing(self):
        send = FakeOutlineSend(designer_json(sidecar=BROKEN_SIDECAR), GOOD_SHELF)
        with self.assertRaises(factory.OutlineFailed) as caught:
            self.build(send)

        self.assertEqual(caught.exception.reason, "compile_failed")
        self.assertIn("sidecar declares num 9", caught.exception.detail)
        self.assertEqual(send.roles().count("curriculum-designer"), 2)
        self.assertEqual(send.roles().count("resource-curator"), 1)
        for path in self.paths():
            self.assertFalse(os.path.exists(path), path)

    def test_a_malformed_envelope_refuses_before_the_curator_runs(self):
        send = FakeOutlineSend("Sure! Here is your course outline.", GOOD_SHELF)
        with self.assertRaises(factory.OutlineFailed) as caught:
            self.build(send)

        self.assertEqual(caught.exception.reason, "validation_failed")
        self.assertEqual(send.roles(), ["curriculum-designer"])
        for path in self.paths():
            self.assertFalse(os.path.exists(path), path)

    def test_an_empty_half_of_the_envelope_is_a_refusal_too(self):
        send = FakeOutlineSend(json.dumps({"curriculum_md": GOOD_CURRICULUM,
                                           "course_yaml": "  "}), GOOD_SHELF)
        with self.assertRaises(factory.OutlineFailed) as caught:
            self.build(send)
        self.assertEqual(caught.exception.reason, "validation_failed")
        self.assertIn("course_yaml", caught.exception.detail)

    def test_a_wrong_course_id_is_a_finding_not_a_fixup(self):
        wrong = GOOD_SIDECAR.replace("id: tiny-demo", "id: tiny_demo")
        send = FakeOutlineSend(
            on_rewrite(designer_json(sidecar=wrong), designer_json()), GOOD_SHELF)
        report = self.build(send)

        self.assertEqual(report.retried, ("curriculum-designer",))
        self.assertIn("the minted id is 'tiny-demo'",
                      send.prompts("curriculum-designer")[1])

    def test_a_shelf_that_disagrees_with_the_sidecar_is_a_finding(self):
        send = FakeOutlineSend(designer_json(),
                               on_rewrite(WRONG_SHELF, GOOD_SHELF))
        report = self.build(send)

        # Only the curator is implicated: the `where` names its file.
        self.assertEqual(report.retried, ("resource-curator",))
        self.assertEqual(send.roles().count("curriculum-designer"), 1)
        findings = send.prompts("resource-curator")[1]
        self.assertIn("resource key 'primer'", findings)      # missing entry
        self.assertIn("Some Other Book", findings)            # invented entry
        manifest, _ = compile_draft(self.draft)
        self.assertIsNotNone(manifest)

    def test_a_sidecar_the_loader_cannot_parse_becomes_a_finding(self):
        # `hours_per_week: 4` subscripts an int inside the loader. The stage
        # converts the crash into a finding rather than dying on it.
        send = FakeOutlineSend(
            on_rewrite(designer_json(sidecar=CRASHING_SIDECAR), designer_json()),
            GOOD_SHELF)
        report = self.build(send)

        self.assertEqual(report.retried, ("curriculum-designer",))
        self.assertIn("TypeError", send.prompts("curriculum-designer")[1])
        manifest, _ = compile_draft(self.draft)
        self.assertIsNotNone(manifest)

    def test_an_unparseable_sidecar_twice_refuses_without_crashing(self):
        send = FakeOutlineSend(designer_json(sidecar=CRASHING_SIDECAR), GOOD_SHELF)
        with self.assertRaises(factory.OutlineFailed) as caught:
            self.build(send)
        self.assertEqual(caught.exception.reason, "compile_failed")
        self.assertIn("TypeError", caught.exception.detail)

    def test_a_budget_spent_mid_rewrite_still_keeps_nothing(self):
        # The first designer call spends the whole stage budget, so its
        # rewrite is refused by the runner. Nothing partial survives that.
        send = FakeOutlineSend(
            designer_json(sidecar=BROKEN_SIDECAR), GOOD_SHELF,
            usage={"input_tokens": 900_000, "output_tokens": 20_000,
                   "cache_write_tokens": 0, "cache_read_tokens": 0})
        with self.assertRaises(BudgetExceeded):
            self.build(send)
        for path in self.paths():
            self.assertFalse(os.path.exists(path), path)

    def test_budget_refusal_propagates_untouched(self):
        def expensive(model, system, prompt, max_tokens):
            return designer_json(), {"input_tokens": 900_000,
                                     "output_tokens": 20_000,
                                     "cache_write_tokens": 0,
                                     "cache_read_tokens": 0}
        runner = Runner(self.engine, self.scope, send=expensive)
        runner.run_role("curriculum-designer", "p")     # $5.00 of a $5.00 stage
        with self.assertRaises(BudgetExceeded):
            factory.build_outline(runner, profile.ProfileState(), "tiny-demo",
                                  SCOPE, self.draft)


def shelf_entry(title, url, essay="Because this one, for this learner."):
    return (f"### {title}\n*Somebody · 2026 · free*\n→ <{url}>\n\n{essay}\n\n")


def shelf_doc(*entries):
    return ("# Learning resources\n\nTier 1 is the core path.\n\n---\n\n"
            "## Tier 1 — Core path\n\n" + "".join(entries)
            + "---\n\n*Resources v1.0 — 2026-08-30.*\n")


class ShelfAgreementTest(unittest.TestCase):
    """The curator's markdown and the sidecar name the same resources.

    Only `build_outline` checks this — `docs.resources_doc` points the
    compiler at the file but nothing reads it — and the check is exact by
    design. The curator is handed each key's title and URL in
    `<resource_shelf>`, so a heading it had to guess at is a heading that
    drifted, and a matcher generous enough to forgive the drift is generous
    enough to bless a fabrication.
    """

    def resource(self, key, title, url, **kw):
        from curricle.schema import Resource
        return Resource(key=key, title=title, url=url, **kw)

    def test_an_honest_shelf_has_nothing_to_say(self):
        res = self.resource("primer", "The Manifest Primer",
                            "https://example.invalid/primer")
        self.assertEqual(factory.shelf_findings(
            (res,), shelf_doc(shelf_entry("The Manifest Primer",
                                          "https://example.invalid/primer"))), [])

    def test_both_directions_of_disagreement_are_findings(self):
        res = self.resource("primer", "The Manifest Primer",
                            "https://example.invalid/primer")
        missing = factory.shelf_findings((res,), shelf_doc())
        self.assertEqual(len(missing), 1)
        self.assertIn("'primer'", missing[0].message)
        self.assertEqual(missing[0].where, "learning/learning-resources.md")

        invented = factory.shelf_findings((), shelf_doc(shelf_entry(
            "A Book Nobody Asked For", "https://example.invalid/x")))
        self.assertEqual(len(invented), 1)
        self.assertIn("A Book Nobody Asked For", invented[0].message)

    def test_a_subtitled_impostor_does_not_claim_the_real_entry(self):
        # The exploit an approximate matcher blesses: a real title, extended,
        # pointing somewhere else. Exactness refuses it from both sides.
        res = self.resource("crafting", "Crafting Interpreters",
                            "https://craftinginterpreters.com/")
        findings = factory.shelf_findings((res,), shelf_doc(shelf_entry(
            "Crafting Interpreters: The Video Series",
            "https://not-crafting-interpreters.invalid/videos")))
        self.assertEqual(len(findings), 2)
        blob = " ".join(f.message for f in findings)
        self.assertIn("'crafting'", blob)
        self.assertIn("The Video Series", blob)

    def test_the_right_title_pointing_somewhere_else_is_a_finding(self):
        res = self.resource("crafting", "Crafting Interpreters",
                            "https://craftinginterpreters.com/")
        findings = factory.shelf_findings((res,), shelf_doc(shelf_entry(
            "Crafting Interpreters", "https://mirror.invalid/crafting")))
        self.assertEqual(len(findings), 1)
        self.assertIn("https://mirror.invalid/crafting", findings[0].message)
        self.assertIn("https://craftinginterpreters.com/", findings[0].message)

    def test_a_shorter_title_does_not_steal_a_longer_one(self):
        # Two honest resources whose titles nest. Greedy approximate matching
        # let 'Python' claim 'Fluent Python' and then refuse an honest shelf.
        one = self.resource("py", "Python", "https://example.invalid/python")
        two = self.resource("fluent", "Fluent Python",
                            "https://example.invalid/fluent")
        doc = shelf_doc(shelf_entry("Python", "https://example.invalid/python"),
                        shelf_entry("Fluent Python",
                                    "https://example.invalid/fluent"))
        self.assertEqual(factory.shelf_findings((one, two), doc), [])
        self.assertEqual(factory.shelf_findings((two, one), doc), [])

    def test_typography_is_not_disagreement(self):
        # `&` for "and", a trailing slash, backticks and curly quotes: the two
        # files spell these differently and mean the same resource.
        both = (self.resource("ci", "Compilers & Interpreters",
                              "https://example.invalid/c/"),
                self.resource("tok", "Python: the tokenize module",
                              "https://docs.python.invalid/tokenize"))
        doc = shelf_doc(
            shelf_entry("Compilers and Interpreters", "https://example.invalid/c"),
            shelf_entry("Python: the `tokenize` module",
                        "https://docs.python.invalid/tokenize"))
        self.assertEqual(factory.shelf_findings(both, doc), [])

    def test_the_example_course_agrees_with_its_own_shelf(self):
        # The exemplar both roles are shown must itself pass the check, or
        # they are being calibrated on a shelf the factory would refuse.
        from curricle.sidecar import load_sidecar
        root = os.path.join(llm.home(), "examples", "tinylang", "learning")
        sidecar = load_sidecar(os.path.join(root, "course.yaml"))
        with open(os.path.join(root, "learning-resources.md"),
                  encoding="utf-8") as f:
            self.assertEqual(factory.shelf_findings(sidecar.resources, f.read()),
                             [])


class BuildPlanTest(unittest.TestCase):
    """The plan the outline gate shows, and what it says the build will cost."""

    def manifest_for(self, curriculum, sidecar):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "learning"))
        for rel, body in zip(factory.OUTLINE_FILES,
                             (curriculum, sidecar, GOOD_SHELF)):
            with open(os.path.join(tmp.name, rel), "w", encoding="utf-8") as f:
                f.write(body)
        manifest, issues = compile_draft(tmp.name)
        self.assertIsNotNone(manifest, [str(i) for i in issues])
        return manifest

    def test_two_unit_phase_takes_first_second_and_last(self):
        plan = factory.default_build_plan(
            self.manifest_for(GOOD_CURRICULUM, GOOD_SIDECAR))
        self.assertEqual(plan, {
            "phase_id": "p1", "lesson_unit": "u1", "widget_unit": "u2",
            "widget_concept": "The compiler refuses rather than guesses.",
            "exercise_unit": "u2", "quiz": True, "bank": True})
        # The keys are BuildSpec's fields: an approved plan reaches the build
        # with nothing in between to mistranslate it.
        self.assertEqual(factory.BuildSpec(**plan),
                         factory.BuildSpec(phase_id="p1", lesson_unit="u1",
                                           widget_unit="u2",
                                           widget_concept=plan["widget_concept"],
                                           exercise_unit="u2"))

    def test_one_unit_phase_gets_no_widget(self):
        curriculum = GOOD_CURRICULUM[:GOOD_CURRICULUM.index("### Unit 2")] + (
            "### — Phase 1 Checkpoint —\nYou can write a sidecar that compiles.\n"
            "\n---\n\n*Curriculum v1.0 — 2026-08-30: initial version.*\n")
        sidecar = (GOOD_SIDECAR[:GOOD_SIDECAR.index("- id: u2")]
                   .replace("capstone: u2", "capstone: u1"))
        plan = factory.default_build_plan(self.manifest_for(curriculum, sidecar))
        self.assertEqual(plan["lesson_unit"], "u1")
        self.assertIsNone(plan["widget_unit"])
        self.assertIsNone(plan["widget_concept"])
        self.assertEqual(plan["exercise_unit"], "u1")

    def test_estimate_is_the_sum_of_the_lines_the_plan_activates(self):
        config = load_models_config()

        def line(role):
            input_tokens, output_tokens = factory.ESTIMATE_TOKENS[role]
            return config.cost(config.model_for_role(role),
                               input_tokens, output_tokens)

        plan = {"phase_id": "p1", "lesson_unit": "u1", "widget_unit": "u2",
                "widget_concept": "closures", "exercise_unit": "u2",
                "quiz": True, "bank": True}
        expected = sum((line(r) for _, r in factory.PLAN_ROLES), Decimal(0))
        self.assertEqual(factory.estimate_build_cost(config, plan), expected)

        thinner = {**plan, "widget_unit": None, "widget_concept": None}
        self.assertEqual(
            factory.estimate_build_cost(config, plan)
            - factory.estimate_build_cost(config, thinner),
            line("widget-builder"))


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.tenant = db.create_tenant(conn, "factory-runner")
        cls.scope = db.for_tenant(cls.tenant)
        cls.config = load_models_config()

    def test_roles_load_and_map_to_models(self):
        for name in ("lesson-writer", "quiz-author", "exercise-author",
                     "widget-builder", "bank-author"):
            role = load_role(name)
            self.assertTrue(role.system)
            self.assertIn(self.config.model_for_role(name), self.config.prices)

    def test_call_is_metered(self):
        def fake_send(model, system, prompt, max_tokens):
            return "output", {"input_tokens": 1000, "output_tokens": 500,
                              "cache_write_tokens": 0, "cache_read_tokens": 0}
        runner = Runner(self.engine, self.scope, self.config, send=fake_send)
        result = runner.run_role("quiz-author", "prompt")
        # opus-5: 1000 in * $5/M + 500 out * $25/M = $0.005 + $0.0125
        self.assertEqual(result.cost_usd, Decimal("0.0175"))
        self.assertEqual(runner.spent("quiz-author"), Decimal("0.017500"))

    def test_budget_refusal(self):
        def expensive(model, system, prompt, max_tokens):
            return "x", {"input_tokens": 900_000, "output_tokens": 20_000,
                         "cache_write_tokens": 0, "cache_read_tokens": 0}
        with self.engine.begin() as conn:
            t = db.create_tenant(conn, "factory-budget")
        runner = Runner(self.engine, db.for_tenant(t), self.config,
                        send=expensive)
        runner.run_role("widget-builder", "p")     # $4.50+$0.50 = $5.00 spent
        with self.assertRaises(BudgetExceeded):
            runner.run_role("widget-builder", "p")


@unittest.skipUnless(HAVE_ML, "ml-ai course not present")
class BuildPhaseTest(unittest.TestCase):
    """End-to-end build against the real ml-ai manifest, fake transport."""

    @classmethod
    def setUpClass(cls):
        from curricle.compiler import compile_course
        from curricle.sidecar import load_sidecar
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            t = db.create_tenant(conn, "factory-build")
        cls.scope = db.for_tenant(t)
        cls.manifest, _ = compile_course(
            ML_ROOT, load_sidecar(os.path.join(ML_ROOT, "course.yaml")))

    def test_build_quiz_and_exercise_into_draft(self):
        responses = {"quiz-author": GOOD_QUIZ, "exercise-author": GOOD_EXERCISE}

        def fake_send(model, system, prompt, max_tokens):
            # Route by which role's system prompt this is.
            role = ("quiz-author" if "checkpoint-quiz questions" in system
                    else "exercise-author")
            self.assertIn("Learner Profile", prompt)      # calibration present
            return responses[role], {"input_tokens": 10, "output_tokens": 10,
                                     "cache_write_tokens": 0,
                                     "cache_read_tokens": 0}

        runner = Runner(self.engine, self.scope, send=fake_send)
        with tempfile.TemporaryDirectory() as content_root:
            os.makedirs(os.path.join(content_root, "interactive/quizzes"))
            # A quiz shell must exist in the (temp) content root.
            import shutil
            shutil.copy(
                os.path.join(ML_ROOT, "interactive/quizzes/phase-1-checkpoint.html"),
                os.path.join(content_root, "interactive/quizzes/phase-1-checkpoint.html"))
            spec = factory.BuildSpec(phase_id="p2", exercise_unit="u3",
                                     quiz=True, bank=False)
            report = factory.build_phase(
                runner, self.manifest, profile.ProfileState(),
                content_root, spec)
            roles = {a.role for a in report.artifacts}
            self.assertEqual(roles, {"quiz-author", "exercise-author"})
            quiz_path = os.path.join(
                report.draft_dir, "quizzes/phase-2-checkpoint.html")
            self.assertTrue(os.path.exists(quiz_path))
            with open(quiz_path) as f:
                self.assertIn("Question 0?", f.read())
            self.assertTrue(os.path.exists(os.path.join(
                report.draft_dir, "exercises/unit-03-bpe/task.md")))


GOOD_LESSON = "# Lesson\n" + "context " * 400 + "\n> PAUSE.\nmore"
GOOD_WIDGET = ("<!DOCTYPE html><html><body><script>let x=1;</script>"
               "</body></html>")
GOOD_BANK = ("## Module 3 — Tokenization\n\n**3.1 (R)** What is BPE?\n"
             "**Answer:** Byte-pair encoding.\n**Note:** Merges by frequency.")

BUILD_RESPONSES = {
    "lesson-writer": GOOD_LESSON,
    "widget-builder": GOOD_WIDGET,
    "exercise-author": GOOD_EXERCISE,
    "quiz-author": GOOD_QUIZ,
    "bank-author": GOOD_BANK,
}


class FakeBuildSend:
    """A scripted transport for the five build roles, routed by prompt tag.

    By tag rather than by the contract's wording, for the same reason
    `FakeOutlineSend` does it: the prompt assembly is what these tests pin,
    and each role is handed exactly one exemplar section of its own.
    """

    TAGS = (("<exemplar_lesson>", "lesson-writer"),
            ("<exemplar_widget>", "widget-builder"),
            ("<exemplar_exercise>", "exercise-author"),
            ("<exemplar_questions>", "quiz-author"),
            ("<existing_bank>", "bank-author"))

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model, system, prompt, max_tokens):
        role = next(r for tag, r in self.TAGS if tag in prompt)
        self.calls.append((role, prompt))
        return BUILD_RESPONSES[role], {"input_tokens": 10, "output_tokens": 10,
                                       "cache_write_tokens": 0,
                                       "cache_read_tokens": 0}

    def prompt(self, role):
        return next(p for r, p in self.calls if r == role)


# The tiny demo course again, this time declaring one material of every kind
# the build looks for — the phase-2-and-later case, where the course's own
# earlier work is the exemplar and the house set must stay out of the way.
NATIVE_MATERIALS = """
materials:
- id: l-u01
  kind: lesson
  title: Native lesson
  path: interactive/lessons/unit-01-lesson.md
  unit: u1
- id: w-native
  kind: widget
  title: Native widget
  path: interactive/widgets/native.html
  unit: u1
- id: x-u01
  kind: exercise
  title: unit-01-native
  path: interactive/exercises/unit-01-native
  unit: u1
  grader: {type: unit-test, runner: python-unittest, command: python test_native.py}
- id: q-phase-1
  kind: quiz
  title: Phase 1 checkpoint
  path: interactive/quizzes/phase-1-checkpoint.html
  phase_num: 1
- id: bank
  kind: question-bank
  title: Question bank
  path: interactive/quizzes/question-bank.md
"""

NATIVE_FILES = {
    "lessons/unit-01-lesson.md": "# Native lesson\nNATIVE-LESSON.\n> PAUSE.\n",
    "widgets/native.html": ("<!DOCTYPE html><html><body>NATIVE-WIDGET"
                            "<script>let x=1;</script></body></html>\n"),
    "exercises/unit-01-native/task.md": "# Native task\nNATIVE-EXERCISE.\n",
    "quizzes/phase-1-checkpoint.html": (
        "<title>Phase 1 Checkpoint</title>\n<script>\n"
        "const QUIZ_DATA = [\n  {q: 'NATIVE-QUIZ'}\n];\n</script>\n"),
    "quizzes/question-bank.md": "# Bank\n\n## Unit 1\nNATIVE-BANK.\n",
}

FULL_SPEC = factory.BuildSpec(phase_id="p1", lesson_unit="u1",
                              widget_unit="u2", widget_concept="refusal",
                              exercise_unit="u2", quiz=True, bank=True)


class HouseFallbackBuildTest(unittest.TestCase):
    """The fallback, where it is decided: prompt assembly, not the course tree.

    A brand-new course has no materials at all, so every exemplar lookup in
    `build_phase` comes up empty and every one of them falls back to the
    shipped set. Nothing about the fallback is written down — it is recomputed
    per call — so what these tests read is the prompt each role received.
    """

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()

    def setUp(self):
        with self.engine.begin() as conn:
            self.tenant = db.create_tenant(conn, f"house-{self.id()}")
        self.scope = db.for_tenant(self.tenant)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def course(self, sidecar, files=()):
        """A compiled tiny-demo course on disk, and its content root."""
        root = os.path.join(self.tmp.name, "course")
        os.makedirs(os.path.join(root, "learning"))
        for rel, body in zip(factory.OUTLINE_FILES,
                             (GOOD_CURRICULUM, sidecar, GOOD_SHELF)):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
                f.write(body)
        for rel, body in dict(files).items():
            path = os.path.join(root, "learning", "interactive", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        manifest, issues = compile_draft(root)
        self.assertIsNotNone(manifest, [str(i) for i in issues])
        return manifest, os.path.join(root, "learning")

    def build(self, manifest, content_root):
        send = FakeBuildSend()
        report = factory.build_phase(Runner(self.engine, self.scope, send=send),
                                     manifest, profile.ProfileState(),
                                     content_root, FULL_SPEC)
        return send, report

    def test_an_empty_course_is_built_against_the_house_set(self):
        manifest, _ = self.course(GOOD_SIDECAR)
        # Not the course's own tree: a first build has nothing in it, and the
        # fallback must never put anything there either.
        content_root = os.path.join(self.tmp.name, "empty")
        send, report = self.build(manifest, content_root)

        self.assertEqual({a.role for a in report.artifacts},
                         {"lesson-writer", "widget-builder", "exercise-author",
                          "quiz-author", "bank-author"})
        self.assertIn(factory.house_exemplar("lesson"),
                      send.prompt("lesson-writer"))
        self.assertIn(factory.house_exemplar("widget"),
                      send.prompt("widget-builder"))
        self.assertIn(factory.house_exercise_exemplar(),
                      send.prompt("exercise-author"))
        self.assertIn(factory._quiz_exemplar(factory.house_exemplar("quiz")),
                      send.prompt("quiz-author"))
        self.assertIn(factory.house_exemplar("bank"),
                      send.prompt("bank-author"))

        # The quiz path is the one that used to refuse outright. It now renders
        # into the house shell — whose "Phase 1" strings are what `old_phase`
        # already defaults to.
        with open(os.path.join(report.draft_dir,
                               "quizzes/phase-1-checkpoint.html")) as f:
            html = f.read()
        self.assertIn("Question 0?", html)
        self.assertIn("Phase 1 Checkpoint", html)
        self.assertNotIn("Why are lexing and parsing two stages", html)

        # The course tree stays honest: only the draft was written to, and
        # nothing under it came from `curricle/exemplars/`.
        self.assertEqual(os.listdir(os.path.join(content_root, "interactive")),
                         [".draft-p1"])

    def test_a_course_with_its_own_materials_keeps_using_them(self):
        manifest, content_root = self.course(GOOD_SIDECAR + NATIVE_MATERIALS,
                                             NATIVE_FILES)
        send, _ = self.build(manifest, content_root)

        for role, marker in (("lesson-writer", "NATIVE-LESSON"),
                             ("widget-builder", "NATIVE-WIDGET"),
                             ("exercise-author", "NATIVE-EXERCISE"),
                             ("quiz-author", "NATIVE-QUIZ"),
                             ("bank-author", "NATIVE-BANK")):
            self.assertIn(marker, send.prompt(role), role)
        for role, kind in (("lesson-writer", "lesson"),
                           ("widget-builder", "widget"),
                           ("bank-author", "bank")):
            self.assertNotIn(factory.house_exemplar(kind), send.prompt(role))
        self.assertNotIn(factory.house_exercise_exemplar(),
                         send.prompt("exercise-author"))
        self.assertNotIn("Why are lexing and parsing two stages",
                         send.prompt("quiz-author"))


if __name__ == "__main__":
    unittest.main()
