"""Load and strictly validate a course sidecar (course.yaml).

The sidecar carries what curriculum.md legitimately doesn't: ids, glosses,
steps, the material registry, track ladders, milestones, resource keys.
Prose never lives here — if a field starts wanting paragraphs, it belongs
in the markdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .schema import (
    Condition, Docs, Grader, Resource, SchemaError,
    Stage, Step, Track, TriggerPhrase, ensure_empty, take,
)

SIDECAR_VERSION = 1


@dataclass(frozen=True)
class SidecarCourse:
    id: str
    title: str
    mode: str
    hours_per_week: tuple[int, int]
    cadence: str | None = None
    description: str | None = None
    profile_line: str | None = None
    docs: Docs = field(default_factory=Docs)
    out_of_scope: tuple[str, ...] = ()
    capstone: str | None = None
    coverage_ignore: tuple[str, ...] = ()   # interactive/ paths that are support
                                            # files, not materials (generators…)
    trigger_phrases: tuple[TriggerPhrase, ...] = ()
    storage_key: str | None = None


@dataclass(frozen=True)
class SidecarUnit:
    id: str
    num: int
    gloss: str | None = None
    phase_body: bool = False
    provenance: str = "bespoke"
    steps: tuple[Step, ...] = ()
    depends_on: tuple[str, ...] = ()
    load_bearing: bool | None = None
    skippable_note: str | None = None
    condition: Condition | None = None
    note: str | None = None


@dataclass(frozen=True)
class SidecarMilestone:
    id: str
    phase_num: int
    kind: str
    label: str
    detail: str | None = None
    after_unit: str | None = None
    hours_per_month: int | None = None
    gate_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class SidecarMaterial:
    id: str
    kind: str
    title: str
    path: str
    unit: str | None = None
    phase_num: int | None = None
    track: str | None = None
    also_units: tuple[str, ...] = ()
    grader: Grader | None = None
    blurb: str | None = None


@dataclass(frozen=True)
class Sidecar:
    course: SidecarCourse
    tracks: tuple[Track, ...] = ()
    resources: tuple[Resource, ...] = ()
    units: tuple[SidecarUnit, ...] = ()
    milestones: tuple[SidecarMilestone, ...] = ()
    materials: tuple[SidecarMaterial, ...] = ()

    def unit_by_num(self, num: int) -> SidecarUnit | None:
        for u in self.units:
            if u.num == num:
                return u
        return None


def load_sidecar(path: str) -> Sidecar:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: sidecar must be a mapping")
    version = take(data, "sidecar_version", path, required=True)
    if version != SIDECAR_VERSION:
        raise SchemaError(f"{path}: sidecar_version {version} != {SIDECAR_VERSION}")

    course = _course(take(data, "course", path, required=True), f"{path}:course")
    tracks = tuple(
        _track(t, f"{path}:tracks[{i}]")
        for i, t in enumerate(take(data, "tracks", path, default=[]) or [])
    )
    resources = tuple(
        _resource(r, f"{path}:resources[{i}]")
        for i, r in enumerate(take(data, "resources", path, default=[]) or [])
    )
    units = tuple(
        _unit(u, f"{path}:units[{i}]")
        for i, u in enumerate(take(data, "units", path, default=[]) or [])
    )
    milestones = tuple(
        _milestone(m, f"{path}:milestones[{i}]")
        for i, m in enumerate(take(data, "milestones", path, default=[]) or [])
    )
    materials = tuple(
        _material(m, f"{path}:materials[{i}]")
        for i, m in enumerate(take(data, "materials", path, default=[]) or [])
    )
    ensure_empty(data, path)
    return Sidecar(course=course, tracks=tracks, resources=resources,
                   units=units, milestones=milestones, materials=materials)


def _course(d: dict, ctx: str) -> SidecarCourse:
    hpw = take(d, "hours_per_week", ctx, required=True)
    docs_d = take(d, "docs", ctx, default={}) or {}
    docs = Docs(
        readme=take(docs_d, "readme", ctx),
        resources_doc=take(docs_d, "resources_doc", ctx),
        curriculum_doc=take(docs_d, "curriculum_doc", ctx),
        review=take(docs_d, "review", ctx),
        exploration=take(docs_d, "exploration", ctx),
    )
    ensure_empty(docs_d, f"{ctx}.docs")
    course = SidecarCourse(
        id=take(d, "id", ctx, required=True),
        title=take(d, "title", ctx, required=True),
        mode=take(d, "mode", ctx, required=True),
        hours_per_week=(int(hpw[0]), int(hpw[1])),
        cadence=take(d, "cadence", ctx),
        profile_line=take(d, "profile_line", ctx),
        docs=docs,
        out_of_scope=tuple(take(d, "out_of_scope", ctx, default=[]) or []),
        capstone=take(d, "capstone", ctx),
        coverage_ignore=tuple(take(d, "coverage_ignore", ctx, default=[]) or []),
        description=take(d, "description", ctx),
        trigger_phrases=tuple(
            TriggerPhrase(say=take(t, "say", ctx, required=True),
                          note=take(t, "note", ctx))
            for t in take(d, "trigger_phrases", ctx, default=[]) or []
        ),
        storage_key=take(d, "storage_key", ctx),
    )
    ensure_empty(d, ctx)
    return course


def _track(d: dict, ctx: str) -> Track:
    stages = tuple(
        Stage(id=take(s, "id", ctx, required=True),
              label=take(s, "label", ctx, required=True),
              goal=take(s, "goal", ctx))
        for s in take(d, "stages", ctx, required=True)
    )
    track = Track(
        id=take(d, "id", ctx, required=True),
        name=take(d, "name", ctx, required=True),
        stages=stages,
        cadence=take(d, "cadence", ctx),
        row_labels=tuple(take(d, "row_labels", ctx, default=[]) or []),
        checkpoint_labels=tuple(take(d, "checkpoint_labels", ctx, default=[]) or []),
    )
    ensure_empty(d, ctx)
    return track


def _resource(d: dict, ctx: str) -> Resource:
    res = Resource(
        key=take(d, "key", ctx, required=True),
        title=take(d, "title", ctx, required=True),
        url=take(d, "url", ctx, required=True),
        formats=tuple(take(d, "formats", ctx, default=[]) or []),
        tier=take(d, "tier", ctx),
        cost=take(d, "cost", ctx),
        why_this_one=take(d, "why_this_one", ctx),
        covers=take(d, "covers", ctx),
        verified_at=str(take(d, "verified_at", ctx) or "") or None,
        access_note=take(d, "access_note", ctx),
    )
    ensure_empty(d, ctx)
    return res


def _unit(d: dict, ctx: str) -> SidecarUnit:
    cond_d = take(d, "condition", ctx)
    condition = None
    if cond_d:
        if True in cond_d:  # YAML 1.1 reads a bare `on:` key as boolean True
            cond_d["on"] = cond_d.pop(True)
        condition = Condition(
            on=take(cond_d, "on", ctx, required=True),
            state=take(cond_d, "state", ctx, default="pending"),
        )
        ensure_empty(cond_d, f"{ctx}.condition")
    steps = tuple(
        Step(id=take(s, "id", ctx, required=True),
             label=take(s, "label", ctx, required=True))
        for s in take(d, "steps", ctx, default=[]) or []
    )
    unit = SidecarUnit(
        id=take(d, "id", ctx, required=True),
        num=int(take(d, "num", ctx, required=True)),
        gloss=take(d, "gloss", ctx),
        phase_body=bool(take(d, "phase_body", ctx, default=False)),
        provenance=take(d, "provenance", ctx, default="bespoke"),
        steps=steps,
        depends_on=tuple(take(d, "depends_on", ctx, default=[]) or []),
        load_bearing=take(d, "load_bearing", ctx),
        skippable_note=take(d, "skippable_note", ctx),
        condition=condition,
        note=take(d, "note", ctx),
    )
    ensure_empty(d, ctx)
    return unit


def _milestone(d: dict, ctx: str) -> SidecarMilestone:
    ms = SidecarMilestone(
        id=take(d, "id", ctx, required=True),
        phase_num=int(take(d, "phase_num", ctx, required=True)),
        kind=take(d, "kind", ctx, required=True),
        label=take(d, "label", ctx, required=True),
        detail=take(d, "detail", ctx),
        after_unit=take(d, "after_unit", ctx),
        hours_per_month=take(d, "hours_per_month", ctx),
        gate_for=tuple(take(d, "gate_for", ctx, default=[]) or []),
    )
    ensure_empty(d, ctx)
    return ms


def _material(d: dict, ctx: str) -> SidecarMaterial:
    grader_d = take(d, "grader", ctx)
    grader = None
    if grader_d:
        grader = Grader(
            type=take(grader_d, "type", ctx, required=True),
            runner=take(grader_d, "runner", ctx),
            oracle=take(grader_d, "oracle", ctx),
            command=take(grader_d, "command", ctx),
        )
        ensure_empty(grader_d, f"{ctx}.grader")
    mat = SidecarMaterial(
        id=take(d, "id", ctx, required=True),
        kind=take(d, "kind", ctx, required=True),
        title=take(d, "title", ctx, required=True),
        path=take(d, "path", ctx, required=True),
        unit=take(d, "unit", ctx),
        phase_num=take(d, "phase_num", ctx),
        track=take(d, "track", ctx),
        also_units=tuple(take(d, "also_units", ctx, default=[]) or []),
        grader=grader,
        blurb=take(d, "blurb", ctx),
    )
    ensure_empty(d, ctx)
    return mat
