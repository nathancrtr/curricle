"""Render the per-unit page and the document reader.

The unit page is the click target the curriculum was missing: everything a
unit owns, on one served page. It is a *walk*, not a dossier: the page
answers, in order, why you are here (masthead), what to do first (the
chapter, or the readings when there is no chapter), the work, what to know,
what your assistant can run for you, what runs in the browser, and what
done means — milestone, mark, checkpoint, the way on. The rows of the
curriculum are structured data with roles (`_ROLE`), and the page places
each by its role rather than printing them in authoring order; materials
are placed by kind the same way, so a lesson guide is offered as the
sentence that runs it, never as a card inviting a human to read a script
written for a model. It exists only on the served app (the standalone
exports keep their current shape): the whole point is that the links
resolve against the content routes.

The reader is the served face of a markdown material: the same document the
repo holds, rendered through `blockmd` inside the theme instead of arriving
as text/plain. A lesson gets a framing banner because a lesson guide is a
dialogue script — the honest presentation says "run this with Claude", it
does not pretend the page is the tutor (invariant L1 keeps the LLM off the
request path, so the tutor lives in a Claude session, not here).

Design: the *companion* system (theme.py). The unit page tracks the unit —
its mark and its steps — so those are live; the reader tracks nothing and
therefore carries no progress gesture at all.
"""

from __future__ import annotations

import html
import json
import posixpath

import re

from . import theme
from .blockmd import block_html
from .inlinemd import inline_html
from .refs import RefResolver
from .schema import Manifest, Material, Unit

