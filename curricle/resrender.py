"""Render the resources view from a manifest.

The third surface: the tiered shelf with per-entry "why this one" and access
notes, an in-hand tracker over the tier-1 core path, per-entry notes, and
free-only / not-in-hand filters. State lives in its own localStorage key
(resource acquisition is not course progress — the corpus's rule, kept),
taken from the manifest so the legacy tf-resources key survives.

Design and interaction ported from textual-flow's hand-built page; data is
a pure function of the manifest's resources + resource_tiers.
"""

from __future__ import annotations

import html
import json

from .inlinemd import inline_html
from .schema import Manifest, Resource

STYLE = """\
  :root { --bg:#faf8f4; --panel:#fff; --ink:#2b2620; --muted:#7a7268; --faint:#a29a8e;
          --line:#e3ddd2; --line-soft:#eee9e0; --accent:#7c5cbf; --accent-ink:#fff;
          --marker:rgba(124,92,191,.16); --good:#4a7a4e; --warn:#b3543a; --chip:#f3efe8; }
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
  h1 em { font-style:italic; color:var(--muted); }
  .standfirst { max-width:56ch; margin:18px 0 0; color:var(--muted); font-size:16px; }
  .controls { display:flex; flex-wrap:wrap; align-items:center; gap:14px 22px;
              margin:28px 0 0; padding:14px 0;
              border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
  .meter { display:flex; align-items:center; gap:12px; }
  .ticks { display:flex; gap:4px; }
  .tick { width:13px; height:5px; border-radius:1px; background:var(--line);
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
  .tier { margin:52px 0 0; }
  .tier-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 14px;
               padding-bottom:9px; border-bottom:2px solid var(--ink); }
  .tier-tag { font:500 11px ui-monospace,Menlo,monospace; letter-spacing:.15em; text-transform:uppercase; }
  .tier-name { font-size:19px; font-style:italic; color:var(--muted); }
  .tier-role { margin:12px 0 0; font-size:14.5px; color:var(--muted); max-width:64ch; }
  .subhead { font:500 11px ui-monospace,Menlo,monospace; letter-spacing:.14em; text-transform:uppercase;
             color:var(--faint); margin:26px 0 0; }
  .entry { border-bottom:1px solid var(--line-soft); padding:18px 0 16px; }
  .entry.hidden { display:none; }
  .entry.compact { padding:12px 0 10px; }
  .title { font-weight:400; font-size:19px; line-height:1.3; margin:0; }
  .entry.compact .title { font-size:16px; }
  .title a { text-decoration:none; }
  .title a:hover { text-decoration:underline; text-decoration-color:var(--line); text-underline-offset:4px; }
  .chips { display:inline-flex; flex-wrap:wrap; gap:5px; vertical-align:3px; margin-left:9px; }
  .chip { font:500 9px ui-monospace,Menlo,monospace; letter-spacing:.11em; text-transform:uppercase;
          border:1px solid var(--line); border-radius:999px; padding:1px 7px; color:var(--muted); }
  .chip.free { color:var(--good); border-color:#bcd2bd; }
  .chip.paid { color:var(--warn); border-color:#e4c4b8; }
  .cite { font:11px ui-monospace,Menlo,monospace; color:var(--faint); margin:6px 0 0; line-height:1.5; }
  .why { position:relative; margin:9px 0 0; font-size:14.5px; max-width:62ch; }
  .why-mark { position:absolute; z-index:0; inset:-.1em -.4em -.05em -.3em;
              background:var(--marker); border-radius:.6em .2em .5em .3em;
              transform:scaleX(0); transform-origin:0 50%;
              transition:transform .55s cubic-bezier(.2,.7,.3,1); }
  .why-text { position:relative; z-index:1; }
  .entry.inhand .why-mark { transform:scaleX(1); }
  .access { margin:8px 0 0; font:13px ui-sans-serif,system-ui,sans-serif; color:var(--muted); }
  .access b { color:var(--ink); font-weight:600; }
  .links { display:flex; flex-wrap:wrap; gap:6px 16px; margin:9px 0 0; }
  .rlink { font:10.5px ui-monospace,Menlo,monospace; letter-spacing:.09em; text-transform:uppercase;
           text-decoration:none; border-bottom:1px solid var(--line); padding-bottom:2px;
           transition:border-color .2s; }
  .rlink:hover { border-color:var(--accent); }
  .rlink .arr { color:var(--faint); margin-left:4px; }
  .actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px 18px; margin:10px 0 0; }
  .act { font:10.5px ui-monospace,Menlo,monospace; letter-spacing:.1em; text-transform:uppercase;
         color:var(--muted); transition:color .2s; }
  .act:hover { color:var(--ink); }
  .mark { display:flex; align-items:center; gap:7px; }
  .dot { width:9px; height:9px; border-radius:50%; border:1px solid var(--faint);
         background:transparent; transition:.3s; }
  .entry.inhand .dot { background:var(--accent); border-color:var(--accent); }
  .notewrap { display:grid; grid-template-rows:0fr; transition:grid-template-rows .3s ease; }
  .entry.noting .notewrap { grid-template-rows:1fr; }
  .notewrap > div { overflow:hidden; }
  textarea { width:100%; max-width:62ch; min-height:52px; resize:vertical; margin-top:10px;
             font:14px/1.55 ui-sans-serif,system-ui,sans-serif; color:var(--ink);
             background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:9px 11px; }
  textarea::placeholder { color:var(--faint); }
  .entry.hasnote .nlabel { color:var(--accent); }
  .section { margin:56px 0 0; }
  .section > h2 { font-size:22px; font-weight:400; margin:0 0 6px; padding-bottom:8px;
                  border-bottom:2px solid var(--ink); }
  .section ol { font-size:14.5px; padding-left:22px; }
  .section li { margin:0 0 5px; }
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
  code { font-family:ui-monospace,Menlo,monospace; font-size:.92em; background:var(--chip);
         padding:0 4px; border-radius:4px; }
  @media (prefers-reduced-motion:reduce) { * { transition-duration:.01ms !important; } }
"""

