"""The web app: the three course views over the progress service.

Same pages the static renderers emit, with the state adapter switched to
server mode — initial state folded from the event ledger, writes POSTed to
a per-course events endpoint. Routes mirror the static filenames
(index.html, curriculum.html, learning-resources.html) so every relative
link inside the pages resolves unchanged, and course content under
`interactive/` plus the canonical markdown are served from the course repo.

T1 in practice: the app is configured with a tenant slug and resolves it to
a real row at startup. No slug, no app — there is no default tenant.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import db, progress
from .compiler import compile_course
from .currender import render_curriculum
from .hubrender import render_hub
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
    sidecar = load_sidecar(os.path.join(root, "learning", "course.yaml"))
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
        items = "".join(
            f'<li><a href="/c/{h.slug}/">{h.slug}</a> — {h.manifest.course.title}'
            f" ({len(h.manifest.units)} units)</li>"
            for h in courses.values())
        return (f"<!DOCTYPE html><title>curricle</title>"
                f"<body style=\"font:16px/1.6 Georgia,serif;background:#faf8f4;"
                f"color:#2b2620;max-width:640px;margin:3rem auto;padding:0 1rem\">"
                f"<h1 style=\"font-weight:400\">curricle</h1>"
                f"<p>Signed-in tenant: <b>{tenant_slug}</b></p><ul>{items}</ul>")

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
