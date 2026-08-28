"""Render the curriculum view from a manifest.

The replacement for the hand-mirrored curriculum.html: every unit as an
expandable entry (syllabus rows, check-yourself, per-unit note), phase
checkpoints with track goals, a done-meter and remaining-filter. Progress
shares the hub's localStorage key and shape; notes live in their own key —
both taken from the manifest, so the legacy keys survive.

Design and interaction are ported from textual-flow's hand-built page; the
data is a pure function of the manifest. Stepped units improve on the
original's composite-id mapping: the steps render as their own checkboxes
inside the entry, and "Mark done" marks them all.
"""

from __future__ import annotations

import html
import json

from .inlinemd import inline_html
from .schema import Manifest

STYLE = """\
  :root { --bg:#faf8f4; --panel:#fff; --ink:#2b2620; --muted:#7a7268; --faint:#a29a8e;
          --line:#e3ddd2; --line-soft:#eee9e0; --accent:#7c5cbf; --accent-ink:#fff;
          --marker:rgba(124,92,191,.16); --good:#4a7a4e; --chip:#f3efe8; }
  * { box-sizing:border-box; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.6 Georgia, 'Times New Roman', serif; }
  a { color:var(--accent); }
  :focus-visible { outline:2px solid var(--accent); outline-offset:3px; border-radius:2px; }
  .wrap { max-width:820px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:56px 0 26px; }
  .eyebrow { font:11px ui-monospace,Menlo,monospace; letter-spacing:.15em; text-transform:uppercase;
             color:var(--faint); margin:0 0 18px; }
  .eyebrow a { color:var(--accent); text-decoration:none; }
  h1 { font-weight:400; font-size:clamp(34px,6.5vw,50px); line-height:1.06;
       letter-spacing:-.01em; margin:0; }
  .standfirst { max-width:54ch; margin:18px 0 0; color:var(--muted); font-size:16px; }
  .how { margin:30px 0 0; padding:16px 18px; border:1px solid var(--line); border-radius:8px;
         background:var(--panel); }
  .how h2 { font:500 11px ui-monospace,Menlo,monospace; letter-spacing:.14em;
            text-transform:uppercase; color:var(--faint); margin:0 0 10px; }
  .how p { margin:0 0 10px; font-size:14.5px; }
  .how p:last-child { margin-bottom:0; }
  .controls { display:flex; flex-wrap:wrap; align-items:center; gap:14px 22px;
              margin:30px 0 0; padding:14px 0;
              border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
  .meter { display:flex; align-items:center; gap:12px; }
  .ticks { display:flex; gap:3px; flex-wrap:wrap; max-width:340px; }
  .tick { width:10px; height:5px; border-radius:1px; background:var(--line);
          transition:background .35s ease; }
  .tick.on { background:var(--accent); }
  .count { font:11.5px ui-monospace,Menlo,monospace; letter-spacing:.05em;
           color:var(--muted); white-space:nowrap; }
  .spacer { flex:1 1 auto; }
  button { font:inherit; color:inherit; background:none; border:none; padding:0; cursor:pointer; }
  .filter { font:11px ui-monospace,Menlo,monospace; letter-spacing:.11em; text-transform:uppercase;
            color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:6px 13px;
            transition:.2s; }
  .filter:hover { border-color:var(--accent); color:var(--ink); }
  .filter[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
  .phase { margin:52px 0 0; }
  .phase-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 14px;
                padding-bottom:9px; border-bottom:2px solid var(--ink); }
  .phase-tag { font:500 11px ui-monospace,Menlo,monospace; letter-spacing:.15em; text-transform:uppercase; }
  .phase-name { font-size:19px; font-style:italic; color:var(--muted); }
  .phase-weeks { font:11px ui-monospace,Menlo,monospace; color:var(--faint); margin-left:auto; }
  .phase-goal { margin:12px 0 0; font-size:14.5px; color:var(--muted); max-width:64ch; }
  .entry { border-bottom:1px solid var(--line-soft); }
  .entry.hidden { display:none; }
  .head { display:grid; grid-template-columns:44px 1fr; gap:0 16px; width:100%;
          text-align:left; padding:20px 0 4px; }
  .head:hover .title { text-decoration:underline; text-decoration-color:var(--line);
                       text-underline-offset:4px; }
  .num { font:11.5px ui-monospace,Menlo,monospace; color:var(--faint); padding-top:6px; }
  .body-col { min-width:0; }
  .title { font-weight:400; font-size:20px; line-height:1.25; margin:0; }
  .tag { display:inline-block; vertical-align:2px; margin-left:8px;
         font:500 9px ui-monospace,Menlo,monospace; letter-spacing:.12em; text-transform:uppercase;
         color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:1px 7px; }
  .tag.w { color:var(--accent); border-color:#cfc0ea; }
  .gloss { position:relative; margin:9px 0 0; font-size:14.5px; max-width:60ch; color:var(--ink); }
  .gloss-mark { position:absolute; z-index:0; inset:-.1em -.4em -.05em -.3em;
                background:var(--marker); border-radius:.6em .2em .5em .3em;
                transform:scaleX(0); transform-origin:0 50%;
                transition:transform .55s cubic-bezier(.2,.7,.3,1); }
  .gloss-text { position:relative; z-index:1; }
  .entry.done .gloss-mark { transform:scaleX(1); }
  .actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px 18px;
             margin:10px 0 0; padding:0 0 18px 60px; }
  .act { font:10.5px ui-monospace,Menlo,monospace; letter-spacing:.1em; text-transform:uppercase;
         color:var(--muted); transition:color .2s; }
  .act:hover { color:var(--ink); }
  .chev { display:inline-block; transition:transform .3s ease; margin-right:6px; }
  .entry.open .chev { transform:rotate(90deg); }
  .mark { display:flex; align-items:center; gap:7px; }
  .dot { width:9px; height:9px; border-radius:50%; border:1px solid var(--faint);
         background:transparent; transition:.3s; }
  .entry.done .dot { background:var(--accent); border-color:var(--accent); }
  .detail { display:grid; grid-template-rows:0fr; transition:grid-template-rows .35s cubic-bezier(.4,0,.2,1); }
  .entry.open .detail { grid-template-rows:1fr; }
  .detail-inner { overflow:hidden; }
  .detail-pad { padding:0 0 26px 60px; max-width:66ch; }
  .row { margin:0 0 12px; font-size:14.5px; }
  .row b.lbl { display:block; font:500 10px ui-monospace,Menlo,monospace; letter-spacing:.14em;
               text-transform:uppercase; color:var(--faint); margin:0 0 3px; }
  .row a { text-underline-offset:2px; }
  .key { border-left:3px solid var(--accent); background:var(--panel); padding:9px 13px;
         border-radius:0 6px 6px 0; }
  .steps { margin:0 0 12px; }
  .step-row { display:flex; align-items:baseline; gap:8px; font-size:14.5px; margin:0 0 4px; }
  .step-row input { accent-color:var(--accent); }
  .step-row.done label { color:var(--muted); text-decoration:line-through; }
  .notes-label { display:block; font:500 10px ui-monospace,Menlo,monospace; letter-spacing:.14em;
                 text-transform:uppercase; color:var(--faint); margin:18px 0 6px; }
  textarea { width:100%; min-height:64px; resize:vertical; font:14px/1.55 ui-sans-serif,system-ui,sans-serif;
             color:var(--ink); background:var(--panel); border:1px solid var(--line);
             border-radius:6px; padding:10px 12px; }
  textarea::placeholder { color:var(--faint); }
  .checkpoint { margin:26px 0 0; padding:14px 17px; background:var(--panel);
                border:1px solid var(--line); border-left:3px solid var(--good); border-radius:8px;
                font-size:14.5px; }
  .checkpoint b.cp { display:block; font:500 10.5px ui-monospace,Menlo,monospace;
                     letter-spacing:.14em; text-transform:uppercase; color:var(--good); margin:0 0 6px; }
  .checkpoint .track-goal { margin-top:8px; color:var(--muted); }
  details.check { margin:22px 0 0; padding:12px 16px; background:var(--panel);
                  border:1px solid var(--line); border-radius:8px; font-size:14.5px; }
  details.check summary { cursor:pointer; font-weight:700; }
  details.check div { margin-top:10px; color:var(--muted); }
  .section { margin:56px 0 0; }
  .section > h2 { font-size:22px; font-weight:400; margin:0 0 6px; padding-bottom:8px;
                  border-bottom:2px solid var(--ink); }
  .section p, .section li { font-size:14.5px; }
  .section .sub { color:var(--muted); margin:10px 0 0; }
  .say { font:13px ui-monospace,Menlo,monospace; background:var(--chip); padding:2px 7px;
         border-radius:6px; }
  .saylist { list-style:none; padding:0; margin:12px 0 0; }
  .saylist li { margin:0 0 9px; }
  code { font-family:ui-monospace,Menlo,monospace; font-size:.92em; background:var(--chip);
         padding:0 4px; border-radius:4px; }
  .empty { display:none; padding:44px 0; text-align:center; font-style:italic;
           font-size:18px; color:var(--muted); }
  .empty.show { display:block; }
  footer { margin-top:64px; padding-top:22px; border-top:1px solid var(--line);
           font:12.5px ui-sans-serif,system-ui,sans-serif; color:var(--muted); }
  .saving { position:fixed; bottom:18px; left:50%; transform:translateX(-50%) translateY(12px);
            font:10px ui-monospace,Menlo,monospace; letter-spacing:.12em; text-transform:uppercase;
            background:var(--ink); color:var(--bg); padding:7px 14px; border-radius:3px;
            opacity:0; pointer-events:none; transition:.25s; }
  .saving.show { opacity:1; transform:translateX(-50%) translateY(0); }
  @media (max-width:620px) {
    .head { grid-template-columns:1fr; }
    .num { padding:0 0 4px; }
    .actions, .detail-pad { padding-left:0; }
    .phase-weeks { margin-left:0; }
  }
  @media (prefers-reduced-motion:reduce) {
    * { transition-duration:.01ms !important; }
  }
"""

