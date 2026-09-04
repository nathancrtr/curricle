"""Render a course hub page from a manifest.

The hub is the course's front door: progress checkboxes per phase, secondary
track steppers, material cards, trigger phrases, document links. It is a pure
function of the manifest — the generated page carries no hand-maintained data,
which is what retires the three-place registration rule.

Fidelity contract with the hand-built original (textual-flow's index.html):
same checkable ids, same localStorage key and value shape ({id: bool}), same
graceful degradation. Existing learner state loads unchanged.

Design: the *companion* system (see theme.py). The hub opens with the welcome
panel — the waypath plus plain second-person copy and a Begin/Continue action
that goes straight to the next step — because "where was I, what's next?" is
the question this page exists to answer. Zero progress renders as the whole
path laid out ahead, never as an empty bar. The program itself is a single
vertical spine: phases in walking order down one column, a rail threading the
phase badges, the one undone-next row raised as the page's single hot element.
A curriculum is sequential; the layout carries the sequence.
"""

from __future__ import annotations

import html
import json
import posixpath

from . import theme
from .inlinemd import inline_html
from .refs import RefResolver
from .schema import Manifest

STYLE = theme.style("""\
  .wrap { max-width:1020px; margin:0 auto; padding:36px 24px 80px; }
  header.top { margin:0 0 20px; }
  h1 { font-size:clamp(26px,4.5vw,34px); font-weight:700; letter-spacing:-.01em;
       margin:0 0 6px; }
  h2 { font-size:20px; font-weight:700; margin:40px 0 14px; }
  h2 .sub { font-size:14px; font-weight:500; }
  .sub { color:var(--muted); margin:0; }
  .courseid { font-size:13.5px; font-weight:600; color:var(--muted); margin:0 0 10px; }

  /* the welcome panel — the waypath lives here */
  .welcome { margin:22px 0 0; padding:20px 22px; }
  .welcome .waypath { margin:0 0 12px; }
  #summary { font-size:16.5px; margin:0; }
  #summary b { font-family:""" + theme.FONT_DISPLAY + """; }
  .welcome .go { display:flex; flex-wrap:wrap; gap:10px; margin:16px 0 0; }

  /* the program spine — one column, phases in walking order. Sequence is
     carried by the layout itself: a vertical rail threads the phase badges
     top to bottom, so reading order can never be ambiguous. */
  .spine { position:relative; max-width:820px; }
  .spine::before { content:""; position:absolute; left:15px; top:10px; bottom:12px;
                   width:2px; border-radius:1px; background:var(--line); }
  .phase { position:relative; padding:0 0 0 50px; margin:0 0 34px; }
  .phase:last-child { margin-bottom:0; }
  /* the rail is a path between phase markers — it ends at the last badge,
     it does not trail past it */
  .phase:last-child::after { content:""; position:absolute; left:14px; top:34px;
                             bottom:-2px; width:4px; background:var(--bg); }
  .phase-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 10px;
                margin:0 0 4px; }
  .phase-num { position:absolute; left:0; top:-2px; display:grid;
               place-items:center; width:32px; height:32px; border-radius:var(--r-ctl);
               background:var(--bg); color:var(--muted);
               border:1px solid var(--line); box-shadow:0 0 0 5px var(--bg);
               font:700 15px """ + theme.FONT_DISPLAY + """; }
  .phase.current .phase-num { background:var(--accent-strong);
                              border-color:var(--accent-strong);
                              color:var(--on-accent); }
  .phase h3 { margin:0; font-size:17px; font-weight:700; line-height:1.3; }
  .phase-count { margin-left:auto; font-size:13.5px; font-weight:600;
                 color:var(--muted); white-space:nowrap;
                 font-variant-numeric:tabular-nums; }
  .phase .goal { font-size:14px; line-height:1.55; color:var(--muted);
                 margin:0 0 10px; max-width:64ch; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
          gap:16px; }
  .unit { display:flex; align-items:flex-start; gap:10px; padding:7px 10px;
          margin:0 -10px; border-radius:var(--r-card); font-size:15px; line-height:1.5; }
  .unit input { flex:none; width:18px; height:18px; margin:3px 0 0;
                accent-color:var(--accent-strong); cursor:pointer;
                scroll-margin-top:24vh; }
  .unit label { cursor:pointer; min-width:0; }
  .unit label .chip { margin-left:7px; vertical-align:1px; }
  /* A row's title navigates to its unit page (served); it reads as the row
     until hovered, so the spine stays a list, not a wall of links. The
     done-strike is drawn by the label and runs through the anchor. */
  .unit label .ulink { color:inherit; text-decoration:none; }
  .unit label .ulink:hover { color:var(--accent-text);
                             text-decoration:underline;
                             text-underline-offset:2px; }
  .unit label .next-flag { display:none; margin:0 8px 0 0; }
  .unit.done label { color:var(--muted); text-decoration:line-through;
                     text-decoration-color:var(--faint); }
  .unit.next { background:var(--panel); border:1.5px solid var(--accent);
               box-shadow:var(--shadow); padding:10px 12px; margin:5px -12px; }
  .unit.next label .next-flag { display:inline-block; }
  /* Source order is load-bearing here: .unit.ms and .unit.next are both
     (0,2,0), so a milestone that is *also* the next row keeps its green fill
     only because this rule comes second. Reorder them and the hot milestone
     row turns white and loses its milestone identity — the ring and the
     "next" chip already say hot; the fill is the only thing saying
     milestone. */
  .unit.ms { background:var(--good-soft); }
  .unit.ms .flag { flex:none; margin:5px 1px 0; color:var(--good-text); }
  .unit.ms input { accent-color:var(--good); }
  /* ...and on that fill the ring keeps --accent-strong. Under the warm
     palette this was forced arithmetic: --accent on --good-soft computed
     2.82, under the 3.0 non-text floor. Under verdigris it clears (3.71
     light / 6.11 dark) and the rule survives on the reason that outlived
     the number — the hot ring is one token everywhere it appears, the same
     one the holding phase's badge and the lit waypath stones carry
     (5.04 light / 6.11 dark here), because a "you are here" mark that
     changes color with its background is two marks. */
  .unit.ms.next { border-color:var(--accent-strong); }
  @media (max-width:560px) {
    .spine::before { left:12px; }
    .phase { padding-left:40px; }
    .phase:last-child::after { left:11px; top:28px; }
    .phase-num { width:26px; height:26px; border-radius:var(--r-ctl); top:0;
                 font-size:13px; box-shadow:0 0 0 4px var(--bg); }
  }

  .card { padding:16px 18px; }
  .card h3 { margin:0 0 4px; font-size:16px; font-weight:700; }
  .card h3 a { color:var(--ink); text-decoration:none; }
  .card h3 a:hover { color:var(--accent-text); text-decoration:underline;
                     text-underline-offset:3px; }
  .card p { margin:0; font-size:13.5px; line-height:1.5; color:var(--muted); }

  .say { font:13.5px """ + theme.FONT_MONO + """; background:var(--chip);
         padding:3px 9px; border-radius:var(--r-ctl); display:inline-block; margin:2px 0; }
  .phrases { padding:16px 18px; font-size:14.5px; line-height:2; }
  ul.docs { margin:0; padding:0 0 0 2px; list-style:none;
            font-size:14.5px; line-height:2.1; }
  ul.docs a { text-decoration:none; font-weight:600; }
  ul.docs a:hover { text-decoration:underline; text-underline-offset:3px; }
  .docs-panel { padding:14px 20px; }

  .track { display:flex; flex-wrap:wrap; gap:8px; align-items:center;
           padding:14px 16px; font-size:14px; }
  .track .step { min-height:36px; display:inline-flex; align-items:center;
                 border:1.5px solid var(--line); border-radius:var(--r-ctl);
                 padding:4px 14px; background:var(--chip); cursor:pointer;
                 font-weight:500; transition:border-color .2s, background .3s; }
  .track .step:hover { border-color:var(--accent); }
  .track .step.done { background:var(--good-soft); border-color:var(--good);
                      color:var(--good-text); }
  .track .step.done::before { content:"✓"; margin-right:6px; font-weight:700; }
  .track .arrow { color:var(--muted); }
  .track-tools { margin:10px 0 0; font-size:14px; color:var(--muted); }
""")

