"""Render the resources view from a manifest.

The third surface: the tiered shelf with per-entry "why this one" and access
notes, an in-hand tracker over the tier-1 core path, per-entry notes, and
free-only / not-in-hand filters. State lives in its own localStorage key
(resource acquisition is not course progress — the corpus's rule, kept),
taken from the manifest so the legacy tf-resources key survives.

Interaction ported from textual-flow's hand-built page; data is a pure
function of the manifest's resources + resource_tiers.

Design: the *companion* system (see theme.py). The core-path meter is the
waypath over tier 1; free/paid chips keep their text labels — the green and
warm tints are reinforcement, the words carry the meaning.
"""

from __future__ import annotations

import html
import json

from . import theme
from .inlinemd import inline_html
from .schema import Manifest, Resource

STYLE = theme.style("""\
  .wrap { max-width:840px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:40px 0 26px; }
  h1 { font-weight:700; font-size:clamp(30px,5.5vw,42px); line-height:1.12;
       letter-spacing:-.01em; margin:14px 0 0; }
  .standfirst { max-width:58ch; margin:14px 0 0; color:var(--muted); font-size:16.5px; }
  .standfirst b { color:var(--ink); }
  .controls { margin:26px 0 0; padding:16px 20px; }
  .controls .waypath { margin:2px 0 14px; }
  .meta-row { display:flex; flex-wrap:wrap; align-items:center; gap:12px 22px; }
  .spacer { flex:1 1 auto; }
  .tier { margin:52px 0 0; }
  .tier-head { display:flex; align-items:flex-start; gap:12px; }
  .tier-num { flex:none; display:grid; place-items:center; width:36px; height:36px;
              border-radius:12px; background:var(--accent-soft);
              color:var(--accent-text); font:700 17px """ + theme.FONT_DISPLAY + """; }
  .tier-name { font-family:""" + theme.FONT_DISPLAY + """; font-size:21px;
               font-weight:700; margin:4px 0 0; }
  .tier-role { margin:12px 0 0; font-size:14.5px; color:var(--muted); max-width:66ch; }
  .subhead { font-size:12px; font-weight:700; letter-spacing:.06em;
             text-transform:uppercase; color:var(--muted); margin:26px 0 0; }
  .entry { border-bottom:1px solid var(--line-soft); padding:18px 0 16px; }
  .entry.hidden { display:none; }
  .entry.compact { padding:12px 0 10px; }
  .title { font-weight:600; font-size:18px; line-height:1.35; margin:0; }
  .entry.compact .title { font-size:15.5px; }
  .title a { color:var(--ink); text-decoration:none; }
  .title a:hover { color:var(--accent-text); text-decoration:underline;
                   text-underline-offset:3px; }
  .entry.inhand .title { color:var(--muted); }
  .chips { display:inline-flex; flex-wrap:wrap; gap:5px; vertical-align:2px; margin-left:9px; }
  .cite { font-size:12.5px; font-weight:500; color:var(--muted); margin:5px 0 0;
          line-height:1.5; }
  .why { position:relative; margin:9px 0 0; font-size:14.5px; line-height:1.55;
         max-width:64ch; }
  .why-mark { position:absolute; z-index:0; inset:-.1em -.4em -.05em -.3em;
              background:var(--accent-soft); border-radius:.6em .3em .5em .4em;
              transform:scaleX(0); transform-origin:0 50%;
              transition:transform .55s cubic-bezier(.2,.7,.3,1); }
  .why-text { position:relative; z-index:1; }
  .entry.inhand .why-mark { transform:scaleX(1); }
  .access { margin:8px 0 0; font-size:13.5px; color:var(--muted); }
  .access b { color:var(--ink); font-weight:600; }
  .links { display:flex; flex-wrap:wrap; gap:6px 8px; margin:10px 0 0; }
  .rlink { display:inline-flex; align-items:center; gap:5px; min-height:30px;
           font-size:12.5px; font-weight:600; text-decoration:none;
           color:var(--accent-text); background:var(--accent-soft);
           border-radius:999px; padding:2px 12px; transition:filter .2s; }
  .rlink:hover { filter:brightness(.96); }
  .rlink .arr { opacity:.7; }
  .actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px 20px; margin:8px 0 0; }
  .act { display:inline-flex; align-items:center; gap:7px; min-height:34px;
         font-size:13.5px; font-weight:600; color:var(--muted);
         border-radius:999px; padding:4px 10px; margin-left:-10px;
         transition:color .2s, background .2s; }
  .act:hover { color:var(--ink); background:var(--chip); }
  .dot { width:11px; height:11px; border-radius:50%; border:2px solid var(--faint);
         background:transparent; transition:.3s; }
  .entry.inhand .dot { background:var(--good); border-color:var(--good); }
  .entry.inhand .mlabel { color:var(--good-text); }
  .notewrap { display:grid; grid-template-rows:0fr; transition:grid-template-rows .3s ease; }
  .entry.noting .notewrap { grid-template-rows:1fr; }
  .notewrap > div { overflow:hidden; }
  textarea { width:100%; max-width:64ch; min-height:52px; resize:vertical; margin-top:10px;
             font:14px/1.55 """ + theme.FONT_BODY + """; color:var(--ink);
             background:var(--panel); border:1.5px solid var(--line);
             border-radius:12px; padding:9px 12px; }
  textarea::placeholder { color:var(--muted); }
  textarea:focus { outline:none; border-color:var(--accent); }
  .entry.hasnote .nlabel { color:var(--accent-text); }
  .section { margin:56px 0 0; }
  .section > h2 { font-size:22px; font-weight:700; margin:0 0 10px; }
  .section ol { font-size:14.5px; padding-left:22px; }
  .section li { margin:0 0 6px; }
  .tier-intro { margin:6px 0 0; font-size:14.5px; color:var(--muted); max-width:66ch; }
  .empty { display:none; padding:44px 0; text-align:center;
           font-size:17px; color:var(--muted); }
  .empty.show { display:block; }
""")