STYLE = theme.style("""\
  /* 600 - 48px of padding = 552px, which is `--measure` exactly. The unit
     page is a text page: when the column is wider than the measure, the
     heading and the nav end 160px to the right of every paragraph and the
     page grows a phantom margin nothing occupies. One edge instead. */
  .wrap { max-width:600px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:36px 0 10px; }
  h1 { font-weight:700; font-size:clamp(26px,5vw,36px); line-height:1.15;
       letter-spacing:-.01em; margin:14px 0 0; }
  .gloss { margin:12px 0 0; color:var(--muted); font-size:16px;
           max-width:var(--measure); }
  .phasegoal { margin:10px 0 0; color:var(--muted); font-size:14px;
               max-width:var(--measure); }
  .phasegoal b { color:var(--ink); font-weight:600; }
  .context { margin:14px 0 0; color:var(--muted); font-size:13.5px;
             line-height:1.7; max-width:var(--measure); }
  .context .chip { vertical-align:1px; }
  .chip.gate { background:var(--warn-soft); color:var(--warn-text); }
  .row { margin:0 0 14px; font-size:14.5px; line-height:1.6;
         max-width:var(--measure); }
  .row b.lbl { display:block; font-size:14px; font-weight:700;
               color:var(--ink); margin:0 0 3px; }
  .key { border-left:2px solid var(--accent); padding:2px 0 2px 14px;
         background:none; }
  .key b.lbl { color:var(--accent-text); }
  /* The deliverable takes the green family — the tint that means "done"
     everywhere else, because the milestone is what done will mean here. */
  .deliver { border-left:2px solid var(--good); padding:2px 0 2px 14px;
             background:none; }
  .deliver b.lbl { color:var(--good-text); }
  .unote { margin:24px 0 0; padding:13px 17px; background:var(--chip);
           border-radius:var(--r-card); font-size:14px; line-height:1.6;
           max-width:var(--measure); }
  .unote b.lbl { display:block; font-size:14px; font-weight:700;
                 color:var(--ink); margin:0 0 3px; }
  /* Sections are ruled fields: a hairline above, the label in the ink. */
  .sec { margin:34px 0 0; padding-top:16px; border-top:1px solid var(--line); }
  .sec h2 { font-size:18px; font-weight:700; margin:0 0 8px;
            letter-spacing:-.005em; }
  .sec .sub { color:var(--muted); font-size:13.5px; margin:-4px 0 12px;
              max-width:var(--measure); }
  .sec .row { margin:0; }
  .sec .row + .row, .sec .row + details, .sec details + .row { margin-top:14px; }
  .sec .row b.lbl { font-size:15px; }
  .sec .trackline { color:var(--muted); font-size:13.5px; font-weight:600; }
  /* The start panel is the one field with a fill and holds the page's one
     primary action: the chapter is the unit's text, so the accent — which
     means "your next action" everywhere — lands here and nowhere else. */
  .start { margin:26px 0 0; padding:18px 20px 16px; }
  .start .kicker { font-size:13px; font-weight:700; color:var(--accent-text);
                   margin:0 0 6px; }
  .start h2 { font-size:20px; margin:0 0 6px; line-height:1.3; }
  .start p { margin:0 0 12px; font-size:14.5px; color:var(--muted);
             line-height:1.55; max-width:var(--measure); }
  .start p.readings { color:var(--ink); }
  .start .acts { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  .start .acts a.more { font-size:13.5px; color:var(--accent-text); }
  ul.know { margin:0; padding-left:20px; font-size:14.5px; line-height:1.55;
            max-width:var(--measure); }
  ul.know li { margin:0 0 5px; }
  /* The assistant section: what to type, then what will happen. */
  .say-row { display:grid; grid-template-columns:auto 1fr; gap:6px 14px;
             align-items:baseline; margin:0 0 10px; font-size:14.5px;
             max-width:var(--measure); }
  .say-row .say { white-space:nowrap; }
  .say-row .what { color:var(--muted); line-height:1.5; }
  .exercise { margin:12px 0 0; padding:13px 17px; }
  .exercise .chip { margin:0 0 6px; }
  .exercise h3 { margin:0 0 4px; font-size:15.5px; }
  .exercise h3 a { text-decoration:none; }
  .exercise h3 a:hover { text-decoration:underline; text-underline-offset:3px; }
  .exercise p { margin:0 0 8px; font-size:13.5px; color:var(--muted); }
  .exercise .cmd { display:block; font:12.5px """ + theme.FONT_MONO + """; background:var(--chip);
                   padding:6px 10px; margin:0 0 10px; overflow-x:auto;
                   white-space:pre; }
  .steps { margin:18px 0 0; padding:16px 20px; }
  .steps h3 { font-size:15px; font-weight:700; color:var(--ink); margin:0 0 10px; }
  .step-row { display:flex; align-items:baseline; gap:9px; font-size:14.5px;
              margin:0 0 6px; }
  .step-row input { width:17px; height:17px; accent-color:var(--accent-strong); }
  .step-row.done label { color:var(--muted); text-decoration:line-through;
                         text-decoration-color:var(--faint); }
  .done-acts { display:flex; align-items:center; gap:14px; margin:18px 0 0; }
  .done-acts .hint { font-size:13.5px; color:var(--muted); }
  /* auto-fit, not auto-fill: a unit with one material had it sitting in a
     230px track with two empty tracks beside it. Empty tracks collapse. */
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
          gap:14px; }
  .card { padding:15px 18px 13px; display:flex; flex-direction:column; }
  .card .chip { margin:0 0 9px; align-self:flex-start; }
  .card h3 { margin:0 0 6px; font-size:16px; line-height:1.35; }
  .card h3 a { text-decoration:none; }
  .card h3 a:hover { text-decoration:underline; text-underline-offset:3px; }
  .card p { margin:0 0 10px; font-size:13.5px; color:var(--muted); line-height:1.5; }
  .cardact { margin-top:auto; font-size:13px; font-weight:600;
             color:var(--accent-text); text-decoration:none; }
  .cardact:hover { text-decoration:underline; text-underline-offset:3px; }
  details.check { margin:14px 0 0; padding:13px 17px; background:var(--panel);
                  border:1.5px solid var(--line); border-radius:var(--r-card);
                  font-size:14.5px; }
  details.check summary { cursor:pointer; font-weight:600; }
  details.check div { margin-top:10px; color:var(--muted); }
  .cp { margin:22px 0 0; padding:2px 0 2px 16px; background:none;
        border-left:2px solid var(--good); font-size:14.5px; }
  .cp b.cpl { display:block; font-size:14px; font-weight:700;
              color:var(--good-text); margin:0 0 6px; }
  .cp .track-goal { margin-top:8px; color:var(--muted); }
  /* A side-quest milestone that follows this unit: the product's one drawn
     glyph, the same flag the curriculum and hub give the same row. */
  .side { margin:22px 0 0; padding:2px 0 2px 16px; background:none;
          border-left:2px solid var(--good); font-size:14.5px; }
  .side b.sl { display:block; font-size:14px; font-weight:700;
               color:var(--good-text); margin:0 0 4px; }
  .side b.sl svg { vertical-align:-1px; margin-right:5px; }
  .side p { margin:0; color:var(--muted); max-width:var(--measure); }
  /* Pagination, drawn as two destinations rather than two arrows. The
     glyph pair said the direction and the ellipsis ate the title that said
     the destination — on a 46%-wide nowrap pill, "Unit 3 — Local stemmata
     and genealogical cohe..." is exactly the half of the label a reader
     needs, clipped. A word says the direction unambiguously, including to a
     screen reader, and the title is then free to wrap. */
  .unav { display:flex; align-items:flex-start; gap:16px; margin:34px 0 0; }
  .unav .spacer { flex:1 1 auto; }
  /* Equal halves. Sizing each to its own label gave two boxes of different
     widths sitting side by side, which is the sort of thing a reader feels
     without being able to name. */
  .unav a { flex:0 1 46%; max-width:46%; text-decoration:none; display:block;
            border:1px solid var(--line); border-radius:var(--r-card);
            padding:10px 14px; color:var(--ink); }
  .unav a:hover { border-color:var(--accent); }
  .unav a.next { text-align:right; }
  .unav b.dir { display:block; font-size:12.5px; font-weight:700;
                color:var(--muted); margin:0 0 2px; }
  .unav a.next b.dir { color:var(--accent-text); }

  /* ---- the reader ---- */
  .doc { margin:26px 0 0; font-size:15.5px; line-height:1.65; }
  .doc h1 { font-size:clamp(24px,4.5vw,32px); margin:26px 0 8px; }
  .doc h2 { font-size:20px; margin:30px 0 8px; }
  .doc h3 { font-size:16.5px; margin:24px 0 6px; }
  .doc p, .doc li { max-width:var(--measure); }
  .doc li { margin:0 0 6px; }
  .doc blockquote { margin:14px 0; padding:10px 16px; border-left:3px solid
                    var(--accent); background:var(--accent-soft);
                    border-radius:0 var(--r-card) var(--r-card) 0; }
  .doc blockquote p { margin:0; }
  .doc pre { background:var(--chip); padding:12px 15px; border-radius:var(--r-card);
             overflow-x:auto; font-size:13px; line-height:1.5; }
  .doc pre code { background:none; padding:0; }
  .doc .tablewrap { overflow-x:auto; }
  .doc table { border-collapse:collapse; font-size:14px; }
  .doc th, .doc td { border:1px solid var(--line); padding:5px 11px; text-align:left; }
  .doc th { background:var(--chip); }
  .doc h2, .doc h3 { scroll-margin-top:16px; }
  .doc figure { margin:18px 0; }
  /* Figures are mostly Graphviz SVGs: black strokes on a transparent
     ground, so they get a white plate in both themes rather than vanishing
     against the dark panel. */
  .doc figure img { display:block; max-width:100%; height:auto; padding:8px;
                    background:#FFFFFF; border:1px solid var(--line);
                    border-radius:var(--r-card); }
  .doc figcaption { margin:6px 0 0; font-size:13.5px; color:var(--muted);
                    max-width:68ch; }
  .doc sup.fn { font-size:.72em; line-height:0; }
  .doc sup.fn a { text-decoration:none; font-weight:600; }
  .doc .footnotes { margin:38px 0 0; padding:14px 0 0; border-top:1px solid var(--line);
                    font-size:13.5px; color:var(--muted); }
  .doc .footnotes ol { padding-left:22px; }
  .doc .footnotes li { max-width:72ch; margin:0 0 6px; }
  .doc .footnotes li:target { color:var(--ink); }
  .doc .fnback { text-decoration:none; margin-left:4px; }
  .doc details { margin:14px 0; padding:10px 16px; border:1.5px solid var(--line);
                 border-radius:var(--r-card); background:var(--panel); }
  .doc details summary { cursor:pointer; font-weight:600; }
  .doc details[open] summary { margin-bottom:8px; }
  .doc .callout { margin:14px 0; padding:10px 16px; border-left:3px solid var(--accent);
                  background:var(--accent-soft);
                  border-radius:0 var(--r-card) var(--r-card) 0; }
  .doc .callout p { margin:0 0 8px; }
  .doc .callout p:last-child { margin-bottom:0; }
  .doc .callout-title { font-weight:700; font-size:13px; letter-spacing:.04em;
                        text-transform:uppercase; }
  .doc .callout.tip { border-color:var(--good); background:var(--good-soft); }
  .doc .callout.warning, .doc .callout.caution {
    border-color:var(--warn-text); background:var(--warn-soft); }
  .banner { margin:22px 0 0; padding:13px 17px; border:1.5px solid var(--line);
            border-radius:var(--r-card); font-size:14px; color:var(--muted);
            background:var(--panel); }
  .banner b { color:var(--ink); }
  .say { font:13px """ + theme.FONT_MONO + """; background:var(--chip);
         padding:2px 8px; border-radius:var(--r-ctl); }
""")

