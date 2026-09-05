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
import posixpath
import re

from . import theme
from .inlinemd import inline_html
from .refs import RefResolver
from .schema import Manifest

STYLE = theme.style("""\
  .wrap { max-width:840px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:40px 0 26px; }
  h1 { font-weight:700; font-size:clamp(30px,5.5vw,42px); line-height:1.12;
       letter-spacing:-.01em; margin:14px 0 0; }
  .standfirst { max-width:var(--measure); margin:14px 0 0;
                color:var(--muted); font-size:16.5px; }
  .how { margin:26px 0 0; padding:18px 22px; }
  .how h2 { font-size:15px; font-weight:700; color:var(--ink); margin:0 0 10px; }
  .how p { margin:0 0 10px; font-size:14.5px; line-height:1.6; }
  .how p:last-child { margin-bottom:0; }
  .controls { margin:26px 0 0; padding:16px 20px; }
  .controls .waypath { margin:2px 0 14px; }
  .meta-row { display:flex; flex-wrap:wrap; align-items:center; gap:12px 22px; }
  .spacer { flex:1 1 auto; }
  .phase { margin:52px 0 0; }
  .phase-head { display:flex; align-items:flex-start; gap:12px; }
  .phase-num { flex:none; display:grid; place-items:center; width:36px; height:36px;
               border-radius:var(--r-ctl); background:var(--bg);
               border:1px solid var(--line);
               color:var(--muted); font:700 17px """ + theme.FONT_DISPLAY + """; }
  .phase-name { font-family:""" + theme.FONT_DISPLAY + """; font-size:21px;
                font-weight:700; margin:4px 0 0; }
  .phase-weeks { margin:8px 0 0 auto; }
  .phase-goal { margin:12px 0 0; font-size:14.5px; color:var(--muted);
                max-width:var(--measure); }
  .entry { border-bottom:1px solid var(--line-soft); scroll-margin-top:18px; }
  .entry.hidden { display:none; }
  /* "You are here", ported from the hub's hot row — the same accent ring
     and the same worded chip, because a learner arriving on this page from
     a bookmark or the back button used to get no answer at all: `nextId`
     fed the meter's ring and nothing below it, so every undone entry looked
     identical. This is the page the Continue pill lands on and the page a
     learner works in for two years.

     The hub's own numbers, -10px against 8.5px of padding, so the two hot
     treatments are one object rather than two that resemble each other.
     The bleed is exactly what the ring adds (8.5 + 1.5), so the number
     gutter of the hot entry lands on the same vertical as every other
     entry's and nothing shifts sideways when the ring moves. Two rows in
     one list drawn to two different edges is the kind of miss that reads
     as carelessness even when nobody can name it.

     `--accent`, not `--accent-strong`. The hub needs the stronger token for
     a row that is *both* a milestone and next, where the ring lands on the
     `--good-soft` fill; here a milestone entry carries no fill at all (its
     green is the flag in the gutter and the done-highlight behind a gloss,
     which by definition is not drawn on the row that is next), so the ring
     is always on the ground and `--accent` clears it. */
  .entry.next { border:1.5px solid var(--accent); box-shadow:var(--shadow);
                margin:0 -10px; padding:0 8.5px; }
  .title .next-flag { display:none; }
  .entry.next .title .next-flag { display:inline-block; }
  /* The ring in the meter is the same gesture as the ring on the entry, so
     it goes where the entry is. A link, not a scroll handler: it is an
     address on this page, it belongs in the status bar on hover, and it
     should open in a new tab if somebody wants that. */
  a.wp-stone.here { cursor:pointer; }
  a.wp-stone.here:hover { background:var(--accent-soft); }
  .head { display:grid; grid-template-columns:44px 1fr; gap:0 16px; width:100%;
          text-align:left; padding:20px 0 4px; border-radius:var(--r-card); }
  .head:hover .title { color:var(--accent-text); }
  .num { font:600 13px """ + theme.FONT_DISPLAY + """; color:var(--muted);
         padding-top:7px; }
  /* A milestone's gutter carries the flag instead of a number, in the green
     that means done/checkpoint everywhere else — the same glyph in the same
     tint the hub gives the same row. */
  .num .flag { color:var(--good-text); vertical-align:-1px; }
  .body-col { min-width:0; }
  .title { font-weight:600; font-size:19px; line-height:1.3; margin:0; }
  .title .chip { vertical-align:3px; margin-left:8px; }
  .gloss { position:relative; margin:8px 0 0; font-size:14.5px; line-height:1.55;
           max-width:var(--measure); color:var(--ink); }
  .gloss-mark { position:absolute; z-index:0; inset:-.1em -.4em -.05em -.3em;
                background:var(--good-soft); border-radius:.6em .3em .5em .4em;
                transform:scaleX(0); transform-origin:0 50%;
                transition:transform .55s cubic-bezier(.2,.7,.3,1); }
  .gloss-text { position:relative; z-index:1; }
  .entry.done .gloss-mark { transform:scaleX(1); }
  .entry.done .title { color:var(--muted); }
  .actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px 20px;
             margin:8px 0 0; padding:0 0 18px 60px; }
  .act { display:inline-flex; align-items:center; gap:7px; min-height:34px;
         font-size:13.5px; font-weight:600; color:var(--muted);
         border-radius:var(--r-ctl); padding:4px 10px; margin-left:-10px;
         transition:color .2s, background .2s; }
  .act:hover { color:var(--ink); background:var(--chip); }
  .chev { display:inline-block; transition:transform .3s ease; }
  .entry.open .chev { transform:rotate(90deg); }
  .dot { width:11px; height:11px; border-radius:0; border:2px solid var(--faint);
         background:transparent; transition:.3s; }
  .entry.done .dot { background:var(--good); border-color:var(--good); }
  .entry.done .mlabel { color:var(--good-text); }
  .detail { display:grid; grid-template-rows:0fr; transition:grid-template-rows .35s cubic-bezier(.4,0,.2,1); }
  .entry.open .detail { grid-template-rows:1fr; }
  .detail-inner { overflow:hidden; }
  .detail-pad { padding:0 0 26px 60px; max-width:var(--measure); }
  .row { margin:0 0 12px; font-size:14.5px; line-height:1.6; }
  .row b.lbl { display:block; font-size:14px; font-weight:700; color:var(--ink);
               margin:0 0 3px; }
  .row a { text-underline-offset:2px; }
  .key { border-left:2px solid var(--accent); padding:2px 0 2px 14px;
         background:none; }
  .key b.lbl { color:var(--accent-text); }
  .steps { margin:0 0 12px; }
  .step-row { display:flex; align-items:baseline; gap:9px; font-size:14.5px; margin:0 0 6px; }
  .step-row input { width:17px; height:17px; accent-color:var(--accent-strong); }
  .step-row.done label { color:var(--muted); text-decoration:line-through;
                         text-decoration-color:var(--faint); }
  .notes-label { display:block; font-size:14px; font-weight:700; color:var(--ink);
                 margin:18px 0 6px; }
  textarea { width:100%; min-height:64px; resize:vertical;
             font:14px/1.55 """ + theme.FONT_BODY + """;
             color:var(--ink); background:var(--panel); border:1.5px solid var(--line);
             border-radius:var(--r-card); padding:10px 13px; }
  /* Placeholder copy is read to be acted on, so it is body text, not a
     decorative mark: --muted, never --faint, which does not clear the 4.5
     text floor in either palette. */
  textarea::placeholder { color:var(--muted); }
  textarea:focus { outline:none; border-color:var(--accent); }
  .checkpoint { margin:26px 0 0; padding:2px 0 2px 16px; background:none;
                border-left:2px solid var(--good); font-size:14.5px; }
  .checkpoint b.cp { display:block; font-size:14px; font-weight:700;
                     color:var(--good-text); margin:0 0 6px; }
  .checkpoint .track-goal { margin-top:8px; color:var(--muted); }
  details.check { margin:22px 0 0; padding:13px 17px; background:var(--panel);
                  border:1.5px solid var(--line); border-radius:var(--r-card); font-size:14.5px; }
  details.check summary { cursor:pointer; font-weight:600; }
  details.check div { margin-top:10px; color:var(--muted); }
  .section { margin:56px 0 0; }
  .section > h2 { font-size:22px; font-weight:700; margin:0 0 10px; }
  .section p, .section li { font-size:14.5px; }
  .section .sub { color:var(--muted); margin:10px 0 0; }
  .say { font:13.5px """ + theme.FONT_MONO + """; background:var(--chip); padding:3px 9px;
         border-radius:var(--r-ctl); }
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
// [shut, open] for the expand control. A milestone is not a unit, and what
// its detail holds is the note box and nothing else, so it says so.
const TOGGLE = e => e.ms ? ["Note", "Hide note"] : ["Full unit", "Hide unit"];
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
              <h3 class="title">${e.title}<span
                class="chip acc next-flag">next</span>${(e.tags || []).map(t =>
                `<span class="chip${t === "widget" ? " acc" : ""}">${t}</span>`).join("")}</h3>
              ${e.gloss ? `<p class="gloss"><span class="gloss-mark"></span><span class="gloss-text">${e.gloss}</span></p>` : ""}
            </span>
          </button>
          <div class="actions">
            <button class="act toggle"><span class="chev">›</span><span class="tlabel">${TOGGLE(e)[0]}</span></button>
            <button class="act mark"><span class="dot"></span><span class="mlabel">${isDone(e) ? "Done" : "Mark done"}</span></button>
            ${e.href ? `<a class="act" href="${e.href}">Unit page</a>` : ""}
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
  // The path counts steps and the list shows entries, and the two are not
  // the same sequence: a stepped unit is one entry standing for several
  // stones. `isDone` already knows the difference, so the first entry it
  // calls undone is the one to mark hot — and it is always the entry that
  // owns `nextId`, which is what lets the ring point at it.
  const hot = ALL.find(e => !isDone(e)) || null;
  document.querySelectorAll(".entry").forEach(entry =>
    entry.classList.toggle("next", !!hot && entry.dataset.id === hot.id));
  const stone = waypath($("ticks"), HUB_IDS, i => !!progress[i], nextId,
    () => hot ? "#u-" + encodeURIComponent(hot.id) : null);
  if (stone && hot) {
    // Set, never interpolated: an entry title reaches the page as markup
    // and reaches an attribute as text, and this is the attribute path.
    stone.setAttribute("aria-label", "Go to where you are: " + hot.title);
    stone.setAttribute("title", "Where you are: " + hot.title);
  }
}

function openEntry(entry, want) {
  const on = want !== undefined ? want : !entry.classList.contains("open");
  entry.classList.toggle("open", on);
  entry.querySelector(".head").setAttribute("aria-expanded", String(on));
  const e = ALL.find(x => x.id === entry.dataset.id);
  entry.querySelector(".tlabel").textContent = TOGGLE(e)[on ? 1 : 0];
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


def derived_interactive_html(mf: Manifest, unit_id: str,
                             rr: RefResolver) -> str:
    """The Interactive row, computed from material attachments (spec rule 2:
    attachment is declared once, on the material; this row is a projection).
    Kind in words, title as the link — never a naked path."""
    parts = []
    for m in mf.materials_for_unit(unit_id):
        kind = html.escape(m.kind.replace("-", " "))
        parts.append(f'{kind} — <a href="{html.escape(rr.material_href(m))}">'
                     f"{html.escape(m.title)}</a>")
    return " · ".join(parts)


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
                      initial: dict | None = None,
                      unit_pages: bool = False) -> str:
    c = mf.course
    e = html.escape
    # One resolver for the whole page: it sits at the course base, and unit
    # pages / the reader exist only when served.
    rr = RefResolver(mf, to_root="", served=api is not None)
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
                    rows.append([r.label, inline_html(r.content, rr), cls])
                # The Interactive row derives from material attachments; an
                # authored one (compiler-warned, pre-migration) is honored
                # instead so the row never appears twice.
                if not any(r.label == "Interactive" for r in u.rows):
                    derived = derived_interactive_html(mf, u.id, rr)
                    if derived:
                        rows.append(["Interactive", derived, ""])
                entries.append({
                    "id": u.id, "num": f"{u.num:02d}", "title": u.title,
                    "gloss": inline_html(u.gloss, rr) if u.gloss else "",
                    "tags": list(mf.tags_for_unit(u.id)),
                    "rows": rows,
                    "check": ({"q": inline_html(u.check.q, rr),
                               "ans": inline_html(u.check.ans, rr)}
                              if u.check else None),
                    "steps": ([[s.id, s.label] for s in u.steps] or None
                              if u.steps else None),
                    # Units link to their served page.
                    # Only the app has unit pages — the standalone render
                    # carries no href key and the template renders nothing.
                    **({"href": f"unit/{u.id}.html"} if unit_pages else {}),
                })
            else:
                m = milestones_by_id[entry_id]
                entries.append({
                    # The number gutter holds a number for a unit and the
                    # product's one drawn glyph for a milestone — the same
                    # flag the hub gives the same row. It used to hold "·",
                    # which reads as a stray period beside the label.
                    "id": m.id, "num": theme.FLAG_SVG,
                    "title": theme.strip_leading_pictograph(m.label),
                    "gloss": inline_html(m.detail, rr) if m.detail else "",
                    "tags": [m.kind], "rows": [], "check": None, "steps": None,
                    # Not a unit: the expand control says so (TOGGLE).
                    "ms": True,
                })
        checkpoint = None
        if p.checkpoint:
            checkpoint = {
                "text": inline_html(p.checkpoint.prose, rr),
                "goals": [[track_names.get(tid, tid), inline_html(text, rr)]
                          for tid, text in p.checkpoint.track_goals],
            }
        phases_js.append({
            "num": str(p.num), "name": p.title,
            "weeks": _weeks_label(p.weeks), "goal": inline_html(p.goal, rr),
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
                paras.append(f"<p>{inline_html(line, rr)}</p>")
        how = f'<div class="how panel">{"".join(paras)}</div>'

    says = ""
    if c.trigger_phrases:
        items = []
        for tp in c.trigger_phrases:
            note = f" — {e(tp.note)}" if tp.note else ""
            items.append(f'<li><span class="say">{e(tp.say)}</span>{note}</li>')
        says = ('<section class="section"><h2>Working with your assistant</h2>'
                f'<ul class="saylist">{"".join(items)}</ul></section>')

    n_units = sum(1 for u in mf.units)

    # A course whose curriculum.md opens by restating its own description —
    # which is the natural thing for an author to write, and what the shipped
    # example does — printed that sentence twice in a row: once as the
    # standfirst and again as the first line of the panel below it, at two
    # different measures, sixty pixels apart. The page is the authored text's
    # frame, so the authored text wins and the standfirst stands down.
    def _opens_with_description() -> bool:
        if not (c.description and c.preamble):
            return False
        squash = lambda t: " ".join(t.split()).casefold()
        first = squash(re.sub(r"[*_`\[\]]", "", c.preamble[0]))
        return first.startswith(squash(c.description)[:60])

    standfirst = (f'<p class="standfirst">{e(c.description)}</p>'
                  if c.description and not _opens_with_description() else "")

    # Where the marks actually go: the tenant's ledger when served, this
    # browser only when the page is a standalone file. See hubrender — the
    # two pages share the storage key and must not disagree about what it
    # means.
    kept = ("are kept for you on the server" if api
            else "live in this browser's localStorage")

    # Canonical-text pointer: the name comes from the manifest, and served
    # it opens in the themed reader instead of as text/plain (the raw file
    # stays reachable at its own path).
    cur_name = posixpath.basename(c.docs.curriculum_doc
                                  or "learning/curriculum.md")
    cur_href = f"read/{cur_name}" if api else cur_name

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
    <p class="eyebrow"><a href="index.html">Course hub</a>
    <span class="sep">/</span> Curriculum</p>
    <h1>{e(c.title)}</h1>
    <p class="pagefacts">{len(mf.phases)} phases, {n_units} units</p>
    {standfirst}
    {how}
    <div class="controls panel">
      <!-- Not aria-hidden: one stone in this path is a link to the entry
           the ring marks, and a focusable element inside an aria-hidden
           subtree is reachable by keyboard and invisible to a screen
           reader. The decorative stones hide themselves instead — see
           theme.WAYPATH_JS. -->
      <div class="waypath" id="ticks"></div>
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
    <a href="{e(cur_href)}">{e(cur_name)}</a> (v{e(c.version.rev)}, {e(c.version.date)}) ·
    progress marks are shared with <a href="index.html">the hub</a> and
    {kept} · <a href="index.html">Back to the hub</a>
  </footer>
</div>
<div class="saving" id="toast">Saved</div>
<script>
{script}</script>
</body>
</html>
"""
