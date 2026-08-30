"""The tutor export: an MCP server over manifest + profile + progress.

Phase 4 (platform-design.md §6.4). The trigger-phrase protocol every course
README carries — "Teach me Unit N interactively", "Quiz me on Phase N" —
becomes a tool surface the learner's own assistant calls: read tools that
serve context (the course, the profile projection, progress, lesson guides,
the question bank) and write tools that accept evidence (progress events;
profile *proposals*, which render nowhere until /profile accepts them).

The invariants hold by construction, not policy:

- **L1** — this module serves context and accepts evidence; it never
  imports the model runner and cannot reach a model (the guard test greps
  this file for the runner module's name). **L3** — everything
  conversational happens on the learner's assistant, against exported
  context: their inference bill, not ours.
- **T1** — the tenant is an explicit CLI argument resolved to a real row at
  startup; an unknown slug is a refusal, not a default.
- **The agent proposes, the human publishes** — the one profile write tool
  emits ``propose`` events that wait on /profile, and a wire proposal must
  name its source. ``demonstrated`` evidence is not proposable over the
  wire at all: that tier means course activity proved it, and the course
  activity path (``checkpoint_result``) already proposes it itself.

Transport: MCP's stdio transport — newline-delimited JSON-RPC 2.0 on
stdin/stdout, stdlib only, matching this layer's no-new-dependency rule.
Auth is process ownership: the server runs on the learner's own machine
against their own database, the same posture as ``serve`` (real identity
arrives with multi-tenancy, Phase 5).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Callable

import sqlalchemy as sa

from . import db, profile, progress
from .profilerender import render_skill_md
from .refs import resolve_markdown
from .schema import Manifest, Material, Phase, Unit
from .webapp import CourseHandle, load_course

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "curricle-tutor", "version": "1"}


class ToolError(ValueError):
    """A tool call that cannot be honored — reported to the caller as an
    isError result with enough text to self-correct, never a crash."""


# ---------------------------------------------------------------------------
# Context assembly (pure functions over manifest + state)
# ---------------------------------------------------------------------------

def _phase_of(mf: Manifest, unit_id: str) -> Phase | None:
    return next((p for p in mf.phases if unit_id in p.entries), None)


def _material_line(m: Material) -> str:
    grader = ""
    if m.grader:
        grader = f" · grader: {m.grader.type}"
        if m.grader.command:
            grader += f" · run: `{m.grader.command}`"
    blurb = f" — {m.blurb}" if m.blurb else ""
    return f"- **{m.title}** ({m.kind}, id `{m.id}`, `{m.path}`){grader}{blurb}"


def course_overview(mf: Manifest, state: progress.ProgressState) -> str:
    c = mf.course
    lines = [f"# {c.title} (`{c.id}`)", ""]
    if c.description:
        lines += [c.description, ""]
    lines.append(f"Mode: {c.mode} · pacing: "
                 f"{c.pacing.hours_per_week[0]}–{c.pacing.hours_per_week[1]} h/wk")
    units_by_id = {u.id: u for u in mf.units}
    milestones_by_id = {m.id: m for m in mf.milestones}
    for p in mf.phases:
        lines += ["", f"## Phase {p.num} — {p.title}",
                  f"Goal: {resolve_markdown(p.goal, mf)}"]
        for entry in p.entries:
            if entry in units_by_id:
                u = units_by_id[entry]
                mark = "x" if state.done.get(u.id) or (
                    u.steps and all(state.done.get(s.id) for s in u.steps)
                ) else " "
                gloss = f" — {resolve_markdown(u.gloss, mf)}" if u.gloss else ""
                lines.append(f"- [{mark}] Unit {u.num} (`{u.id}`): {u.title}{gloss}")
            else:
                ms = milestones_by_id[entry]
                mark = "x" if state.done.get(ms.id) else " "
                lines.append(f"- [{mark}] Milestone (`{ms.id}`): {ms.label}")
        if p.checkpoint:
            lines.append(f"- Checkpoint: {resolve_markdown(p.checkpoint.prose, mf)}")
    for t in mf.tracks:
        lines += ["", f"## Track: {t.name} (`{t.id}`)"]
        for s in t.stages:
            mark = "x" if state.done.get(s.id) else " "
            lines.append(f"- [{mark}] `{s.id}`: {s.label}")
    return "\n".join(lines)


def unit_context(mf: Manifest, u: Unit, state: progress.ProgressState) -> str:
    phase = _phase_of(mf, u.id)
    lines = [f"# Unit {u.num} — {u.title} (`{u.id}`)"]
    if u.gloss:
        lines.append(resolve_markdown(u.gloss, mf))
    if phase:
        lines.append(f"\nPhase {phase.num} — {phase.title}: "
                     f"{resolve_markdown(phase.goal, mf)}")
    lines.append("")
    for r in u.rows:
        lines.append(f"**{r.label}:** {resolve_markdown(r.content, mf)}")
    if u.note:
        lines.append(f"\n*Note:* {resolve_markdown(u.note, mf)}")
    if u.check:
        lines.append(f"\n**Check yourself:** {u.check.q}\n"
                     f"*(answer, for the tutor only:)* {u.check.ans}")
    if u.steps:
        lines.append("\nSteps (each is its own progress mark):")
        for s in u.steps:
            mark = "x" if state.done.get(s.id) else " "
            lines.append(f"- [{mark}] `{s.id}`: {s.label}")
    else:
        lines.append(f"\nMarked done: {'yes' if state.done.get(u.id) else 'no'}")
    mats = mf.materials_for_unit(u.id)
    if mats:
        lines.append("\nMaterials:")
        lines += [_material_line(m) for m in mats]
    if state.notes.get(u.id):
        lines.append(f"\nLearner's own note on this unit:\n> {state.notes[u.id]}")
    return "\n".join(lines)


TEACH_PREAMBLE = """\
You are running a Socratic lesson from this course. The contract, from the
course's own house rules: one question per turn; let the learner answer
before you continue; at a **PAUSE** in the guide, stop and wait — the reveal
comes after their attempt, never before. Formalize last: names and notation
arrive after the idea is theirs. Calibrate with the learner profile below —
do not scaffold what it marks known; build from zero what it marks unknown.

