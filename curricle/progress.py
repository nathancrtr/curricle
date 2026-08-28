"""The progress engine: append-only events, a pure fold, derived state.

House pattern (job-radar's eventlog, adopted by design): state is an event
ledger folded by a pure function; anything stored beside it is a projection,
and a disagreement is a bug in the projection, never the fold. Events are
ordered by row id — sequence, not clock.

Validation happens at append: an event naming a subject the manifest does
not know is refused. The manifest is the contract; the ledger only ever
holds ids a course actually defines (retired ids stay valid through
tombstones — ids are forever).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa

from . import db
from .schema import Manifest


class InvalidEvent(ValueError):
    pass


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _known_subjects(manifest: Manifest) -> dict[str, frozenset[str]]:
    progress_ids = frozenset(manifest.progress_ids())
    retired = frozenset(t.id for t in manifest.retired)
    unit_ids = frozenset(u.id for u in manifest.units)
    return {
        "mark": progress_ids | retired,
        "note": unit_ids | retired,
        "resource_mark": frozenset(r.key for r in manifest.resources),
        "resource_note": frozenset(r.key for r in manifest.resources),
        "checkpoint_result": frozenset(
            m.id for m in manifest.materials if m.kind in ("quiz", "trainer")),
        "session_note": unit_ids | frozenset({""}),
    }


_PAYLOAD_RULES = {
    "mark": ("done", bool),
    "note": ("text", str),
    "resource_mark": ("inhand", bool),
    "resource_note": ("text", str),
    "session_note": ("text", str),
}


def validate_event(manifest: Manifest, kind: str, subject_id: str,
                   payload: dict) -> None:
    if kind not in db.EVENT_KINDS:
        raise InvalidEvent(f"unknown kind {kind!r}")
    subjects = _known_subjects(manifest)[kind]
    if subject_id not in subjects:
        raise InvalidEvent(
            f"{kind}: subject {subject_id!r} is not defined by course "
            f"{manifest.course.id!r}")
    if not isinstance(payload, dict):
        raise InvalidEvent("payload must be an object")
    rule = _PAYLOAD_RULES.get(kind)
    if rule:
        key, typ = rule
        if key not in payload or not isinstance(payload[key], typ):
            raise InvalidEvent(f"{kind}: payload needs {key!r} ({typ.__name__})")
    if kind == "checkpoint_result":
        for key in ("score", "total"):
            if not isinstance(payload.get(key), int):
                raise InvalidEvent(f"checkpoint_result: payload needs int {key!r}")


def append_event(conn: sa.Connection, scope: db.TenantScope, manifest: Manifest,
                 kind: str, subject_id: str, payload: dict) -> None:
    validate_event(manifest, kind, subject_id, payload)
    conn.execute(scope.events_insert(
        course=manifest.course.id, kind=kind,
        subject_id=subject_id, payload=payload))


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------

@dataclass
class ProgressState:
    done: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    res_inhand: dict[str, bool] = field(default_factory=dict)
    res_notes: dict[str, str] = field(default_factory=dict)
    checkpoint_results: list[dict] = field(default_factory=list)
    session_notes: list[dict] = field(default_factory=list)


def fold(events) -> ProgressState:
    """events: iterable of (kind, subject_id, payload), in ledger order."""
    st = ProgressState()
    for kind, subject_id, payload in events:
        if kind == "mark":
            st.done[subject_id] = bool(payload.get("done"))
        elif kind == "note":
            text = payload.get("text", "")
            if text:
                st.notes[subject_id] = text
            else:
                st.notes.pop(subject_id, None)
        elif kind == "resource_mark":
            st.res_inhand[subject_id] = bool(payload.get("inhand"))
        elif kind == "resource_note":
            text = payload.get("text", "")
            if text:
                st.res_notes[subject_id] = text
            else:
                st.res_notes.pop(subject_id, None)
        elif kind == "checkpoint_result":
            st.checkpoint_results.append({"material": subject_id, **payload})
        elif kind == "session_note":
            st.session_notes.append({"subject": subject_id, **payload})
    return st


def load_state(conn: sa.Connection, scope: db.TenantScope,
               course_id: str) -> ProgressState:
    rows = conn.execute(scope.events_select(course_id))
    return fold((r.kind, r.subject_id, r.payload) for r in rows)


# ---------------------------------------------------------------------------
# Derived views (computed, never stored)
# ---------------------------------------------------------------------------

def summarize(manifest: Manifest, state: ProgressState) -> dict:
    stage_ids = {s.id for t in manifest.tracks for s in t.stages}
    program_ids = [p for p in manifest.progress_ids() if p not in stage_ids]
    done = sum(1 for p in program_ids if state.done.get(p))
    next_up = next((p for p in program_ids if not state.done.get(p)), None)
    return {
        "program_done": done,
        "program_total": len(program_ids),
        "next_up": next_up,
        "tracks": {
            t.id: sum(1 for s in t.stages if state.done.get(s.id))
            for t in manifest.tracks
        },
    }


def client_state(state: ProgressState) -> dict:
    """The shape the rendered pages consume — mirrors the localStorage keys'
    value shapes exactly, so the same page JS works over either store."""
    return {
        "progress": state.done,
        "curriculum_notes": state.notes,
        "resources": {"inhand": state.res_inhand, "notes": state.res_notes},
    }
