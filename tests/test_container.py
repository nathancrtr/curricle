"""The image's two files have to agree with each other.

`Dockerfile` copies named paths and `.dockerignore` keeps named paths out of
the build context, and nothing checked that the two lists were compatible.
They stopped being compatible: the `COPY docs/ ./docs/` that came with the
served tutor doc landed while `.dockerignore` still excluded `docs/`, and the
image build failed with `"/docs": not found` — but only at the *next tag*,
because `.github/workflows/release.yml` runs on `v*` and nothing else. A
change that breaks the image can therefore sit on `main` indefinitely, and
this one did, until a release went to publish it.

So the agreement is checked here, in the suite that runs on every push and
every pull request. No Docker: a build is minutes and a runner, and the bug
this is for is a two-line disagreement between two text files that a parser
can see from the outside. What this cannot see — that a copied path is the
*right* one, that the app finds it at runtime — is not what broke.
"""

import fnmatch
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE = os.path.join(REPO_ROOT, "Dockerfile")
DOCKERIGNORE = os.path.join(REPO_ROOT, ".dockerignore")


def ignore_patterns() -> list[str]:
    with open(DOCKERIGNORE, encoding="utf-8") as f:
        return [line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")]


def copy_sources() -> list[str]:
    """Every source path a `COPY` names, destinations and flags dropped.

    The last word of a COPY is where it lands inside the image; everything
    before it is a path in the build context, which is what `.dockerignore`
    governs. `--from=` and friends are flags, not paths.
    """
    out: list[str] = []
    with open(DOCKERFILE, encoding="utf-8") as f:
        for line in f:
            if not re.match(r"^COPY\s", line):
                continue
            words = [w for w in line.split()[1:] if not w.startswith("--")]
            out.extend(words[:-1])          # the last word is the destination
    return out


def is_excluded(path: str, patterns: list[str]) -> bool:
    """Docker's rule: the last pattern that matches decides, `!` negates."""
    verdict = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        raw = (pattern[1:] if negated else pattern).strip("/")
        candidate = path.strip("/")
        if fnmatch.fnmatch(candidate, raw) or candidate.startswith(raw + "/"):
            verdict = not negated
    return verdict


class DockerfileAndIgnoreAgree(unittest.TestCase):
    def test_every_copied_path_can_reach_the_build_context(self):
        patterns = ignore_patterns()
        sources = copy_sources()
        # A guard reading an empty list would pass forever. The Dockerfile
        # copies named paths rather than `COPY . .` precisely so this list
        # exists, so its being non-empty is part of the claim.
        self.assertGreater(len(sources), 5, sources)
        for source in sources:
            with self.subTest(copy=source):
                self.assertFalse(
                    is_excluded(source, patterns),
                    f"Dockerfile copies {source!r} but .dockerignore excludes "
                    f"it — the build fails with '/{source.strip('/')}: not "
                    f"found', and only at the next v* tag")

    def test_every_copied_path_is_actually_in_the_repository(self):
        # The other half of the same failure: a COPY of a path nobody
        # committed fails identically, and just as late.
        for source in copy_sources():
            with self.subTest(copy=source):
                self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, source)),
                                f"Dockerfile copies {source!r}, which is not "
                                f"in the repository")

    def test_the_credential_boundary_is_still_excluded(self):
        """`local/` holds the API key and the personal profile seed.

        It is gitignored for that reason and excluded from the build context
        for the same one — the image goes to a public registry. This is the
        one entry in `.dockerignore` that is a security control rather than
        a size or tidiness decision, so it is asserted rather than assumed,
        and asserted here because the file it lives in is now edited for
        other reasons.
        """
        patterns = ignore_patterns()
        for secret in ("local", "local/anthropic-key", "local/seed.yaml"):
            with self.subTest(path=secret):
                self.assertTrue(is_excluded(secret, patterns))
        # And nothing copies it back in by another name.
        for source in copy_sources():
            self.assertFalse(source.strip("/").startswith("local"),
                             f"Dockerfile copies {source!r}")


class TheMatcherItself(unittest.TestCase):
    """The guard above is only as good as this, so this is checked too."""

    def test_a_directory_pattern_covers_what_is_under_it(self):
        self.assertTrue(is_excluded("docs/mcp-config.md", ["docs/"]))
        self.assertTrue(is_excluded("docs", ["docs/"]))
        self.assertFalse(is_excluded("documents/", ["docs/"]))

    def test_a_later_negation_wins(self):
        self.assertFalse(is_excluded("docs/mcp-config.md",
                                     ["docs/", "!docs/mcp-config.md"]))
        # …and order is the whole rule: reversed, the exclusion wins again.
        self.assertTrue(is_excluded("docs/mcp-config.md",
                                    ["!docs/mcp-config.md", "docs/"]))

    def test_globs_match(self):
        self.assertTrue(is_excluded("thing.pyc", ["*.pyc"]))
        self.assertFalse(is_excluded("thing.py", ["*.pyc"]))


if __name__ == "__main__":
    unittest.main()