SCRIPT = theme.WAYPATH_JS + """\
const KEY = %(key)s;
const API = %(api)s;          // null: localStorage mode; else: POST events here
const INITIAL = %(initial)s;  // {inhand, notes} server-folded, or null
const TIERS = %(tiers)s;

let state = Object.assign({ inhand: {}, notes: {} }, INITIAL || {});
if (!API) {
  try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
}
function send(kind, id, payload) {
  fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, subject_id: id, payload }) }).catch(() => {});
}

const TIER1_IDS = (TIERS[0] || {groups:[]}).groups.flatMap(g => g.entries.map(e => e.id));
const ALL = TIERS.flatMap(t => t.groups.flatMap(g => g.entries));
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let saveTimer, toastTimer;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(state)); toast("Saved"); } catch (e) {}
  }, 400);
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1200);
}

function render() {
  $("list").innerHTML = TIERS.map(tier => `
    <section class="tier">
      <div class="tier-head">
        <span class="tier-num">${tier.num}</span>
        <h2 class="tier-name">${tier.name}</h2>
      </div>
      <p class="tier-role">${tier.role}</p>
      ${tier.groups.map(g => `
        ${g.sub ? `<p class="subhead">${g.sub}</p>` : ""}
        ${g.entries.map(e => `
          <article class="entry${tier.compact ? " compact" : ""}${state.inhand[e.id] ? " inhand" : ""}${state.notes[e.id] ? " hasnote" : ""}" data-id="${e.id}">
            <h3 class="title">${e.links.length
              ? `<a href="${e.links[0][1]}" ${e.links[0][1].startsWith("http") ? 'target="_blank" rel="noopener"' : ""}>${e.title}</a>`
              : e.title}<span class="chips">${e.chips.map(([t, c]) =>
                `<span class="chip${c ? " " + c : ""}">${t}</span>`).join("")}</span></h3>
            ${e.cite ? `<p class="cite">${e.cite}</p>` : ""}
            ${e.why ? `<p class="why"><span class="why-mark"></span><span class="why-text">${e.why}</span></p>` : ""}
            ${e.access ? `<p class="access">${e.access}</p>` : ""}
            ${e.links.length ? `<div class="links">${e.links.map(([l, u]) =>
              `<a class="rlink" href="${u}" ${u.startsWith("http") ? 'target="_blank" rel="noopener"' : ""}>${l}<span class="arr">↗</span></a>`).join("")}</div>` : ""}
            <div class="actions">
              <button class="act mark"><span class="dot"></span><span class="mlabel">${state.inhand[e.id] ? "In hand" : "Mark in hand"}</span></button>
              <button class="act note nlabel">Note${state.notes[e.id] ? " ●" : ""}</button>
            </div>
            <div class="notewrap"><div>
              <textarea placeholder="Loan due dates, which edition you bought, where your copy lives…">${esc(state.notes[e.id] || "")}</textarea>
            </div></div>
          </article>`).join("")}`).join("")}
    </section>`).join("");
  wire();
  updateMeter();
  applyFilter();
}

function updateMeter() {
  const n = TIER1_IDS.filter(i => state.inhand[i]).length;
  const nextId = TIER1_IDS.find(i => !state.inhand[i]) || null;
  $("count").textContent = `core path: ${n} of ${TIER1_IDS.length} in hand`;
  waypath($("ticks"), TIER1_IDS, i => !!state.inhand[i], nextId);
}

function wire() {
  document.querySelectorAll(".entry").forEach(entry => {
    const id = entry.dataset.id;
    entry.querySelector(".mark").addEventListener("click", () => {
      state.inhand[id] = !state.inhand[id];
      entry.classList.toggle("inhand", state.inhand[id]);
      entry.querySelector(".mlabel").textContent = state.inhand[id] ? "In hand" : "Mark in hand";
      updateMeter();
      if (API) send("resource_mark", id, { inhand: !!state.inhand[id] }); else save();
      if (needOnly) setTimeout(applyFilter, 600);
    });
    entry.querySelector(".note").addEventListener("click", () => {
      entry.classList.toggle("noting");
      if (entry.classList.contains("noting")) entry.querySelector("textarea").focus();
    });
    const ta = entry.querySelector("textarea");
    ta.addEventListener("input", () => {
      state.notes[id] = ta.value;
      entry.classList.toggle("hasnote", !!ta.value);
      entry.querySelector(".note").textContent = "Note" + (ta.value ? " ●" : "");
      if (API) {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => { send("resource_note", id, { text: ta.value }); toast("Saved"); }, 400);
      } else save();
    });
  });
}

let freeOnly = false, needOnly = false;
function applyFilter() {
  let shown = 0;
  document.querySelectorAll(".entry").forEach(entry => {
    const e = ALL.find(x => x.id === entry.dataset.id);
    const hide = (freeOnly && !e.free) || (needOnly && state.inhand[e.id]);
    entry.classList.toggle("hidden", hide);
    if (!hide) shown++;
  });
  document.querySelectorAll(".tier").forEach(t => {
    const any = [...t.querySelectorAll(".entry")].some(x => !x.classList.contains("hidden"));
    t.style.display = any ? "" : "none";
  });
  document.querySelectorAll(".subhead").forEach(sh => {
    let el = sh.nextElementSibling, any = false;
    while (el && el.classList.contains("entry")) {
      if (!el.classList.contains("hidden")) { any = true; break; }
      el = el.nextElementSibling;
    }
    sh.style.display = any ? "" : "none";
  });
  $("empty").classList.toggle("show", shown === 0);
}
function wireFilter(btn, get, set) {
  btn.addEventListener("click", () => {
    set(!get());
    btn.setAttribute("aria-pressed", String(get()));
    applyFilter();
  });
}
wireFilter($("f-free"), () => freeOnly, v => freeOnly = v);
wireFilter($("f-need"), () => needOnly, v => needOnly = v);

render();
"""


