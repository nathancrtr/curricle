"""The course factory: build a phase's interactive layer as metered LLM jobs.

The pipeline is the course-builder skill translated into code. Each artifact
is one role call through the metered executor; outputs are validated
strictly (a quiz missing a `why` fails generation, not review), land in a
draft directory, and reach the course only through an explicit promote —
generated content is proposed, the human publishes.

One stage earlier, `build_outline` drafts the course itself — curriculum,
sidecar, resource shelf — and there the validator is the compiler: the draft
is compiled where it stands and its error-level issues are the findings the
roles get one rewrite from. A generated course artifact that does not
compile clean was not generated.

Calibration is the point: every prompt carries the learner profile — the
*derived* projection from the evidence ledger, not a hand-written blurb —
plus exemplars from the course's own earlier phases, so the factory writes
in the course's established voice for this specific learner. A course's
*first* build has no earlier phases to quote, so each of those lookups falls
back to the shipped house set in `curricle/exemplars/`; from phase 2 on the
course's own materials take over, exactly as before.

That handover has one wrinkle, and `render_quiz_html` carries it: what phase
2 reads as its quiz shell is phase 1's *rendered page*, which — if phase 1
fell back — is the house shell wearing a course's identity rather than a page
the course wrote. So a house render stamps its lineage into the page and a
later render recomputes the house copy from its own phase and question count,
instead of either freezing last phase's wording or editing an edit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal

import yaml

from .compiler import Issue, compile_course
from .llm import FactoryConfigMissing, ModelsConfig, Runner, home
from .profile import ProfileState
from .profilerender import render_skill_md
from .schema import Manifest, Phase, Resource, SchemaError, Unit
from .sidecar import load_sidecar


class ValidationFailed(ValueError):
    pass


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def unit_md(unit: Unit) -> str:
    parts = [f"## Unit {unit.num}: {unit.title}"]
    if unit.gloss:
        parts.append(f"*{unit.gloss}*")
    for row in unit.rows:
        parts.append(f"### {row.label}\n{row.content}")
    return "\n\n".join(parts)


def phase_md(manifest: Manifest, phase: Phase) -> str:
    units = {u.id: u for u in manifest.units}
    parts = [f"# Phase {phase.num} — {phase.title}", f"**Goal:** {phase.goal}"]
    parts.extend(unit_md(units[e]) for e in phase.entries if e in units)
    if phase.checkpoint:
        parts.append(f"**Checkpoint:** {phase.checkpoint.prose}")
    return "\n\n".join(parts)


def read_exemplar(content_root: str, manifest: Manifest, kind: str,
                  max_bytes: int = 40_000) -> str | None:
    """The smallest existing material of this kind — the style anchor."""
    candidates = []
    for m in manifest.materials:
        if m.kind != kind:
            continue
        path = os.path.join(content_root, m.path)
        if os.path.isfile(path) and os.path.getsize(path) <= max_bytes:
            candidates.append((os.path.getsize(path), path))
    if not candidates:
        return None
    _, path = min(candidates)
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_exercise_exemplar(content_root: str, manifest: Manifest) -> str | None:
    for m in manifest.materials:
        if m.kind != "exercise":
            continue
        d = os.path.join(content_root, m.path)
        if not os.path.isdir(d):
            continue
        parts = []
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if os.path.isfile(p) and os.path.getsize(p) < 20_000:
                with open(p, encoding="utf-8") as f:
                    parts.append(f"--- {fn} ---\n{f.read()}")
        if parts:
            return "\n\n".join(parts)
    return None


# The house exemplars: what the roles are shown when the course itself has
# nothing of the kind yet, which for a brand-new course is everything. They
# live inside the package rather than at `llm.home()` because they are library
# data, not operator configuration — an installed curricle carries its
# reference voice the way it carries its renderers, and there is no version of
# the factory that should write a first lesson with no lesson in front of it.
EXEMPLARS_DIR = os.path.join(os.path.dirname(__file__), "exemplars")

HOUSE_EXEMPLARS = {
    "lesson": "lesson.md",
    "widget": "widget.html",
    "quiz": "quiz-shell.html",
    "bank": "bank-section.md",
}


def house_exemplar(kind: str) -> str:
    """The shipped exemplar of `kind` — refuse an unknown one, don't guess."""
    with open(os.path.join(EXEMPLARS_DIR, HOUSE_EXEMPLARS[kind]),
              encoding="utf-8") as f:
        return f.read()


def house_exercise_exemplar() -> str:
    """The shipped exercise, in `read_exercise_exemplar`'s file-blob format."""
    d = os.path.join(EXEMPLARS_DIR, "exercise")
    parts = []
    for fn in sorted(os.listdir(d)):
        with open(os.path.join(d, fn), encoding="utf-8") as f:
            parts.append(f"--- {fn} ---\n{f.read()}")
    return "\n\n".join(parts)


@dataclass
class BuildSpec:
    phase_id: str
    lesson_unit: str | None = None
    widget_unit: str | None = None
    widget_concept: str | None = None
    exercise_unit: str | None = None
    quiz: bool = True
    bank: bool = True


@dataclass
class Artifact:
    role: str
    rel_path: str          # destination relative to content_root, post-promote
    content: str
    material: dict         # sidecar materials entry to append on promote
    note: str = ""