SCRIPT = """\
const API = %(api)s;
const UNIT = %(unit)s;         // {id, steps: [id...]} — what this page may mark
let progress = %(initial)s || {};

function send(kind, id, payload) {
  fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, subject_id: id, payload }) }).catch(() => {});
}
let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1200);
}
function putMark(id, v) { progress[id] = v; send("mark", id, { done: v }); toast("Saved"); }

const ids = UNIT.steps.length ? UNIT.steps : [UNIT.id];
const isDone = () => ids.every(i => !!progress[i]);
const mark = document.getElementById("mark");
function sync() {
  mark.setAttribute("aria-pressed", String(isDone()));
  mark.textContent = isDone() ? "Done" : "Mark done";
  document.querySelectorAll(".step-row").forEach(r => {
    const cb = r.querySelector("input");
    cb.checked = !!progress[cb.id];
    r.classList.toggle("done", cb.checked);
  });
}
mark.addEventListener("click", () => {
  const v = !isDone();
  ids.forEach(i => putMark(i, v));
  sync();
});
document.querySelectorAll(".step-row input").forEach(cb =>
  cb.addEventListener("change", () => { putMark(cb.id, cb.checked); sync(); }));
sync();
"""

# What a card invites you to do, by material kind. The title names the
# thing; the chip says what it is, in words; the verb is the action line.
_VERB = {"widget": "Open the widget", "trainer": "Open the trainer",
         "quiz": "Take the quiz", "exercise": "Read the brief",
         "companion": "Read the companion", "question-bank": "Browse the questions"}

