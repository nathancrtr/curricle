"""Compile curriculum.md + sidecar into a validated Manifest.

The compiler's job is refusal: every convention the corpus keeps by
discipline becomes a check here. Errors block emission; warnings ship but
are printed. Both carry enough location to fix without hunting.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .mdparse import DIALECTS, MdDoc, MdPhase, MdRow
from .refs import find_refs, iter_content
from .schema import (
    Check, Checkpoint, Course, Manifest, MANIFEST_VERSION, Material, Milestone,
    Pacing, Phase, Row, Unit, Version,
)
from .sidecar import Sidecar, SidecarUnit

URL_RE = re.compile(r"https?://\S+")
INTERACTIVE_PATH_RE = re.compile(r"(interactive/[A-Za-z0-9_./\-]+[A-Za-z0-9_\-/])")


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7s} {self.where}: {self.message}"


class Issues(list):
    def error(self, where: str, message: str) -> None:
        self.append(Issue("error", where, message))

    def warn(self, where: str, message: str) -> None:
        self.append(Issue("warning", where, message))

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self)


def compile_course(course_root: str, sidecar: Sidecar) -> tuple[Manifest | None, Issues]:
    issues = Issues()
    curriculum_rel = sidecar.course.docs.curriculum_doc or "learning/curriculum.md"
    curriculum_path = os.path.join(course_root, curriculum_rel)
    content_root = os.path.join(course_root, os.path.dirname(curriculum_rel))

    if not os.path.exists(curriculum_path):
        issues.error(curriculum_rel, "curriculum file not found")
        return None, issues
    parse = DIALECTS.get(sidecar.course.dialect)
    if parse is None:
        issues.error("course", f"unknown dialect {sidecar.course.dialect!r}")
        return None, issues
    with open(curriculum_path, encoding="utf-8") as f:
        doc = parse(f.read())
    if not doc.phases:
        issues.error(curriculum_rel, "no '## Phase N — Title' headers found")
        return None, issues

    units: list[Unit] = []
    phases: list[Phase] = []
    matched_nums: set[int] = set()

    for md_phase in doc.phases:
        phase_id = f"p{md_phase.num}"
        if not md_phase.goal:
            issues.warn(f"{phase_id}", "phase has no **Goal:** line")

        entry_ids: list[str] = []

        # Phase-body unit: label-bullets before any unit header, claimed by a
        # sidecar unit with phase_body:true and num == phase num (textual-flow's
        # Phase 0). Unclaimed body rows are only worth a warning if they look
        # like course content rather than stray formatting.
        if md_phase.body_rows:
            sc = sidecar.unit_by_num(md_phase.num)
            if sc is not None and sc.phase_body:
                unit = _build_unit(sc, md_phase.num, md_phase.title, phase_id,
                                   md_phase.body_rows, sidecar, issues)
                if md_phase.body_check:
                    unit = _replace(unit, check=Check(md_phase.body_check.q,
                                                      md_phase.body_check.ans))
                units.append(unit)
                entry_ids.append(unit.id)
                matched_nums.add(sc.num)
            else:
                issues.warn(phase_id, f"{len(md_phase.body_rows)} label-bullet(s) "
                            "before any unit header and no phase_body sidecar unit")

        for md_unit in md_phase.units:
            sc = sidecar.unit_by_num(md_unit.num)
            if sc is None:
                sc = SidecarUnit(id=f"u{md_unit.num}", num=md_unit.num)
                issues.warn(f"unit u{md_unit.num}",
                            "no sidecar entry; id minted, no gloss")
            elif sc.phase_body:
                issues.error(f"unit {sc.id}",
                             f"phase_body unit also matches '### Unit {md_unit.num}'")
            matched_nums.add(md_unit.num)
            unit = _build_unit(sc, md_unit.num, md_unit.title, phase_id,
                               md_unit.rows, sidecar, issues)
            if md_unit.check:
                unit = _replace(unit, check=Check(md_unit.check.q, md_unit.check.ans))
            units.append(unit)
            entry_ids.append(unit.id)

        # Milestones for this phase, positioned after their anchor unit.
        for ms in sidecar.milestones:
            if ms.phase_num != md_phase.num:
                continue
            if ms.after_unit:
                if ms.after_unit in entry_ids:
                    entry_ids.insert(entry_ids.index(ms.after_unit) + 1, ms.id)
                else:
                    issues.error(f"milestone {ms.id}",
                                 f"after_unit '{ms.after_unit}' not in phase {phase_id}")
                    entry_ids.append(ms.id)
            else:
                entry_ids.append(ms.id)

        phases.append(Phase(
            id=phase_id, num=md_phase.num, title=md_phase.title,
            goal=md_phase.goal, weeks=md_phase.weeks, entries=tuple(entry_ids),
            checkpoint=_build_checkpoint(md_phase, phase_id, sidecar, issues),
        ))

    for sc in sidecar.units:
        if sc.num not in matched_nums:
            issues.error(f"unit {sc.id}",
                         f"sidecar declares num {sc.num} but curriculum has no such unit")

    milestones = tuple(
        Milestone(id=m.id, phase=f"p{m.phase_num}", kind=m.kind, label=m.label,
                  detail=m.detail, after_unit=m.after_unit,
                  hours_per_month=m.hours_per_month, gate_for=m.gate_for)
        for m in sidecar.milestones
    )
    materials = _build_materials(sidecar)

    manifest = Manifest(
        manifest_version=MANIFEST_VERSION,
        course=_build_course(doc, sidecar, issues),
        tracks=sidecar.tracks,
        resources=sidecar.resources,
        resource_tiers=sidecar.resource_tiers,
        phases=tuple(phases),
        units=tuple(units),
        milestones=milestones,
        materials=materials,
    )
    _validate(manifest, content_root, issues, course_root=course_root,
              coverage_ignore=sidecar.course.coverage_ignore)
    return (None, issues) if issues.has_errors else (manifest, issues)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _replace(unit: Unit, **kw) -> Unit:
    from dataclasses import replace
    return replace(unit, **kw)


def _build_unit(sc: SidecarUnit, num: int, title: str, phase_id: str,
                md_rows: list[MdRow], sidecar: Sidecar, issues: Issues) -> Unit:
    track_by_label = {
        label: t.id for t in sidecar.tracks for label in t.row_labels
    }
    rows = []
    for r in md_rows:
        kind = "key" if r.label == "Key insight" else None
        rows.append(Row(label=r.label, content=r.content, kind=kind,
                        track=track_by_label.get(r.label)))
    return Unit(
        id=sc.id, num=num, phase=phase_id, title=title, rows=tuple(rows),
        gloss=sc.gloss, provenance=sc.provenance, depends_on=sc.depends_on,
        load_bearing=sc.load_bearing, skippable_note=sc.skippable_note,
        condition=sc.condition, steps=sc.steps, note=sc.note,
    )


def _build_checkpoint(md_phase: MdPhase, phase_id: str,
                      sidecar: Sidecar, issues: Issues) -> Checkpoint | None:
    cp = md_phase.checkpoint
    if cp is None:
        issues.warn(phase_id, "no '— Phase N Checkpoint —' block")
        return None
    goal_by_label = {
        label: t.id for t in sidecar.tracks for label in t.checkpoint_labels
    }
    track_goals = []
    for label, text in cp.labeled_lines:
        if label in goal_by_label:
            track_goals.append((goal_by_label[label], text))
        else:
            issues.warn(phase_id, f"checkpoint bold-label '{label}' matches no track")
    quiz = next(
        (m.id for m in sidecar.materials
         if m.kind == "quiz" and m.phase_num == md_phase.num), None,
    )
    return Checkpoint(prose=cp.prose, quiz=quiz, track_goals=tuple(track_goals))


def _build_course(doc: MdDoc, sidecar: Sidecar, issues: Issues) -> Course:
    sc = sidecar.course
    if doc.versions:
        rev, date, note = doc.versions[-1]
        version = Version(rev=rev, date=date, note=note or None)
        history = tuple(Version(rev=r, date=d, note=n or None)
                        for r, d, n in doc.versions[:-1])
    else:
        issues.warn(sc.id, "no version footer found; defaulting to rev 0")
        version, history = Version(rev="0", date="unknown"), ()
    return Course(
        id=sc.id, title=sc.title, mode=sc.mode, version=version,
        pacing=Pacing(hours_per_week=sc.hours_per_week, cadence=sc.cadence),
        docs=sc.docs, description=sc.description, profile_line=sc.profile_line,
        out_of_scope=sc.out_of_scope, capstone=sc.capstone,
        version_history=history, trigger_phrases=sc.trigger_phrases,
        storage_key=sc.storage_key,
        preamble=tuple(line for line in doc.preamble
                       if not line.startswith("# ")),
        resources_intro=sc.resources_intro,
        reading_order=sc.reading_order,
    )


def _build_materials(sidecar: Sidecar) -> tuple[Material, ...]:
    out = []
    for m in sidecar.materials:
        out.append(Material(
            id=m.id, kind=m.kind, title=m.title, path=m.path, unit=m.unit,
            phase=f"p{m.phase_num}" if m.phase_num is not None else None,
            track=m.track, also_units=m.also_units, grader=m.grader,
            blurb=m.blurb,
        ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(mf: Manifest, content_root: str, issues: Issues, *,
              course_root: str,
              coverage_ignore: tuple[str, ...] = ()) -> None:
    # Global id uniqueness across everything progress-bearing or referenceable.
    seen: dict[str, str] = {}
    def claim(id_: str, what: str) -> None:
        if id_ in seen:
            issues.error(id_, f"id used by both {seen[id_]} and {what}")
        seen[id_] = what
    for p in mf.phases:
        claim(p.id, "phase")
    for u in mf.units:
        claim(u.id, "unit")
        for s in u.steps:
            claim(s.id, "step")
    for m in mf.milestones:
        claim(m.id, "milestone")
    for t in mf.tracks:
        claim(t.id, "track")
        for s in t.stages:
            claim(s.id, "stage")
    for mat in mf.materials:
        claim(mat.id, "material")
    keys = [r.key for r in mf.resources]
    for k in set(keys):
        if keys.count(k) > 1:
            issues.error(k, "duplicate resource key")

    unit_ids = {u.id for u in mf.units}
    phase_ids = {p.id for p in mf.phases}
    track_ids = {t.id for t in mf.tracks}

    # Reference resolution.
    for u in mf.units:
        for dep in u.depends_on:
            if dep not in unit_ids and dep not in phase_ids:
                issues.error(f"unit {u.id}", f"depends_on '{dep}' does not resolve")
    if mf.course.capstone and mf.course.capstone not in unit_ids:
        issues.error("course", f"capstone '{mf.course.capstone}' is not a unit")
    for m in mf.milestones:
        for g in m.gate_for:
            if g not in unit_ids:
                issues.error(f"milestone {m.id}", f"gate_for '{g}' is not a unit")
    for mat in mf.materials:
        if mat.unit and mat.unit not in unit_ids:
            issues.error(f"material {mat.id}", f"unit '{mat.unit}' does not resolve")
        if mat.phase and mat.phase not in phase_ids:
            issues.error(f"material {mat.id}", f"phase '{mat.phase}' does not resolve")
        if mat.track and mat.track not in track_ids:
            issues.error(f"material {mat.id}", f"track '{mat.track}' does not resolve")
        for also in mat.also_units:
            if also not in unit_ids:
                issues.error(f"material {mat.id}", f"also_units '{also}' does not resolve")
        target = os.path.join(content_root, mat.path)
        if not os.path.exists(target):
            issues.error(f"material {mat.id}", f"path does not exist: {mat.path}")

    # Coverage: every file under interactive/ should be registered exactly once.
    registered = {os.path.normpath(m.path) for m in mf.materials}
    registered_dirs = {p for p in registered
                       if os.path.isdir(os.path.join(content_root, p))}
    interactive_root = os.path.join(content_root, "interactive")
    if os.path.isdir(interactive_root):
        for dirpath, dirnames, filenames in os.walk(interactive_root):
            rel_dir = os.path.relpath(dirpath, content_root)
            if any(rel_dir == d or rel_dir.startswith(d + os.sep)
                   for d in registered_dirs):
                dirnames.clear()          # an exercise dir registers as a whole
                continue
            if os.path.basename(rel_dir) == "figures":
                # A chapter's rendered figures live in a `figures/` directory
                # beside it (docs/chapter-pattern.md): assets of a registered
                # document, not materials, so coverage skips them.
                dirnames.clear()
                continue
            for fn in filenames:
                if fn.startswith("."):
                    continue
                rel = os.path.normpath(os.path.join(rel_dir, fn))
                if rel not in registered and rel not in {
                    os.path.normpath(p) for p in coverage_ignore
                }:
                    issues.warn("coverage", f"unregistered file: {rel}")

    # Content hygiene: bare URLs belong in resources, not prose (warn for now —
    # ml-ai has two dozen; ref-scheme links are the sanctioned path).
    for u in mf.units:
        for r in u.rows:
            urls = URL_RE.findall(r.content)
            if urls:
                issues.warn(f"unit {u.id} [{r.label}]",
                            f"{len(urls)} bare URL(s) in content: {urls[0]}…"
                            if len(urls) > 1 else
                            f"bare URL in content: {urls[0]}")
            if r.label == "Interactive":
                # The Interactive row is derived from material attachments
                # (spec rule 2); an authored one is duplication that will
                # drift. Renderers honor it while it exists, and skip
                # deriving their own for that unit.
                issues.warn(f"unit {u.id} [Interactive]",
                            "authored Interactive row; the row derives from "
                            "materials — move any prose into blurbs and "
                            "delete it")
                for path in INTERACTIVE_PATH_RE.findall(r.content):
                    norm = os.path.normpath(path)
                    if norm not in registered and not any(
                        norm.startswith(d + os.sep) or norm == d
                        for d in registered_dirs
                    ):
                        issues.warn(f"unit {u.id} [Interactive]",
                                    f"references unregistered path: {path}")

    # Reference links (refs.py): every res:/unit:/mat:/repo: target must
    # resolve — a dangling reference is the compile error a dead URL never
    # got to be. The walk over content-bearing fields lives in refs.py,
    # shared with the app's repo/ route.
    resource_keys = {r.key for r in mf.resources}
    material_ids = {m.id for m in mf.materials}
    for where, text in iter_content(mf):
        for scheme, target in find_refs(text or ""):
            if scheme == "res" and target not in resource_keys:
                issues.error(where, f"res:{target} names no resource")
            elif scheme == "unit" and target not in unit_ids:
                issues.error(where, f"unit:{target} names no unit")
            elif scheme == "mat" and target not in material_ids:
                issues.error(where, f"mat:{target} names no material")
            elif scheme == "repo":
                if os.path.normpath(target).startswith((os.pardir, os.sep)):
                    issues.error(where, f"repo:{target} escapes the repo")
                elif not os.path.exists(os.path.join(course_root, target)):
                    issues.error(where, f"repo:{target} does not exist")

    # Progress ids are the outward contract; they must be well-formed.
    pids = mf.progress_ids()
    if len(pids) != len(set(pids)):
        dupes = sorted({p for p in pids if pids.count(p) > 1})
        issues.error("progress", f"duplicate progress ids: {dupes}")
