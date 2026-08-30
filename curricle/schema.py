"""The course manifest data model.

This module is the contract. Every structure the compiler emits and every
structure a renderer or the progress service consumes is defined here, and
nowhere else. Decoding is strict: an unknown key raises, because a silently
ignored field is a schema disagreement waiting to ship.

Design rules carried over from the schema spec (learning/platform-manifest.md):
ids are forever (tombstones, never deletion); attachment is declared once on
the material; tags are computed, never stored; everything progress-bearing is
enumerable via ``Manifest.progress_ids()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

MANIFEST_VERSION = 1

COURSE_MODES = ("subject", "project", "research")
PROVENANCES = ("spine", "overlay", "fork", "bespoke")
MATERIAL_KINDS = (
    "lesson", "widget", "quiz", "trainer", "exercise", "companion", "question-bank",
)
GRADER_TYPES = (
    "unit-test", "property-test", "oracle", "drill", "annotation", "artifact", "external",
)
MILESTONE_KINDS = (
    "contact", "preregistration", "publication", "artifact", "side-quest", "external",
)
RESOURCE_FORMATS = ("TEXT", "CODE", "VIDEO", "PAPER", "TOOL", "DATA")
CONDITION_STATES = ("pending", "open", "closed")

# Core row labels get styled treatment in renderers; anything else passes
# through as an extension row (rule: fixed core, open extension).
CORE_ROW_LABELS = (
    "Build", "Read", "Concepts", "Exercise", "Milestone",
    "Key insight", "Interactive", "Caveat", "Goal",
)


class SchemaError(ValueError):
    """A manifest or sidecar document violated the contract."""


# ---------------------------------------------------------------------------
# Strict decoding helpers
# ---------------------------------------------------------------------------

def take(d: dict, key: str, ctx: str, *, required: bool = False, default: Any = None) -> Any:
    if key in d:
        return d.pop(key)
    if required:
        raise SchemaError(f"{ctx}: missing required key '{key}'")
    return default


def ensure_empty(d: dict, ctx: str) -> None:
    if d:
        raise SchemaError(f"{ctx}: unknown key(s) {sorted(d)!r}")


def expect_enum(value: str, allowed: tuple[str, ...], ctx: str) -> str:
    if value not in allowed:
        raise SchemaError(f"{ctx}: {value!r} not one of {allowed}")
    return value


# ---------------------------------------------------------------------------
# Leaf structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Version:
    rev: str
    date: str            # ISO date as string; markdown footers carry prose dates too
    note: str | None = None


@dataclass(frozen=True)
class Pacing:
    hours_per_week: tuple[int, int]
    cadence: str | None = None


@dataclass(frozen=True)
class Docs:
    readme: str | None = None
    resources_doc: str | None = None
    curriculum_doc: str | None = None
    review: str | None = None
    exploration: str | None = None


@dataclass(frozen=True)
class TriggerPhrase:
    say: str
    note: str | None = None


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    mode: str
    version: Version
    pacing: Pacing
    docs: Docs = field(default_factory=Docs)
    description: str | None = None       # one-paragraph front-door prose
    profile_line: str | None = None
    out_of_scope: tuple[str, ...] = ()
    capstone: str | None = None
    version_history: tuple[Version, ...] = ()
    trigger_phrases: tuple[TriggerPhrase, ...] = ()
    storage_key: str | None = None       # legacy localStorage key (tf-progress);
                                         # None derives "{id}-progress"
    preamble: tuple[str, ...] = ()       # curriculum.md prose before Phase 0,
                                         # one markdown paragraph per item
    resources_intro: str | None = None   # standfirst for the resources view
    reading_order: tuple[str, ...] = ()  # "suggested reading order" items

    def __post_init__(self) -> None:
        expect_enum(self.mode, COURSE_MODES, f"course {self.id}")

    @property
    def progress_storage_key(self) -> str:
        return self.storage_key or f"{self.id}-progress"

    @property
    def notes_storage_key(self) -> str:
        return self._sibling_key("curriculum-notes")

    @property
    def resources_storage_key(self) -> str:
        return self._sibling_key("resources")

    def _sibling_key(self, suffix: str) -> str:
        base = self.progress_storage_key
        if base.endswith("-progress"):
            return base[: -len("progress")] + suffix
        return f"{self.id}-{suffix}"


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    goal: str | None = None


@dataclass(frozen=True)
class Track:
    id: str
    name: str
    stages: tuple[Stage, ...]
    cadence: str | None = None
    # Curriculum row labels / checkpoint labels that belong to this track,
    # so the compiler can attribute "Greek track" rows and "Greek by now"
    # checkpoint lines without hard-coding a subject.
    row_labels: tuple[str, ...] = ()
    checkpoint_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resource:
    key: str
    title: str
    url: str                                  # primary link target
    formats: tuple[str, ...] = ()
    tier: int | None = None
    group: str | None = None                  # sub-heading within the tier
    cite: str | None = None                   # author · publisher · year line
    cost: str | None = None                   # the cost chip text ("paid ~$20")
    free: bool | None = None                  # a genuine no-cost path exists
    links: tuple[tuple[str, str], ...] = ()   # (label, url); first is primary
    why_this_one: str | None = None
    covers: str | None = None
    verified_at: str | None = None
    access_note: str | None = None

    def __post_init__(self) -> None:
        for f in self.formats:
            expect_enum(f, RESOURCE_FORMATS, f"resource {self.key} formats")

    @property
    def all_links(self) -> tuple[tuple[str, str], ...]:
        return self.links or (("Link", self.url),)


@dataclass(frozen=True)
class ResourceTier:
    num: int
    name: str
    role: str                                 # what belonging to this tier means
    compact: bool = False                     # dense rendering (tools/reference)


@dataclass(frozen=True)
class Row:
    label: str
    content: str                 # markdown, verbatim from the authoring source
    kind: str | None = None      # "key" marks the highlighted-callout treatment
    track: str | None = None     # scopes the row to a secondary track


@dataclass(frozen=True)
class Check:
    q: str
    ans: str


@dataclass(frozen=True)
class Step:
    id: str
    label: str


@dataclass(frozen=True)
class Condition:
    on: str
    state: str = "pending"

    def __post_init__(self) -> None:
        expect_enum(self.state, CONDITION_STATES, f"condition '{self.on}'")


@dataclass(frozen=True)
class Unit:
    id: str
    num: int
    phase: str
    title: str
    rows: tuple[Row, ...]
    gloss: str | None = None
    provenance: str = "bespoke"
    depends_on: tuple[str, ...] = ()
    load_bearing: bool | None = None
    skippable_note: str | None = None
    condition: Condition | None = None
    steps: tuple[Step, ...] = ()
    check: Check | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        expect_enum(self.provenance, PROVENANCES, f"unit {self.id}")


@dataclass(frozen=True)
class Milestone:
    id: str
    phase: str
    kind: str
    label: str
    detail: str | None = None
    after_unit: str | None = None
    hours_per_month: int | None = None
    gate_for: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        expect_enum(self.kind, MILESTONE_KINDS, f"milestone {self.id}")


@dataclass(frozen=True)
class Grader:
    type: str
    runner: str | None = None
    oracle: str | None = None
    command: str | None = None       # the literal "run this" line shown to learners

    def __post_init__(self) -> None:
        expect_enum(self.type, GRADER_TYPES, "grader")


@dataclass(frozen=True)
class Material:
    id: str
    kind: str
    title: str
    path: str                        # relative to the course content root
    unit: str | None = None          # owning unit — exactly one of unit/phase/track,
    phase: str | None = None         #   or none of them (course-level material)
    track: str | None = None
    also_units: tuple[str, ...] = ()
    grader: Grader | None = None
    blurb: str | None = None         # one- or two-sentence card description

    def __post_init__(self) -> None:
        expect_enum(self.kind, MATERIAL_KINDS, f"material {self.id}")
        owners = [o for o in (self.unit, self.phase, self.track) if o]
        if len(owners) > 1:
            raise SchemaError(f"material {self.id}: more than one owner {owners}")


@dataclass(frozen=True)
class Checkpoint:
    prose: str
    quiz: str | None = None                       # material id
    track_goals: tuple[tuple[str, str], ...] = () # (track id, goal text)


@dataclass(frozen=True)
class Phase:
    id: str
    num: int
    title: str
    goal: str
    entries: tuple[str, ...]         # unit and milestone ids, in order
    weeks: tuple[int, int | None] | None = None   # (23, None) = "Weeks 23+"
    checkpoint: Checkpoint | None = None


@dataclass(frozen=True)
class Tombstone:
    id: str
    at: str
    reason: str
    superseded_by: str | None = None


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Manifest:
    manifest_version: int
    course: Course
    tracks: tuple[Track, ...]
    resources: tuple[Resource, ...]
    resource_tiers: tuple[ResourceTier, ...]
    phases: tuple[Phase, ...]
    units: tuple[Unit, ...]
    milestones: tuple[Milestone, ...]
    materials: tuple[Material, ...]
    retired: tuple[Tombstone, ...] = ()

    # -- lookups ------------------------------------------------------------

    def unit(self, unit_id: str) -> Unit:
        for u in self.units:
            if u.id == unit_id:
                return u
        raise KeyError(unit_id)

    def materials_for_unit(self, unit_id: str) -> tuple[Material, ...]:
        return tuple(
            m for m in self.materials
            if m.unit == unit_id or unit_id in m.also_units
        )

    # -- derived data (rule: computed, never stored) ------------------------

    def progress_ids(self) -> tuple[str, ...]:
        """Every id a progress event may reference, in course order.

        A stepped unit contributes its steps, not itself: the unit's own
        state is a rollup. Milestones and track stages are progress-bearing;
        quizzes are events with payloads, not checkboxes, so materials are
        deliberately absent here.
        """
        ids: list[str] = []
        milestones_by_phase: dict[str, list[Milestone]] = {}
        for m in self.milestones:
            milestones_by_phase.setdefault(m.phase, []).append(m)
        units_by_id = {u.id: u for u in self.units}
        for phase in self.phases:
            for entry in phase.entries:
                if entry in units_by_id:
                    u = units_by_id[entry]
                    if u.steps:
                        ids.extend(s.id for s in u.steps)
                    else:
                        ids.append(u.id)
                else:
                    ids.append(entry)   # milestone
        for track in self.tracks:
            ids.extend(s.id for s in track.stages)
        return tuple(ids)

    def tags_for_unit(self, unit_id: str) -> tuple[str, ...]:
        """The hub chip set — derived from attachments, never authored.

        A phase's checkpoint quiz contributes a "quiz" chip to the phase's
        last unit (the hub's hand-typed convention, now computed).
        """
        tags: list[str] = []
        for m in self.materials_for_unit(unit_id):
            if m.kind == "lesson" and "lesson" not in tags:
                tags.append("lesson")
            elif m.kind in ("widget", "trainer") and "widget" not in tags:
                tags.append("widget")
            elif m.kind in ("quiz",) and "quiz" not in tags:
                tags.append("quiz")
            elif m.kind == "exercise" and m.grader and m.grader.type in (
                "unit-test", "property-test", "oracle",
            ) and "tests" not in tags:
                tags.append("tests")
        if "quiz" not in tags:
            phase_quizzes = {m.phase for m in self.materials
                             if m.kind == "quiz" and m.phase}
            for phase in self.phases:
                unit_entries = [e for e in phase.entries
                                if any(u.id == e for u in self.units)]
                if (unit_entries and unit_entries[-1] == unit_id
                        and phase.id in phase_quizzes):
                    tags.append("quiz")
        return tuple(tags)

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        return _strip(asdict(self))


def _strip(value: Any) -> Any:
    """Drop empty-optional noise so the emitted YAML reads like the spec."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items()
                if v is not None and v != () and v != []}
    if isinstance(value, (list, tuple)):
        return [_strip(v) for v in value]
    return value
