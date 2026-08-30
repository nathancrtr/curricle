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

It is also where a new course's name comes from: `mint_course_id` turns a
learner's working title into the one string that is both the course id and
the directory holding it, collision-checked against everything already in
the home. Naming belongs here because the collision check is a question
about this directory, and because the id and the basename must agree.

What this module does *not* do is decide whether a course may be served.
`course_roots` answers a filesystem question — which immediate
subdirectories carry a sidecar — and nothing more; the compile gate is
`webapp.load_course`, which every registration path goes through. A
directory here is a candidate, never a promise.
"""

from __future__ import annotations

import os
import re

ENV_DIR = "CURRICLE_COURSES_DIR"

# The two places a course keeps its sidecar, in the order load_course looks:
# `learning/course.yaml` by convention, `course.yaml` for courses whose
# content lives at the repo root.
SIDECAR_NAMES = (os.path.join("learning", "course.yaml"), "course.yaml")

# A minted id is a directory name, a URL segment and a slug in a sidecar all
# at once, so it is ASCII, lowercase and short. Forty characters is long
# enough for a real title and short enough to read in a path.
ID_MAX = 40

# What a title with nothing sluggable in it becomes. A course still needs a
# home, and "" is not a directory name.
ID_FALLBACK = "course"

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


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


def mint_course_id(title: str, taken: set[str]) -> str:
    """The id a new course gets, which is also the name of its directory.

    One string does both jobs on purpose. Registration keys on the directory
    basename — the front door's rescan and `register_from_home` both look a
    slug up by directory name — so a course whose directory disagrees with
    the id in its sidecar is a course nothing can serve. Minting the pair as
    the same string makes the invariant true by construction rather than
    checked afterwards, and the collision check below is therefore against
    directory names as well as against loaded slugs.

    The rule: lowercase, runs of anything else become `-`, trimmed, capped at
    ID_MAX, and `course` when a title leaves nothing behind (a title written
    entirely in a non-Latin script is the honest case, not an odd one). A
    name already spoken for takes `-2`, `-3`, … — the suffix rides on top of
    the cap, because a disambiguator that could itself be truncated would not
    disambiguate.

    Ids are forever once `scope_saved` names one, so this is called once, at
    the moment the scope is saved, and never recomputed from a title again.
    """
    slug = _NOT_SLUG.sub("-", title.lower()).strip("-")[:ID_MAX].strip("-")
    slug = slug or ID_FALLBACK
    if slug not in taken:
        return slug
    return next(f"{slug}-{n}" for n in range(2, len(taken) + 3)
                if f"{slug}-{n}" not in taken)


def taken_ids(courses: dict, courses_dir: str | None) -> set[str]:
    """Every id a new course may not have: served slugs, and every name in
    the home.

    The directory listing is deliberately blunter than `course_roots`. That
    one answers "what can be served", and a course being built — a directory
    holding nothing but its `.draft-onboarding/` tree — cannot be; but its
    name is spoken for all the same, and minting a second course into it
    would have two flows writing one draft.
    """
    taken = set(courses)
    if courses_dir:
        root = os.path.abspath(os.path.expanduser(courses_dir))
        if os.path.isdir(root):
            taken |= {name for name in os.listdir(root)
                      if os.path.isdir(os.path.join(root, name))}
    return taken


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