# Where a curriculum row lands on the walk. The labels are the schema's
# enumerated vocabulary (`CORE_ROW_LABELS`); a label outside this map — a
# course's own ("Variant disambiguation", "Caveat to carry forward") — keeps
# its authoring order after the known sections, as its own field. Track rows
# are placed by their track, not their label.
_ROLE = {"Build": "work", "Exercise": "work", "Read": "read",
         "Concepts": "know", "Milestone": "done", "Key insight": "done"}

_CHAPTER_LINK_RE = re.compile(r"\[[^\]]*\]\(mat:([^)]+)\)")
_FIRST_LINK_RE = re.compile(r"^\s*\[([^\]]+)\]\(([^)]+)\)")


def trigger_phrase(mf: Manifest, kind: str, *, unit: Unit | None = None,
                   phase_num: int | None = None) -> tuple[str, str | None] | None:
    """The course's own trigger phrase of a kind ("teach" or "quiz"), aimed
    at the unit or phase at hand. Corpus phrases name their example by
    number ("Teach me Unit 2 interactively.", "Quiz me on Phase 1."), so
    the example is retargeted rather than always citing the example."""
    for tp in mf.course.trigger_phrases:
        low = tp.say.lower()
        if kind == "teach" and ("teach" in low or "lesson" in low):
            say = tp.say
            if unit is not None:
                say = re.sub(r"[Uu]nit \d+", f"Unit {unit.num}", say)
            return say, tp.note
        if kind == "quiz" and "quiz" in low:
            say = tp.say
            if phase_num is not None:
                say = re.sub(r"[Pp]hase \d+", f"Phase {phase_num}", say)
            return say, tp.note
    return None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _cards(materials: list[Material], rr: RefResolver) -> str:
    e = html.escape
    cards = []
    for m in materials:
        href = e(rr.material_href(m))
        blurb = f"<p>{e(m.blurb)}</p>" if m.blurb else ""
        cards.append(
            f'<div class="card panel">'
            f'<span class="chip{" acc" if m.kind in ("widget", "trainer") else ""}">'
            f"{e(m.kind)}</span>"
            f'<h3><a href="{href}">{e(m.title)}</a></h3>{blurb}'
            f'<a class="cardact" href="{href}">'
            f'{e(_VERB.get(m.kind, "Open"))}</a></div>')
    return f'<div class="grid">{"".join(cards)}</div>'


def _row(r, rr: RefResolver, cls: str = "") -> str:
    e = html.escape
    return (f'<div class="row{cls}"><b class="lbl">{e(r.label)}</b>'
            f"{inline_html(r.content, rr)}</div>")


def _context_line(mf: Manifest, u: Unit, rr: RefResolver) -> str:
    """What the sidecar knows about this unit's place, in words: what it
    builds on, whether the path load-bears here, when it may be skipped,
    what gates it. Rendered only when there is something to say."""
    e = html.escape
    bits: list[str] = []
    if u.depends_on:
        units_by_id = {x.id: x for x in mf.units}
        links = []
        for dep in u.depends_on:
            d = units_by_id.get(dep)
            label = f"Unit {d.num} — {d.title}" if d else dep
            links.append(f'<a href="{e(rr.unit_href(dep))}">{e(label)}</a>'
                         if d else e(dep))
        bits.append("Builds on " + ", ".join(links) + ".")
    if u.load_bearing:
        bits.append('<span class="chip">load-bearing</span>')
    elif u.load_bearing is False:
        bits.append('<span class="chip">safe to skim</span>')
    if u.skippable_note:
        bits.append(f"Skippable: {inline_html(u.skippable_note, rr)}")
    if u.condition:
        bits.append(f'<span class="chip gate">gated · {e(u.condition.state)}'
                    f"</span> waits on {e(u.condition.on)}.")
    return f'<p class="context">{" ".join(bits)}</p>' if bits else ""