SCRIPT = theme.WAYPATH_JS + """\
const KEY = %(key)s;
const API = %(api)s;          // null: localStorage mode; else: POST events here
const INITIAL = %(initial)s;  // server-folded state, or null
const PHASES = %(phases)s;
const TRACKS = %(tracks)s;
const HREFS = %(hrefs)s;      // row id -> its unit page; {} standalone

let saved = INITIAL || {};
if (!API) { try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {} }
function put(id, v) {
  saved[id] = v;
  if (API) fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "mark", subject_id: id, payload: { done: v } }) }).catch(() => {});
  else try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
}

const allUnits = PHASES.flatMap(p => p.units.map(u => u[0]));
function refresh() {
  const done = allUnits.filter(id => saved[id]).length;
  let nextId = null, next = null;
  for (const p of PHASES) {
    for (const u of p.units) if (!saved[u[0]]) { nextId = u[0]; next = u[1]; break; }
    if (next) break;
  }
  waypath(document.getElementById("path"), allUnits, id => !!saved[id], nextId);
  const s = document.getElementById("summary");
  if (done === 0)
    s.innerHTML = `<b>The path is laid.</b> ${allUnits.length} steps from here to done — begin with <b>${next}</b>.`;
  else if (next)
    s.innerHTML = `<b>Welcome back.</b> ${done} of ${allUnits.length} done · next up: <b>${next}</b>`;
  else
    s.innerHTML = `<b>Every step walked.</b> Course complete — all ${allUnits.length}.`;
  PHASES.forEach((p, i) => {
    const d = p.units.filter(u => saved[u[0]]).length;
    phaseEls[i].count.textContent = `${d} of ${p.units.length}`;
    phaseEls[i].div.classList.toggle("current",
      p.units.some(u => u[0] === nextId));
  });
  for (const id in rows) rows[id].classList.toggle("next", id === nextId);
  const r = document.getElementById("resume");
  if (r) {
    r.hidden = !next;
    if (next) {
      // Server mode deep-links into the curriculum at the next entry;
      // a standalone file jumps down this page to the row itself.
      r.href = API ? `curriculum.html#u-${encodeURIComponent(nextId)}`
                   : `#${encodeURIComponent(nextId)}`;
      r.textContent = done === 0 ? "Begin" : "Continue";
    }
  }
}

const phasesDiv = document.getElementById("phases");
const phaseEls = [], rows = {};
for (const p of PHASES) {
  const div = document.createElement("section");
  div.className = "phase";
  const head = document.createElement("div"); head.className = "phase-head";
  const num = document.createElement("span"); num.className = "phase-num";
  num.textContent = p.num;
  const h = document.createElement("h3"); h.textContent = p.name;
  const count = document.createElement("span"); count.className = "phase-count";
  head.appendChild(num); head.appendChild(h); head.appendChild(count);
  const g = document.createElement("p"); g.className = "goal";
  g.innerHTML = p.goal;   // pre-rendered by the generator; no user content

  div.appendChild(head); div.appendChild(g);
  for (const [id, label, tags, kind] of p.units) {
    const row = document.createElement("div");
    row.className = "unit" + (saved[id] ? " done" : "") + (kind === "m" ? " ms" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.id = id; cb.checked = !!saved[id];
    cb.onchange = () => { put(id, cb.checked); row.classList.toggle("done", cb.checked); refresh(); };
    row.appendChild(cb);
    if (kind === "m") row.insertAdjacentHTML("beforeend", %(flag)s);
    const lb = document.createElement("label");
    lb.htmlFor = id;
    const nf = document.createElement("span");
    nf.className = "chip acc next-flag"; nf.textContent = "next";
    lb.appendChild(nf);
    if (HREFS[id]) {
      // The title navigates to the unit's page; the checkbox stays the
      // marking control. An anchor inside the label does not activate the
      // checkbox — interactive descendants opt out of label forwarding.
      const a = document.createElement("a");
      a.className = "ulink"; a.href = HREFS[id]; a.textContent = label;
      lb.appendChild(a);
    } else {
      lb.appendChild(document.createTextNode(label));
    }
    for (const t of (tags || [])) {
      const s = document.createElement("span");
      s.className = "chip" + (t === "widget" ? " acc" : ""); s.textContent = t;
      lb.appendChild(s);
    }
    row.appendChild(lb);
    rows[id] = row;
    div.appendChild(row);
  }
  phaseEls.push({ div, count });
  phasesDiv.appendChild(div);
}

for (const track of TRACKS) {
  const el = document.getElementById("track-" + track.id);
  track.stages.forEach(([id, label], i) => {
    if (i) { const a = document.createElement("span"); a.className = "arrow"; a.textContent = "\\u2192"; el.appendChild(a); }
    const b = document.createElement("button");
    b.className = "step" + (saved[id] ? " done" : "");
    b.textContent = label;
    b.onclick = () => { put(id, !saved[id]); b.classList.toggle("done", saved[id]); };
    el.appendChild(b);
  });
}
refresh();
"""


