"""The managed courses home: where wizard-created courses live.

One directory per course, all of them under `CURRICLE_COURSES_DIR`
(onboarding-design.md §7). `serve` reads it at startup beside any `--course`
flags, which keep working unchanged — the home is a second source of course
roots, not a replacement for the first.

There is no default location, on purpose, and for the same reason `db.py`
refuses to default the database URL: a path that a stranger's machine
happens to have is not a decision anybody made, and a courses home guessed
wrong is a serve that silently publishes the wrong tree (or silently
publishes nothing). An unconfigured caller gets an exception. Callers for
whom the home is genuinely optional — `serve` on a checkout with only
`--course` roots — ask `maybe_courses_dir()` and get None.

What this module does *not* do is decide whether a course may be served.
`course_roots` answers a filesystem question — which immediate
subdirectories carry a sidecar — and nothing more; the compile gate is
`webapp.load_course`, which every registration path goes through. A
directory here is a candidate, never a promise.
"""

from __future__ import annotations

import os

ENV_DIR = "CURRICLE_COURSES_DIR"

# The two places a course keeps its sidecar, in the order load_course looks:
# `learning/course.yaml` by convention, `course.yaml` for courses whose
# content lives at the repo root.
SIDECAR_NAMES = (os.path.join("learning", "course.yaml"), "course.yaml")


def courses_dir() -> str:
    """The configured courses home, or an exception. No default."""
    path = os.environ.get(ENV_DIR)
    if not path:
        raise RuntimeError(
            f"{ENV_DIR} is not set. There is no default courses directory — "
            "configure one explicitly (dev example: ~/curricle-courses)."
        )
    return path


def maybe_courses_dir() -> str | None:
    """The courses home if configured, None if not — for callers to whom an
    unconfigured home is a legitimate state rather than a mistake."""
    return os.environ.get(ENV_DIR) or None


def course_roots(dir_path: str) -> list[str]:
    """Absolute paths of the course directories inside `dir_path`, by name.

    A subdirectory counts as a course when it carries a sidecar. Everything
    else in the home is passed over in silence: a stray `.DS_Store`, a
    scratch directory, and — the case this rule exists for — a course being
    built, holding only its `.draft-onboarding/` tree. A draft is not a
    course until promotion moves the real files into place, and the front
    door must not blink while that is happening.
    """
    root = os.path.abspath(os.path.expanduser(dir_path))
    if not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        candidate = os.path.join(root, name)
        if not os.path.isdir(candidate):
            continue
        if any(os.path.exists(os.path.join(candidate, s)) for s in SIDECAR_NAMES):
            found.append(candidate)
    return found