def _start_panel(u: Unit, chapter: Material | None, read, rr: RefResolver) -> str:
    """What to do first. The chapter when there is one — it is the unit's
    text, and the page's one primary action opens it. Otherwise the Read row
    *is* the start, with the first reading it names as the action."""
    e = html.escape
    if chapter:
        return (f'<section class="start panel"><p class="kicker">Start here</p>'
                f"<h2>{e(chapter.title)}</h2>"
                f"<p>The unit's text: it teaches the unit in full, with its sources "
                f"as footnotes. The readings below go deeper; none is required to "
                f"follow it.</p>"
                f'<div class="acts"><a class="pill primary" '
                f'href="{e(rr.material_href(chapter))}">Read the chapter</a>'
                f"</div></section>")
    if read is None:
        return ""
    acts = ""
    first = _FIRST_LINK_RE.match(read.content)
    target = rr.resolve(first.group(2)) if first else None
    if first and target:
        href, external = target
        acts = (f'<div class="acts"><a class="pill primary" href="{e(href)}"'
                f'{" target=_blank rel=noopener" if external else ""}>'
                f"Read {e(first.group(1))}</a>"
                f'<a class="more" href="{e(rr.to_root)}learning-resources.html">'
                f"All the course's resources</a></div>")
    return (f'<section class="start panel"><p class="kicker">Start here</p>'
            f"<h2>The readings</h2>"
            f'<p class="readings">{inline_html(read.content, rr)}</p>{acts}</section>')


def _section(title: str, body: str, sub: str = "", *, extra: str = "") -> str:
    if not body:
        return ""
    sub_html = f'<p class="sub">{sub}</p>' if sub else ""
    return f'<section class="sec"><h2>{title}{extra}</h2>{sub_html}{body}</section>'


