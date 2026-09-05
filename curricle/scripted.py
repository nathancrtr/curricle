"""The scripted model: walking the wizard without a key or a bill.

`python -m curricle work --scripted` runs the real worker over the real
queue, with the one seam the design put there — `worker.RUNNER_FACTORY` —
handing every stage a `Runner` whose transport is this module instead of
the Anthropic SDK. Everything else is the production path: the claim, the
outline stage compiling its draft, the gate's numbers, the build's
validators, promotion moving files into the courses home. What changes is
that the model's answers are canned, so the whole flow costs nothing and
needs no credential, and a person can sit in a browser and see every screen
the wizard has.

The canned course is a two-unit demo small enough to read and real enough
to compile. Its answers are the same fixtures the factory and flow suites
already prove the pipeline against; they live here so the CLI and the tests
answer with one script rather than two that drift. The designer reads the
`<course_id>` and `<scope>` sections of its prompt and answers under the
name the scope form minted, so the title a person types is the course they
land on.

Two dials exist because a stage that finishes in a millisecond is a stage
whose pending face nobody can look at, and a failure face nobody can reach
is a failure face nobody has reviewed (issue #61): `--linger` makes each
worker stage take that many seconds, and `--fail stage:reason` makes the
first run of that stage stop with that reason, in the ledger's own
vocabulary, so the retry button is a real retry.

The token ledger still fills: `Runner` meters every scripted call at the
prices in `models.yaml`, so the gate's estimate and the landing's receipt
are the real arithmetic over pretend tokens. Use a tenant you do not mind
carrying a pretend receipt.

This module is imported by the worker's entry point and by tests; the web
app never imports it (L1), and it never reaches the network by construction
— there is no `send` here that could.
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
import time
from typing import Callable

import yaml

from . import llm, onboarding, worker

# ---------------------------------------------------------------------------
# The canned course
# ---------------------------------------------------------------------------

COURSE_ID = "tiny-demo"
TITLE = "Tiny demo"

CURRICULUM = """\
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

SIDECAR = """\
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

SHELF = """\
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

# Question 4 names a phase on purpose: a later phase's quiz is entitled to
# ask what an earlier one covered, in those words, and the renderer's phase
# renumbering must never reach the model's own sentences.
QUIZ = json.dumps([
    {"q": "What did Phase 1 cover?" if i == 4 else f"Question {i}?", "options": [
        {"text": "right", "correct": True, "why": "because"},
        {"text": "wrong a", "correct": False, "why": "misconception a"},
        {"text": "wrong b", "correct": False, "why": "misconception b"},
        {"text": "wrong c", "correct": False, "why": "misconception c"},
    ]} for i in range(10)
])

