"""Every face of the onboarding wizard, rendered from synthetic state.

`python -m curricle faces --out build/wizard` writes one file per face per
theme, an index, and a viewer that shows a face at two widths in both
themes side by side. No database, no worker, no model: every screen in
`wizard.py` is a pure function of the fold and of what the route hands it,
so this module builds the states by hand — a profile with claims in it, a
flow at each stop in each status, a failure for every (stage, reason) pair
the wording table knows — and draws the same page shell the route draws.

This is the review surface the live walk cannot be. A real run hurries past
its pending faces in seconds and reaches one failure face at most; the
promote stage's faces had never been rendered before this existed (issue
#61). The gallery also stands in for the screenshot pass the design review
asks for: two widths and two themes of every face, in one place, without
spending anything.

Two honesty notes. The pending faces are drawn without their poll script
and without the refresh fallback, because a static file has no status
route to ask; what is left is exactly the page at rest. And the gate face
compiles `examples/tinylang` as its draft, because a gate with nothing to
gate is a placeholder, and the example course is the one draft this
repository ships.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from . import onboarding, profile, theme, wizard
from .compiler import compile_course
from .schema import Manifest
from .sidecar import load_sidecar

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_COURSE = os.path.join(REPO_ROOT, "examples", "tinylang")

TENANT = "you"
COURSE_ID = "tiny-demo"
COURSES_DIR = "/home/you/curricle-courses"

# One claim per profile field the forms ask about, in a learner's own
# voice — the flow test's learner, so the filled forms and the review read
# as a person rather than as lorem.
CLAIMS = {
    "meta": "An engineer studying interpreters by building one.",
    "background": "Eight years of backend services in Go and Python, mostly "
                  "over Postgres.",
    "education": "A linguistics degree, a long time ago.",
    "style": "Learns by implementing — pair every abstract idea with "
             "something runnable.",
    "pacing": "About four hours a week, as two evening sessions.",
    "calibration": "Open with the failure the idea prevents, show it "
                   "concretely, then name it formally.",
    "subject_adapters": "Whatever the subject, bridge from hands-on intuition "
                        "to the formal idea.",
}

PLAN = {"phase_id": "p1", "lesson_unit": "u1", "widget_unit": "u2",
        "widget_concept": "precedence as a table of binding powers",
        "exercise_unit": "u2", "quiz": True, "bank": True}
# The estimate ends in a zero on purpose. These numbers are strings the whole
# way from the ledger to the page precisely so that nothing reformats them,
# and a trailing zero is the only fixture that can prove it: a float anywhere
# on the path renders "1.40" as "1.3" and every assertion on the number
# fails. The old "1.37" survived that round trip unchanged and so tested
# nothing. The cents are also checked against the rendered pages — the
# stylesheets quote contrast ratios in their comments, and "1.30" would have
# matched one of those, silently defeating the gate test's `assertNotIn`.
OUTLINE = {"plan": PLAN, "estimate_usd": "1.40", "headroom_usd": "20.00"}
SCOPE = {"title": "Interpreters, end to end", "subject": "interpreters",
         "mode": "project", "hours_per_week": 4}


@dataclass(frozen=True)
class Face:
    name: str               # file stem; also the viewer's hash
    stop: str
    sub: str | None
    screen: wizard.Screen
    note: str               # one line saying what state this face shows


def _profile(filled: bool) -> profile.ProfileState:
    if not filled:
        return profile.ProfileState()
    return profile.fold(
        ("assert", field, f"{field}-1", {"text": text, "tier": "attested"})
        for field, text in CLAIMS.items())


def _flow(stage: str, status: str, reason: str | None = None,
          **fields) -> onboarding.CourseFlow:
    flow = onboarding.CourseFlow(
        course_id=COURSE_ID, stage=stage, status=status, reason=reason,
        scope=SCOPE, updated_at=datetime.now(timezone.utc) - timedelta(minutes=3))
    for k, v in fields.items():
        setattr(flow, k, v)
    return flow


def _spend(drafted: bool = True, built: bool = False) -> wizard.Spend:
    return wizard.Spend(draft=Decimal("0.21") if drafted else Decimal(0),
                        build=Decimal("1.29") if built else Decimal(0),
                        drafts=1 if drafted else 0)


def example_manifest() -> Manifest | None:
    """The example course compiled, or None when the checkout has no
    examples directory (an installed copy)."""
    sidecar_path = os.path.join(EXAMPLE_COURSE, "learning", "course.yaml")
    if not os.path.exists(sidecar_path):
        return None
    manifest, _ = compile_course(EXAMPLE_COURSE, load_sidecar(sidecar_path))
    return manifest


def faces() -> list[Face]:
    """Every face, in walking order."""
    out: list[Face] = []

    def add(name, stop, sub, screen, note):
        out.append(Face(name, stop, sub, screen, note))

    # Stop 0 — welcome, with and without a worker to wait on.
    add("welcome", "profile", "welcome",
        wizard.welcome_screen(worker_running=True), "worker running")
    add("welcome-no-worker", "profile", "welcome",
        wizard.welcome_screen(worker_running=False),
        "no worker: the banner that says so")

    # Stops 1–5 — the forms empty and filled, then the review.
    for number in ("1", "2", "3", "4"):
        add(f"form-{number}-empty", "profile", number,
            wizard.form_screen(number, _profile(False)), "nothing saved yet")
        add(f"form-{number}-filled", "profile", number,
            wizard.form_screen(number, _profile(True)), "every box answered")
    add("review", "profile", "review",
        wizard.review_screen(_profile(True)), "the projection, ready to publish")

    # Stop 6 — the scope form.
    add("scope", "scope", None, wizard.scope_screen(), "the form that calls no model")

    # Stops 7, 9, 10 — each machine turn pending, then failed for every
    # reason the wording table knows.
    # The build faces carry an approved plan and two landed artifacts, so
    # the path in the panel has stones lit, one ringed and some to come.
    build = {"approval": {"plan": PLAN, "estimate_usd": "1.40"},
             "landed": ("lesson", "widget")}
    for stage, draw in (("outline", lambda f: wizard.outline_screen(f)),
                        ("build", lambda f: wizard.build_screen(
                            f, _spend(built=f.reason is not None))),
                        ("promote", lambda f: wizard.promote_screen(f))):
        extra = build if stage == "build" else {}
        add(f"{stage}-pending", stage, None,
            draw(_flow(stage, "pending", **extra)),
            "a machine's turn, three minutes in"
            + (", two of five landed" if extra else ""))
        for reason in onboarding.REASONS:
            add(f"{stage}-failed-{reason.replace('_', '-')}", stage, None,
                draw(_flow(stage, "failed", reason, **extra)),
                f"failed: {reason}")

    # Stop 8 — the gate over the example course, and over a draft that
    # will not compile.
    manifest = example_manifest()
    add("outline-gate", "outline_gate", None,
        wizard.outline_gate_screen(_flow("outline_gate", "waiting",
                                         outline=OUTLINE), manifest, _spend()),
        "the outline read back, and the number to approve")
    add("outline-gate-broken", "outline_gate", None,
        wizard.outline_gate_screen(_flow("outline_gate", "waiting",
                                         outline=OUTLINE), None, _spend()),
        "the draft would not compile")

    # Stop 10 — landed.
    add("landing", "done", None,
        wizard.landing_screen(_flow("done", "waiting", outline=OUTLINE),
                              COURSES_DIR, TENANT, _spend(built=True)),
        "the course, the receipt, the two ways on")

    # The placeholder a stop with no flow behind it falls back to.
    add("placeholder", "outline_gate", None,
        wizard.stage_screen("outline_gate", None),
        "a stop reached with no flow — the fallback screen")
    return out


def _still(page: str) -> str:
    """The page at rest: no poll, no refresh fallback."""
    return (page.replace(f"<script>{wizard.POLL_JS}</script>", "")
                .replace(wizard.NOSCRIPT_REFRESH, ""))


def render(face: Face, dark: bool) -> str:
    page = _still(wizard._page(face.stop, face.screen, TENANT, face.sub))
    stamp = "dark" if dark else "light"
    return page.replace('<html lang="en">', f'<html lang="en" data-theme="{stamp}">', 1)


_GALLERY_CSS = theme.style("""\
  .wrap { max-width:1000px; margin:0 auto; padding:24px 24px 60px; }
  h1 { font-size:24px; margin:0 0 4px; }
  .lede { color:var(--muted); margin:0 0 22px; }
  h2 { font-size:15px; margin:26px 0 8px; color:var(--muted); font-weight:700; }
  ul { list-style:none; padding:0; margin:0; }
  li { display:flex; gap:12px; align-items:baseline; padding:5px 0;
       border-top:1px solid var(--line-soft); font-size:14.5px; }
  li a { min-width:260px; }
  li span { color:var(--muted); }
  .frames { display:grid; grid-template-columns:400px 1fr; gap:18px; margin-top:18px; }
  .frames iframe { width:100%; border:1px solid var(--line); background:var(--bg); }
  .frames .narrow iframe { width:390px; }
  .frames b { display:block; font-size:13px; color:var(--muted); margin:0 0 6px; }
  .nav { display:flex; gap:14px; align-items:baseline; font-size:14.5px; }
  .nav .spacer { flex:1; }
  .full { width:100%; }