@dataclass
class BuildReport:
    artifacts: list[Artifact] = field(default_factory=list)
    costs: dict[str, str] = field(default_factory=dict)
    draft_dir: str = ""


def _prompt(profile_md: str, sections: list[tuple[str, str]]) -> str:
    parts = [
        "<learner_profile>\n" + profile_md + "\n</learner_profile>",
    ]
    for tag, body in sections:
        parts.append(f"<{tag}>\n{body}\n</{tag}>")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Validators — refusal, not review
# ---------------------------------------------------------------------------

def _strip_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"\A```[a-zA-Z]*\n(.*)\n```\Z", text, re.S)
    return m.group(1) if m else text


def validate_lesson(text: str) -> str:
    text = _strip_fence(text)
    if not text.lstrip().startswith("#"):
        raise ValidationFailed("lesson must start with a markdown heading")
    if "PAUSE" not in text:
        raise ValidationFailed("lesson has no PAUSE stop-points")
    if len(text) < 2_000 or len(text) > 60_000:
        raise ValidationFailed(f"lesson length {len(text)} outside sane bounds")
    return text


def validate_quiz(text: str) -> list[dict]:
    try:
        data = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise ValidationFailed(f"quiz is not valid JSON: {exc}")
    if not isinstance(data, list) or not 8 <= len(data) <= 14:
        raise ValidationFailed(f"quiz needs 8–14 questions, got "
                               f"{len(data) if isinstance(data, list) else 'non-list'}")
    for i, item in enumerate(data):
        opts = item.get("options")
        if not item.get("q") or not isinstance(opts, list) or len(opts) != 4:
            raise ValidationFailed(f"question {i + 1}: needs q + exactly 4 options")
        correct = [o for o in opts if o.get("correct") is True]
        if len(correct) != 1:
            raise ValidationFailed(f"question {i + 1}: needs exactly 1 correct "
                                   f"option, got {len(correct)}")
        for j, o in enumerate(opts):
            if not o.get("text") or not str(o.get("why", "")).strip():
                raise ValidationFailed(
                    f"question {i + 1} option {j + 1}: every option carries "
                    "text and a why")
    return data


def validate_exercise(text: str, workdir: str) -> dict:
    try:
        data = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise ValidationFailed(f"exercise is not valid JSON: {exc}")
    for key in ("slug", "task_md", "stub_name", "stub", "test_name", "test"):
        if not data.get(key):
            raise ValidationFailed(f"exercise missing {key!r}")
    if not re.match(r"^unit-\d{2}-[a-z0-9-]+$", data["slug"]):
        raise ValidationFailed(f"bad exercise slug {data['slug']!r}")
    if "NotImplementedError" not in data["stub"]:
        raise ValidationFailed("stub must raise NotImplementedError")
    if "unittest" not in data["test"] or "__main__" not in data["test"]:
        raise ValidationFailed("test must use unittest with a __main__ runner")
    # The real smoke test: the tests must run and fail against the stub.
    xdir = os.path.join(workdir, data["slug"])
    os.makedirs(xdir, exist_ok=True)
    for name, content in ((data["stub_name"], data["stub"]),
                          (data["test_name"], data["test"])):
        with open(os.path.join(xdir, name), "w", encoding="utf-8") as f:
            f.write(content)
    proc = subprocess.run([sys.executable, data["test_name"]],
                          cwd=xdir, capture_output=True, text=True, timeout=60)
    if proc.returncode == 0:
        raise ValidationFailed("tests PASS against the stub — they test nothing")
    blob = proc.stdout + proc.stderr
    if "NotImplementedError" not in blob and "FAILED" not in blob \
            and "FAIL:" not in blob and "ERROR" not in blob:
        raise ValidationFailed(f"tests did not run cleanly against the stub:\n"
                               f"{blob[-800:]}")
    if "Traceback (most recent call last)" in blob and "NotImplementedError" \
            not in blob:
        raise ValidationFailed(f"tests crash for the wrong reason:\n{blob[-800:]}")
    return data


EXTERNAL_REF_RE = re.compile(r"https?://")


def validate_widget(text: str) -> str:
    text = _strip_fence(text)
    if not text.lstrip().lower().startswith("<!doctype html"):
        raise ValidationFailed("widget must be a complete HTML document")
    if EXTERNAL_REF_RE.search(text):
        raise ValidationFailed("widget references the network — widgets are "
                               "offline-only, no exceptions")
    if "<script" not in text:
        raise ValidationFailed("widget has no script — nothing to manipulate")
    if len(text) > 200_000:
        raise ValidationFailed("widget exceeds 200KB")
    return text


def validate_bank(text: str) -> str:
    text = _strip_fence(text)
    if not text.lstrip().startswith("##"):
        raise ValidationFailed("bank section must start with a ## heading")
    for marker in ("**Answer:**", "**Note:**"):
        if marker not in text:
            raise ValidationFailed(f"bank section missing {marker}")
    if not re.search(r"\*\*\d+\.\d+ \([RAW]\)\*\*", text):
        raise ValidationFailed("bank items must carry N.M (R|A|W) tags")
    return text


# ---------------------------------------------------------------------------
# Quiz shell: reuse the course's existing checkpoint HTML, swap the data
# and the identity — which quiz this is, and which quiz it reports as
# ---------------------------------------------------------------------------

QUIZ_DATA_RE = re.compile(r"const QUIZ_DATA = \[.*?\n\];", re.S)