def _chips(r: Resource) -> list[list[str]]:
    chips: list[list[str]] = [[f.lower(), ""] for f in r.formats]
    if r.cost:
        chips.append([r.cost, "good" if r.free else "warn"])
    elif r.free:
        chips.append(["free", "good"])
    return chips


def render_resources(mf: Manifest, *, api: str | None = None,
                     initial: dict | None = None) -> str:
    c = mf.course
    e = html.escape

    tiers_js = []
    for tier in sorted(mf.resource_tiers, key=lambda t: t.num):
        groups: list[dict] = []
        for r in mf.resources:
            if r.tier != tier.num:
                continue
            sub = r.group or ""
            if not groups or groups[-1]["sub"] != sub:
                groups.append({"sub": sub, "entries": []})
            groups[-1]["entries"].append({
                "id": r.key,
                "title": r.title,
                "cite": e(r.cite) if r.cite else "",
                "chips": _chips(r),
                "free": bool(r.free),
                # A urn:/isbn identifier satisfies the schema's "has a URL"
                # rule but is not clickable; such entries render linkless,
                # as the hand-built page did.
                "links": [[label, url] for label, url in r.all_links
                          if not url.startswith("urn:")],
                "why": inline_html(r.why_this_one) if r.why_this_one else "",
                "access": inline_html(r.access_note) if r.access_note else "",
            })
        tiers_js.append({
            "num": str(tier.num), "name": tier.name,
            "role": inline_html(tier.role), "compact": tier.compact,
            "groups": groups,
        })

    standfirst = (f'<p class="standfirst">{inline_html(c.resources_intro)}</p>'
                  if c.resources_intro else "")
    reading = ""
    if c.reading_order:
        items = "".join(f"<li>{inline_html(x)}</li>" for x in c.reading_order)
        reading = ('<section class="section"><h2>Suggested reading order</h2>'
                   '<p class="tier-intro">The curriculum formalizes this; here it is '
                   f"at a glance.</p><ol>{items}</ol></section>")
    verified = next((r.verified_at for r in mf.resources if r.verified_at), None)
    verified_line = (f'<span class="sep">·</span> every url verified {e(verified)}'
                     if verified else "")

    script = SCRIPT % {
        "key": json.dumps(c.resources_storage_key),
        "api": json.dumps(api),
        "initial": json.dumps(initial, ensure_ascii=False),
        "tiers": json.dumps(tiers_js, ensure_ascii=False),
    }
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c.title)} — the resources</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <p class="eyebrow"><a href="index.html">← course hub</a>
    <span class="sep">·</span> the resources
    <span class="sep">·</span> {len(mf.resource_tiers)} tiers {verified_line}</p>
    <h1>Your resources</h1>
    {standfirst}
    <div class="controls panel">
      <div class="waypath" id="ticks" aria-hidden="true"></div>
      <div class="meta-row">
      <span class="wp-count" id="count"></span>
      <span class="spacer"></span>
      <button class="pill" id="f-free" aria-pressed="false">Free only</button>
      <button class="pill" id="f-need" aria-pressed="false">Not in hand</button>
      </div>
    </div>
  </header>

  <main id="list"></main>
  <p class="empty" id="empty">Nothing matches this filter.</p>

  {reading}

  <footer>
    Rendered by curricle from the course manifest — canonical text:
    <a href="learning-resources.md">learning-resources.md</a>. In-hand marks and notes
    live in this browser's localStorage ·
    <a href="curriculum.html">the curriculum</a> ·
    <a href="index.html">← back to the hub</a>
  </footer>
</div>
<div class="saving" id="toast">Saved</div>
<script>
{script}</script>
</body>
</html>
"""
