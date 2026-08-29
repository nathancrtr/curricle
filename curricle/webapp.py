"""The web app: the three course views over the progress service.

Same pages the static renderers emit, with the state adapter switched to
server mode — initial state folded from the event ledger, writes POSTed to
a per-course events endpoint. Routes mirror the static filenames
(index.html, curriculum.html, learning-resources.html) so every relative
link inside the pages resolves unchanged, and course content under
`interactive/` plus the canonical markdown are served from the course repo.

T1 in practice: the app is configured with a tenant slug and resolves it to
a real row at startup. No slug, no app — there is no default tenant.

The front door (`/`) is the one page this module draws itself rather than
delegating to a renderer, and it draws it on the same design system (see
theme.py): wordmark, a greeting off the clock, and one panel per course
carrying the waypath in miniature. Every number on it is derived at request
time from the manifest and the fold — nothing about a course's state is
stored here — and it needs no JavaScript at all, so L1 ("no LLM on a request
path") stays trivially true of the whole app: every page is a pure function
of manifest plus ledger.
"""

from __future__ import annotations

import datetime
import html as html_mod
import mimetypes
import os
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import db, profile, progress, theme
from .compiler import compile_course
from .currender import render_curriculum
from .hubrender import render_hub
from .profilerender import render_profile_page
from .resrender import render_resources
from .schema import Manifest
from .sidecar import load_sidecar


@dataclass(frozen=True)
class CourseHandle:
    slug: str
    root: str
    content_root: str
    manifest: Manifest


def load_course(root: str) -> CourseHandle:
    root = os.path.abspath(os.path.expanduser(root))
    sidecar_path = os.path.join(root, "learning", "course.yaml")
    if not os.path.exists(sidecar_path):
        sidecar_path = os.path.join(root, "course.yaml")
    sidecar = load_sidecar(sidecar_path)
    manifest, issues = compile_course(root, sidecar)
    if manifest is None:
        raise RuntimeError(
            f"{root}: course does not compile:\n" +
            "\n".join(str(i) for i in issues if i.level == "error"))
    curriculum_rel = sidecar.course.docs.curriculum_doc or "learning/curriculum.md"
    return CourseHandle(
        slug=manifest.course.id, root=root,
        content_root=os.path.join(root, os.path.dirname(curriculum_rel)),
        manifest=manifest)


# --------------------------------------------------------------------------
# The front door
# --------------------------------------------------------------------------

INDEX_STYLE = theme.style("""\
  .wrap { max-width:760px; margin:0 auto; padding:48px 24px 80px; }
  .topbar { display:flex; align-items:center; gap:12px; margin:0 0 44px; }
  .wordmark { display:inline-flex; align-items:center; gap:10px;
              font:700 22px """ + theme.FONT_DISPLAY + """;
              color:var(--ink); text-decoration:none; letter-spacing:-.01em; }
  .wordmark svg { display:block; }
  .topbar .spacer { flex:1 1 auto; }
  .pill { text-decoration:none; }
  h1 { font-size:clamp(26px,5vw,34px); font-weight:700; letter-spacing:-.01em;
       margin:0 0 6px; }
  .lede { color:var(--muted); font-size:16.5px; margin:0 0 28px; }
  .course { display:block; text-decoration:none; color:inherit;
            padding:22px 24px; margin:0 0 18px;
            transition:box-shadow .2s ease, transform .2s ease, border-color .2s; }
  .course:hover { box-shadow:var(--shadow-lift); transform:translateY(-1px);
                  border-color:var(--accent); }
  .course h2 { font-size:20px; font-weight:700; margin:0 0 4px; }
  .course .desc { font-size:14.5px; line-height:1.55; color:var(--muted);
                  margin:0 0 14px; max-width:58ch; }
  .course .waypath { margin:0 0 10px; gap:5px; }
  .course .wp-stone { width:15px; height:8px; border-radius:4px; }
  .course .meta { display:flex; flex-wrap:wrap; align-items:center; gap:8px 14px;
                  font-size:14px; font-weight:600; color:var(--muted); }
  .course .meta b { color:var(--ink); }
  .course .go { margin-left:auto; color:var(--accent-text); white-space:nowrap; }
  footer { border-top:none; margin-top:48px; padding-top:0; font-size:13px;
           color:var(--muted); }
""")

# The wordmark is the waypath itself, in miniature: three stones — lit, ring,
# unlit — because the mark and the product's promise are the same drawing.
WORDMARK = ('<svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true">'
            '<rect x="0" y="1" width="10" height="10" rx="5" fill="var(--accent)"/>'
            '<rect x="13" y="2" width="8" height="8" rx="4" fill="none" '
            'stroke="var(--accent-strong)" stroke-width="2"/>'
            '<rect x="24" y="1" width="10" height="10" rx="5" fill="var(--stone)"/></svg>')