# The shim call the finished quiz reports through. Its first argument is the
# material id the events API validates the POST against, so a shell copied
# from another quiz reports under that quiz's id: an unknown id 422s and the
# result never reaches the ledger, a *known* one lands on the wrong quiz.
#
# A commented-out call is not a call: `before` is the rest of its own line and
# may not contain `//`, so a shell whose only report is commented out refuses
# rather than rendering mute — and the comment is left as its author wrote it.
# Two cases are knowingly not handled, because handling them means parsing
# JavaScript: a call inside a `/* … */` block, and an id built as a template
# string (`curricle.checkpoint(`q-phase-${n}`…)`), which the quoted-literal
# pattern simply does not match and which therefore refuses.
CHECKPOINT_CALL_RE = re.compile(
    r"""(?m)^(?P<before>(?:(?!//).)*?)"""
    r"""(?P<call>curricle\.checkpoint\(\s*)(?P<q>["'])[^"']*(?P=q)""")

TITLE_RE = re.compile(r"<title>.*?</title>", re.S)

# Rendered into every page descended from the house shell, so a later build
# reusing that page as its shell can tell house lineage from a course's own
# voice. Without it the second render would see a page that no longer equals
# the shipped file, keep its copy, and compound the phase numbers.
HOUSE_MARKER = "<!-- curricle:house-quiz-shell -->"

# The house shell's own subject-matter copy — tinylang's, since that is where
# the shell was curated from — and, alternated in, this function's own output
# from the last time it neutralised a page. Every render recomputes all three
# from scratch, so a descendant gets fresh copy rather than an edit of an
# edit. Applied to house lineage only: a course's own checkpoint page keeps
# its voice, and only its id is rewritten.
HOUSE_INTRO_RE = re.compile(
    r"(?:Eight questions on lexing and parsing"
    r"|\d+ questions on this phase's material)\.")
HOUSE_OUTRO_RE = re.compile(r"On to Phase \d+\.")
HOUSE_FAIL_RE = re.compile(r"reread the misses' explanations, then [^\"]*")


def render_quiz_html(shell: str, questions: list[dict], phase_num: int,
                     old_phase_num: int, *, material_id: str,
                     course_title: str) -> str:
    """The shell wearing the identity of the quiz actually being built.

    Everything the page says about *which* quiz this is came from the page it
    was copied from, so all of it is rewritten: the checkpoint id (the
    load-bearing one), the title, and every "Phase N" in the chrome, in either
    case — the eyebrow spells it lowercase. A shell with no checkpoint call is
    refused rather than shipped mute: a quiz whose result reaches no one is
    not a checkpoint.

    Order matters twice. The data swap goes last, so none of the chrome
    rewriting reaches the generated questions — a phase-2 quiz is entitled to
    mention phase 1, in those words. And the house copy is neutralised after
    the phase renumber, so the outro is computed from the phase being built
    rather than from whatever the renumber left behind.

    Lineage matters once. The house shell's own subject copy is neutralised;
    a course's own page keeps its voice. But the *output* of a house render is
    what the next phase's build reads as its shell — it is no longer equal to
    the shipped file, and mistaking it for a course-native page would freeze
    last phase's copy and compound its numbers. So a house render stamps
    `HOUSE_MARKER` into the page and the marker counts as house lineage, with
    every neutralisation recomputed from this render's phase and question
    count rather than patched forward.
    """
    page, calls = CHECKPOINT_CALL_RE.subn(
        lambda m: m.group("before") + m.group("call")
        + json.dumps(material_id), shell)
    if not calls:
        raise ValidationFailed("quiz shell has no curricle.checkpoint call to "
                               "retarget — its results would reach no one")
    title = f"Phase {phase_num} Checkpoint — {course_title}"
    page = TITLE_RE.sub(lambda m: f"<title>{title}</title>", page, count=1)
    page = re.sub(rf"(?i)\b(phase)\s+{old_phase_num}\b",
                  lambda m: f"{m.group(1)} {phase_num}", page)
    if shell == house_exemplar("quiz") or HOUSE_MARKER in shell:
        page = HOUSE_INTRO_RE.sub(
            f"{len(questions)} questions on this phase's material.",
            page, count=1)
        page = HOUSE_OUTRO_RE.sub(f"On to Phase {phase_num + 1}.",
                                  page, count=1)
        page = HOUSE_FAIL_RE.sub(
            "reread the misses' explanations, then revisit this phase's "
            "materials.", page, count=1)
        page = _stamp_house_lineage(page)

    js_items = ",\n".join(json.dumps(q, ensure_ascii=False, indent=2)
                          for q in questions)
    page, swapped = QUIZ_DATA_RE.subn(
        lambda m: f"const QUIZ_DATA = [\n{js_items}\n];", page, count=1)
    if not swapped:
        raise ValidationFailed("quiz shell has no QUIZ_DATA block to replace")
    return page


def _stamp_house_lineage(page: str) -> str:
    """The marker, once — a re-render of a marked page is still one page."""
    if HOUSE_MARKER in page:
        return page
    if "</head>" in page:
        return page.replace("</head>", f"{HOUSE_MARKER}\n</head>", 1)
    return f"{HOUSE_MARKER}\n{page}"


# ---------------------------------------------------------------------------
# The outline: curriculum + sidecar + shelf, validated by the compiler itself
# ---------------------------------------------------------------------------

