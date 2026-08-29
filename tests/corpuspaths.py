"""Where the sibling courses live, seen from wherever this checkout sits.

The courses are not vendored — the corpus is the compiler's real test suite
(platform-design.md §8) — so four test modules have to find `textual-flow`,
`rhyme-schemer` and `learning/ml-ai` on disk. Each used to compute the parent
of the repo root, which is right from the main checkout and wrong from every
git worktree, where the root is `<repo>/.claude-worktrees/<name>` and the
parent holds no courses. The failure mode is the bad kind: `skipUnless` turns
those tests into skips, and a skipped suite reads as a pass.

So each root walks up on its own, and each is anchored on a marker file that
only a real course has rather than on a bare directory name. Both parts
matter. Independent walks, because a shared anchor halts on the first
*fragment* of a corpus and pins the rest to an ancestor that does not hold
them — a directory with `textual-flow` but no `learning/ml-ai` would take ml-ai
down with it. And a marker rather than a name, because an empty or unrelated
directory called `textual-flow` satisfies `isdir`, sails through the guard,
and then dies in `setUpClass` with `FileNotFoundError`. Roots resolving from
different ancestors is fine, and truer than forcing one answer: each course is
found where it actually is, and one that is genuinely missing degrades to a
clean skip on its own.

The guards import HAVE_TF / HAVE_RS / HAVE_ML from here rather than asking
`os.path.isdir` about a root. Skipping and searching are then literally the
same question — see `_is_course` — instead of two that agree until a decoy
comes between them.

Deliberately not configurable by environment: like the suite's refusal to be
pointed at a real database, what the tests run against is a property of where
the checkout sits, not of the shell that invoked them.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where the search starts and, failing everything, ends: the parent of the
# repo root, which is where the old arithmetic looked.
_START = os.path.dirname(REPO_ROOT)


def _is_course(root: str, marker: str) -> bool:
    """Is there really a course at `root`? The one predicate, used twice.

    `os.path.isfile` on the marker subsumes the directory question: a file —
    or a symlink to one — named `textual-flow` cannot hold
    `learning/course.yaml`, while a symlink to a real course repo can. The
    walk asks this to choose a root and the HAVE_* flags ask it to guard the
    tests, so what the suite skips on is exactly what it searched for.
    """
    return os.path.isfile(os.path.join(root, marker))


def _find(relpath: str, marker: str) -> str:
    """The nearest ancestor's `relpath` that `_is_course` vouches for.

    Stops at the filesystem root, falling back to today's answer — the parent
    of the repo root, where the old arithmetic looked. That fallback is a
    guess, not a finding: nothing reads it except an error message, because
    the HAVE_* flag beside it is what the guards consult.
    """
    d = _START
    while True:
        candidate = os.path.join(d, relpath)
        if _is_course(candidate, marker):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.join(_START, relpath)
        d = parent


# The shapes differ: textual-flow and rhyme-schemer are course repos, each
# carrying its sidecar at learning/course.yaml; ml-ai is a course directory
# inside the learning repo, carrying course.yaml at its own root.
_COURSE_REPO = os.path.join("learning", "course.yaml")
_COURSE_DIR = "course.yaml"

TF_ROOT = _find("textual-flow", _COURSE_REPO)
RS_ROOT = _find("rhyme-schemer", _COURSE_REPO)
ML_ROOT = _find(os.path.join("learning", "ml-ai"), _COURSE_DIR)

# What the guards skip on. A `*_ROOT` always names a root; whether a course is
# actually there is a separate question with its own answer, so no arrangement
# of same-named decoys can make a root look present when it is not.
HAVE_TF = _is_course(TF_ROOT, _COURSE_REPO)
HAVE_RS = _is_course(RS_ROOT, _COURSE_REPO)
HAVE_ML = _is_course(ML_ROOT, _COURSE_DIR)