def _program_ids(manifest: Manifest) -> tuple[str, ...]:
    """The program track's progress ids, in walking order.

    This is the same rule `progress.summarize` folds its counts over — every
    progress id except the secondary tracks' stages. It is spelled again here
    only because summarize returns the numbers and not the ids, and the
    miniature waypath needs one stone per id. It reads `progress_ids()`
    rather than walking the phases a second time, so course order cannot
    drift; `tests/test_frontdoor.py` pins it to summarize id-for-id. A front
    door whose count disagrees with the hub its card links to is the one bug
    this surface must not have.
    """
    stage_ids = {s.id for t in manifest.tracks for s in t.stages}
    return tuple(p for p in manifest.progress_ids() if p not in stage_ids)


def _entry_labels(manifest: Manifest) -> dict[str, str]:
    """How a card names the thing that comes next, per progress id.

    A lookup table, not a third walk over the program: order is
    `_program_ids`' business and this only has to answer for an id summarize
    already chose.
    """
    labels: dict[str, str] = {}
    for u in manifest.units:
        if u.steps:
            labels.update({s.id: s.label for s in u.steps})
        else:
            labels[u.id] = f"Unit {u.num} · {u.title}"
    for m in manifest.milestones:
        labels[m.id] = theme.strip_leading_pictograph(m.label)
    return labels


def create_app(course_roots: list[str], tenant_slug: str,
               database_url: str | None = None) -> FastAPI:
    engine = db.make_engine(database_url)
    with engine.begin() as conn:
        tenant_id = db.tenant_id_for(conn, tenant_slug)   # fail at startup, T1
    scope = db.for_tenant(tenant_id)
    courses = {h.slug: h for h in (load_course(r) for r in course_roots)}

    app = FastAPI(title="curricle", docs_url=None, redoc_url=None)

    def handle(slug: str) -> CourseHandle:
        try:
            return courses[slug]
        except KeyError:
            raise HTTPException(404)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        e = html_mod.escape
        cards = []
        for h in courses.values():
            # One transaction per course. Honest at two, a smell at twenty —
            # the fix is a loader that folds every course in one query, which
            # belongs in progress.py, not here.
            with engine.begin() as conn:
                state = progress.load_state(conn, scope, h.manifest.course.id)
            summary = progress.summarize(h.manifest, state)
            done, total = summary["program_done"], summary["program_total"]
            next_id = summary["next_up"]
            # Falling back to the bare id is deliberate: splitting the walk
            # from the labels means an unlabelled id would otherwise read as
            # no next step at all, and the card would print "Complete." over
            # a course that is not.
            nxt = (_entry_labels(h.manifest).get(next_id, next_id)
                   if next_id else None)
            # The stones mirror theme.WAYPATH_JS: lit when done, and the ring
            # goes to the id summarize named next — not to "whichever stone
            # happens to be the first unlit one here", which is the same
            # answer only for as long as nobody changes either rule.
            spans = []
            for pid in _program_ids(h.manifest):
                cls = "wp-stone"
                if state.done.get(pid):
                    cls += " lit"
                if pid == next_id:
                    cls += " here"
                spans.append(f'<span class="{cls}"></span>')
            if done == 0:
                meta = f"<b>{total} steps</b>, ready when you are"
                if nxt:
                    meta += f" · begin with <b>{e(nxt)}</b>"
                go = "Begin →"
            elif nxt:
                meta = f"<b>{done} of {total}</b> done · next up: <b>{e(nxt)}</b>"
                go = "Continue →"
            else:
                meta = f"<b>Complete.</b> All {total} steps walked."
                go = "Revisit →"
            desc = (f'<p class="desc">{e(h.manifest.course.description)}</p>'
                    if h.manifest.course.description else "")
            cards.append(
                f'<a class="course panel" href="/c/{h.slug}/">'
                f"<h2>{e(h.manifest.course.title)}</h2>{desc}"
                f'<div class="waypath" aria-hidden="true">{"".join(spans)}</div>'
                f'<p class="meta"><span>{meta}</span>'
                f'<span class="go">{go}</span></p></a>')
        hello = theme.greeting(datetime.datetime.now().hour)
        lede = ("Your course is ready when you are."
                if len(cards) == 1 else "Pick up where you left off.")
        if not cards:
            cards.append('<p class="lede">No courses are configured yet — '
                         "start the server with <code>--course</code> "
                         "pointing at a course repo.</p>")
            lede = ""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>curricle — your courses</title>
<style>
{INDEX_STYLE}</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <a class="wordmark" href="/">{WORDMARK} curricle</a>
    <span class="spacer"></span>
    <a class="pill" href="/profile">Your profile</a>
  </div>
  <h1>{hello}, {e(tenant_slug)}.</h1>
  {f'<p class="lede">{lede}</p>' if lede else ""}
  {"".join(cards)}
  <footer>curricle · courses written for you, progress kept for you ·
  signed in as {e(tenant_slug)}</footer>