OUTLINE_FILES = ("learning/curriculum.md", "learning/course.yaml",
                 "learning/learning-resources.md")

EXEMPLAR_COURSE = "tinylang"


class OutlineFailed(ValueError):
    """The outline stage kept nothing.

    `reason` is the machine value the onboarding ledger records (and the
    wizard maps to a human sentence); `detail` is operator-facing — the
    compiler's findings, a parse error — and is never screen copy.
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass
class OutlineReport:
    draft_dir: str
    files: list[str] = field(default_factory=list)     # relative paths written
    costs: dict[str, str] = field(default_factory=dict)
    retried: tuple[str, ...] = ()                      # roles given the rewrite


def _exemplar_file(name: str) -> str:
    """One of the exemplar course's outline files, read from the checkout.

    tinylang is the schema's reference instance — the one course that
    exercises every part of the manifest and compiles clean — so it is what
    the two outline roles are shown. Reading it from `llm.home()` makes the
    outline stage a checkout-mode feature exactly as the roles are.
    """
    path = os.path.join(home(), "examples", EXEMPLAR_COURSE, "learning", name)
    if not os.path.isfile(path):
        raise FactoryConfigMissing.for_path(
            path, f"the {EXEMPLAR_COURSE} exemplar's {name}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def outline_exemplar() -> str:
    """The exemplar's curriculum and sidecar, in one blob the designer reads."""
    return "\n\n".join(
        f"--- file: learning/{name} ---\n{_exemplar_file(name)}"
        for name in ("curriculum.md", "course.yaml"))


# The shelf the learner reviews is the curator's markdown; the shelf the
# compiler resolves `res:` against is the sidecar's. Nothing else checks that
# they are the same shelf, so this does — and it checks by *exact* title and
# URL, because the curator is handed both in `<resource_shelf>`. A matcher
# that guessed would be a matcher that could be talked around: a fabricated
# "…: The Video Series" entry pointing somewhere else is precisely the
# disagreement worth catching, and a fuzzy pass would call it a match.
SHELF_ENTRY_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>()\[\]]+")


def _shelf_entries(md: str) -> list[tuple[str, str]]:
    marks = list(SHELF_ENTRY_RE.finditer(md))
    entries = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        closing = md.find("\n## ", m.end(), end)     # a new tier closes a section
        entries.append((m.group(1).strip(),
                        md[m.end():closing if closing != -1 else end]))
    return entries


def _shelf_name(text: str) -> str:
    """A title's identity, modulo typography the two files spell differently:
    markdown emphasis, quote style, `&` for `and`, whitespace, a full stop."""
    text = re.sub(r"[`*_“”‘’\"']", "", text)
    text = text.replace("&", " and ")
    return re.sub(r"\s+", " ", text).strip().strip(".").lower()


def _same_url(a: str, b: str) -> bool:
    return a.strip().rstrip("/") == b.strip().rstrip("/")


def _entry_urls(heading: str, body: str) -> list[str]:
    return [u.rstrip(".,;>)") for u in URL_IN_TEXT_RE.findall(heading + body)]


def shelf_findings(resources: tuple[Resource, ...], md: str) -> list[Issue]:
    """Compiler-style findings for a shelf that disagrees with the sidecar.

    One `###` entry per resource, its heading the listed title verbatim and
    its link the listed URL. Three ways to disagree, all findings: a key with
    no entry, an entry naming no key, and a pair whose URLs differ — the last
    is how a real title acquires a fabricated destination.
    """
    where = OUTLINE_FILES[2]
    entries = _shelf_entries(md)
    by_name: dict[str, list[int]] = {}
    for i, (heading, _) in enumerate(entries):
        by_name.setdefault(_shelf_name(heading), []).append(i)

    claimed: set[int] = set()
    findings: list[Issue] = []
    for res in resources:
        hit = next((i for i in by_name.get(_shelf_name(res.title), [])
                    if i not in claimed), None)
        if hit is None:
            findings.append(Issue(
                "error", where,
                f"resource key '{res.key}' has no '###' entry titled "
                f"{res.title!r} — the shelf reproduces each listed title "
                f"exactly, and it is the shelf the learner reads"))
            continue
        claimed.add(hit)
        found = _entry_urls(*entries[hit])
        wanted = [u for u in (res.url, *(u for _, u in res.links)) if u]
        if not any(_same_url(f, w) for f in found for w in wanted):
            findings.append(Issue(
                "error", where,
                f"the entry for '{res.key}' links "
                f"{found[0] if found else 'nothing'}; course.yaml lists "
                f"{res.url} — one resource, one destination"))
    for i, (heading, _) in enumerate(entries):
        if i not in claimed:
            findings.append(Issue(
                "error", where,
                f"shelf entry '{heading}' matches no resource in course.yaml — "
                f"the listed keys are the whole shelf, so drop it"))
    return findings


def resource_shelf_lines(course_yaml: str) -> str:
    """The designer's resource entries as `key — title — url`, one per line.

    The curator writes the shelf the learner reads, and the sidecar is the
    shelf the compiler resolves `res:` against; handing over the exact titles
    and URLs is what makes agreement between the two checkable rather than
    guessable. Read leniently — a sidecar too broken to read here is about to
    become a finding of its own, and an empty list is not worth crashing on.
    """
    try:
        entries = yaml.safe_load(course_yaml)["resources"] or []
    except (yaml.YAMLError, AttributeError, TypeError, KeyError, IndexError):
        return ""
    lines = []
    for entry in entries:
        try:
            url = entry.get("url") or entry["links"][0][1]
            lines.append(f"{entry['key']} — {entry['title']} — {url}")
        except (AttributeError, TypeError, KeyError, IndexError):
            continue
    return "\n".join(lines)


