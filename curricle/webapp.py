"""The web app: the three course views over the progress service.

Same pages the static renderers emit, with the state adapter switched to
server mode — initial state folded from the event ledger, writes POSTed to
a per-course events endpoint. Routes mirror the static filenames
(index.html, curriculum.html, learning-resources.html) so every relative
link inside the pages resolves unchanged, and course content under
`interactive/` plus the canonical markdown are served from the course repo.

T1 in practice: the app is configured with a tenant slug and resolves it to
a real row at startup. No slug, no app — there is no default tenant.

Courses arrive from two places: the `--course` roots this app is built with,
and the managed courses home (`coursehome`), which is re-read while the app
runs so a course created after startup can be served without a restart.
Registration is pull-based because `serve` and the worker process share only
the database and the filesystem — nothing can call into this process — so a
route miss and each front-door render consult the home and load what is new.
Every one of those paths goes through `load_course`, so the startup rule
holds unchanged: a course that does not compile is an absence, never a page.

A tenant who has neither published a profile nor got a course is not shown
an empty front door: the gate below redirects every learner-facing route to
`/onboarding/`, where `wizard.py` draws the setup screens (mounted here, so
this module still owns every route the app answers). The gate is the third
registration path, and only in the instant before it redirects — while it
fires, the front door's rescan is the thing it is standing in front of, so
a course copied into the home by hand would otherwise wait for a restart. `/profile` stays
reachable from every state of the account — no state of your account is a
state where your data is hostage — and a tenant with a course configured is
never gated at all.

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
import sys
import threading
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import posixpath

from . import coursehome, db, onboarding, profile, progress, theme, wizard
from .compiler import compile_course
from .currender import render_curriculum
from .hubrender import render_hub
from . import refs
from .profilerender import render_profile_page, write_skill_md
from .resrender import render_resources
from .schema import Manifest, SchemaError
from .sidecar import load_sidecar
from .unitrender import render_reader, render_unit


@dataclass(frozen=True)
class CourseHandle:
    slug: str
    root: str
    content_root: str
    manifest: Manifest
    # What the repo/ route may serve: exactly the repo-relative paths the
    # manifest names — repo: references plus the docs pointers. The course
    # repo holds more than the course (gitignored seeds, keys, .git), so
    # the route hands out what the compiler blessed, never what's on disk.
    repo_paths: frozenset[str] = frozenset()


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
    docs = manifest.course.docs
    repo_paths = refs.repo_ref_targets(manifest) | frozenset(
        p for p in (docs.readme, docs.resources_doc, docs.curriculum_doc,
                    docs.review, docs.exploration) if p)
    return CourseHandle(
        slug=manifest.course.id, root=root,
        content_root=os.path.join(root, os.path.dirname(curriculum_rel)),
        manifest=manifest, repo_paths=repo_paths)


# The two ways a course root is refused rather than served: the compile came
# back dirty (load_course raises RuntimeError) or the sidecar violates the
# contract (SchemaError, out of the strict loader — what a half-written or
# hand-edited course.yaml in the courses home looks like). Both mean "not a
# servable course", which the lazy registration paths turn into absence.
# Anything else — a TypeError out of the compiler, say — is a bug in this
# repository, and a bug that manifests as courses quietly disappearing is a
# bug nobody finds.
REFUSALS = (RuntimeError, SchemaError)


# --------------------------------------------------------------------------
# The front door
# --------------------------------------------------------------------------

# The platform documents the app serves at /docs/<name>, and the page title
# each gets. A name not in here is a 404 whatever is on disk.
PLATFORM_DOCS = {"mcp-config.md": "Connecting the tutor"}

INDEX_STYLE = theme.style("""\
  .wrap { max-width:760px; margin:0 auto; padding:48px 24px 80px; }
  .topbar { display:flex; align-items:center; gap:12px; margin:0 0 44px; }
  .topbar .spacer { flex:1 1 auto; }
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
                  margin:0 0 14px; max-width:var(--measure); }
  .course .waypath { margin:0 0 10px; gap:5px; }
  .course .wp-stone { width:11px; height:11px; }
  /* The card's own padding is symmetric; the meta row's inherited bottom
     margin was not, so every course card sat 23px from its top edge and
     37px from its bottom and read as sagging. */
  .course .meta { display:flex; flex-wrap:wrap; align-items:center; gap:8px 14px;
                  margin:14px 0 0; font-size:14px; font-weight:600;
                  color:var(--muted); }
  .course .meta b { color:var(--ink); }
  .course .go { margin-left:auto; color:var(--accent-text); white-space:nowrap; }
  footer { border-top:none; margin-top:48px; padding-top:0; font-size:13px;
           color:var(--muted); }
