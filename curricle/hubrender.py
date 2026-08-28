"""Render a course hub page from a manifest.

The hub is the course's front door: progress checkboxes per phase, secondary
track steppers, material cards, trigger phrases, document links. It is a pure
function of the manifest — the generated page carries no hand-maintained data,
which is what retires the three-place registration rule.

Fidelity contract with the hand-built original (textual-flow's index.html):
same checkable ids, same localStorage key and value shape ({id: bool}), same
graceful degradation. Existing learner state loads unchanged.
"""

from __future__ import annotations

import html
import json

from .inlinemd import inline_html
from .schema import Manifest

STYLE = """\
  :root { --bg:#faf8f4; --panel:#fff; --ink:#2b2620; --muted:#7a7268; --line:#e3ddd2;
          --accent:#7c5cbf; --good:#4a7a4e; --chip:#f3efe8; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 Georgia, serif; }
  .wrap { max-width:980px; margin:0 auto; padding:28px 20px 80px; }
  h1 { font-size:28px; margin:0 0 4px; }
  h2 { font-size:19px; margin:34px 0 10px; }
  .sub { color:var(--muted); margin:0 0 6px; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px;
           padding:14px 16px; }
  .cols { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px; }
  .phase { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
  .phase h3 { margin:0 0 2px; font-size:15.5px; }
  .phase .goal { font:12.5px/1.45 ui-sans-serif,system-ui,sans-serif; color:var(--muted); margin:0 0 8px; }
  .unit { display:flex; align-items:baseline; gap:8px; font:13.5px/1.7 ui-sans-serif,system-ui,sans-serif; }
  .unit input { accent-color:var(--accent); transform:translateY(1px); }
  .unit label { cursor:pointer; }
  .unit.done label { color:var(--muted); text-decoration:line-through; }
  .tag { font-size:10.5px; border:1px solid var(--line); border-radius:999px; padding:0 6px;
         color:var(--muted); white-space:nowrap; }
  .tag.w { border-color:#c9b8ec; color:var(--accent); }
  #summary { border-left:3px solid var(--accent); background:var(--panel); padding:10px 14px;
             margin:14px 0 0; font:14px/1.6 ui-sans-serif,system-ui,sans-serif; }
  #bar { height:8px; background:var(--chip); border-radius:999px; overflow:hidden; margin-top:8px; }
  #fill { height:100%; background:var(--accent); width:0; transition:width .3s; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
  .card h3 { margin:0 0 4px; font-size:15.5px; }
  .card h3 a { color:var(--accent); text-decoration:none; }
  .card p { margin:0; font:13px/1.5 ui-sans-serif,system-ui,sans-serif; color:var(--muted); }
  .say { font-family:ui-monospace,Menlo,monospace; font-size:13px; background:var(--chip);
         padding:2px 7px; border-radius:6px; display:inline-block; margin:2px 0; }
  ul.docs { margin:6px 0 0; padding-left:20px; font:14px/1.9 ui-sans-serif,system-ui,sans-serif; }
  ul.docs a { color:var(--accent); text-decoration:none; }
  .track { display:flex; flex-wrap:wrap; gap:6px; align-items:center;
           font:13.5px ui-sans-serif,system-ui,sans-serif; }
  .track .step { border:1px solid var(--line); border-radius:999px; padding:3px 12px;
                 background:var(--chip); cursor:pointer; }
  .track .step.done { background:#eef4ec; border-color:var(--good); color:var(--good); }
  .track .arrow { color:var(--muted); }
  footer { margin-top:44px; font:12.5px ui-sans-serif,system-ui,sans-serif; color:var(--muted); }
  code { font-family:ui-monospace,Menlo,monospace; font-size:.92em; background:var(--chip);
         padding:0 4px; border-radius:4px; }
"""

SCRIPT = """\
const KEY = %(key)s;
const PHASES = %(phases)s;
const TRACKS = %(tracks)s;

let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
function persist() { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {} }

const allUnits = PHASES.flatMap(p => p.units.map(u => u[0]));
function refresh() {
  const done = allUnits.filter(id => saved[id]).length;
  let next = null;
  for (const p of PHASES) { for (const u of p.units) if (!saved[u[0]]) { next = u[1]; break; } if (next) break; }
  document.getElementById("fill").style.width = Math.round(100 * done / allUnits.length) + "%%";
  document.getElementById("summary").innerHTML = next
    ? `<b>${done}/${allUnits.length}</b> program-track items done · next up: <b>${next}</b>`
    : `<b>Course complete.</b>`;
}

const phasesDiv = document.getElementById("phases");
for (const p of PHASES) {
  const div = document.createElement("div");
  div.className = "phase";
  const h = document.createElement("h3"); h.textContent = p.name;
  const g = document.createElement("p"); g.className = "goal";
  g.innerHTML = p.goal;   // pre-rendered by the generator; no user content

  div.appendChild(h); div.appendChild(g);
  for (const [id, label, tags] of p.units) {
    const row = document.createElement("div");
    row.className = "unit" + (saved[id] ? " done" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.id = id; cb.checked = !!saved[id];
    cb.onchange = () => { saved[id] = cb.checked; persist(); row.classList.toggle("done", cb.checked); refresh(); };
    const lb = document.createElement("label");
    lb.htmlFor = id; lb.textContent = label;
    row.appendChild(cb); row.appendChild(lb);
    for (const t of tags || []) {
      const s = document.createElement("span");
      s.className = "tag" + (t === "widget" ? " w" : ""); s.textContent = t;
      row.appendChild(s);
    }
    div.appendChild(row);
  }
  phasesDiv.appendChild(div);
}

for (const track of TRACKS) {
  const el = document.getElementById("track-" + track.id);
  track.stages.forEach(([id, label], i) => {
    if (i) { const a = document.createElement("span"); a.className = "arrow"; a.textContent = "\\u2192"; el.appendChild(a); }
    const b = document.createElement("span");
    b.className = "step" + (saved[id] ? " done" : "");
    b.textContent = label;
    b.onclick = () => { saved[id] = !saved[id]; persist(); b.classList.toggle("done", saved[id]); };
    el.appendChild(b);
  });
}
refresh();
"""


