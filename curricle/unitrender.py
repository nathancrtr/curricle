"""Render the per-unit page and the document reader (SPIKE: one-stop-shop).

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

from . import theme
from .blockmd import block_html
from .inlinemd import inline_html
from .schema import Manifest, Material, Unit

STYLE = theme.style("""\
  .wrap { max-width:760px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:36px 0 10px; }
  h1 { font-weight:700; font-size:clamp(26px,5vw,36px); line-height:1.15;
       letter-spacing:-.01em; margin:14px 0 0; }
  .gloss { margin:12px 0 0; color:var(--muted); font-size:16px; max-width:62ch; }
  .actions { display:flex; align-items:center; gap:14px; margin:20px 0 0; }
  .row { margin:0 0 14px; font-size:14.5px; line-height:1.6; max-width:68ch; }
  .row b.lbl { display:block; font-size:11.5px; font-weight:700;
               letter-spacing:.06em; text-transform:uppercase;
               color:var(--muted); margin:0 0 3px; }
  .key { background:var(--accent-soft); padding:11px 15px; border-radius:12px; }
  .key b.lbl { color:var(--accent-text); }
  .rows { margin:30px 0 0; }
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
  .card { padding:15px 18px 13px; }
  .card h3 { margin:0 0 6px; font-size:16px; }
  .card h3 a { text-decoration:none; }
  .card h3 a:hover { text-decoration:underline; text-underline-offset:3px; }
  .card p { margin:0 0 8px; font-size:13.5px; color:var(--muted); line-height:1.5; }
  .card .chip { margin:0; }
  details.check { margin:26px 0 0; padding:13px 17px; background:var(--panel);
                  border:1.5px solid var(--line); border-radius:14px;
                  font-size:14.5px; }
  details.check summary { cursor:pointer; font-weight:600; }
  details.check div { margin-top:10px; color:var(--muted); }
  .cp { margin:30px 0 0; padding:16px 20px; background:var(--good-soft);
        border:1px solid var(--good); border-radius:16px; font-size:14.5px; }
  .cp b { display:block; font-size:12px; font-weight:700; letter-spacing:.06em;
          text-transform:uppercase; color:var(--good-text); margin:0 0 6px; }

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

# What a card invites you to do, by material kind. The verb is the label —
# the chip beside it says what the thing is, in words, per the house rule.
_VERB = {"lesson": "Read the lesson guide", "widget": "Open the widget",
         "trainer": "Open the trainer", "quiz": "Take the quiz",
         "exercise": "Read the brief", "companion": "Open",
         "question-bank": "Browse the questions"}


def _material_href(m: Material) -> str:
    # Served-app hrefs, relative to /c/<slug>/unit/<id>.html — one level up.
    if m.kind == "exercise":
        return "../read/" + posixpath.join(m.path, "task.md")
    if m.path.endswith(".md"):
        return "../read/" + m.path
    return "../" + m.path


def _cards(materials: tuple[Material, ...]) -> str:
    e = html.escape
    cards = []
    for m in materials:
        blurb = f"<p>{e(m.blurb)}</p>" if m.blurb else ""
        cards.append(
            f'<div class="card panel"><h3><a href="{e(_material_href(m))}">'
            f'{e(_VERB.get(m.kind, "Open"))}</a></h3>{blurb}'
            f'<span class="chip{" acc" if m.kind in ("widget", "trainer") else ""}">'
            f"{e(m.kind)}</span> {e(m.title)}</div>")
    return f'<div class="grid">{"".join(cards)}</div>'


def render_unit(mf: Manifest, unit_id: str, *, api: str,
                initial: dict | None = None) -> str:
    e = html.escape
    u: Unit = mf.unit(unit_id)
    phase = next((p for p in mf.phases if unit_id in p.entries), None)

    rows = []
    for r in u.rows:
        cls = " key" if r.kind == "key" else ""
        rows.append(f'<div class="row{cls}"><b class="lbl">{e(r.label)}</b>'
                    f"{inline_html(r.content)}</div>")

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
                     "open right in the browser.</p>" + _cards(mats)
                     + "</section>")

    check = ""
    if u.check:
        check = (f'<details class="check"><summary>Check yourself: '
                 f"{inline_html(u.check.q)}</summary>"
                 f"<div>{inline_html(u.check.ans)}</div></details>")

    cp = ""
    if phase:
        quizzes = [m for m in mf.materials
                   if m.kind == "quiz" and m.phase == phase.id]
        if quizzes:
            links = " · ".join(
                f'<a href="{e(_material_href(m))}">{e(m.title)}</a>'
                for m in quizzes)
            cp = (f'<div class="cp"><b>Phase {phase.num} checkpoint</b>'
                  f"This unit builds toward it — {links}.</div>")

    phase_crumb = (f'<span class="sep">·</span> phase {phase.num}'
                   if phase else "")
    script = SCRIPT % {
        "api": json.dumps(api),
        "unit": json.dumps({"id": u.id,
                            "steps": [s.id for s in u.steps]}),
        "initial": json.dumps(initial, ensure_ascii=False),
    }
    gloss = f'<p class="gloss">{inline_html(u.gloss)}</p>' if u.gloss else ""
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
    <div class="actions">
      <button class="pill" id="mark" aria-pressed="false">Mark done</button>
    </div>
  </header>
  <div class="rows">{"".join(rows)}</div>
  {steps}
  {mats_html}
  {check}
  {cp}
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
                  material: Material | None = None) -> str:
    e = html.escape
    unit_href = (f"unit/{material.unit}.html"
                 if material and material.unit else "curriculum.html")
    banner = ""
    if material and material.kind == "lesson":
        say = next((tp.say for tp in mf.course.trigger_phrases
                    if "lesson" in tp.say.lower()), None)
        phrase = (f' — open a fresh Claude chat in the course repo and say '
                  f'<span class="say">{e(say)}</span>' if say else "")
        banner = ('<div class="banner"><b>This is a dialogue script.</b> '
                  "It is written for a tutor to run with you, one question "
                  f"at a time{phrase}. Reading it straight through works too "
                  "— the questions are the lesson.</div>")
    depth = "../" * (doc_depth(material) if material else 1)
    crumb_unit = (f'<span class="sep">·</span> <a href="{depth}{e(unit_href)}">'
                  f"its unit</a>"
                  if material and material.unit else "")
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
    <p class="eyebrow"><a href="{depth}index.html">← course hub</a>
    <span class="sep">·</span> <a href="{depth}curriculum.html">curriculum</a>
    {crumb_unit}</p>
  </header>
  {banner}
  <div class="doc">
{block_html(md_text)}
  </div>
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