SCRIPT = """\
const KEY = %(key)s;
const NOTES_KEY = %(notes_key)s;
const PHASES = %(phases)s;
const HUB_IDS = %(hub_ids)s;

let progress = {}, notes = {};
try { progress = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
try { notes = JSON.parse(localStorage.getItem(NOTES_KEY) || "{}"); } catch (e) {}

const isDone = e => e.steps ? e.steps.every(s => progress[s[0]]) : !!progress[e.id];
const setDone = (e, v) => { if (e.steps) e.steps.forEach(s => progress[s[0]] = v); else progress[e.id] = v; };

const $ = id => document.getElementById(id);
function persist(key, obj) { try { localStorage.setItem(key, JSON.stringify(obj)); toast("Saved"); } catch (e) {} }
let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1200);
}

const ALL = PHASES.flatMap(p => p.entries);
const esc = s => s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function render() {
  $("list").innerHTML = PHASES.map(p => `
    <section class="phase">
      <div class="phase-head">
        <span class="phase-tag">${p.tag}</span>
        <span class="phase-name">${p.name}</span>
        <span class="phase-weeks">${p.weeks}</span>
      </div>
      <p class="phase-goal">${p.goal}</p>
      ${p.entries.map(e => `
        <article class="entry${isDone(e) ? " done" : ""}" data-id="${e.id}">
          <button class="head" aria-expanded="false">
            <span class="num">${e.num}</span>
            <span class="body-col">
              <h3 class="title">${e.title}${(e.tags || []).map(t =>
                `<span class="tag${t === "widget" ? " w" : ""}">${t}</span>`).join("")}</h3>
              ${e.gloss ? `<p class="gloss"><span class="gloss-mark"></span><span class="gloss-text">${e.gloss}</span></p>` : ""}
            </span>
          </button>
          <div class="actions">
            <button class="act toggle"><span class="chev">›</span><span class="tlabel">Full unit</span></button>
            <button class="act mark"><span class="dot"></span><span class="mlabel">${isDone(e) ? "Done" : "Mark done"}</span></button>
          </div>
          <div class="detail"><div class="detail-inner"><div class="detail-pad">
            ${e.steps ? `<div class="steps">${e.steps.map(([sid, slabel]) => `
              <div class="step-row${progress[sid] ? " done" : ""}">
                <input type="checkbox" id="${sid}" ${progress[sid] ? "checked" : ""}>
                <label for="${sid}">${slabel}</label>
              </div>`).join("")}</div>` : ""}
            ${e.rows.map(([lbl, html, cls]) =>
              `<div class="row ${cls || ""}"><b class="lbl">${lbl}</b>${html}</div>`).join("")}
            ${e.check ? `<details class="check"><summary>Check yourself: ${e.check.q}</summary><div>${e.check.ans}</div></details>` : ""}
            <label class="notes-label" for="n-${e.id}">Your note</label>
            <textarea id="n-${e.id}" placeholder="What stuck, what to chase, where the numbers disagreed…">${esc(notes[e.id] || "")}</textarea>
          </div></div></div>
        </article>`).join("")}
      ${p.checkpoint ? `<div class="checkpoint"><b class="cp">— ${p.tag} checkpoint —</b>${p.checkpoint.text}${(p.checkpoint.goals || []).map(g => `<div class="track-goal"><b>${g[0]}:</b> ${g[1]}</div>`).join("")}</div>` : ""}
    </section>`).join("");
  $("ticks").innerHTML = HUB_IDS.map(() => `<span class="tick"></span>`).join("");
  wire();
  updateMeter();
  applyFilter();
}

function updateMeter() {
  const done = HUB_IDS.filter(i => progress[i]).length;
  $("count").textContent = `${done} of ${HUB_IDS.length} done`;
  document.querySelectorAll(".tick").forEach((t, i) => t.classList.toggle("on", !!progress[HUB_IDS[i]]));
}

function openEntry(entry, want) {
  const on = want !== undefined ? want : !entry.classList.contains("open");
  entry.classList.toggle("open", on);
  entry.querySelector(".head").setAttribute("aria-expanded", String(on));
  entry.querySelector(".tlabel").textContent = on ? "Hide unit" : "Full unit";
}

function syncEntry(entry, e) {
  entry.classList.toggle("done", isDone(e));
  entry.querySelector(".mlabel").textContent = isDone(e) ? "Done" : "Mark done";
  updateMeter();
  persist(KEY, progress);
  if (remainingOnly) setTimeout(applyFilter, 600);
}

function wire() {
  document.querySelectorAll(".entry").forEach(entry => {
    const e = ALL.find(x => x.id === entry.dataset.id);
    entry.querySelector(".head").addEventListener("click", ev => {
      if (ev.target.closest("a")) return;
      openEntry(entry);
    });
    entry.querySelector(".toggle").addEventListener("click", () => openEntry(entry));
    entry.querySelector(".mark").addEventListener("click", () => {
      setDone(e, !isDone(e));
      if (e.steps) entry.querySelectorAll(".step-row").forEach(r => {
        r.querySelector("input").checked = isDone(e);
        r.classList.toggle("done", isDone(e));
      });
      syncEntry(entry, e);
    });
    if (e.steps) entry.querySelectorAll(".step-row input").forEach(cb => {
      cb.addEventListener("click", ev => ev.stopPropagation());
      cb.addEventListener("change", () => {
        progress[cb.id] = cb.checked;
        cb.closest(".step-row").classList.toggle("done", cb.checked);
        syncEntry(entry, e);
      });
    });
    const ta = entry.querySelector("textarea");
    let t;
    ta.addEventListener("input", () => {
      notes[e.id] = ta.value;
      clearTimeout(t); t = setTimeout(() => persist(NOTES_KEY, notes), 500);
    });
  });
}

let remainingOnly = false;
function applyFilter() {
  let shown = 0;
  document.querySelectorAll(".entry").forEach(entry => {
    const hide = remainingOnly && isDone(ALL.find(x => x.id === entry.dataset.id));
    entry.classList.toggle("hidden", hide);
    if (!hide) shown++;
  });
  document.querySelectorAll(".phase").forEach(ph => {
    const any = [...ph.querySelectorAll(".entry")].some(x => !x.classList.contains("hidden"));
    ph.style.display = any ? "" : "none";
  });
  $("empty").classList.toggle("show", shown === 0);
}
$("filter").addEventListener("click", () => {
  remainingOnly = !remainingOnly;
  $("filter").setAttribute("aria-pressed", String(remainingOnly));
  $("filter").textContent = remainingOnly ? "Show all" : "Remaining only";
  applyFilter();
});

render();
"""


