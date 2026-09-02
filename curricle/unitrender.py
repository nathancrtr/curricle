"""Render the per-unit page and the document reader.

The unit page is the click target the curriculum was missing: everything a
unit owns, on one served page — the unit's own rows and steps, its lesson,
widgets, quizzes and exercise briefs as cards, and the phase checkpoint it
feeds. It exists only on the served app (the standalone exports keep their
current shape): the whole point is that the links resolve against the
content routes.

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
  .wrap { max-width:760px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:36px 0 10px; }
  h1 { font-weight:700; font-size:clamp(26px,5vw,36px); line-height:1.15;
       letter-spacing:-.01em; margin:14px 0 0; }
  .gloss { margin:12px 0 0; color:var(--muted); font-size:16px; max-width:62ch; }
  .phasegoal { margin:10px 0 0; color:var(--muted); font-size:14px; max-width:66ch; }
  .phasegoal b { color:var(--ink); font-weight:600; }
  .context { margin:14px 0 0; color:var(--muted); font-size:13.5px;
             line-height:1.7; max-width:68ch; }
  .context .chip { vertical-align:1px; }
  .chip.gate { background:var(--warn-soft); color:var(--warn-text); }
  .actions { display:flex; align-items:center; gap:14px; margin:20px 0 0; }
  .row { margin:0 0 14px; font-size:14.5px; line-height:1.6; max-width:68ch; }
  .row b.lbl { display:block; font-size:11.5px; font-weight:700;
               letter-spacing:.06em; text-transform:uppercase;
               color:var(--muted); margin:0 0 3px; }
  .key { background:var(--accent-soft); padding:11px 15px; border-radius:12px; }
  .key b.lbl { color:var(--accent-text); }
  /* The deliverable takes the green family — the tint that means "done"
     everywhere else, because the milestone is what done will mean here. */
  .deliver { background:var(--good-soft); padding:11px 15px; border-radius:12px; }
  .deliver b.lbl { color:var(--good-text); }
  .rows { margin:30px 0 0; }
  .unote { margin:24px 0 0; padding:13px 17px; background:var(--chip);
           border-radius:14px; font-size:14px; line-height:1.6;
           max-width:68ch; }
  .unote b.lbl { display:block; font-size:11.5px; font-weight:700;
                 letter-spacing:.06em; text-transform:uppercase;
                 color:var(--muted); margin:0 0 3px; }
  .steps { margin:26px 0 0; padding:16px 20px; }
  .steps h2 { font-size:13px; font-weight:700; letter-spacing:.06em;
              text-transform:uppercase; color:var(--muted); margin:0 0 10px; }
  .step-row { display:flex; align-items:baseline; gap:9px; font-size:14.5px;
              margin:0 0 6px; }
  .step-row input { width:17px; height:17px; accent-color:var(--accent-strong); }
  .step-row.done label { color:var(--muted); text-decoration:line-through;
                         text-decoration-color:var(--faint); }
  .mats { margin:34px 0 0; }
  .mats h2 { font-size:20px; font-weight:700; margin:0 0 4px; }
  .mats .sub { color:var(--muted); font-size:14px; margin:0 0 14px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
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
  details.check { margin:26px 0 0; padding:13px 17px; background:var(--panel);
                  border:1.5px solid var(--line); border-radius:14px;
                  font-size:14.5px; }
  details.check summary { cursor:pointer; font-weight:600; }
  details.check div { margin-top:10px; color:var(--muted); }
  .cp { margin:30px 0 0; padding:16px 20px; background:var(--good-soft);
        border:1px solid var(--good); border-radius:16px; font-size:14.5px; }
  .cp b.cpl { display:block; font-size:12px; font-weight:700; letter-spacing:.06em;
              text-transform:uppercase; color:var(--good-text); margin:0 0 6px; }
  .cp .track-goal { margin-top:8px; color:var(--muted); }
  .unav { display:flex; align-items:center; gap:12px; margin:42px 0 0; }
  .unav .spacer { flex:1 1 auto; }
  .unav a { max-width:46%; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; text-decoration:none; }

  /* ---- the reader ---- */
  .doc { margin:26px 0 0; font-size:15.5px; line-height:1.65; }
  .doc h1 { font-size:clamp(24px,4.5vw,32px); margin:26px 0 8px; }
  .doc h2 { font-size:20px; margin:30px 0 8px; }
  .doc h3 { font-size:16.5px; margin:24px 0 6px; }
  .doc p, .doc li { max-width:68ch; }
  .doc li { margin:0 0 6px; }
  .doc blockquote { margin:14px 0; padding:10px 16px; border-left:3px solid
                    var(--accent); background:var(--accent-soft);
                    border-radius:0 12px 12px 0; }
  .doc blockquote p { margin:0; }
  .doc pre { background:var(--chip); padding:12px 15px; border-radius:12px;
             overflow-x:auto; font-size:13px; line-height:1.5; }
  .doc pre code { background:none; padding:0; }
  .doc .tablewrap { overflow-x:auto; }
  .doc table { border-collapse:collapse; font-size:14px; }
  .doc th, .doc td { border:1px solid var(--line); padding:5px 11px; text-align:left; }
  .doc th { background:var(--chip); }
  .banner { margin:22px 0 0; padding:13px 17px; border:1.5px solid var(--line);
            border-radius:14px; font-size:14px; color:var(--muted);
            background:var(--panel); }
  .banner b { color:var(--ink); }
  .say { font:13px """ + theme.FONT_MONO + """; background:var(--chip);
         padding:2px 8px; border-radius:8px; }
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
_VERB = {"lesson": "Read the lesson guide", "widget": "Open the widget",
         "trainer": "Open the trainer", "quiz": "Take the quiz",
         "exercise": "Read the brief", "companion": "Read the companion",
         "question-bank": "Browse the questions"}


def _cards(materials: tuple[Material, ...], rr: RefResolver) -> str:
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
            f'{e(_VERB.get(m.kind, "Open"))} →</a></div>')
    return f'<div class="grid">{"".join(cards)}</div>'


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


def render_unit(mf: Manifest, unit_id: str, *, api: str,
                initial: dict | None = None) -> str:
    e = html.escape
    u: Unit = mf.unit(unit_id)
    rr = RefResolver(mf, to_root="../")   # the page sits at unit/<id>.html
    phase = next((p for p in mf.phases if unit_id in p.entries), None)

    rows = []
    for r in u.rows:
        if r.label == "Interactive":
            continue    # derived: the materials section below is that row
        cls = ""
        if r.kind == "key":
            cls = " key"
        elif r.label == "Milestone":
            cls = " deliver"
        rows.append(f'<div class="row{cls}"><b class="lbl">{e(r.label)}</b>'
                    f"{inline_html(r.content, rr)}</div>")

    note = ""
    if u.note:
        note = (f'<div class="unote"><b class="lbl">Note</b>'
                f"{inline_html(u.note, rr)}</div>")

    steps = ""
    if u.steps:
        items = "".join(
            f'<div class="step-row"><input type="checkbox" id="{e(s.id)}">'
            f'<label for="{e(s.id)}">{e(s.label)}</label></div>'
            for s in u.steps)
        steps = f'<div class="steps panel"><h2>The steps</h2>{items}</div>'

    mats = mf.materials_for_unit(unit_id)
    mats_html = ""
    if mats:
        mats_html = ('<section class="mats"><h2>This unit\'s materials</h2>'
                     '<p class="sub">Lessons read here; widgets and quizzes '
                     "open right in the browser.</p>" + _cards(mats, rr)
                     + "</section>")

    check = ""
    if u.check:
        check = (f'<details class="check"><summary>Check yourself: '
                 f"{inline_html(u.check.q, rr)}</summary>"
                 f"<div>{inline_html(u.check.ans, rr)}</div></details>")

    # The phase's walking order of units, for prev/next and for knowing
    # whether this unit is the one the checkpoint lands on.
    ordered = [uid for p in mf.phases for uid in p.entries
               if any(x.id == uid for x in mf.units)]
    last_in_phase = phase and [uid for uid in phase.entries
                               if any(x.id == uid for x in mf.units)][-1] == unit_id

    cp = ""
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
            cp = (f'<div class="cp"><b class="cpl">Phase {phase.num} checkpoint '
                  f"— this unit closes the phase</b>"
                  f"<p>{inline_html(phase.checkpoint.prose, rr)}</p>"
                  f"{goals}{quiz_line}</div>")
        elif links:
            cp = (f'<div class="cp"><b class="cpl">Phase {phase.num} checkpoint</b>'
                  f"This unit builds toward it — {links}.</div>")

    # Prev/next: the course is a path; the page says where it continues.
    pos = ordered.index(unit_id)
    units_by_id = {x.id: x for x in mf.units}
    nav = ""
    if len(ordered) > 1:
        parts = []
        if pos > 0:
            p_u = units_by_id[ordered[pos - 1]]
            parts.append(f'<a class="pill" href="{e(p_u.id)}.html">'
                         f"← Unit {p_u.num} — {e(p_u.title)}</a>")
        parts.append('<span class="spacer"></span>')
        if pos + 1 < len(ordered):
            n_u = units_by_id[ordered[pos + 1]]
            parts.append(f'<a class="pill primary" href="{e(n_u.id)}.html">'
                         f"Unit {n_u.num} — {e(n_u.title)} →</a>")
        nav = f'<nav class="unav">{"".join(parts)}</nav>'

    phase_line = ""
    if phase:
        phase_line = (f'<p class="phasegoal"><b>Phase {phase.num} — '
                      f"{e(phase.title)}.</b> {inline_html(phase.goal, rr)}</p>")

    phase_crumb = (f'<span class="sep">·</span> phase {phase.num}'
                   if phase else "")
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
    <p class="eyebrow"><a href="../index.html">← course hub</a>
    <span class="sep">·</span> <a href="../curriculum.html">curriculum</a>
    <span class="sep">·</span> unit {u.num:02d}{phase_crumb}</p>
    <h1>{e(u.title)}</h1>
    {gloss}
    {phase_line}
    {_context_line(mf, u, rr)}
    <div class="actions">
      <button class="pill" id="mark" aria-pressed="false">Mark done</button>
    </div>
  </header>
  <div class="rows">{"".join(rows)}</div>
  {note}
  {steps}
  {mats_html}
  {check}
  {cp}
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


def render_reader(mf: Manifest, md_text: str, *, doc_title: str,
                  material: Material | None = None,
                  depth: int | None = None) -> str:
    e = html.escape
    if depth is None:
        depth = doc_depth(material) if material else 1
    up = "../" * depth
    rr = RefResolver(mf, to_root=up)   # the reader exists only served
    unit = (next((x for x in mf.units if x.id == material.unit), None)
            if material and material.unit else None)
    unit_href = f"unit/{unit.id}.html" if unit else "curriculum.html"
    banner = ""
    if material and material.kind == "lesson":
        # The course's own trigger phrase, aimed at *this* unit: the corpus
        # phrases name a unit by number ("Teach me Unit 2 interactively."),
        # so the example is retargeted rather than always citing Unit 2.
        say = next((tp.say for tp in mf.course.trigger_phrases
                    if "teach" in tp.say.lower() or "lesson" in tp.say.lower()),
                   None)
        if say and unit:
            say = re.sub(r"[Uu]nit \d+", f"Unit {unit.num}", say)
        phrase = (f' — open a fresh Claude chat in the course repo and say '
                  f'<span class="say">{e(say)}</span>' if say else "")
        banner = ('<div class="banner"><b>This is a dialogue script.</b> '
                  "It is written for a tutor to run with you, one question "
                  f"at a time{phrase}. Reading it straight through works too "
                  "— the questions are the lesson.</div>")
    crumb_unit = (f'<span class="sep">·</span> <a href="{up}{e(unit_href)}">'
                  f"its unit</a>"
                  if unit else "")
    # The document flows back into the course: the way on from the last
    # line is the unit the document belongs to, not the browser's Back.
    onward = ""
    if unit:
        onward = (f'<nav class="unav"><span class="spacer"></span>'
                  f'<a class="pill primary" href="{up}{e(unit_href)}">'
                  f"Back to Unit {unit.num} — {e(unit.title)} →</a></nav>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(doc_title)} — {e(mf.course.title)}</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow"><a href="{up}index.html">← course hub</a>
    <span class="sep">·</span> <a href="{up}curriculum.html">curriculum</a>
    {crumb_unit}</p>
  </header>
  {banner}
  <div class="doc">
{block_html(md_text, rr)}
  </div>
  {onward}
  <footer>The canonical text lives in the course repo — this page renders it,
    it does not replace it.</footer>
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