def render_unit(mf: Manifest, unit_id: str, *, api: str,
                initial: dict | None = None) -> str:
    e = html.escape
    u: Unit = mf.unit(unit_id)
    rr = RefResolver(mf, to_root="../")   # the page sits at unit/<id>.html
    phase = next((p for p in mf.phases if unit_id in p.entries), None)
    units_by_id = {x.id: x for x in mf.units}
    tracks_by_id = {t.id: t for t in mf.tracks}

    by_kind: dict[str, list[Material]] = {}
    for m in mf.materials_for_unit(unit_id):
        by_kind.setdefault(m.kind, []).append(m)
    # The Interactive row is derived: the materials, placed by kind, are it.
    rows = {r.label: r for r in u.rows if r.label != "Interactive" and not r.track}
    track_rows = [r for r in u.rows if r.track]
    own_rows = [r for r in u.rows
                if r.label not in _ROLE and not r.track and r.label != "Interactive"]

    # -- start here -----------------------------------------------------------
    chapter = by_kind.get("chapter", [None])[0]
    read = rows.get("Read")
    start = _start_panel(u, chapter, read, rr)

    note = ""
    if u.note:
        note = (f'<div class="unote"><b class="lbl">Note</b>'
                f"{inline_html(u.note, rr)}</div>")

    # -- the work: build, then the exercise with its material attached -------
    work = ""
    if "Build" in rows:
        work += _row(rows["Build"], rr)
    if "Exercise" in rows:
        work += _row(rows["Exercise"], rr)
    for m in by_kind.get("exercise", []):
        href = e(rr.material_href(m))
        cmd = (f'<code class="cmd">{e(m.grader.command)}</code>'
               if m.grader and m.grader.command else "")
        work += (f'<div class="exercise panel"><span class="chip">exercise</span>'
                 f'<h3><a href="{href}">{e(m.title)}</a></h3>'
                 f"{f'<p>{e(m.blurb)}</p>' if m.blurb else ''}{cmd}"
                 f'<a class="cardact" href="{href}">{_VERB["exercise"]}</a></div>')
    work_sec = _section("The work", work)

    # -- read: the readings, when the chapter took the start slot ------------
    read_sec = ""
    if chapter and read:
        comp = "".join(
            f'<div class="row"><b class="lbl">Companion</b>'
            f'<a href="{e(rr.material_href(m))}">{e(m.title)}</a>'
            f"{f' — {e(m.blurb)}' if m.blurb else ''}</div>"
            for m in by_kind.get("companion", []))
        read_sec = _section("Read", f'<div class="row">{inline_html(read.content, rr)}</div>'
                            + comp, "Deeper than the chapter, in this order.")
    elif by_kind.get("companion"):
        comp = "".join(
            f'<div class="row"><b class="lbl">Companion</b>'
            f'<a href="{e(rr.material_href(m))}">{e(m.title)}</a>'
            f"{f' — {e(m.blurb)}' if m.blurb else ''}</div>"
            for m in by_kind["companion"])
        read_sec = _section("Read", comp)

    # -- know: the concepts, as the list the author wrote --------------------
    know_sec = ""
    if "Concepts" in rows:
        content = rows["Concepts"].content
        parts = [p.strip() for p in content.split(";") if p.strip()]
        if len(parts) > 1:
            body = ('<ul class="know">'
                    + "".join(f"<li>{inline_html(_cap(p), rr)}</li>" for p in parts)
                    + "</ul>")
        else:
            body = f'<div class="row">{inline_html(content, rr)}</div>'
        know_sec = _section("Concepts", body, "Be able to explain each of these by the end.")

    # -- tracks, and a course's own labels, in authoring order ---------------
    own_secs = ""
    for r in track_rows:
        t = tracks_by_id.get(r.track)
        name = f"{e(t.name)} track" if t else e(r.label)
        cad = (f' <span class="trackline">· {e(t.cadence)}</span>'
               if t and t.cadence else "")
        own_secs += _section(name, f'<div class="row">{inline_html(_cap(r.content), rr)}</div>',
                             extra=cad)
    for r in own_rows:
        cls = " key" if r.kind == "key" else ""
        own_secs += _section(e(r.label),
                             f'<div class="row{cls}">{inline_html(_cap(r.content), rr)}</div>')

    # -- with your assistant: the sentence that runs the guide ---------------
    lesson = by_kind.get("lesson", [None])[0]
    says = ""
    teach = trigger_phrase(mf, "teach", unit=u)
    if teach:
        if lesson:
            what = (f"Runs the Socratic guide written for this unit"
                    f"{': ' + e(lesson.blurb[:1].lower() + lesson.blurb[1:]) if lesson.blurb else ''} "
                    f'<a href="{e(rr.material_href(lesson))}">See the script.</a>')
        else:
            what = ("No guide is written for this unit yet; your assistant "
                    "improvises one from the curriculum and your profile.")
        says += (f'<div class="say-row"><span class="say">{e(teach[0])}</span>'
                 f'<span class="what">{what}</span></div>')
    elif lesson:
        # No trigger phrase to retarget: the guide is still offered as the
        # thing it is, a script for a tutor, with the reader's banner to say so.
        says += (f'<div class="say-row"><span class="say">'
                 f'<a href="{e(rr.material_href(lesson))}">{e(lesson.title)}</a></span>'
                 f'<span class="what">A dialogue script written for a tutor to run '
                 f"with you{f': {e(lesson.blurb)}' if lesson.blurb else '.'}</span></div>")
    # The quiz phrase is offered only where a quiz exists to draw from: a
    # phase with no checkpoint quiz would otherwise advertise "Quiz me on
    # Phase 0" beside a note about Phase 1's quiz.
    phase_quizzes = ([m for m in mf.materials
                      if m.kind == "quiz" and m.phase == phase.id] if phase else [])
    quiz = trigger_phrase(mf, "quiz", phase_num=phase.num) if phase_quizzes else None
    if quiz:
        bank = next((m for m in mf.materials if m.kind == "question-bank"), None)
        bank_link = (f' The pool it draws on is the <a href="{e(rr.material_href(bank))}">'
                     f"{e(bank.title.lower())}</a>." if bank else "")
        q = phase_quizzes[0]
        says += (f'<div class="say-row"><span class="say">{e(quiz[0])}</span>'
                 f'<span class="what">Runs the <a href="{e(rr.material_href(q))}">'
                 f"{e(q.title)}</a> in conversation.{bank_link}</span></div>")
    assist_sec = _section("With your assistant", says,
                          "Open a chat in the course repo, or connect it over MCP, and say:")

    # -- try it: what runs in the browser ------------------------------------
    tries = by_kind.get("widget", []) + by_kind.get("trainer", [])
    try_sec = _section("Try it", _cards(tries, rr) if tries else "",
                       "Runs right here in the browser.")

    # -- done means: the deliverable, the mark, the checkpoint, the way on ----
    done = ""
    if "Milestone" in rows:
        done += _row(rows["Milestone"], rr, " deliver")
    if "Key insight" in rows:
        done += _row(rows["Key insight"], rr, " key")
    if u.check:
        done += (f'<details class="check"><summary>Check yourself: '
                 f"{inline_html(u.check.q, rr)}</summary>"
                 f"<div>{inline_html(u.check.ans, rr)}</div></details>")
    if u.steps:
        items = "".join(
            f'<div class="step-row"><input type="checkbox" id="{e(s.id)}">'
            f'<label for="{e(s.id)}">{e(s.label)}</label></div>'
            for s in u.steps)
        done += f'<div class="steps panel"><h3>The steps</h3>{items}</div>'
    done += ('<div class="done-acts"><button class="pill" id="mark" '
             'aria-pressed="false">Mark done</button>'
             '<span class="hint">Your marks are what the course hub counts.</span></div>')

    # The phase's walking order of units, for prev/next and for knowing
    # whether this unit is the one the checkpoint lands on.
    ordered = [uid for p in mf.phases for uid in p.entries if uid in units_by_id]
    last_in_phase = phase and [uid for uid in phase.entries
                               if uid in units_by_id][-1] == unit_id
    if phase:
        quizzes = [m for m in mf.materials
                   if m.kind == "quiz" and m.phase == phase.id]
        links = " · ".join(
            f'<a href="{e(rr.material_href(m))}">{e(m.title)}</a>'
            for m in quizzes)
        if last_in_phase and phase.checkpoint:
            # The phase closes here: the checkpoint says what must be true
            # now, in the curriculum's own words.
            goals = "".join(
                f'<div class="track-goal"><b>{e(next((t.name for t in mf.tracks if t.id == tid), tid))}:</b> '
                f"{inline_html(text, rr)}</div>"
                for tid, text in phase.checkpoint.track_goals)
            quiz_line = f"<p>Prove it to yourself — {links}.</p>" if links else ""
            done += (f'<div class="cp"><b class="cpl">Phase {phase.num} checkpoint '
                     f"— this unit closes the phase</b>"
                     f"<p>{inline_html(phase.checkpoint.prose, rr)}</p>"
                     f"{goals}{quiz_line}</div>")
        elif links:
            done += (f'<div class="cp"><b class="cpl">Phase {phase.num} checkpoint</b>'
                     f"This unit builds toward it — {links}.</div>")
    # A milestone the phase places after this unit (a side quest, a contact
    # to make) belongs to the walk here, before the way on.
    for m in mf.milestones:
        if m.after_unit == unit_id:
            done += (f'<div class="side"><b class="sl">{theme.FLAG_SVG}'
                     f"Before you go on{', optional' if m.kind == 'side-quest' else ''}: "
                     f"{e(theme.strip_leading_pictograph(m.label))}</b>"
                     f"{f'<p>{inline_html(m.detail, rr)}</p>' if m.detail else ''}</div>")
    done_sec = _section("Done means", done)

    # Prev/next: the course is a path; the page says where it continues.
    pos = ordered.index(unit_id)
    nav = ""
    if len(ordered) > 1:
        parts = []
        if pos > 0:
            p_u = units_by_id[ordered[pos - 1]]
            parts.append(f'<a class="prev" href="{e(p_u.id)}.html">'
                         f'<b class="dir">Previous</b>'
                         f"Unit {p_u.num} — {e(p_u.title)}</a>")
        parts.append('<span class="spacer"></span>')
        if pos + 1 < len(ordered):
            n_u = units_by_id[ordered[pos + 1]]
            parts.append(f'<a class="next" href="{e(n_u.id)}.html">'
                         f'<b class="dir">Next</b>'
                         f"Unit {n_u.num} — {e(n_u.title)}</a>")
        nav = f'<nav class="unav">{"".join(parts)}</nav>'

    phase_line = ""
    if phase:
        phase_line = (f'<p class="phasegoal"><b>Phase {phase.num} — '
                      f"{e(phase.title)}.</b> {inline_html(phase.goal, rr)}</p>")

    script = SCRIPT % {
        "api": json.dumps(api),
        "unit": json.dumps({"id": u.id,
                            "steps": [s.id for s in u.steps]}),
        "initial": json.dumps(initial, ensure_ascii=False),
    }
    gloss = f'<p class="gloss">{inline_html(u.gloss, rr)}</p>' if u.gloss else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(u.title)} — {e(mf.course.title)}</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow"><a href="../index.html">Course hub</a>
    <span class="sep">/</span> <a href="../curriculum.html">Curriculum</a>
    <span class="sep">/</span> Unit {u.num:02d}</p>
    <h1>{e(u.title)}</h1>
    {gloss}
    {phase_line}
    {_context_line(mf, u, rr)}
  </header>
  {start}
  {note}
  {work_sec}
  {read_sec}
  {know_sec}
  {own_secs}
  {assist_sec}
  {try_sec}
  {done_sec}
  {nav}
  <footer>Rendered by curricle from the course manifest ·
    <a href="../curriculum.html#u-{e(u.id)}">this unit on the curriculum</a></footer>
