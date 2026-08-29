"""The course factory: build a phase's interactive layer as metered LLM jobs.

The pipeline is the course-builder skill translated into code. Each artifact
is one role call through the metered executor; outputs are validated
strictly (a quiz missing a `why` fails generation, not review), land in a
draft directory, and reach the course only through an explicit promote —
generated content is proposed, the human publishes.

Calibration is the point: every prompt carries the learner profile — the
*derived* projection from the evidence ledger, not a hand-written blurb —
plus exemplars from the course's own earlier phases, so the factory writes
in the course's established voice for this specific learner.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from .llm import Runner
from .profile import ProfileState
from .profilerender import render_skill_md
from .schema import Manifest, Phase, Unit


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
# ---------------------------------------------------------------------------

QUIZ_DATA_RE = re.compile(r"const QUIZ_DATA = \[.*?\n\];", re.S)


def render_quiz_html(shell: str, questions: list[dict], phase_num: int,
                     old_phase_num: int) -> str:
    js_items = ",\n".join(json.dumps(q, ensure_ascii=False, indent=2)
                          for q in questions)
    replaced = QUIZ_DATA_RE.sub(f"const QUIZ_DATA = [\n{js_items}\n];",
                                shell, count=1)
    if replaced == shell:
        raise ValidationFailed("quiz shell has no QUIZ_DATA block to replace")
    return replaced.replace(f"Phase {old_phase_num}", f"Phase {phase_num}")


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
        exemplar = read_exemplar(content_root, manifest, "lesson") or ""
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

    if spec.widget_unit:
        unit = units[spec.widget_unit]
        exemplar = read_exemplar(content_root, manifest, "widget") or ""
        concept = spec.widget_concept or unit.gloss or unit.title
        text = validate_widget(run("widget-builder", [
            ("course", course_line),
            ("unit", unit_md(unit)),
            ("concept", concept),
            ("exemplar_widget", exemplar),
        ], max_tokens=64000))
        slug = re.sub(r"[^a-z0-9]+", "-", concept.lower()).strip("-")[:32]
        rel = f"widgets/{slug}.html"
        save(rel, text)
        report.artifacts.append(Artifact(
            role="widget-builder", rel_path=f"interactive/{rel}", content=text,
            material={"id": f"w-{slug[:16].rstrip('-')}", "kind": "widget",
                      "title": concept, "path": f"interactive/{rel}",
                      "unit": unit.id}))

    if spec.exercise_unit:
        unit = units[spec.exercise_unit]
        exemplar = read_exercise_exemplar(content_root, manifest) or ""
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

    if spec.quiz:
        shell = read_exemplar(content_root, manifest, "quiz", max_bytes=200_000)
        if shell is None:
            raise ValidationFailed("no existing checkpoint quiz to use as shell")
        old_phase = next((p.num for p in manifest.phases
                          for m in manifest.materials
                          if m.kind == "quiz" and m.phase == p.id), 1)
        questions = validate_quiz(run("quiz-author", [
            ("course", course_line),
            ("phase", phase_context),
            ("exemplar_questions", _quiz_exemplar(shell)),
        ]))
        html = render_quiz_html(shell, questions, phase.num, old_phase)
        rel = f"quizzes/phase-{phase.num}-checkpoint.html"
        save(rel, html)
        report.artifacts.append(Artifact(
            role="quiz-author", rel_path=f"interactive/{rel}", content=html,
            material={"id": f"q-phase-{phase.num}", "kind": "quiz",
                      "title": f"Phase {phase.num} checkpoint",
                      "path": f"interactive/{rel}", "phase_num": phase.num}))

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
            ("existing_bank", exemplar),
        ]))
        rel = f"quizzes/bank-phase-{phase.num}.md"
        save(rel, text)
        report.artifacts.append(Artifact(
            role="bank-author", rel_path="", content=text,
            material={},
            note=f"append to {bank_material.path if bank_material else 'question bank'}"))

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


def write_build_manifest(report: BuildReport, phase_num: int,
                         bank_target: str | None) -> None:
    data = {
        "phase_num": phase_num,
        "bank_target": bank_target,
        "artifacts": [{"rel_path": a.rel_path, "material": a.material,
                       "note": a.note} for a in report.artifacts],
        "costs": report.costs,
    }
    with open(os.path.join(report.draft_dir, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, indent=2)