SCRIPT = """\
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
        <span class="tier-tag">${tier.tag}</span>
        <span class="tier-name">${tier.name}</span>
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
  $("ticks").innerHTML = TIER1_IDS.map(() => `<span class="tick"></span>`).join("");
  wire();
  updateMeter();
  applyFilter();
}

function updateMeter() {
  const n = TIER1_IDS.filter(i => state.inhand[i]).length;
  $("count").textContent = `core path: ${n} of ${TIER1_IDS.length} in hand`;
  document.querySelectorAll(".tick").forEach((t, i) => t.classList.toggle("on", !!state.inhand[TIER1_IDS[i]]));
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
        chips.append([r.cost, "free" if r.free else "paid"])
    elif r.free:
        chips.append(["free", "free"])
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
            "tag": f"tier {tier.num}", "name": tier.name,
            "role": inline_html(tier.role), "compact": tier.compact,
            "groups": groups,
        })

    standfirst = (f'<p class="standfirst">{inline_html(c.resources_intro)}</p>'
                  if c.resources_intro else "")
    reading = ""
    if c.reading_order:
        items = "".join(f"<li>{inline_html(x)}</li>" for x in c.reading_order)
        reading = ('<section class="section"><h2>Suggested reading order</h2>'
                   '<p class="tier-role">The curriculum formalizes this; here it is '
                   f"at a glance.</p><ol>{items}</ol></section>")
    verified = next((r.verified_at for r in mf.resources if r.verified_at), None)
    verified_line = f" · every url verified {e(verified)}" if verified else ""

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
<title>{e(c.id)} — the resources</title>
<style>
{STYLE}</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <p class="eyebrow"><a href="index.html">← course hub</a> &nbsp;·&nbsp; the resources ·
    {len(mf.resource_tiers)} tiers{verified_line}</p>
    <h1>The shelf,<br><em>tiered by role</em></h1>
    {standfirst}
    <div class="controls">
      <div class="meter">
        <div class="ticks" id="ticks" aria-hidden="true"></div>
        <span class="count" id="count"></span>
      </div>
      <span class="spacer"></span>
      <button class="filter" id="f-free" aria-pressed="false">Free only</button>
      <button class="filter" id="f-need" aria-pressed="false">Not in hand</button>
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