""")


def _index(all_faces: list[Face]) -> str:
    e = html.escape
    groups: dict[str, list[Face]] = {}
    for f in all_faces:
        groups.setdefault(f.stop, []).append(f)
    sections = []
    for stop, fs in groups.items():
        title = wizard.STOP_TITLES.get(stop, stop)
        items = "".join(
            f'<li><a href="view.html#{e(f.name)}">{e(f.name)}</a>'
            f"<span>{e(f.note)}</span></li>" for f in fs)
        sections.append(f"<h2>{e(stop)} — {e(title)}</h2><ul>{items}</ul>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wizard faces</title>
<style>
{_GALLERY_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>Every face of the onboarding wizard</h1>
  <p class="lede">{len(all_faces)} faces from synthetic state, each in both
  themes. Open one to see it at two widths side by side. Regenerate with
  <code>python -m curricle faces --out build/wizard</code>.</p>
  {"".join(sections)}
</div>
</body>
</html>
"""


# The viewer: the face named in the hash, four times. Plain script, no
# formatting braces of its own (it is concatenated, never %-formatted).
_VIEW_JS = """
(function () {
  var names = NAMES;
  function show() {
    var name = (location.hash || "#" + names[0]).slice(1);
    var i = names.indexOf(name);
    if (i < 0) { i = 0; name = names[0]; }
    document.getElementById("name").textContent = name;
    document.getElementById("prev").href = "#" + names[(i + names.length - 1) % names.length];
    document.getElementById("next").href = "#" + names[(i + 1) % names.length];
    document.getElementById("light-n").src = name + ".html";
    document.getElementById("light-w").src = name + ".html";
    document.getElementById("dark-n").src = name + ".dark.html";
    document.getElementById("dark-w").src = name + ".dark.html";
  }
  addEventListener("hashchange", show); show();
})();
"""


