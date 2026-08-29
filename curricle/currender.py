"""Render the curriculum view from a manifest.

The replacement for the hand-mirrored curriculum.html: every unit as an
expandable entry (syllabus rows, check-yourself, per-unit note), phase
checkpoints with track goals, a done-meter and remaining-filter. Progress
shares the hub's localStorage key and shape; notes live in their own key —
both taken from the manifest, so the legacy keys survive.

Data and interaction are ported from textual-flow's hand-built page; the
data is a pure function of the manifest. Stepped units improve on the
original's composite-id mapping: the steps render as their own checkboxes
inside the entry, and "Mark done" marks them all.

Design: the *companion* system (see theme.py). The meter is the waypath;
the done-state highlight sweep on a unit's gloss is the one moment of
earned delight this page allows itself.
"""

from __future__ import annotations

import html
import json

from . import theme
from .inlinemd import inline_html
from .schema import Manifest

STYLE = theme.style("""\
  .wrap { max-width:840px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:40px 0 26px; }
  h1 { font-weight:700; font-size:clamp(30px,5.5vw,42px); line-height:1.12;
       letter-spacing:-.01em; margin:14px 0 0; }
  .standfirst { max-width:60ch; margin:14px 0 0; color:var(--muted); font-size:16.5px; }
  .how { margin:26px 0 0; padding:18px 22px; }
  .how h2 { font-size:13px; font-weight:700; letter-spacing:.06em;
            text-transform:uppercase; color:var(--muted); margin:0 0 10px; }
  .how p { margin:0 0 10px; font-size:14.5px; line-height:1.6; }
  .how p:last-child { margin-bottom:0; }
  .controls { margin:26px 0 0; padding:16px 20px; }
  .controls .waypath { margin:2px 0 14px; }
  .meta-row { display:flex; flex-wrap:wrap; align-items:center; gap:12px 22px; }
  .spacer { flex:1 1 auto; }
  .phase { margin:52px 0 0; }
  .phase-head { display:flex; align-items:flex-start; gap:12px; }
  .phase-num { flex:none; display:grid; place-items:center; width:36px; height:36px;
               border-radius:12px; background:var(--accent-soft);
               color:var(--accent-text); font:700 17px """ + theme.FONT_DISPLAY + """; }
  .phase-name { font-family:""" + theme.FONT_DISPLAY + """; font-size:21px;
                font-weight:700; margin:4px 0 0; }
  .phase-weeks { margin:8px 0 0 auto; }
  .phase-goal { margin:12px 0 0; font-size:14.5px; color:var(--muted); max-width:66ch; }
  .entry { border-bottom:1px solid var(--line-soft); scroll-margin-top:18px; }
  .entry.hidden { display:none; }
  .head { display:grid; grid-template-columns:44px 1fr; gap:0 16px; width:100%;
          text-align:left; padding:20px 0 4px; border-radius:12px; }
  .head:hover .title { color:var(--accent-text); }
  .num { font:600 13px """ + theme.FONT_DISPLAY + """; color:var(--muted);
         padding-top:7px; }
  .body-col { min-width:0; }
  .title { font-weight:600; font-size:19px; line-height:1.3; margin:0; }
  .title .chip { vertical-align:3px; margin-left:8px; }
  .gloss { position:relative; margin:8px 0 0; font-size:14.5px; line-height:1.55;
           max-width:62ch; color:var(--ink); }
  .gloss-mark { position:absolute; z-index:0; inset:-.1em -.4em -.05em -.3em;
                background:var(--accent-soft); border-radius:.6em .3em .5em .4em;
                transform:scaleX(0); transform-origin:0 50%;
                transition:transform .55s cubic-bezier(.2,.7,.3,1); }
  .gloss-text { position:relative; z-index:1; }
  .entry.done .gloss-mark { transform:scaleX(1); }
  .entry.done .title { color:var(--muted); }
  .actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px 20px;
             margin:8px 0 0; padding:0 0 18px 60px; }
  .act { display:inline-flex; align-items:center; gap:7px; min-height:34px;
         font-size:13.5px; font-weight:600; color:var(--muted);
         border-radius:999px; padding:4px 10px; margin-left:-10px;
         transition:color .2s, background .2s; }
  .act:hover { color:var(--ink); background:var(--chip); }
  .chev { display:inline-block; transition:transform .3s ease; }
  .entry.open .chev { transform:rotate(90deg); }
  .dot { width:11px; height:11px; border-radius:50%; border:2px solid var(--faint);
         background:transparent; transition:.3s; }
  .entry.done .dot { background:var(--good); border-color:var(--good); }
  .entry.done .mlabel { color:var(--good-text); }
  .detail { display:grid; grid-template-rows:0fr; transition:grid-template-rows .35s cubic-bezier(.4,0,.2,1); }
  .entry.open .detail { grid-template-rows:1fr; }
  .detail-inner { overflow:hidden; }
  .detail-pad { padding:0 0 26px 60px; max-width:68ch; }
  .row { margin:0 0 12px; font-size:14.5px; line-height:1.6; }
  .row b.lbl { display:block; font-size:11.5px; font-weight:700; letter-spacing:.06em;
               text-transform:uppercase; color:var(--muted); margin:0 0 3px; }
  .row a { text-underline-offset:2px; }
  .key { background:var(--accent-soft); padding:11px 15px; border-radius:12px; }
  .key b.lbl { color:var(--accent-text); }
  .steps { margin:0 0 12px; }
  .step-row { display:flex; align-items:baseline; gap:9px; font-size:14.5px; margin:0 0 6px; }
  .step-row input { width:17px; height:17px; accent-color:var(--accent-strong); }
  .step-row.done label { color:var(--muted); text-decoration:line-through;
                         text-decoration-color:var(--faint); }
  .notes-label { display:block; font-size:11.5px; font-weight:700; letter-spacing:.06em;
                 text-transform:uppercase; color:var(--muted); margin:18px 0 6px; }
  textarea { width:100%; min-height:64px; resize:vertical;
             font:14px/1.55 """ + theme.FONT_BODY + """;
             color:var(--ink); background:var(--panel); border:1.5px solid var(--line);
             border-radius:12px; padding:10px 13px; }
  /* Placeholder copy is read to be acted on, so it is body text, not a
     decorative mark: --muted (6.45 on panel), never --faint (4.27). */
  textarea::placeholder { color:var(--muted); }
  textarea:focus { outline:none; border-color:var(--accent); }
  .checkpoint { margin:26px 0 0; padding:16px 20px; background:var(--good-soft);
                border:1px solid var(--good); border-radius:16px; font-size:14.5px; }
  .checkpoint b.cp { display:block; font-size:12px; font-weight:700;
                     letter-spacing:.06em; text-transform:uppercase;
                     color:var(--good-text); margin:0 0 6px; }
  .checkpoint .track-goal { margin-top:8px; color:var(--muted); }
  details.check { margin:22px 0 0; padding:13px 17px; background:var(--panel);
                  border:1.5px solid var(--line); border-radius:14px; font-size:14.5px; }
  details.check summary { cursor:pointer; font-weight:600; }
  details.check div { margin-top:10px; color:var(--muted); }
  .section { margin:56px 0 0; }
  .section > h2 { font-size:22px; font-weight:700; margin:0 0 10px; }
  .section p, .section li { font-size:14.5px; }
  .section .sub { color:var(--muted); margin:10px 0 0; }
  .say { font:13.5px """ + theme.FONT_MONO + """; background:var(--chip); padding:3px 9px;
         border-radius:8px; }
  .saylist { list-style:none; padding:0; margin:12px 0 0; }
  .saylist li { margin:0 0 10px; }
  .empty { display:none; padding:44px 0; text-align:center;
           font-size:17px; color:var(--muted); }
  .empty.show { display:block; }
  @media (max-width:620px) {
    .head { grid-template-columns:1fr; }
    .num { padding:0 0 4px; }
    .actions, .detail-pad { padding-left:0; }
    .phase-weeks { margin:8px 0 0; }
  }
""")

