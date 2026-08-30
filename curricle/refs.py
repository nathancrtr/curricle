"""Reference-scheme links: `res:` / `unit:` / `mat:` / `repo:`.

Rule 4 of the schema spec (platform-manifest.md §3.8): prose content links
by *reference*, not by URL — `[W&G](res:wg)` names the resource entry, and
each renderer resolves it for its own medium. The compiler validates every
reference against the manifest, so a dangling ref is a compile error where a
dead URL used to be a silent regret.

Two halves live here. `find_refs` is the compiler's: enumerate every
scheme-link in a content string so validation can refuse the dangling ones.
`RefResolver` is the renderers': one per rendered page, carrying where that
page sits (`to_root`) and whether the served app's routes exist (`served`),
so the same manifest link lands on the unit page, the reader, and a
standalone file without any renderer growing its own href arithmetic.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from .schema import Manifest, Material, Resource

SCHEMES = ("res", "unit", "mat", "repo")

# Scheme-links inside markdown link targets: `](res:wg)`. Bare `res:wg` in
# running prose is just prose — only a link asks to be resolved.
_REF_RE = re.compile(r"\]\((res|unit|mat|repo):([^)\s]+)\)")


def find_refs(text: str) -> list[tuple[str, str]]:
    """Every (scheme, target) linked from a content string, in order."""
    return [(m.group(1), m.group(2)) for m in _REF_RE.finditer(text)]


def iter_content(mf: Manifest):
    """Every content-bearing (where, text) pair in a manifest — the fields
    reference links may appear in. The compiler validates over exactly this
    walk, and the app derives the servable `repo:` set from the same walk,
    so 'compiles clean' and 'resolves when clicked' cannot disagree."""
    yield "course description", mf.course.description
    yield "course resources_intro", mf.course.resources_intro
    for line in mf.course.preamble:
        yield "course preamble", line
    for u in mf.units:
        for r in u.rows:
            yield f"unit {u.id} [{r.label}]", r.content
        yield f"unit {u.id} gloss", u.gloss
        yield f"unit {u.id} note", u.note
        yield f"unit {u.id} skippable_note", u.skippable_note
        if u.check:
            yield f"unit {u.id} check", u.check.q
            yield f"unit {u.id} check", u.check.ans
    for p in mf.phases:
        yield f"phase {p.id} goal", p.goal
        if p.checkpoint:
            yield f"phase {p.id} checkpoint", p.checkpoint.prose
            for _, text in p.checkpoint.track_goals:
                yield f"phase {p.id} checkpoint", text
    for m in mf.milestones:
        yield f"milestone {m.id}", m.label
        yield f"milestone {m.id}", m.detail
    for mat in mf.materials:
        yield f"material {mat.id} blurb", mat.blurb
    for r in mf.resources:
        yield f"resource {r.key}", r.why_this_one
        yield f"resource {r.key}", r.covers


def repo_ref_targets(mf: Manifest) -> frozenset[str]:
    """Every repo-relative path the manifest's content links via `repo:` —
    the exact set the served `repo/` route may hand out. The course repo
    holds more than the course (gitignored seeds, keys), so the route
    serves what the compiler blessed, never 'whatever is on disk'."""
    return frozenset(
        target
        for _, text in iter_content(mf)
        for scheme, target in find_refs(text or "")
        if scheme == "repo")


def resolve_markdown(text: str, mf: Manifest) -> str:
    """Resolve reference links for a plain-markdown medium (the MCP tutor
    export): no pages exist there, so `res:` becomes the verified URL,
    `mat:`/`repo:` become the repo-relative path in code, and `unit:` keeps
    just its label — the assistant reaches units through tools, not hrefs."""
    resources = {r.key: r for r in mf.resources}
    materials = {m.id: m for m in mf.materials}
    out = []
    last = 0
    for link in re.finditer(r"\[([^\]]+)\]\((res|unit|mat|repo):([^)\s]+)\)", text):
        label, scheme, target = link.group(1), link.group(2), link.group(3)
        out.append(text[last:link.start()])
        last = link.end()
        if scheme == "res" and target in resources:
            url = resources[target].all_links[0][1]
            if url.startswith(("http://", "https://")):
                out.append(f"[{label}]({url})")
            else:
                out.append(label)
        elif scheme == "mat" and target in materials:
            out.append(f"{label} (`{materials[target].path}`)")
        elif scheme == "repo":
            out.append(f"{label} (`{target}`)")
        else:
            out.append(label)
    out.append(text[last:])
    return "".join(out)


def split_ref(href: str) -> tuple[str, str] | None:
    """(scheme, target) if `href` is a reference, else None."""
    scheme, sep, target = href.partition(":")
    if sep and scheme in SCHEMES and target:
        return scheme, target
    return None


@dataclass(frozen=True)
class RefResolver:
    """Resolve reference links for one rendered page.

    `to_root` is the relative prefix from the page to the course base — ""
    for the hub/curriculum/resources pages, "../" for a unit page, deeper
    for the reader. `served` says whether the app's routes (unit pages,
    `read/`, `repo/`) exist; a standalone file resolves to the honest
    nearest thing instead of a dead route.
    """

    mf: Manifest
    to_root: str = ""
    served: bool = True

    # -- per-kind targets ---------------------------------------------------

    def material_href(self, m: Material) -> str:
        """Where a material opens from this page.

        Served, markdown goes through the themed reader (an exercise reads
        as its brief, `task.md`); widgets and quizzes are their own HTML and
        serve as themselves. Standalone, every path is just the file beside
        the page — raw, but real.
        """
        path = m.path
        if m.kind == "exercise":
            path = posixpath.join(path, "task.md")
        if self.served and path.endswith(".md"):
            return f"{self.to_root}read/{path}"
        return f"{self.to_root}{path}"

    def unit_href(self, unit_id: str) -> str:
        if self.served:
            return f"{self.to_root}unit/{unit_id}.html"
        return f"{self.to_root}curriculum.html#u-{unit_id}"

    def resource_href(self, r: Resource) -> tuple[str, bool]:
        """(href, external). An identifier-only URL (`urn:isbn:` — a real
        entry, not a fetchable one) lands on the shelf entry instead of
        pretending to be a link."""
        primary = r.all_links[0][1]
        if primary.startswith(("http://", "https://")):
            return primary, True
        return f"{self.to_root}learning-resources.html#res-{r.key}", False

    def repo_href(self, path: str) -> str:
        """A repo-relative file. Served, markdown reads in the theme via the
        `repo/` route; standalone, the link climbs from the content root the
        page sits in (the honest relative path, reachable or not)."""
        if self.served:
            return f"{self.to_root}repo/{path}"
        content_dir = posixpath.dirname(
            self.mf.course.docs.curriculum_doc or "learning/curriculum.md")
        return f"{self.to_root}{posixpath.relpath(path, content_dir or '.')}"

    # -- the one entry point ------------------------------------------------

    def resolve(self, href: str) -> tuple[str, bool] | None:
        """(resolved href, opens-externally) for a reference link, or None
        when `href` carries no scheme. An unresolvable target returns None
        too — the compiler refuses those, so reaching one here means the
        renderer was handed content the compiler never blessed; degrading
        to plain text beats emitting a dead link."""
        ref = split_ref(href)
        if ref is None:
            return None
        scheme, target = ref
        if scheme == "res":
            r = next((r for r in self.mf.resources if r.key == target), None)
            return self.resource_href(r) if r else None
        if scheme == "unit":
            if any(u.id == target for u in self.mf.units):
                return self.unit_href(target), False
            return None
        if scheme == "mat":
            m = next((m for m in self.mf.materials if m.id == target), None)
            return (self.material_href(m), False) if m else None
        if scheme == "repo":
            return self.repo_href(target), False
        return None