</div>
<div class="saving" id="toast">Saved</div>
<script>
{script}</script>
</body>
</html>
"""


def render_reader(mf: Manifest | None, md_text: str, *, doc_title: str,
                  material: Material | None = None,
                  depth: int | None = None,
                  doc_dir: str | None = None,
                  platform_doc: str | None = None) -> str:
    """A markdown document in the theme.

    `platform_doc` names a repository document that belongs to curricle
    rather than to a course (`docs/mcp-config.md`), served at `/docs/`: it
    has no manifest, so `mf` is None and every reference link degrades to
    its label, its crumb leads home to the front door rather than to a
    course hub, and its footer names the file rather than a course repo.
    """
    e = html.escape
    if depth is None:
        depth = doc_depth(material) if material else 1
    up = "../" * depth
    if doc_dir is None:
        doc_dir = posixpath.dirname(material.path) if material else ""
    # The reader exists only served; the document's own directory lets its
    # relative figures resolve through the content route.
    rr = RefResolver(mf, to_root=up, doc_dir=doc_dir)
    unit = (next((x for x in mf.units if x.id == material.unit), None)
            if mf is not None and material and material.unit else None)
    unit_href = f"unit/{unit.id}.html" if unit else "curriculum.html"
    banner = ""
    if material and material.kind == "chapter":
        # A chapter is the unit's own text: it carries its sources as
        # footnotes and closes by saying how it was checked, so the banner
        # says what the page is and where its reliability comes from.
        banner = ('<div class="banner"><b>This is the unit\'s chapter.</b> '
                  "It teaches the unit's content in full; the readings on the "
                  "unit page go deeper, they are not required to follow it. "
                  "Footnotes name the source of every substantive claim, and "
                  "the last section says what was verified against what.</div>")
    elif material and material.kind == "lesson":
        # The course's own trigger phrase, aimed at *this* unit: the corpus
        # phrases name a unit by number ("Teach me Unit 2 interactively."),
        # so the example is retargeted rather than always citing Unit 2.
        tp = trigger_phrase(mf, "teach", unit=unit)
        say = tp[0] if tp else None
        phrase = (f' — open a fresh chat with your assistant in the course repo and say '
                  f'<span class="say">{e(say)}</span>' if say else "")
        banner = ('<div class="banner"><b>This is a dialogue script.</b> '
                  "It is written for a tutor to run with you, one question "
                  f"at a time{phrase}. Reading it straight through works too "
                  "— the questions are the lesson.</div>")
    crumb_unit = (f'<span class="sep">/</span> <a href="{up}{e(unit_href)}">'
                  f"Unit {unit.num:02d}</a>"
                  if unit else "")
    # The document flows back into the course: the way on from the last
    # line is the unit the document belongs to, not the browser's Back.
    onward = ""
    if unit:
        onward = (f'<nav class="unav"><span class="spacer"></span>'
                  f'<a class="next" href="{up}{e(unit_href)}">'
                  f'<b class="dir">Back to the unit</b>'
                  f"Unit {unit.num} — {e(unit.title)}</a></nav>")
    if platform_doc:
        suffix = "curricle"
        crumbs = ('<a href="/">Your courses</a> <span class="sep">/</span> '
                  f"{e(platform_doc)}")
        foot = (f"This is <code>{e(platform_doc)}</code> from the curricle "
                "checkout, rendered — the file is the canonical text.")
    else:
        suffix = mf.course.title if mf is not None else "curricle"
        crumbs = (f'<a href="{up}index.html">Course hub</a> '
                  f'<span class="sep">/</span> <a href="{up}curriculum.html">'
                  f"Curriculum</a> {crumb_unit}")
        foot = ("The canonical text lives in the course repo — this page "
                "renders it, it does not replace it.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(doc_title)} — {e(suffix)}</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">{crumbs}</p>
  </header>
  {banner}
  <div class="doc">
{block_html(md_text, rr)}
  </div>
  {onward}
  <footer>{foot}</footer>
</div>
</body>
</html>
"""


def doc_depth(material: Material | None) -> int:
    """How many levels below the content root the served document sits —
    the reader mounts at read/<path>, so its relative links climb from
    there."""
    if material is None:
        return 1
    path = material.path
    if material.kind == "exercise":
        path = posixpath.join(path, "task.md")
    return len([p for p in ("read/" + path).split("/") if p]) - 1