def _outline_envelope(text: str) -> tuple[str, str]:
    """The designer's JSON envelope. Malformed is a refusal, not a rewrite:
    an envelope the compiler never sees is not a compiler finding."""
    try:
        data = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise OutlineFailed("validation_failed",
                            f"curriculum-designer did not return JSON: {exc}")
    if not isinstance(data, dict):
        raise OutlineFailed("validation_failed",
                            "curriculum-designer returned a JSON "
                            f"{type(data).__name__}, not an object")
    missing = [k for k in ("curriculum_md", "course_yaml")
               if not str(data.get(k) or "").strip()]
    if missing:
        raise OutlineFailed("validation_failed",
                            f"curriculum-designer envelope is missing "
                            f"{', '.join(missing)}")
    return str(data["curriculum_md"]), str(data["course_yaml"])


def _course_id_findings(course_yaml: str, course_id: str) -> list[Issue]:
    """A wrong course id is a finding, never a fixup: the id is minted
    upstream and the sidecar is the model's to get right."""
    try:
        found = yaml.safe_load(course_yaml)["course"]["id"]
    except (yaml.YAMLError, AttributeError, TypeError, KeyError, IndexError):
        return []            # the load path below names this better than we can
    if found != course_id:
        return [Issue("error", OUTLINE_FILES[1],
                      f"course.id is {found!r}; the minted id is {course_id!r} "
                      f"and is used verbatim")]
    return []


def _outline_findings(draft_dir: str, course_yaml: str, resources_md: str,
                      course_id: str) -> list[Issue]:
    """Compile the draft in place and collect everything that blocks it.

    Warnings never block — errors block emission, warnings print, the same
    deal a human author gets. The load path is wrapped because the sidecar
    loader guards what it can and raises through what it can't (a scalar
    where it subscripts a pair is a TypeError, not a where-bearing Issue):
    either way the role gets a finding it can act on rather than the stage
    getting a traceback.
    """
    findings = _course_id_findings(course_yaml, course_id)
    try:
        sidecar = load_sidecar(os.path.join(draft_dir, OUTLINE_FILES[1]))
        _, issues = compile_course(draft_dir, sidecar)
    except (SchemaError, TypeError, ValueError, yaml.YAMLError) as exc:
        findings.append(Issue("error", OUTLINE_FILES[1],
                              f"the sidecar could not be loaded — "
                              f"{type(exc).__name__}: {exc}"))
        return findings
    findings.extend(i for i in issues if i.level == "error")
    findings.extend(shelf_findings(sidecar.resources, resources_md))
    return findings


def _implicated(findings: list[Issue]) -> tuple[str, ...]:
    """Attribution by `where`: the shelf is the curator's, everything else
    the designer's. Roles come back in run order — a rewritten curriculum is
    what the curator's rewrite is curating against."""
    roles = []
    if any("learning-resources" not in f.where for f in findings):
        roles.append("curriculum-designer")
    if any("learning-resources" in f.where for f in findings):
        roles.append("resource-curator")
    return tuple(roles)