</div>
</body>
</html>
"""

    @app.get("/profile", response_class=HTMLResponse)
    def profile_page() -> str:
        with engine.begin() as conn:
            state = profile.load_profile(conn, scope)
        return render_profile_page(state, tenant_slug)

    @app.post("/api/profile/events")
    async def post_profile_event(request: Request) -> JSONResponse:
        body = await request.json()
        kind, fld, key = body.get("kind"), body.get("field"), body.get("key")
        payload = body.get("payload", {})
        if not all(isinstance(x, str) for x in (kind, fld, key)):
            raise HTTPException(422, "kind, field, key are required strings")
        if kind == "propose" and not payload.get("source"):
            # Anything arriving over the wire as a proposal names its source.
            raise HTTPException(422, "propose requires payload.source")
        try:
            with engine.begin() as conn:
                profile.append_profile_event(conn, scope, kind, fld, key, payload)
                state = profile.load_profile(conn, scope)
        except profile.InvalidProfileEvent as exc:
            raise HTTPException(422, str(exc))
        return JSONResponse({"ok": True, "pending": len(state.pending)})

    @app.get("/c/{slug}/")
    def course_root(slug: str) -> RedirectResponse:
        handle(slug)
        return RedirectResponse(f"/c/{slug}/index.html")

    def _state(h: CourseHandle) -> dict:
        with engine.begin() as conn:
            return progress.client_state(
                progress.load_state(conn, scope, h.manifest.course.id))

    @app.get("/c/{slug}/index.html", response_class=HTMLResponse)
    def hub(slug: str) -> str:
        h = handle(slug)
        return render_hub(h.manifest, api="api/events",
                          initial=_state(h)["progress"])

    @app.get("/c/{slug}/curriculum.html", response_class=HTMLResponse)
    def curriculum(slug: str) -> str:
        h = handle(slug)
        st = _state(h)
        return render_curriculum(
            h.manifest, api="api/events",
            initial={"progress": st["progress"], "notes": st["curriculum_notes"]})

    @app.get("/c/{slug}/learning-resources.html", response_class=HTMLResponse)
    def resources(slug: str) -> str:
        h = handle(slug)
        return render_resources(h.manifest, api="api/events",
                                initial=_state(h)["resources"])

    @app.post("/c/{slug}/api/events")
    async def post_event(slug: str, request: Request) -> JSONResponse:
        h = handle(slug)
        body = await request.json()
        kind = body.get("kind")
        subject_id = body.get("subject_id")
        payload = body.get("payload", {})
        if not isinstance(kind, str) or not isinstance(subject_id, str):
            raise HTTPException(422, "kind and subject_id are required strings")
        try:
            with engine.begin() as conn:
                progress.append_event(conn, scope, h.manifest,
                                      kind, subject_id, payload)
                if kind == "checkpoint_result":
                    # Checkpoint results become proposed profile evidence —
                    # the misses matter as much as the score (§Phase 2).
                    profile.propose_from_checkpoint(conn, scope, h.manifest,
                                                    subject_id, payload)
                state = progress.load_state(conn, scope, h.manifest.course.id)
        except progress.InvalidEvent as exc:
            raise HTTPException(422, str(exc))
        return JSONResponse({"ok": True,
                             "summary": progress.summarize(h.manifest, state)})

    @app.get("/c/{slug}/api/state")
    def get_state(slug: str) -> JSONResponse:
        h = handle(slug)
        with engine.begin() as conn:
            state = progress.load_state(conn, scope, h.manifest.course.id)
        return JSONResponse({"state": progress.client_state(state),
                             "summary": progress.summarize(h.manifest, state)})

    # Course content: interactive materials and the canonical markdown, read
    # from the course repo. Path-traversal is refused by construction: the
    # resolved path must stay inside content_root.
    @app.get("/c/{slug}/{path:path}")
    def content(slug: str, path: str) -> Response:
        h = handle(slug)
        target = os.path.realpath(os.path.join(h.content_root, path))
        if not target.startswith(os.path.realpath(h.content_root) + os.sep):
            raise HTTPException(404)
        if os.path.isdir(target):
            task = os.path.join(target, "task.md")
            target = task if os.path.exists(task) else target
        if not os.path.isfile(target):
            raise HTTPException(404)
        ctype = mimetypes.guess_type(target)[0] or "text/plain"
        if target.endswith(".md"):
            ctype = "text/plain"
        with open(target, "rb") as f:
            return Response(f.read(), media_type=f"{ctype}; charset=utf-8"
                            if ctype.startswith("text/") else ctype)

    return app
