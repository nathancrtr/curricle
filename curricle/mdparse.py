"""Parse the corpus's curriculum.md conventions into a document model.

This is deliberately a parser for the *house format*, not for markdown in
general: the conventions it recognizes are exactly the ones stable across
rhyme-schemer, textual-flow, and ml-ai (see docs/platform-manifest.md §5).
Anything it does not recognize is preserved-and-ignored, never guessed at —
the compiler decides which unrecognized content matters.

The document model is structural: phase and unit boundaries, label-bullet
rows, checkpoints, check-yourself blocks, version footers. Row content stays
verbatim markdown; prose fidelity is the whole point (open question 1 in the
schema spec).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ### Unit 8 — Unequal lengths: sequence alignment
UNIT_RE = re.compile(r"^### Unit (\d+) — (.+?)\s*$")
# ## Phase 3 — From pair-scores to a rhyme scheme (Weeks 11–15)
# Also: (Week 0) — a single week; (Weeks 23+) — open-ended.
PHASE_RE = re.compile(
    r"^## Phase (?P<num>\d+) — (?P<title>.+?)"
    r"(?: \(Weeks? (?P<start>\d+)(?:\s*[–-]\s*(?P<end>\d+)|(?P<plus>\+))?\))?\s*$"
)
# ### — Phase 2 Checkpoint —
CHECKPOINT_RE = re.compile(r"^###\s*—\s*Phase (\d+) Checkpoint\s*—\s*$")
# - **Build:** Generalize `rhyme_score` …
ROW_RE = re.compile(r"^- \*\*(.+?):?\*\*:?\s*(.*)$")
# **Goal:** … (phase-level bold label line, also used for checkpoint track goals)
BOLD_LABEL_RE = re.compile(r"^\*\*(.+?):?\*\*:?\s*(.*)$")
# *Curriculum v1.2 — August 2026: …*  /  *Version 1.0 — 2026-08-27. …*
# /  *Curriculum version 2.0 — June 2026. …*
VERSION_RE = re.compile(
    r"^\*(?:Curriculum v(?:ersion )?|Version )(\d+(?:\.\d+)*)\s*—\s*([^:.]+)[:.]\s*(.*?)\*?\s*$"
)
CHECK_YOURSELF_RE = re.compile(r"^>\s*\*\*Check yourself:?\*\*:?\s*(.*)$")
# **Greek by now:** — a labeled span *inline* in checkpoint prose (textual-flow
# writes track goals mid-paragraph). Conservative: capitalized, short, no colon.
INLINE_LABEL_RE = re.compile(r"\*\*([A-Z][^*:]{2,40}):\*\*")


@dataclass
class MdRow:
    label: str
    content: str
    line: int


@dataclass
class MdCheck:
    q: str
    ans: str


@dataclass
class MdUnit:
    num: int
    title: str
    line: int
    rows: list[MdRow] = field(default_factory=list)
    check: MdCheck | None = None
    extra_prose: list[str] = field(default_factory=list)  # unrecognized paragraphs


@dataclass
class MdCheckpoint:
    phase_num: int
    prose: str
    labeled_lines: list[tuple[str, str]] = field(default_factory=list)
    # bold-label lines inside the checkpoint ("Greek by now" → track goals)


@dataclass
class MdPhase:
    num: int
    title: str
    line: int
    weeks: tuple[int, int | None] | None = None   # end None = open-ended
    goal: str = ""
    body_rows: list[MdRow] = field(default_factory=list)   # label-bullets before
    body_check: MdCheck | None = None                      # any unit header
    units: list[MdUnit] = field(default_factory=list)
    checkpoint: MdCheckpoint | None = None
    extra_prose: list[str] = field(default_factory=list)


@dataclass
class MdDoc:
    phases: list[MdPhase] = field(default_factory=list)
    versions: list[tuple[str, str, str]] = field(default_factory=list)  # rev, date, note
    preamble: list[str] = field(default_factory=list)  # everything before Phase 1


def parse_curriculum(text: str) -> MdDoc:
    doc = MdDoc()
    lines = text.splitlines()
    phase: MdPhase | None = None
    unit: MdUnit | None = None
    checkpoint: MdCheckpoint | None = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        m = PHASE_RE.match(line)
        if m:
            weeks = None
            if m.group("start"):
                start = int(m.group("start"))
                if m.group("end"):
                    weeks = (start, int(m.group("end")))
                elif m.group("plus"):
                    weeks = (start, None)      # open-ended: "Weeks 23+"
                else:
                    weeks = (start, start)     # single week: "Week 0"
            phase = MdPhase(
                num=int(m.group("num")), title=m.group("title"), line=i + 1,
                weeks=weeks,
            )
            doc.phases.append(phase)
            unit = None
            checkpoint = None
            i += 1
            continue

        m = CHECKPOINT_RE.match(line)
        if m and phase is not None:
            checkpoint = MdCheckpoint(phase_num=int(m.group(1)), prose="")
            phase.checkpoint = checkpoint
            unit = None
            i += 1
            continue

        m = UNIT_RE.match(line)
        if m and phase is not None:
            unit = MdUnit(num=int(m.group(1)), title=m.group(2), line=i + 1)
            phase.units.append(unit)
            checkpoint = None
            i += 1
            continue

        m = VERSION_RE.match(line)
        if m:
            doc.versions.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
            i += 1
            continue

        m = CHECK_YOURSELF_RE.match(line)
        if m and phase is not None:
            check, i = _parse_check(lines, i, m.group(1))
            if unit is not None:
                unit.check = check
            else:
                phase.body_check = check
            continue

        m = ROW_RE.match(line)
        if m and phase is not None and checkpoint is None:
            content, i = _with_continuations(lines, i, m.group(2))
            row = MdRow(label=m.group(1), content=content, line=i)
            if unit is not None:
                unit.rows.append(row)
            else:
                phase.body_rows.append(row)
            continue

        m = BOLD_LABEL_RE.match(line)
        if m and phase is not None:
            label, rest = m.group(1), m.group(2)
            if checkpoint is not None:
                checkpoint.labeled_lines.append((label, rest))
            elif label == "Goal" and not phase.goal:
                phase.goal = rest
            else:
                # A bold-label paragraph at phase level (e.g. the contact-
                # milestone paragraph). Preserved; the compiler may match it.
                target = unit.extra_prose if unit else phase.extra_prose
                target.append(line)
            i += 1
            continue

        # Everything else: preserved prose, attributed to the innermost scope.
        if line.strip() and line.strip() != "---":
            if checkpoint is not None:
                _absorb_checkpoint_line(checkpoint, line)
            elif unit is not None:
                unit.extra_prose.append(line)
            elif phase is not None:
                phase.extra_prose.append(line)
            else:
                doc.preamble.append(line)
        i += 1

    return doc


def _absorb_checkpoint_line(checkpoint: MdCheckpoint, line: str) -> None:
    """Checkpoint prose, with inline labeled spans split out as track goals."""
    parts = INLINE_LABEL_RE.split(line)
    prose = parts[0].strip()
    if prose:
        checkpoint.prose = (checkpoint.prose + "\n" + prose).strip()
    # parts then alternates label, text, label, text, …
    for label, text in zip(parts[1::2], parts[2::2]):
        checkpoint.labeled_lines.append((label.strip(), text.strip()))


# ---------------------------------------------------------------------------
# The "headings" dialect (ml-ai's generation): H1 phases, "## Module N: Title"
# units, H3 field sections whose bodies are the row content, checkpoints as
# blockquoted headings. Same document model out; the compiler doesn't care
# which dialect fed it.
# ---------------------------------------------------------------------------

H1_PHASE_RE = re.compile(r"^# Phase (?P<num>\d+) — (?P<title>.+?)\s*$")
H2_UNIT_RE = re.compile(r"^## (?:Module|Unit) (?P<num>\d+):? (?P<title>.+?)\s*$")
H3_FIELD_RE = re.compile(r"^### (.+?)\s*$")
BQ_CHECKPOINT_RE = re.compile(r"^>\s*#+\s*—\s*Phase (\d+) Checkpoint\s*—\s*$")
META_LINE_RE = re.compile(r"^\*\*Track [AB]:\*\* .+$")


def parse_curriculum_headings(text: str) -> MdDoc:
    doc = MdDoc()
    lines = text.splitlines()
    phase: MdPhase | None = None
    unit: MdUnit | None = None
    section_label: str | None = None
    section_lines: list[str] = []
    checkpoint: MdCheckpoint | None = None

    def flush_section() -> None:
        nonlocal section_label, section_lines
        if section_label is not None and unit is not None:
            content = "\n".join(section_lines).strip()
            if content:
                unit.rows.append(MdRow(label=section_label, content=content, line=0))
        section_label, section_lines = None, []

    for i, line in enumerate(lines):
        m = H1_PHASE_RE.match(line)
        if m:
            flush_section()
            phase = MdPhase(num=int(m.group("num")), title=m.group("title"),
                            line=i + 1)
            doc.phases.append(phase)
            unit = None
            checkpoint = None
            continue

        m = BQ_CHECKPOINT_RE.match(line)
        if m and phase is not None:
            flush_section()
            checkpoint = MdCheckpoint(phase_num=int(m.group(1)), prose="")
            phase.checkpoint = checkpoint
            unit = None
            continue

        m = H2_UNIT_RE.match(line)
        if m and phase is not None:
            flush_section()
            unit = MdUnit(num=int(m.group("num")), title=m.group("title"),
                          line=i + 1)
            phase.units.append(unit)
            checkpoint = None
            continue

        m = H3_FIELD_RE.match(line)
        if m and unit is not None:
            flush_section()
            section_label = m.group(1)
            continue

        m = VERSION_RE.match(line)
        if m:
            doc.versions.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
            continue

        if checkpoint is not None and line.startswith(">"):
            _absorb_checkpoint_line(checkpoint, line[1:].strip())
            continue

        if section_label is not None:
            section_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped or stripped in ("---",):
            continue
        if unit is not None:
            if META_LINE_RE.match(stripped):
                unit.rows.append(MdRow(label="Tracks", content=stripped, line=i + 1))
            else:
                unit.extra_prose.append(line)
        elif phase is not None:
            m = BOLD_LABEL_RE.match(stripped)
            if m and m.group(1) == "Goal" and not phase.goal:
                phase.goal = m.group(2)
            else:
                phase.extra_prose.append(line)
        else:
            doc.preamble.append(line)

    flush_section()
    return doc


DIALECTS = {
    "bullets": parse_curriculum,
    "headings": parse_curriculum_headings,
}


def _with_continuations(lines: list[str], i: int, first: str) -> tuple[str, int]:
    """A row bullet plus its indented continuation lines, verbatim."""
    parts = [first]
    i += 1
    while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
        parts.append(lines[i].strip())
        i += 1
    return " ".join(parts), i


def _parse_check(lines: list[str], i: int, q_first: str) -> tuple[MdCheck, int]:
    """A '> **Check yourself:**' blockquote with a <details> answer."""
    q_parts = [q_first] if q_first else []
    ans_parts: list[str] = []
    in_answer = False
    i += 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith(">"):
            break
        body = line[1:].strip()
        if "<details" in body:
            in_answer = True
        elif "</details" in body:
            i += 1
            break
        elif "<summary" in body:
            pass
        elif in_answer:
            if body:
                ans_parts.append(body)
        else:
            if body:
                q_parts.append(body)
        i += 1
    return MdCheck(q=" ".join(q_parts).strip(), ans=" ".join(ans_parts).strip()), i