SCRIPT = theme.WAYPATH_JS + """\
const KEY = %(key)s;
const NOTES_KEY = %(notes_key)s;
const API = %(api)s;          // null: localStorage mode; else: POST events here
const INITIAL = %(initial)s;  // {progress, notes} server-folded, or null
const PHASES = %(phases)s;
const HUB_IDS = %(hub_ids)s;

let progress = (INITIAL && INITIAL.progress) || {};
let notes = (INITIAL && INITIAL.notes) || {};
if (!API) {
  try { progress = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
  try { notes = JSON.parse(localStorage.getItem(NOTES_KEY) || "{}"); } catch (e) {}
}
function send(kind, id, payload) {
  fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, subject_id: id, payload }) }).catch(() => {});
}
function putMark(id, v) {
  progress[id] = v;
  if (API) send("mark", id, { done: v });
  else persist(KEY, progress);
}

const isDone = e => e.steps ? e.steps.every(s => progress[s[0]]) : !!progress[e.id];
const setDone = (e, v) => { if (e.steps) e.steps.forEach(s => putMark(s[0], v)); else putMark(e.id, v); };

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
        <span class="phase-num">${p.num}</span>
        <h2 class="phase-name">${p.name}</h2>
        ${p.weeks ? `<span class="phase-weeks chip">${p.weeks}</span>` : ""}
      </div>
      <p class="phase-goal">${p.goal}</p>
      ${p.entries.map(e => `
        <article class="entry${isDone(e) ? " done" : ""}" id="u-${e.id}" data-id="${e.id}">
          <button class="head" aria-expanded="false">
            <span class="num">${e.num}</span>
            <span class="body-col">
              <h3 class="title">${e.title}${(e.tags || []).map(t =>
                `<span class="chip${t === "widget" ? " acc" : ""}">${t}</span>`).join("")}</h3>
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
      ${p.checkpoint ? `<div class="checkpoint"><b class="cp">Phase ${p.num} checkpoint</b>${p.checkpoint.text}${(p.checkpoint.goals || []).map(g => `<div class="track-goal"><b>${g[0]}:</b> ${g[1]}</div>`).join("")}</div>` : ""}
    </section>`).join("");
  wire();
  updateMeter();
  applyFilter();
}

function updateMeter() {
  const done = HUB_IDS.filter(i => progress[i]).length;
  const nextId = HUB_IDS.find(i => !progress[i]) || null;
  $("count").textContent = done === 0
    ? `${HUB_IDS.length} steps ahead of you`
    : `${done} of ${HUB_IDS.length} done`;
  waypath($("ticks"), HUB_IDS, i => !!progress[i], nextId);
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
        putMark(cb.id, cb.checked);
        cb.closest(".step-row").classList.toggle("done", cb.checked);
        syncEntry(entry, e);
      });
    });
    const ta = entry.querySelector("textarea");
    let t;
    ta.addEventListener("input", () => {
      notes[e.id] = ta.value;
      clearTimeout(t);
      t = setTimeout(() => {
        if (API) { send("note", e.id, { text: ta.value }); toast("Saved"); }
        else persist(NOTES_KEY, notes);
      }, 500);
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

// The hub's Begin/Continue action arrives here as #u-<id> — an entry id, or
// a step id inside one. Open that entry and bring it into view.
function openHash() {
  const m = location.hash.match(/^#u-(.+)$/);
  if (!m) return;
  // A fragment carrying a malformed escape throws in the decode instead of
  // returning a string; unreadable is unresolvable, so it is the same no-op.
  let id;
  try { id = decodeURIComponent(m[1]); } catch (err) { return; }
  const e = ALL.find(x => x.id === id || (x.steps || []).some(s => s[0] === id));
  if (!e) return;
  const entry = document.querySelector(`.entry[data-id="${CSS.escape(e.id)}"]`);
  if (!entry) return;
  openEntry(entry, true);
  entry.scrollIntoView({ block: "start" });
}

render();
window.addEventListener("hashchange", openHash);
openHash();
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


def render_curriculum(mf: Manifest, *, api: str | None = None,
                      initial: dict | None = None) -> str:
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
                    "id": m.id, "num": "·",
                    "title": theme.strip_leading_pictograph(m.label),
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
            "num": str(p.num), "name": p.title,
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
        how = f'<div class="how panel">{"".join(paras)}</div>'

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
        "api": json.dumps(api),
        "initial": json.dumps(initial, ensure_ascii=False),
        "phases": json.dumps(phases_js, ensure_ascii=False),
        "hub_ids": json.dumps(hub_ids),
    }
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c.title)} — curriculum</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <p class="eyebrow"><a href="index.html">← course hub</a>
    <span class="sep">·</span> the curriculum
    <span class="sep">·</span> {len(mf.phases)} phases · {n_units} units</p>
    <h1>{e(c.title)}</h1>
    {standfirst}
    {how}
    <div class="controls panel">
      <div class="waypath" id="ticks" aria-hidden="true"></div>
      <div class="meta-row">
      <span class="wp-count" id="count"></span>
      <span class="spacer"></span>
      <button class="pill" id="filter" aria-pressed="false">Remaining only</button>
      </div>
    </div>
  </header>

  <main id="list"></main>
  <p class="empty" id="empty">Nothing left under this filter — everything here is done.</p>

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