def build_outline(runner: Runner, profile: ProfileState, course_id: str,
                  scope_payload: dict, draft_dir: str,
                  note: str | None = None) -> OutlineReport:
    """Draft a whole course outline into `draft_dir`, compiler-validated.

    Two roles in one order that matters: the designer writes `curriculum.md`
    and the full `course.yaml` — resource keys included, because `res:` links
    resolve against the sidecar — and the curator then writes the
    human-facing shelf for exactly those keys.

    The validator is the compiler. The draft is compiled where it stands, in
    a tree whose layout is the course layout, and its error-level issues are
    the findings the implicated roles get one rewrite from. A second failure
    keeps nothing: the three files are deleted so a retry starts clean.
    `BudgetExceeded` propagates — a spent stage is the runner's refusal to
    report, not ours to swallow.
    """
    profile_md = render_skill_md(profile)
    scope_md = yaml.safe_dump(scope_payload, sort_keys=False,
                              allow_unicode=True)
    report = OutlineReport(draft_dir=draft_dir, files=list(OUTLINE_FILES))
    spend: dict[str, list] = {}

    def run(role: str, sections: list[tuple[str, str]],
            max_tokens: int = 32000) -> str:
        result = runner.run_role(role, _prompt(profile_md, sections), max_tokens)
        # A rewrite is the same stage spending more: one line per role, the
        # build's format, totals rather than the last call's numbers.
        acc = spend.setdefault(role, [result.model, 0, 0, Decimal(0)])
        acc[1] += result.input_tokens
        acc[2] += result.output_tokens
        acc[3] += result.cost_usd
        report.costs[role] = f"${acc[3]:.4f} ({acc[0]}, {acc[1]}in/{acc[2]}out)"
        return result.text

    def designer(findings: str = "") -> str:
        sections = [("scope", scope_md), ("course_id", course_id),
                    ("exemplar_course", outline_exemplar())]
        if findings:
            sections.append(("compiler_findings", findings))
        if note:
            sections.append(("reviewer_note", note))
        # Two complete files in one envelope: a truncated response is a
        # malformed envelope, and a malformed envelope gets no rewrite.
        return run("curriculum-designer", sections, max_tokens=64000)

    def curator(curriculum_md: str, course_yaml: str,
                findings: str = "") -> str:
        # The shelf list, not the sidecar: the curator needs the keys, titles
        # and URLs it must reproduce, and nothing else in course.yaml is its
        # business.
        sections = [("scope", scope_md), ("curriculum_md", curriculum_md),
                    ("resource_shelf", resource_shelf_lines(course_yaml)),
                    ("exemplar_resources", _exemplar_file("learning-resources.md"))]
        if findings:
            sections.append(("compiler_findings", findings))
        if note:
            sections.append(("reviewer_note", note))
        text = _strip_fence(run("resource-curator", sections))
        if not text.strip():
            raise OutlineFailed("validation_failed",
                                "resource-curator returned an empty document")
        return text

    def write(curriculum_md: str, course_yaml: str, resources_md: str) -> None:
        os.makedirs(os.path.join(draft_dir, "learning"), exist_ok=True)
        for rel, body in zip(OUTLINE_FILES,
                             (curriculum_md, course_yaml, resources_md)):
            with open(os.path.join(draft_dir, rel), "w", encoding="utf-8") as f:
                f.write(body if body.endswith("\n") else body + "\n")

    def discard() -> None:
        for rel in OUTLINE_FILES:
            path = os.path.join(draft_dir, rel)
            if os.path.exists(path):
                os.remove(path)

    curriculum_md, course_yaml = _outline_envelope(designer())
    resources_md = curator(curriculum_md, course_yaml)
    write(curriculum_md, course_yaml, resources_md)

    findings = _outline_findings(draft_dir, course_yaml, resources_md, course_id)
    if findings:
        # One rewrite round, for the implicated roles only — a role nothing
        # names keeps its first output. A designer rewrite that moved the
        # resource keys therefore leaves the shelf disagreeing, and the second
        # check refuses it; the learner retries against a clean draft.
        report.retried = _implicated(findings)
        text = "\n".join(str(f) for f in findings)
        kept = False
        try:
            if "curriculum-designer" in report.retried:
                curriculum_md, course_yaml = _outline_envelope(designer(text))
            if "resource-curator" in report.retried:
                resources_md = curator(curriculum_md, course_yaml, text)
            write(curriculum_md, course_yaml, resources_md)
            findings = _outline_findings(draft_dir, course_yaml, resources_md,
                                         course_id)
            if findings:
                raise OutlineFailed("compile_failed",
                                    "\n".join(str(f) for f in findings))
            kept = True
        finally:
            # Every way out but success — a refusal, a spent budget, anything
            # the runner raises mid-rewrite — leaves nothing partial behind.
            if not kept:
                discard()
    return report


# ---------------------------------------------------------------------------
# The build plan and what it will cost
# ---------------------------------------------------------------------------

def default_build_plan(manifest: Manifest) -> dict:
    """What phase 1 gets built, derived from the outline rather than asked for.

    A lesson on the phase's first unit, a widget on its second, an exercise
    on its last, the checkpoint quiz, and a bank section only if there is a
    bank to append it to. Deterministic beats another model call: the learner
    reads the plan at the gate and can regenerate the phase if it is wrong.

    The bank is the one entry that asks a question about the course rather
    than about the phase, and it is the same question `build_phase` asks to
    find `bank_target`: a question-bank material in the manifest. A section
    is not a file — it is text appended to somebody else's — so a course
    with no bank has nowhere to put one, and `promote` silently drops it.
    Planning it anyway would bill a learner for an artifact that cannot
    survive publication, which is the honest reading of this being a *plan*:
    it says what will be bought, so it may not name what cannot be kept.
    (A brand-new wizard course has no bank yet, so it gets `False` here and
    `estimate_build_cost` stops charging for it — the number at the gate and
    what the build buys stay the same thing. Minting a bank file for a new
    course is the proper fix and is its own issue.)

    The keys are `BuildSpec`'s field names, so an approved plan reaches the
    build as `BuildSpec(**plan)` with nothing in between to mistranslate —
    which is why the bank's key stays and only its value moves.
    """
    phase = next((p for p in manifest.phases if p.num == 1), None)
    if phase is None:
        raise ValueError(f"{manifest.course.id} has no phase 1 to build")
    units = {u.id: u for u in manifest.units}
    entries = [units[e] for e in phase.entries if e in units]
    if not entries:
        raise ValueError(f"phase {phase.id} has no units to build against")
    widget = entries[1] if len(entries) > 1 else None
    return {
        "phase_id": phase.id,
        "lesson_unit": entries[0].id,
        "widget_unit": widget.id if widget else None,
        "widget_concept": (widget.gloss or widget.title) if widget else None,
        "exercise_unit": entries[-1].id,
        "quiz": True,
        "bank": any(m.kind == "question-bank" for m in manifest.materials),
    }


# Assumed tokens per artifact, priced at real models.yaml rates. Honest rough
# numbers: the ceiling the learner also sees is the per-stage budget, and
# this is the expectation — that is the guarantee.
ESTIMATE_TOKENS = {
    "lesson-writer":   (12_000, 12_000),   # (input, output)
    "widget-builder":  (12_000, 30_000),
    "exercise-author": (12_000, 8_000),
    "quiz-author":     (14_000, 8_000),
    "bank-author":     (14_000, 6_000),
}