def _weeks_label(weeks: tuple[int, int | None] | None) -> str:
    if weeks is None:
        return ""
    start, end = weeks
    if end is None:
        return f"Weeks {start}+"
    if end == start:
        return f"Week {start}"
    return f"Weeks {start}–{end}"


def render_curriculum(mf: Manifest) -> str:
    c = mf.course
    e = html.escape
    units_by_id = {u.id: u for u in mf.units}
    milestones_by_id = {m.id: m for m in mf.milestones}
    track_names = {t.id: t.name for t in mf.tracks}
    stage_ids = {s.id for t in mf.tracks for s in t.stages}
    hub_ids = [pid for pid in mf.progress_ids() if pid not in stage_ids]

    phases_js = []
    for p in mf.phases:
        entries = []
        for entry_id in p.entries:
            if entry_id in units_by_id:
                u = units_by_id[entry_id]
                rows = []
                for r in u.rows:
                    cls = "key" if r.kind == "key" else ""
                    rows.append([r.label, inline_html(r.content), cls])
                entries.append({
                    "id": u.id, "num": f"{u.num:02d}", "title": u.title,
                    "gloss": inline_html(u.gloss) if u.gloss else "",
                    "tags": list(mf.tags_for_unit(u.id)),
                    "rows": rows,
                    "check": ({"q": inline_html(u.check.q),
                               "ans": inline_html(u.check.ans)} if u.check else None),
                    "steps": ([[s.id, s.label] for s in u.steps] or None
                              if u.steps else None),
                })
            else:
                m = milestones_by_id[entry_id]
                entries.append({
                    "id": m.id, "num": "·", "title": m.label,
                    "gloss": inline_html(m.detail) if m.detail else "",
                    "tags": [m.kind], "rows": [], "check": None, "steps": None,
                })
        checkpoint = None
        if p.checkpoint:
            checkpoint = {
                "text": inline_html(p.checkpoint.prose),
                "goals": [[track_names.get(tid, tid), inline_html(text)]
                          for tid, text in p.checkpoint.track_goals],
            }
        phases_js.append({
            "tag": f"phase {p.num}", "name": p.title,
            "weeks": _weeks_label(p.weeks), "goal": inline_html(p.goal),
            "entries": entries, "checkpoint": checkpoint,
        })

    # --- static sections ---------------------------------------------------
    how = ""
    if c.preamble:
        paras = []
        for line in c.preamble:
            if line.startswith("## "):
                paras.append(f"<h2>{e(line[3:])}</h2>")
            else:
                paras.append(f"<p>{inline_html(line)}</p>")
        how = f'<div class="how">{"".join(paras)}</div>'

    says = ""
    if c.trigger_phrases:
        items = []
        for tp in c.trigger_phrases:
            note = f" — {e(tp.note)}" if tp.note else ""
            items.append(f'<li><span class="say">{e(tp.say)}</span>{note}</li>')
        says = ('<section class="section"><h2>Working with Claude</h2>'
                f'<ul class="saylist">{"".join(items)}</ul></section>')

    n_units = sum(1 for u in mf.units)
    standfirst = (f'<p class="standfirst">{e(c.description)}</p>'
                  if c.description else "")

    script = SCRIPT % {
        "key": json.dumps(c.progress_storage_key),
        "notes_key": json.dumps(c.notes_storage_key),
        "phases": json.dumps(phases_js, ensure_ascii=False),
        "hub_ids": json.dumps(hub_ids),
    }
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c.id)} — curriculum</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <p class="eyebrow"><a href="index.html">← course hub</a> &nbsp;·&nbsp; the curriculum ·
    {len(mf.phases)} phases · {n_units} units</p>
    <h1>{e(c.title)}</h1>
    {standfirst}
    {how}
    <div class="controls">
      <div class="meter">
        <div class="ticks" id="ticks" aria-hidden="true"></div>
        <span class="count" id="count"></span>
      </div>
      <span class="spacer"></span>
      <button class="filter" id="filter" aria-pressed="false">Remaining only</button>
    </div>
  </header>

  <main id="list"></main>
  <p class="empty" id="empty">Nothing remaining at this filter.</p>

  {says}

  <footer>
    Rendered by curricle from the course manifest — canonical text:
    <a href="curriculum.md">curriculum.md</a> (v{e(c.version.rev)}, {e(c.version.date)}) ·
    progress marks are shared with <a href="index.html">the hub</a> and live in this
    browser's localStorage · <a href="index.html">← back to the hub</a>
  </footer>
</div>
<div class="saving" id="toast">Saved</div>
<script>
{script}</script>
</body>
</html>
"""