When the unit is done, offer to record it: call `record_progress_event`
with kind "mark" and the unit id (or each step id), payload {"done": true}.
If the conversation surfaced something durable about the learner, propose
it with `propose_profile_evidence` — it waits for their review; nothing is
published without them.
"""

# Kept .format-free — the payload example carries literal braces, the same
# trap theme.WAYPATH_JS documents; the scope note is spliced by .replace.
QUIZ_PREAMBLE = """\
Quiz the learner from the question bank below<SCOPE>. House rules: draw a
mix of recall / application / explain-why items; one question per turn;
a wrong answer is taught, not just marked — the distractors target named
misconceptions, so diagnose from the specific wrong choice. Keep score.

When the quiz ends, record it: call `record_progress_event` with kind
"checkpoint_result", subject_id one of the quiz material ids listed below,
and payload {"score": <int>, "total": <int>, "misses": [<short strings>]}.
The misses matter as much as the score — they become proposed profile
evidence the learner reviews. If no quiz material exists for this scope,
say so and record nothing.
"""

REVIEW_PREAMBLE = """\
Review the learner's work against this exercise brief. The test bar is the
grader — have them run the command below and read failures together; review
for the brief's actual intent, not style preferences. When it is green and
understood, offer to mark the owning unit done via `record_progress_event`.
"""


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------

@dataclass
class TutorServer:
    courses: dict[str, CourseHandle]
    engine: sa.Engine
    scope: db.TenantScope
    tenant: str

    # -- plumbing -----------------------------------------------------------

    def _course(self, args: dict) -> CourseHandle:
        slug = args.get("course")
        if slug:
            if slug not in self.courses:
                raise ToolError(f"unknown course {slug!r}; loaded: "
                                f"{sorted(self.courses)}")
            return self.courses[slug]
        if len(self.courses) == 1:
            return next(iter(self.courses.values()))
        raise ToolError("several courses are loaded; pass course= one of "
                        f"{sorted(self.courses)}")

    def _state(self, h: CourseHandle) -> progress.ProgressState:
        with self.engine.begin() as conn:
            return progress.load_state(conn, self.scope, h.manifest.course.id)

    def _unit(self, h: CourseHandle, unit_arg) -> Unit:
        mf = h.manifest
        unit_id = str(unit_arg)
        for u in mf.units:
            if u.id == unit_id or (unit_id.isdigit() and u.num == int(unit_id)):
                return u
        raise ToolError(f"no unit {unit_arg!r} in {mf.course.id}; units: "
                        + ", ".join(f"{u.id} (Unit {u.num})" for u in mf.units))

    def _read_material(self, h: CourseHandle, m: Material) -> str:
        path = m.path
        if m.kind == "exercise":
            path = os.path.join(path, "task.md")
        with open(os.path.join(h.content_root, path), encoding="utf-8") as f:
            return f.read()

    # -- read tools ---------------------------------------------------------

    def get_course(self, args: dict) -> str:
        h = self._course(args)
        return course_overview(h.manifest, self._state(h))

    def get_profile(self, args: dict) -> str:
        with self.engine.begin() as conn:
            state = profile.load_profile(conn, self.scope)
        return render_skill_md(state)

    def get_progress(self, args: dict) -> str:
        h = self._course(args)
        state = self._state(h)
        s = progress.summarize(h.manifest, state)
        lines = [f"{h.manifest.course.title}: {s['program_done']} of "
                 f"{s['program_total']} done · next up: {s['next_up'] or '—'}"]
        for t in h.manifest.tracks:
            lines.append(f"Track {t.name}: {s['tracks'][t.id]} of "
                         f"{len(t.stages)} stages")
        if state.checkpoint_results:
            lines.append("\nCheckpoint results, oldest first:")
            for r in state.checkpoint_results:
                lines.append(f"- {r['material']}: {r.get('score')}/{r.get('total')}"
                             + (f" · missed: {r['misses']}" if r.get("misses") else ""))
        return "\n".join(lines)

    def get_lesson_guide(self, args: dict) -> str:
        h = self._course(args)
        u = self._unit(h, args.get("unit"))
        lessons = [m for m in h.manifest.materials_for_unit(u.id)
                   if m.kind in ("lesson", "companion")]
        if not lessons:
            have = sorted(m.unit for m in h.manifest.materials
                          if m.kind == "lesson" and m.unit)
            raise ToolError(f"unit {u.id} has no lesson guide; units with "
                            f"guides: {have}. Improvise from get_course + "
                            "the unit's Concepts row instead.")
        return "\n\n---\n\n".join(self._read_material(h, m) for m in lessons)

    def get_question_bank(self, args: dict) -> str:
        h = self._course(args)
        banks = [m for m in h.manifest.materials if m.kind == "question-bank"]
        if not banks:
            raise ToolError(f"{h.manifest.course.id} has no question bank")
        return "\n\n---\n\n".join(self._read_material(h, m) for m in banks)

    # -- the trigger-phrase protocol, as tools ------------------------------

    def whats_next(self, args: dict) -> str:
        h = self._course(args)
        mf = h.manifest
        state = self._state(h)
        s = progress.summarize(mf, state)
        nxt = s["next_up"]
        if nxt is None:
            return (f"{mf.course.title}: every step is walked "
                    f"({s['program_done']}/{s['program_total']}).")
        step_owner = next((u for u in mf.units
                           if any(st.id == nxt for st in u.steps)), None)
        unit = step_owner or next((u for u in mf.units if u.id == nxt), None)
        if unit is None:      # a milestone entry
            ms = next(m for m in mf.milestones if m.id == nxt)
            return (f"Next up: milestone `{ms.id}` — {ms.label}"
                    + (f"\n{ms.detail}" if ms.detail else ""))
        head = f"Next up: `{nxt}`"
        if step_owner:
            step = next(st for st in step_owner.steps if st.id == nxt)
            head += f" — step “{step.label}” of Unit {unit.num}"
        return head + "\n\n" + unit_context(mf, unit, state)

    def teach_unit(self, args: dict) -> str:
        h = self._course(args)
        u = self._unit(h, args.get("unit"))
        mf = h.manifest
        parts = [TEACH_PREAMBLE, unit_context(mf, u, self._state(h))]
        lessons = [m for m in mf.materials_for_unit(u.id)
                   if m.kind in ("lesson", "companion")]
        if lessons:
            for m in lessons:
                parts.append(f"## Lesson guide: {m.title}\n\n"
                             + self._read_material(h, m))
        else:
            parts.append("*(No written guide for this unit — improvise the "
                         "dialogue from the Concepts and Build rows above, "
                         "same contract.)*")
        with self.engine.begin() as conn:
            pstate = profile.load_profile(conn, self.scope)
        parts.append("## The learner\n\n" + render_skill_md(pstate))
        return "\n\n".join(parts)

    def quiz_me(self, args: dict) -> str:
        h = self._course(args)
        mf = h.manifest
        phase = args.get("phase")
        scope_note = f" (scope: Phase {phase})" if phase is not None else ""
        quizzes = [m for m in mf.materials if m.kind == "quiz"
                   and (phase is None or m.phase == f"p{phase}")]
        quiz_ids = ("Quiz material ids for recording: "
                    + (", ".join(f"`{m.id}`" for m in quizzes) if quizzes
                       else "(none for this scope — do not record)"))
        return "\n\n".join([QUIZ_PREAMBLE.replace("<SCOPE>", scope_note),
                            quiz_ids, self.get_question_bank(args)])

    def review_exercise(self, args: dict) -> str:
        h = self._course(args)
        u = self._unit(h, args.get("unit"))
        exercises = [m for m in h.manifest.materials_for_unit(u.id)
                     if m.kind == "exercise"]
        if not exercises:
            raise ToolError(f"unit {u.id} has no exercise material")
        parts = [REVIEW_PREAMBLE]
        for m in exercises:
            parts.append(_material_line(m) + "\n\n" + self._read_material(h, m))
        return "\n\n".join(parts)

    # -- write tools --------------------------------------------------------

    def record_progress_event(self, args: dict) -> str:
        h = self._course(args)
        kind = args.get("kind")
        subject_id = args.get("subject_id")
        payload = args.get("payload", {})
        if not isinstance(kind, str) or not isinstance(subject_id, str):
            raise ToolError("kind and subject_id are required strings")
        try:
            with self.engine.begin() as conn:
                progress.append_event(conn, self.scope, h.manifest,
                                      kind, subject_id, payload)
                if kind == "checkpoint_result":
                    profile.propose_from_checkpoint(conn, self.scope,
                                                    h.manifest, subject_id,
                                                    payload)
                state = progress.load_state(conn, self.scope,
                                            h.manifest.course.id)
        except progress.InvalidEvent as exc:
            raise ToolError(str(exc))
        s = progress.summarize(h.manifest, state)
        out = (f"Recorded. {s['program_done']}/{s['program_total']} done · "
               f"next up: {s['next_up'] or '—'}")
        if kind == "checkpoint_result":
            out += ("\nThe result was also proposed as profile evidence — "
                    "the learner reviews it on /profile.")
        return out

    def propose_profile_evidence(self, args: dict) -> str:
        field = args.get("field")
        key = args.get("key")
        text = args.get("text")
        source = args.get("source")
        tier = args.get("tier", "attested")
        if not (isinstance(field, str) and isinstance(key, str)):
            raise ToolError("field and key are required strings")
        if not (isinstance(source, str) and source.strip()):
            raise ToolError("a wire proposal must name its source")
        if tier == "demonstrated":
            raise ToolError(
                "'demonstrated' means course activity proved it; that tier "
                "arrives only through checkpoint_result events, not wire "
                "proposals. Use 'attested' (the learner said it) or 'thin'.")
        try:
            with self.engine.begin() as conn:
                profile.append_profile_event(
                    conn, self.scope, "propose", field, key,
                    payload={"text": text, "tier": tier, "source": source})
        except profile.InvalidProfileEvent as exc:
            raise ToolError(str(exc))
        return (f"Proposed ({field}/{key}, tier {tier}). It renders nowhere "
                "until the learner accepts it on /profile.")


# ---------------------------------------------------------------------------
# Tool declarations (name → description + schema + bound method)
# ---------------------------------------------------------------------------

def _course_prop() -> dict:
    return {"type": "string",
            "description": "Course slug; omit when only one course is loaded."}


def tool_table(server: TutorServer) -> list[
        tuple[str, str, dict, Callable[[dict], str]]]:
    unit_prop = {"type": "string",
                 "description": "Unit id (e.g. 'u8') or bare number."}
    return [
        ("get_course",
         "The course at a glance: phases, units with done-state, tracks, "
         "checkpoints. Ids in backticks are the ids other tools take.",
         {"type": "object", "properties": {"course": _course_prop()}},
         server.get_course),
        ("get_profile",
         "The learner profile — a fold over their evidence ledger, rendered. "
         "Calibrate everything against it: skip what it marks known, "
         "scaffold what it marks unknown.",
         {"type": "object", "properties": {}},
         server.get_profile),
        ("get_progress",
         "Where the learner is: done counts, next_up, track ladders, past "
         "checkpoint results with misses.",
         {"type": "object", "properties": {"course": _course_prop()}},
         server.get_progress),
        ("get_lesson_guide",
         "The unit's Socratic lesson guide (plus companions), verbatim.",
         {"type": "object",
          "properties": {"course": _course_prop(), "unit": unit_prop},
          "required": ["unit"]},
         server.get_lesson_guide),
        ("get_question_bank",
         "The course question bank, verbatim (items tagged recall / "
         "application / explain-why).",
         {"type": "object", "properties": {"course": _course_prop()}},
         server.get_question_bank),
        ("whats_next",
         "The resuming tool: the first unfinished step, with its unit's "
         "full context.",
         {"type": "object", "properties": {"course": _course_prop()}},
         server.whats_next),
        ("teach_unit",
         "Everything needed to run one unit as a Socratic dialogue: the "
         "contract, the unit's syllabus and materials, the lesson guide, "
         "the learner profile. Equivalent of saying 'Teach me Unit N "
         "interactively' in the course repo.",
         {"type": "object",
          "properties": {"course": _course_prop(), "unit": unit_prop},
          "required": ["unit"]},
         server.teach_unit),
        ("quiz_me",
         "Everything needed to quiz the learner: the contract, the quiz "
         "material ids results are recorded against, the question bank. "
         "Optionally scoped to one phase.",
         {"type": "object",
          "properties": {"course": _course_prop(),
                         "phase": {"type": "integer",
                                   "description": "Phase number to scope to."}}},
         server.quiz_me),
        ("review_exercise",
         "The unit's exercise brief and grader, for reviewing the learner's "
         "work. The test bar is the grader.",
         {"type": "object",
          "properties": {"course": _course_prop(), "unit": unit_prop},
          "required": ["unit"]},
         server.review_exercise),
        ("record_progress_event",
         "Append one validated progress event to the learner's ledger. "
         "Kinds and payloads: mark {done: bool} on a unit/step/milestone id; "
         "note {text} on a unit; checkpoint_result {score: int, total: int, "
         "misses: [str]} on a quiz material id; session_note {text} on a "
         "unit id or ''. Subjects the course does not define are refused.",
         {"type": "object",
          "properties": {"course": _course_prop(),
                         "kind": {"type": "string"},
                         "subject_id": {"type": "string"},
                         "payload": {"type": "object"}},
          "required": ["kind", "subject_id", "payload"]},
         server.record_progress_event),
        ("propose_profile_evidence",
         "Propose one profile claim for the learner's review — it renders "
         "nowhere until they accept it on /profile. Must name a source; "
         "tier is 'attested' (the learner said it) or 'thin' (uncorroborated "
         "inference). Fields: " + ", ".join(profile.FIELDS) + ".",
         {"type": "object",
          "properties": {"field": {"type": "string"},
                         "key": {"type": "string"},
                         "text": {"type": "string"},
                         "tier": {"type": "string",
                                  "enum": ["attested", "thin"]},
                         "source": {"type": "string"}},
          "required": ["field", "key", "text", "source"]},
         server.propose_profile_evidence),
    ]


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------

def handle_message(server: TutorServer, msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method = msg.get("method")
    msg_id = msg.get("id")

    def result(payload: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": payload}

    def error(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": message}}

    if msg_id is None:                    # a notification; never answered
        return None
    if method == "initialize":
        return result({"protocolVersion":
                       (msg.get("params") or {}).get("protocolVersion")
                       or PROTOCOL_VERSION,
                       "capabilities": {"tools": {}},
                       "serverInfo": SERVER_INFO})
    if method == "ping":
        return result({})
    if method == "tools/list":
        return result({"tools": [
            {"name": name, "description": desc, "inputSchema": schema}
            for name, desc, schema, _ in tool_table(server)]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        handler = next((fn for n, _, _, fn in tool_table(server) if n == name),
                       None)
        if handler is None:
            return error(-32602, f"unknown tool {name!r}")
        try:
            text = handler(params.get("arguments") or {})
        except ToolError as exc:
            return result({"content": [{"type": "text", "text": str(exc)}],
                           "isError": True})
        return result({"content": [{"type": "text", "text": text}],
                       "isError": False})
    return error(-32601, f"method {method!r} not supported")


def serve_stdio(server: TutorServer, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle_message(server, msg)
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return 0


def build_server(course_roots: list[str], tenant_slug: str,
                 database_url: str | None = None) -> TutorServer:
    engine = db.make_engine(database_url)
    with engine.begin() as conn:
        tenant_id = db.tenant_id_for(conn, tenant_slug)   # fail at startup, T1
    return TutorServer(
        courses={h.slug: h for h in (load_course(r) for r in course_roots)},
        engine=engine, scope=db.for_tenant(tenant_id), tenant=tenant_slug)