PLAN_ROLES = (
    ("lesson_unit", "lesson-writer"),
    ("widget_unit", "widget-builder"),
    ("exercise_unit", "exercise-author"),
    ("quiz", "quiz-author"),
    ("bank", "bank-author"),
)


def estimate_build_cost(config: ModelsConfig, plan: dict) -> Decimal:
    """What the plan is expected to cost, at today's prices."""
    total = Decimal(0)
    for key, role in PLAN_ROLES:
        if not plan.get(key):
            continue
        input_tokens, output_tokens = ESTIMATE_TOKENS[role]
        total += config.cost(config.model_for_role(role),
                             input_tokens, output_tokens)
    return total


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

def build_phase(runner: Runner, manifest: Manifest, profile: ProfileState,
                content_root: str, spec: BuildSpec) -> BuildReport:
    phase = next(p for p in manifest.phases if p.id == spec.phase_id)
    units = {u.id: u for u in manifest.units}
    profile_md = render_skill_md(profile)
    phase_context = phase_md(manifest, phase)
    course_line = f"{manifest.course.title} ({manifest.course.id})"

    draft = os.path.join(content_root, "interactive",
                         f".draft-{phase.id}")
    os.makedirs(draft, exist_ok=True)
    report = BuildReport(draft_dir=draft)

    # A run may die mid-build (network, credits, validator). The manifest is
    # checkpointed after every artifact so nothing finished is ever orphaned,
    # and a resumed run (re-invoke with only the missing artifacts' flags)
    # merges into the same draft.
    bank_target = next((m.path for m in manifest.materials
                        if m.kind == "question-bank"), None)
    manifest_path = os.path.join(draft, "manifest.json")
    prior_artifacts: list[dict] = []
    prior_costs: dict[str, str] = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            prior = json.load(f)
        prior_artifacts = prior.get("artifacts", [])
        prior_costs = prior.get("costs", {})

    def checkpoint() -> None:
        fresh = [{"rel_path": a.rel_path, "material": a.material,
                  "note": a.note} for a in report.artifacts]
        fresh_keys = {(a["rel_path"], a["note"]) for a in fresh}
        kept = [a for a in prior_artifacts
                if (a["rel_path"], a.get("note", "")) not in fresh_keys]
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"phase_num": phase.num, "bank_target": bank_target,
                       "artifacts": kept + fresh,
                       "costs": {**prior_costs, **report.costs}}, f, indent=2)

    def run(role: str, sections: list[tuple[str, str]], max_tokens: int = 32000):
        result = runner.run_role(role, _prompt(profile_md, sections), max_tokens)
        report.costs[role] = f"${result.cost_usd:.4f} ({result.model}, " \
                             f"{result.input_tokens}in/{result.output_tokens}out)"
        return result.text

    def save(rel: str, content: str) -> str:
        path = os.path.join(draft, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        return path

    if spec.lesson_unit:
        unit = units[spec.lesson_unit]
        exemplar = (read_exemplar(content_root, manifest, "lesson")
                    or house_exemplar("lesson"))
        template = _lesson_template()
        text = validate_lesson(run("lesson-writer", [
            ("course", course_line),
            ("unit", unit_md(unit)),
            ("exemplar_lesson", exemplar),
            ("lesson_guide_template", template),
        ]))
        rel = f"lessons/unit-{unit.num:02d}-lesson.md"
        save(rel, text)
        report.artifacts.append(Artifact(
            role="lesson-writer", rel_path=f"interactive/{rel}", content=text,
            material={"id": f"l-u{unit.num:02d}", "kind": "lesson",
                      "title": f"{unit.title} (Socratic)",
                      "path": f"interactive/{rel}", "unit": unit.id}))
        checkpoint()

    if spec.widget_unit:
        unit = units[spec.widget_unit]
        exemplar = (read_exemplar(content_root, manifest, "widget")
                    or house_exemplar("widget"))
        concept = spec.widget_concept or unit.gloss or unit.title
        text = validate_widget(run("widget-builder", [
            ("course", course_line),
            ("unit", unit_md(unit)),
            ("concept", concept),
            ("exemplar_widget", exemplar),
        ], max_tokens=64000))
        slug = re.sub(r"[^a-z0-9]+", "-", concept.lower()).strip("-")
        if len(slug) > 28:
            slug = slug[:28].rsplit("-", 1)[0]
        rel = f"widgets/{slug}.html"
        save(rel, text)
        report.artifacts.append(Artifact(
            role="widget-builder", rel_path=f"interactive/{rel}", content=text,
            material={"id": f"w-{slug[:16].rstrip('-')}", "kind": "widget",
                      "title": concept, "path": f"interactive/{rel}",
                      "unit": unit.id}))
        checkpoint()

    if spec.exercise_unit:
        unit = units[spec.exercise_unit]
        exemplar = (read_exercise_exemplar(content_root, manifest)
                    or house_exercise_exemplar())
        data = validate_exercise(run("exercise-author", [
            ("course", course_line),
            ("unit", unit_md(unit)),
            ("exemplar_exercise", exemplar),
        ]), workdir=os.path.join(draft, "exercises"))
        xrel = f"exercises/{data['slug']}"
        save(f"{xrel}/task.md", data["task_md"])
        save(f"{xrel}/{data['stub_name']}", data["stub"])
        save(f"{xrel}/{data['test_name']}", data["test"])
        report.artifacts.append(Artifact(
            role="exercise-author", rel_path=f"interactive/{xrel}",
            content=data["task_md"],
            material={"id": f"x-u{unit.num:02d}", "kind": "exercise",
                      "title": data["slug"], "path": f"interactive/{xrel}",
                      "unit": unit.id,
                      "grader": {"type": "unit-test", "runner": "python-unittest",
                                 "command": f"python {data['test_name']}"}}))
        checkpoint()

    if spec.quiz:
        # The shell is the course's own checkpoint page with its data swapped;
        # a course that has none gets the house one, whose strings say "Phase
        # 1" — which is what `old_phase` falls back to just below.
        shell = (read_exemplar(content_root, manifest, "quiz",
                               max_bytes=200_000)
                 or house_exemplar("quiz"))
        old_phase = next((p.num for p in manifest.phases
                          for m in manifest.materials
                          if m.kind == "quiz" and m.phase == p.id), 1)
        questions = validate_quiz(run("quiz-author", [
            ("course", course_line),
            ("phase", phase_context),
            ("exemplar_questions", _quiz_exemplar(shell)),
        ]))
        # One id, spelled once: the page reports under exactly the material
        # the promote step registers, or the POST is refused (or, worse,
        # accepted against some other phase's quiz).
        quiz_id = f"q-phase-{phase.num}"
        html = render_quiz_html(shell, questions, phase.num, old_phase,
                                material_id=quiz_id,
                                course_title=manifest.course.title)
        rel = f"quizzes/phase-{phase.num}-checkpoint.html"
        save(rel, html)
        report.artifacts.append(Artifact(
            role="quiz-author", rel_path=f"interactive/{rel}", content=html,
            material={"id": quiz_id, "kind": "quiz",
                      "title": f"Phase {phase.num} checkpoint",
                      "path": f"interactive/{rel}", "phase_num": phase.num}))
        checkpoint()

    if spec.bank:
        bank_material = next((m for m in manifest.materials
                              if m.kind == "question-bank"), None)
        exemplar = ""
        if bank_material:
            with open(os.path.join(content_root, bank_material.path),
                      encoding="utf-8") as f:
                exemplar = f.read()[:20_000]
        text = validate_bank(run("bank-author", [
            ("course", course_line),
            ("phase", phase_context),
            ("existing_bank", exemplar or house_exemplar("bank")),
        ]))
        rel = f"quizzes/bank-phase-{phase.num}.md"
        save(rel, text)
        report.artifacts.append(Artifact(
            role="bank-author", rel_path="", content=text,
            material={},
            note=f"append to {bank_material.path if bank_material else 'question bank'}"))
        checkpoint()

    return report


def _lesson_template() -> str:
    path = os.path.expanduser(
        "~/.claude/skills/course-builder/assets/lesson-guide-template.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "(no template on this machine — follow the exemplar's structure)"


def _quiz_exemplar(shell: str) -> str:
    m = QUIZ_DATA_RE.search(shell)
    return m.group(0)[:12_000] if m else ""


# ---------------------------------------------------------------------------
# Promote: draft → course, sidecar updated, compile must stay clean
# ---------------------------------------------------------------------------

def promote(course_root: str, content_root: str, sidecar_path: str,
            phase_id: str) -> list[str]:
    import shutil

    import yaml

    from .compiler import compile_course
    from .sidecar import load_sidecar

    draft = os.path.join(content_root, "interactive", f".draft-{phase_id}")
    manifest_path = os.path.join(draft, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"no draft build manifest at {manifest_path}")
    with open(manifest_path, encoding="utf-8") as f:
        build = json.load(f)

    moved: list[str] = []
    with open(sidecar_path, encoding="utf-8") as f:
        sidecar_data = yaml.safe_load(f)
    sidecar_data.setdefault("materials", [])
    existing_ids = {m["id"] for m in sidecar_data["materials"]}

    for art in build["artifacts"]:
        if not art["rel_path"]:            # bank section: append, don't move
            bank_rel = build.get("bank_target")
            src = os.path.join(draft, "quizzes",
                               f"bank-phase-{build['phase_num']}.md")
            if bank_rel and os.path.exists(src):
                with open(src, encoding="utf-8") as f:
                    section = f.read()
                with open(os.path.join(content_root, bank_rel),
                          "a", encoding="utf-8") as f:
                    f.write("\n---\n\n" + section)
                moved.append(f"{bank_rel} (appended)")
            continue
        src = os.path.join(draft, os.path.relpath(art["rel_path"], "interactive"))
        dst = os.path.join(content_root, art["rel_path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        moved.append(art["rel_path"])
        if art["material"] and art["material"]["id"] not in existing_ids:
            sidecar_data["materials"].append(art["material"])

    with open(sidecar_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sidecar_data, f, sort_keys=False, allow_unicode=True,
                       width=110)

    manifest, issues = compile_course(course_root, load_sidecar(sidecar_path))
    if manifest is None:
        raise ValidationFailed(
            "promotion broke the course compile:\n" +
            "\n".join(str(i) for i in issues if i.level == "error"))
    shutil.rmtree(draft)
    return moved