EXERCISE = json.dumps({
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

LESSON = "# Lesson\n" + "context " * 400 + "\n> PAUSE.\nmore"
WIDGET = ("<!DOCTYPE html><html><body><script>let x=1;</script>"
          "</body></html>")
BANK = ("## Module 3 — Tokenization\n\n**3.1 (R)** What is BPE?\n"
        "**Answer:** Byte-pair encoding.\n**Note:** Merges by frequency.")

BUILD_RESPONSES = {
    "lesson-writer": LESSON,
    "widget-builder": WIDGET,
    "exercise-author": EXERCISE,
    "quiz-author": QUIZ,
    "bank-author": BANK,
}

# Roles are told apart by the one prompt section each carries and no other
# does: the prompt assembly in `factory.py` is the contract, so a scripted
# model routed on it is routed on exactly what a real one is briefed with.
BUILD_TAGS = (("<exemplar_lesson>", "lesson-writer"),
              ("<exemplar_widget>", "widget-builder"),
              ("<exemplar_exercise>", "exercise-author"),
              ("<exemplar_questions>", "quiz-author"),
              ("<existing_bank>", "bank-author"))

USAGE = {"input_tokens": 100, "output_tokens": 200,
         "cache_write_tokens": 0, "cache_read_tokens": 0}


def designer_json(curriculum: str = CURRICULUM, sidecar: str = SIDECAR) -> str:
    """The designer's envelope: two complete files in one JSON object."""
    return json.dumps({"curriculum_md": curriculum, "course_yaml": sidecar})


def _section(prompt: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.S)
    return m.group(1) if m else None


def answer_as(prompt: str) -> tuple[str, str, str]:
    """(curriculum, sidecar, shelf) under the id and title the prompt names.

    The scope form mints the course id from the title a person typed, and
    the outline stage refuses a sidecar declaring any other id — so the
    canned course answers under that id, or the scripted walk would stop at
    a compile finding the moment anyone typed a title of their own.
    """
    course_id = (_section(prompt, "course_id") or COURSE_ID).strip()
    title = TITLE
    scope = _section(prompt, "scope")
    if scope:
        try:
            title = str(yaml.safe_load(scope).get("title") or TITLE)
        except (yaml.YAMLError, AttributeError):
            title = TITLE
    sidecar = SIDECAR.replace(f"id: {COURSE_ID}", f"id: {course_id}", 1)
    sidecar = sidecar.replace(f"title: {TITLE}",
                              "title: " + json.dumps(title), 1)
    curriculum = CURRICULUM.replace("# Tiny Demo: Curriculum",
                                    f"# {title}: Curriculum", 1)
    shelf = SHELF.replace("# Tiny Demo: Learning resources",
                          f"# {title}: Learning resources", 1)
    return curriculum, sidecar, shelf


class ScriptedSend:
    """A transport that answers every factory role from the script above.

    The signature is `llm._anthropic_send`'s, which is what makes it a
    transport: `Runner` calls it where it would call the SDK and meters what
    comes back. Every call is logged as (role, prompt) so a test can say
    "these calls are the whole of what was bought" against one list.
    """

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model: str, system: str, prompt: str,
                 max_tokens: int) -> tuple[str, dict]:
        build_role = next((r for tag, r in BUILD_TAGS if tag in prompt), None)
        if build_role is not None:
            role, text = build_role, BUILD_RESPONSES[build_role]
        elif "<course_id>" in prompt:
            curriculum, sidecar, _ = answer_as(prompt)
            role, text = "curriculum-designer", designer_json(curriculum, sidecar)
        else:
            role, text = "resource-curator", answer_as(prompt)[2]
        self.calls.append((role, prompt))
        return text, dict(USAGE)

    def roles(self) -> list[str]:
        return [role for role, _ in self.calls]


def runner_factory(engine, scope) -> llm.Runner:
    """`worker.RUNNER_FACTORY` for a scripted worker: a real, metering
    `Runner` with this module as its transport. It reads `models.yaml` and
    `roles/` exactly as the production one does — the script replaces the
    model, not the factory around it."""
    return llm.Runner(engine, scope, send=ScriptedSend())


# ---------------------------------------------------------------------------
# The two dials
# ---------------------------------------------------------------------------

class BadFailSpec(ValueError):
    pass


def parse_fail(spec: str) -> tuple[str, str]:
    """`stage:reason`, both in the ledger's vocabulary or refused."""
    stage, sep, reason = spec.partition(":")
    if not sep or stage not in onboarding.WORKER_STAGES \
            or reason not in onboarding.REASONS:
        raise BadFailSpec(
            f"--fail wants STAGE:REASON with STAGE one of "
            f"{', '.join(sorted(onboarding.WORKER_STAGES))} and REASON one of "
            f"{', '.join(onboarding.REASONS)}; got {spec!r}")
    return stage, reason


def handlers(*, linger: float = 0.0, fail: tuple[tuple[str, str], ...] = (),
             base: dict[str, Callable] | None = None,
             sleep: Callable[[float], None] = time.sleep,
             log=sys.stderr) -> dict[str, Callable]:
    """The worker's stage handlers, wrapped with the two dials.

    `linger` holds each stage for that many seconds before running it, so
    its pending face stays on screen long enough to be looked at. `fail`
    is a set of (stage, reason) pairs; the first claim of each such stage
    stops with that reason instead of running, and the next claim — the
    retry the wizard offers — runs for real. Both wrap `worker.HANDLERS`
    unless `base` says otherwise, and the wrapped handler is what
    `run_once` is handed, so the ledger sees exactly what it would see
    from a real failure: a `StageFailed` in its own vocabulary.
    """
    base = worker.HANDLERS if base is None else base
    pending = {stage: reason for stage, reason in fail}

    def wrap(stage: str, handler: Callable) -> Callable:
        def run(engine, scope, run_row):
            reason = pending.pop(stage, None)
            if reason is not None:
                print(f"scripted: failing {stage} with {reason!r} (once)",
                      file=log)
                raise worker.StageFailed(reason, "scripted failure, on request")
            if linger:
                print(f"scripted: lingering {linger:g}s on {stage}", file=log)
                sleep(linger)
            return handler(engine, scope, run_row)
        return run

    return {stage: wrap(stage, h) for stage, h in base.items()}