def _viewer(all_faces: list[Face]) -> str:
    import json
    names = json.dumps([f.name for f in all_faces])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wizard face</title>
<style>
{_GALLERY_CSS}</style>
</head>
<body>
<div class="wrap full">
  <p class="nav"><a href="index.html">All faces</a>
    <span class="spacer"></span>
    <a id="prev" href="#">Previous</a> <b id="name"></b> <a id="next" href="#">Next</a></p>
  <div class="frames">
    <div class="narrow"><b>light · 390px</b><iframe id="light-n" height="900"></iframe></div>
    <div><b>light · full width</b><iframe id="light-w" height="900"></iframe></div>
    <div class="narrow"><b>dark · 390px</b><iframe id="dark-n" height="900"></iframe></div>
    <div><b>dark · full width</b><iframe id="dark-w" height="900"></iframe></div>
  </div>
</div>
<script>
{_VIEW_JS.replace("NAMES", names)}</script>
</body>
</html>
"""


def write_all(out_dir: str) -> list[str]:
    """Write every face in both themes plus the index and the viewer;
    return the paths written."""
    os.makedirs(out_dir, exist_ok=True)
    all_faces = faces()
    written = []
    for face in all_faces:
        for dark in (False, True):
            path = os.path.join(out_dir, face.name + (".dark.html" if dark else ".html"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(render(face, dark))
            written.append(path)
    for name, body in (("index.html", _index(all_faces)),
                       ("view.html", _viewer(all_faces))):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        written.append(path)
    return written