""")

# The wordmark is `theme.WORDMARK`, drawn by the design system and used here
# and by the wizard's masthead. It moved out of this module when the wizard
# grew a masthead of its own: `webapp` imports `wizard`, so a mark the wizard
# could reach had to live below them both.


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


# The whole client contract for a native material, served as one file. A
# material links it and calls `curricle.checkpoint("<its material id>",
# {score, total, misses})` once, when the learner finishes; the server
# validates the id against the manifest and the payload against the event
# rules, so a typo here is a 422, not silent data. The base URL is derived
# from the page's own path — materials never hard-code where they are
# mounted. Kept `%`-free and f-string-free on principle (see theme.py's
# formatting hazard note).
MATERIAL_JS = """\
(() => {
  const m = location.pathname.match(/^(.*\\/c\\/[^/]+\\/)/);
  const base = m ? m[1] : "./";
  function post(kind, subject_id, payload) {
    return fetch(base + "api/events", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, subject_id, payload }),
    });
  }
  window.curricle = {
    post,
    checkpoint: (id, result) => post("checkpoint_result", id, result),
  };
})();
"""


# What the onboarding gate lets through: the wizard itself, and the profile
# surface in both its shapes, because the promise is that your own data is
# reachable from every state of your account. The wizard needs no asset of
# its own — its stylesheet is inlined in the page, like every other page
# here — so there is nothing else on this list, and anything added to it is
# a route an unstarted tenant may reach.
GATE_EXEMPT = ("/onboarding", "/profile", "/api/profile")


def create_app(course_roots: list[str], tenant_slug: str,
               database_url: str | None = None,
               courses_dir: str | None = None,
               profile_skill_out: str | None = None) -> FastAPI:
    engine = db.make_engine(database_url)
    with engine.begin() as conn:
        tenant_id = db.tenant_id_for(conn, tenant_slug)   # fail at startup, T1
    scope = db.for_tenant(tenant_id)
    courses: dict[str, CourseHandle] = {}
    # Registration happens on request threads now, and uvicorn runs the sync
    # routes in a threadpool: two requests that miss on the same new course
    # would otherwise both compile it and race the collision check, which is
    # a check that only means anything if check-and-insert is one step. The
    # lock is held across the compile too — the simpler correct shape, and
    # contention here is two threads at the moment a course first appears.
    registration = threading.Lock()

    def register_course(root: str) -> CourseHandle:
        """Compile one course root and add it to the served map.

        The single insertion point — startup and both lazy paths arrive here
        — so "never serve a course that does not compile" stays one rule in
        one place: `load_course` raises on a dirty compile and this does not
        catch it. Callers decide what a refusal means (a failure to start,
        or a 404); none of them may decide it means a half-loaded handle.

        Two roots claiming one course id is refused rather than resolved.
        Which of them wins would otherwise depend on load order, and a
        served course whose identity depends on argument order is exactly
        the guess this codebase does not make. Sameness is realpath: one
        directory reached twice, once through a symlink, is one root.
        """
        with registration:
            h = load_course(root)
            prior = courses.get(h.slug)
            if prior is not None and (os.path.realpath(prior.root)
                                      != os.path.realpath(h.root)):
                raise RuntimeError(
                    f"two course roots claim the id {h.slug!r}: {prior.root} "
                    f"and {h.root} — refusing to guess which one to serve")
            courses[h.slug] = h
            return h

    for root in course_roots:
        register_course(root)
    for root in (coursehome.course_roots(courses_dir) if courses_dir else ()):
        register_course(root)

    def register_from_home(slug: str) -> CourseHandle | None:
        """Try the courses home for a slug this app has not loaded.

        A miss is a miss, whatever caused it: no home configured, no such
        directory, a directory that is not a course yet, a course that does
        not compile. The caller gets None and the learner gets a 404 — the
        wizard's own ledger is where a failed build explains itself, not a
        page served to whoever guessed the URL.

        The lookup is by directory name and the answer is by course id, and
        those are not the same thing: a directory whose sidecar declares
        some other id registers under that id and is *not* returned here.
        Serving it under the name in the URL would publish a course under a
        slug it never claimed, and every link inside the page would then
        disagree with the address bar. (Minting is what keeps the two equal
        for wizard-created courses; this is what happens when they aren't.)
        """
        if not courses_dir:
            return None
        root = os.path.join(os.path.abspath(os.path.expanduser(courses_dir)),
                            slug)
        if root not in coursehome.course_roots(courses_dir):
            return None
        try:
            register_course(root)
        except REFUSALS as exc:
            print(f"courses: {root} not registered: {exc}", file=sys.stderr)
            return None
        return courses.get(slug)

    def scan_home() -> None:
        """Register every course in the home this app has not loaded yet.

        The pull path's wide end: a directory nobody asked for by name, but
        which appeared since the last time anyone looked — the promotion
        that finished in the worker process, or a course somebody copied in
        by hand. Only unknown directories are compiled, so a loaded course
        is never recompiled, and a refusal leaves that course off the app as
        it was off it a moment ago rather than taking the caller down.

        Synchronous, and the compile inside it can be a real amount of work:
        every caller from the event loop hands it to the threadpool.
        """
        for root in (coursehome.course_roots(courses_dir) if courses_dir else ()):
            if os.path.basename(root) not in courses:
                try:
                    register_course(root)
                except REFUSALS as exc:
                    print(f"courses: {root} not registered: {exc}",
                          file=sys.stderr)

    app = FastAPI(title="curricle", docs_url=None, redoc_url=None)
    wizard.mount(app, engine=engine, scope=scope, tenant_slug=tenant_slug,
                 courses=courses, courses_dir=courses_dir,
                 profile_skill_out=profile_skill_out)

    @app.middleware("http")
    async def onboarding_gate(request: Request, call_next):
        """Send an unstarted tenant to the wizard, from wherever they asked.

        Two conditions, both cheap and both re-asked every request: no course
        is configured, and the onboarding fold has no `profile_published`
        row. The course check comes first because it is free and because it
        is the one that exempts a corpus user entirely — someone serving
        their own course repos is never gated, whatever their profile says.

        Nothing about the decision is cached beyond the request. A cookie or
        a module-level flag would be a second place the wizard's position is
        recorded, and the ledger is the only one allowed to have it: a reload
        can never put the wizard behind work already done.

        307 rather than 302 so a POST arrives at the wizard as a POST — a
        gated write that silently became a GET would look to the caller like
        a write that succeeded.

        The one thing this does beyond deciding is scan the courses home,
        and only in the moment it is about to redirect. While the gate fires
        it is the front door's lazy rescan that never runs, so a tenant who
        skipped the wizard and copied a course into the home would stay
        gated until somebody restarted the process — an honest bug with a
        dishonest symptom, since their course is sitting right there. One
        scan at that exact point costs nothing on any other request, and it
        goes through the threadpool and through `register_course`'s lock
        like every other registration: a compile on the event loop would
        stall every request in the process, which is a worse bug than the
        one being fixed. (Wizard users never reach it — publishing gives
        them a course, and a published profile turns the gate off anyway.)
        """
        path = request.url.path
        if not courses and not any(path == prefix or path.startswith(prefix + "/")
                                   for prefix in GATE_EXEMPT):
            # The route functions are sync and run in the threadpool; this
            # middleware is async and runs on the loop, so its one query goes
            # to the threadpool by hand rather than blocking every other
            # request for the length of a round trip.
            def published() -> bool:
                with engine.begin() as conn:
                    return onboarding.load_state(conn, scope).profile_published

            if not await run_in_threadpool(published):
                await run_in_threadpool(scan_home)
                if not courses:
                    return RedirectResponse("/onboarding/", status_code=307)
        return await call_next(request)

    def handle(slug: str) -> CourseHandle:
        h = courses.get(slug) or register_from_home(slug)
        if h is None:
            raise HTTPException(404)
        return h

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        e = html_mod.escape
        # The front door is where a course finished since the last request
        # first appears, so it rescans the home before drawing.
        scan_home()
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
                meta = f"<b>{total} steps</b>"
                if nxt:
                    meta += f" · begin with <b>{e(nxt)}</b>"
                go = "Begin"
            elif nxt:
                meta = f"<b>{done} of {total}</b> done · next up: <b>{e(nxt)}</b>"
                go = "Continue"
            else:
                meta = f"<b>Complete.</b> All {total} steps walked."
                go = "Revisit"
            desc = (f'<p class="desc">{e(h.manifest.course.description)}</p>'
                    if h.manifest.course.description else "")
            cards.append(
                f'<a class="course panel" href="/c/{h.slug}/">'
                f"<h2>{e(h.manifest.course.title)}</h2>{desc}"
                f'<div class="waypath" aria-hidden="true">{"".join(spans)}</div>'
                f'<p class="meta"><span>{meta}</span>'
                f'<span class="go">{go}</span></p></a>')
        hello = theme.greeting(datetime.datetime.now().hour)
        lede = ("Your course, and where you are on it."
                if len(cards) == 1 else "Pick up where you left off.")
        if not cards:
            cards.append('<p class="lede">No courses are configured yet — '
                         "start the server with <code>--course</code> "
                         "pointing at a course repo, or set "
                         f"<code>{coursehome.ENV_DIR}</code> to a directory "
                         "of courses.</p>")
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
    <a class="wordmark" href="/">{theme.WORDMARK} curricle</a>
    <span class="spacer"></span>
    <a class="pill" href="/profile">Your profile</a>
  </div>
  <h1>{hello}.</h1>
  {f'<p class="lede">{lede}</p>' if lede else ""}
  {"".join(cards)}
  <footer>curricle · signed in as {e(tenant_slug)}</footer>
</div>
</body>
</html>
"""

    def render_projection(state: profile.ProfileState) -> None:
        """Re-render the installed SKILL.md, when one is installed.

        The other half of the wizard's hook (design §4, Stop 5): every path
        that writes a profile event re-renders, so nobody has to remember to.
        `propose` changes `pending` rather than the fold's claims and so
        re-renders to the same bytes — idempotent, and cheaper to do than to
        reason about which kinds could have moved a claim.

        Called after the transaction commits, never inside it: a file beside
        an uncommitted row would be a projection of a ledger that might yet
        roll back.
        """
        if profile_skill_out is not None:
            write_skill_md(state, profile_skill_out)

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
        render_projection(state)
        return JSONResponse({"ok": True, "pending": len(state.pending)})

    # Platform documents: the checkout's own docs/, served through the
    # themed reader from a short allowlist. Not the `repo/` route — that one
    # is manifest-blessed per course by design — and not "whatever is under
    # docs/": a page the landing card links to on a browser-only flow has
    # to exist, and the list is how that is known (issue #60).
    @app.get("/docs/{name}", response_class=HTMLResponse)
    def platform_doc(name: str) -> str:
        title = PLATFORM_DOCS.get(name)
        if title is None:
            raise HTTPException(404)
        target = os.path.join(coursehome.checkout_home(), "docs", name)
        if not os.path.isfile(target):
            raise HTTPException(404)
        with open(target, encoding="utf-8") as f:
            text = f.read()
        return render_reader(None, text, doc_title=title, depth=1,
                             doc_dir="", platform_doc=f"docs/{name}")

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
            h.manifest, api="api/events", unit_pages=True,
            initial={"progress": st["progress"], "notes": st["curriculum_notes"]})

    @app.get("/c/{slug}/learning-resources.html", response_class=HTMLResponse)
    def resources(slug: str) -> str:
        h = handle(slug)
        return render_resources(h.manifest, api="api/events",
                                initial=_state(h)["resources"])

    # The shared assets a native material links —
    # the theme as a stylesheet, and the one line of reporting machinery.
    # Serving them beside the content is the decision that materials are
    # served-app citizens, not standalone files (DIRECTION: server-required
    # is accepted; the static export bundles these alongside).
    @app.get("/c/{slug}/theme.css")
    def theme_css(slug: str) -> Response:
        handle(slug)
        return Response(theme.style(""),
                        media_type="text/css; charset=utf-8")

    @app.get("/c/{slug}/material.js")
    def material_js(slug: str) -> Response:
        handle(slug)
        return Response(MATERIAL_JS,
                        media_type="text/javascript; charset=utf-8")

    @app.get("/c/{slug}/unit/{unit_id}.html", response_class=HTMLResponse)
    def unit_page(slug: str, unit_id: str) -> str:
        h = handle(slug)
        if not any(u.id == unit_id for u in h.manifest.units):
            raise HTTPException(404)
        return render_unit(h.manifest, unit_id, api="../api/events",
                           initial=_state(h)["progress"])

    # A markdown material, rendered inside the theme instead of arriving as
    # text/plain. The raw file stays reachable at its own path — this route
    # is a view of it, not a replacement.
    @app.get("/c/{slug}/read/{path:path}", response_class=HTMLResponse)
    def read_doc(slug: str, path: str) -> str:
        h = handle(slug)
        target = os.path.realpath(os.path.join(h.content_root, path))
        if not target.startswith(os.path.realpath(h.content_root) + os.sep):
            raise HTTPException(404)
        if not target.endswith(".md") or not os.path.isfile(target):
            raise HTTPException(404)
        material = next(
            (m for m in h.manifest.materials
             if m.path == path
             or (m.kind == "exercise"
                 and posixpath.join(m.path, "task.md") == path)), None)
        title = material.title if material else posixpath.basename(path)
        with open(target, encoding="utf-8") as f:
            text = f.read()
        depth = len([seg for seg in f"read/{path}".split("/") if seg]) - 1
        return render_reader(h.manifest, text, doc_title=title,
                             material=material, depth=depth)

    # A repo-level document the manifest points at (a repo: reference, or a
    # docs pointer): markdown reads in the theme, anything else serves raw.
    # Only manifest-blessed paths — see CourseHandle.repo_paths.
    @app.get("/c/{slug}/repo/{path:path}")
    def repo_doc(slug: str, path: str) -> Response:
        h = handle(slug)
        if path not in h.repo_paths:
            raise HTTPException(404)
        target = os.path.realpath(os.path.join(h.root, path))
        if not target.startswith(os.path.realpath(h.root) + os.sep):
            raise HTTPException(404)
        if not os.path.isfile(target):
            raise HTTPException(404)
        if target.endswith(".md"):
            with open(target, encoding="utf-8") as f:
                text = f.read()
            depth = len([seg for seg in f"repo/{path}".split("/") if seg]) - 1
            return HTMLResponse(render_reader(
                h.manifest, text, doc_title=posixpath.basename(path),
                depth=depth))
        ctype = mimetypes.guess_type(target)[0] or "text/plain"
        with open(target, "rb") as f:
            return Response(f.read(), media_type=f"{ctype}; charset=utf-8"
                            if ctype.startswith("text/") else ctype)

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