def render_hub(mf: Manifest, *, api: str | None = None,
               initial: dict | None = None) -> str:
    c = mf.course
    e = html.escape
    units_by_id = {u.id: u for u in mf.units}
    milestones_by_id = {m.id: m for m in mf.milestones}

    # --- data payloads ------------------------------------------------------
    # Rows are heterogeneous on purpose: [id, label, tags] for units and for
    # the steps of a stepped unit, [id, label, tags, "m"] for a true
    # milestone. That is forced, not chosen. tests/test_corpus.py's
    # TestHubParity pins p0's last row to exactly ["p0-para", <label>,
    # ["quiz"]] — p0-para is a *step* of the stepped unit u0, not a
    # milestone — so giving every row a fourth element to make the shape
    # uniform breaks a pin that exists to protect stored progress ids from
    # migrating out from under the learner. The reader destructures a
    # trailing `kind`, which is simply undefined on the three-element rows.
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
                m = milestones_by_id[entry]
                rows.append([entry, theme.strip_leading_pictograph(m.label),
                             [], "m"])
        phases_js.append({"num": str(p.num),
                          "name": p.title,
                          "goal": inline_html(p.goal), "units": rows})
    tracks_js = [{"id": t.id, "stages": [[s.id, s.label] for s in t.stages]}
                 for t in mf.tracks]

    # Row id -> unit page, served only (the app is the only place unit pages
    # exist). A separate map, not a fifth row element: TestHubParity pins the
    # row arrays' exact shapes to protect stored progress ids, and the rows
    # carry ids, never navigation. A step navigates to the unit that owns it;
    # a milestone owns no page and stays plain text.
    hrefs_js: dict[str, str] = {}
    if api:
        for u in mf.units:
            for rid in ([s.id for s in u.steps] or [u.id]):
                hrefs_js[rid] = f"unit/{u.id}.html"

    # --- sections -----------------------------------------------------------
    parts: list[str] = []
    if api:
        parts.append('<p class="eyebrow"><a href="/">Your courses</a></p>')
    parts.append('<header class="top">')
    parts.append(f"<h1>{e(c.title)}</h1>")
    parts.append(f'<p class="courseid">{e(c.id)}</p>')
    if c.description:
        parts.append(f'<p class="sub">{e(c.description)}</p>')
    go_links = '<div class="go"><a class="pill primary" id="resume" href="#" hidden></a>'
    if api:
        go_links += '<a class="pill" href="curriculum.html">The curriculum</a>'
        # The resources page exists for every course; a *shelf* does not.
        # With no entries in the manifest that page has nothing to tier and
        # nothing to track (resrender says so honestly), so offering it as a
        # sibling pill routes people to an empty room. Same rule that keeps
        # these pills out of standalone renders: a dead primary button is
        # worse than none.
        if mf.resources:
            go_links += '<a class="pill" href="learning-resources.html">The resources</a>'
    go_links += "</div>"
    parts.append('<div class="welcome panel">'
                 '<div class="waypath" id="path" aria-hidden="true"></div>'
                 '<p id="summary"></p>'
                 f"{go_links}</div>")
    parts.append("</header>")

    parts.append("<h2>The program track</h2>\n"
                 '<div class="spine" id="phases"></div>')

    def material_href(m) -> str:
        # Served markdown reads in the themed reader (an exercise opens as
        # its brief, task.md); everything else opens at its own path.
        # Standalone has no reader and keeps raw links. Same resolution the
        # unit page uses (refs.RefResolver.material_href).
        return RefResolver(mf, served=api is not None).material_href(m)

    for t in mf.tracks:
        cadence = f' <span class="sub" style="font-size:14px">({e(t.cadence)})</span>' \
            if t.cadence else ""
        parts.append(f"<h2>The {e(t.name)} track{cadence}</h2>\n"
                     f'<div class="panel track" id="track-{e(t.id)}"></div>')
        # A track's own materials live with the track, not in a grid of
        # everyone's: the trainers are Greek-track furniture, so they sit
        # under the Greek track's stepper. Served only — standalone keeps
        # the card grid below instead.
        tools = [m for m in mf.materials if m.track == t.id]
        if api and tools:
            links = " · ".join(
                f'<a href="{e(material_href(m))}">{e(m.title)}</a>'
                for m in tools)
            parts.append(f'<p class="track-tools">Its tools, in the '
                         f"browser: {links}</p>")

    # The card grids were the pre-unit-page way to reach materials, and on
    # the served app they were a junk drawer: every widget and quiz of the
    # whole course, unordered, beside a spine that already walks the course
    # in order. Served, unit-owned materials live on their unit pages, a
    # track's on its track, the unowned in the documents panel — so the
    # grids render only standalone, where no unit pages exist and the cards
    # are the only browser access a course-repo reader has.
    cards = [m for m in mf.materials
             if m.kind in ("widget", "trainer", "quiz") ]
    if cards and not api:
        parts.append("<h2>Widgets &amp; quizzes "
                     '<span class="sub">(self-contained — '
                     "they open right here in the browser)</span></h2>")
        parts.append('<div class="grid">')
        for m in cards:
            blurb = f"<p>{e(m.blurb)}</p>" if m.blurb else ""
            parts.append(f'<div class="card panel"><h3><a href="{e(m.path)}">'
                         f"{e(m.title)}</a></h3>{blurb}</div>")
        parts.append("</div>")

    if c.trigger_phrases:
        parts.append("<h2>Working with your assistant "
                     '<span class="sub">(open a fresh chat '
                     "in this repo and say the words)</span></h2>")
        parts.append('<div class="panel phrases">')
        for tp in c.trigger_phrases:
            note = f" — {e(tp.note)}" if tp.note else ""
            parts.append(f'<div><span class="say">{e(tp.say)}</span>{note}</div>')
        parts.append("</div>")

    exercises = [m for m in mf.materials if m.kind == "exercise"]
    if exercises and not api:   # served: an exercise's brief is on its unit page
        parts.append("<h2>Exercises "
                     '<span class="sub">(stub + failing tests; '
                     "green bar = done — run in a terminal)</span></h2>")
        parts.append('<div class="grid">')
        for m in exercises:
            blurb = e(m.blurb) if m.blurb else ""
            cmd = (f" <code>{e(m.grader.command)}</code>"
                   if m.grader and m.grader.command else "")
            parts.append(f'<div class="card panel"><h3>{e(m.title)}</h3>'
                         f"<p>{blurb}{cmd}</p></div>")
        parts.append("</div>")

    # --- the documents -----------------------------------------------------
    # Every path here is course-repo-relative, and the page lives in the
    # curriculum doc's directory — that is the content root the app serves
    # from, and it refuses anything resolving outside it. So a doc kept above
    # that root (textual-flow's REVIEW.md and exploration/) is a link that
    # 404s on a served instance; a repo-level file serves through the repo/
    # route instead, and only a directory pointer is dropped there rather
    # than shipped dead. A standalone render sits in the course repo, where
    # the same relative paths do resolve, so it keeps them all.
    #
    # The link text is the document's own file name. The manifest carries no
    # titles for documents — schema.Docs is five optional path strings — so
    # a human name would have to be invented in this renderer; what it can
    # drop is the leading "../", which is navigation, not a name.
    d = c.docs
    doc_root = posixpath.dirname(d.curriculum_doc or "learning/curriculum.md")
    doc_items = []

    def add_doc(path: str, gloss: str) -> None:
        href = posixpath.relpath(path, doc_root)
        if path.endswith("/"):
            href += "/"                       # a directory keeps its slash
        if api and href.startswith("../"):
            # Outside the content root. A repo-level *file* is servable via
            # the repo/ route (which serves exactly the docs the manifest
            # names); a directory pointer still has nowhere to land.
            if path.endswith("/"):
                return
            name = posixpath.basename(path)
            doc_items.append(f'<li><a href="repo/{e(path)}">{e(name)}</a>'
                             f" — {gloss}</li>")
            return
        if api and href.endswith(".md"):
            # Served, a markdown document goes through the themed reader
            # rather than arriving as text/plain; the raw file stays at its
            # own path. Standalone renders keep the raw link — read/ only
            # exists on the app.
            href = "read/" + href
        name = posixpath.basename(path.rstrip("/")) + ("/" if path.endswith("/") else "")
        doc_items.append(f'<li><a href="{e(href)}">{e(name)}</a> — {gloss}</li>')

    if d.curriculum_doc:
        add_doc(d.curriculum_doc,
                f"the whole course: {len(mf.phases)} phases, {len(mf.units)} units")
    if d.resources_doc:
        add_doc(d.resources_doc, "every source, tiered by role")
    if d.readme:
        add_doc(d.readme, "how to drive all of this")
    if d.review:
        add_doc(d.review, "research positioning")
    if d.exploration:
        add_doc(d.exploration, "how this program was chosen")
    # Materials nothing owns — no unit, no phase, no track (the question
    # bank) — are course-wide reference, which is what this panel holds.
    # Served only: standalone they are already on the card grid above.
    if api:
        for m in mf.materials:
            if not (m.unit or m.phase or m.track):
                gloss = e(m.blurb) if m.blurb else m.kind.replace("-", " ")
                doc_items.append(f'<li><a href="{e(material_href(m))}">'
                                 f"{e(m.title)}</a> — {gloss}</li>")
    if doc_items:
        parts.append("<h2>The documents</h2>\n<div class=\"panel docs-panel\">"
                     "<ul class=\"docs\">" + "\n".join(doc_items) + "</ul></div>")

    # Where the marks actually go. Served, they are rows in the tenant's
    # append-only ledger — the front door on the same instance promises
    # "progress kept for you" and means it. Telling that learner their
    # two-year record lives in localStorage invites them to treat it as a
    # cache they may clear. Standalone renders genuinely are localStorage.
    kept = ("progress is kept for you on the server" if api
            else "progress is stored in this browser's localStorage")
    parts.append(f"<footer>{e(c.id)} course hub · generated by curricle from the "
                 f"course manifest · course v{e(c.version.rev)} — {e(c.version.date)} · "
                 f"{kept}</footer>")

    script = SCRIPT % {
        "key": json.dumps(c.progress_storage_key),
        "api": json.dumps(api),
        "initial": json.dumps(initial, ensure_ascii=False),
        "phases": json.dumps(phases_js, ensure_ascii=False),
        "tracks": json.dumps(tracks_js, ensure_ascii=False),
        "hrefs": json.dumps(hrefs_js),
        "flag": json.dumps(theme.FLAG_SVG),
    }
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c.title)} — course hub</title>
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