def render_hub(mf: Manifest) -> str:
    c = mf.course
    e = html.escape
    units_by_id = {u.id: u for u in mf.units}
    milestones_by_id = {m.id: m for m in mf.milestones}

    # --- data payloads ------------------------------------------------------
    phases_js = []
    for p in mf.phases:
        rows = []
        for entry in p.entries:
            if entry in units_by_id:
                u = units_by_id[entry]
                tags = list(mf.tags_for_unit(u.id))
                if u.steps:
                    for s in u.steps:
                        rows.append([s.id, s.label, []])
                    if tags and rows:
                        rows[-1][2] = tags   # chips ride the last step, hub-style
                else:
                    rows.append([u.id, f"Unit {u.num} · {u.title}", tags])
            else:
                rows.append([entry, milestones_by_id[entry].label, []])
        phases_js.append({"name": f"Phase {p.num} — {p.title}",
                          "goal": inline_html(p.goal), "units": rows})
    tracks_js = [{"id": t.id, "stages": [[s.id, s.label] for s in t.stages]}
                 for t in mf.tracks]

    # --- sections -----------------------------------------------------------
    parts: list[str] = []
    parts.append(f"<h1>{e(c.id)}</h1>")
    if c.description:
        parts.append(f'<p class="sub">{e(c.description)} Tick things off as they are '
                     "truly done; progress lives in this browser only.</p>")
    parts.append('<div id="summary"></div>\n<div id="bar"><div id="fill"></div></div>')

    parts.append("<h2>The program track</h2>\n"
                 '<div class="cols" id="phases"></div>')

    for t in mf.tracks:
        cadence = f' <span class="sub" style="font-size:13px">({e(t.cadence)})</span>' \
            if t.cadence else ""
        parts.append(f"<h2>The {e(t.name)} track{cadence}</h2>\n"
                     f'<div class="panel track" id="track-{e(t.id)}"></div>')

    cards = [m for m in mf.materials
             if m.kind in ("widget", "trainer", "quiz") ]
    if cards:
        parts.append("<h2>Widgets &amp; quizzes "
                     '<span class="sub" style="font-size:13px">(self-contained — '
                     "they open right here in the browser)</span></h2>")
        parts.append('<div class="cols">')
        for m in cards:
            blurb = f"<p>{e(m.blurb)}</p>" if m.blurb else ""
            parts.append(f'<div class="card"><h3><a href="{e(m.path)}">'
                         f"{e(m.title)}</a></h3>{blurb}</div>")
        parts.append("</div>")

    if c.trigger_phrases:
        parts.append("<h2>Worked with Claude "
                     '<span class="sub" style="font-size:13px">(open a fresh chat '
                     "in this repo and say the words)</span></h2>")
        parts.append('<div class="panel" style="font:14px/2 ui-sans-serif,system-ui,sans-serif">')
        for tp in c.trigger_phrases:
            note = f" — {e(tp.note)}" if tp.note else ""
            parts.append(f'<div><span class="say">{e(tp.say)}</span>{note}</div>')
        parts.append("</div>")

    exercises = [m for m in mf.materials if m.kind == "exercise"]
    if exercises:
        parts.append("<h2>Exercises "
                     '<span class="sub" style="font-size:13px">(stub + failing tests; '
                     "green bar = done — run in a terminal)</span></h2>")
        parts.append('<div class="cols">')
        for m in exercises:
            blurb = e(m.blurb) if m.blurb else ""
            cmd = (f" <code>{e(m.grader.command)}</code>"
                   if m.grader and m.grader.command else "")
            parts.append(f'<div class="card"><h3>{e(m.title)}</h3>'
                         f"<p>{blurb}{cmd}</p></div>")
        parts.append("</div>")

    doc_items = []
    d = c.docs
    if d.curriculum_doc:
        doc_items.append(f'<li><a href="curriculum.md">curriculum.md</a> — the whole course: '
                         f"{len(mf.phases)} phases, {len(mf.units)} units</li>")
    if d.resources_doc:
        doc_items.append('<li><a href="learning-resources.md">learning-resources.md</a> — '
                         "every source, tiered by role</li>")
    if d.readme:
        doc_items.append('<li><a href="README.md">README.md</a> — how to drive all of this</li>')
    if d.review:
        doc_items.append('<li><a href="../REVIEW.md">../REVIEW.md</a> — research positioning</li>')
    if d.exploration:
        doc_items.append('<li><a href="../exploration/">../exploration/</a> — how this '
                         "program was chosen</li>")
    if doc_items:
        parts.append("<h2>The documents</h2>\n<div class=\"panel\"><ul class=\"docs\">"
                     + "\n".join(doc_items) + "</ul></div>")

    parts.append(f"<footer>{e(c.id)} course hub · generated by curricle from the "
                 f"course manifest · course v{e(c.version.rev)} — {e(c.version.date)} · "
                 "progress is stored in this browser's localStorage</footer>")

    script = SCRIPT % {
        "key": json.dumps(c.progress_storage_key),
        "phases": json.dumps(phases_js, ensure_ascii=False),
        "tracks": json.dumps(tracks_js, ensure_ascii=False),
    }
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c.id)} — course hub</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">
{body}
</div>
<script>
{script}</script>
</body>
</html>
"""
