"""CLI: compile a course manifest.

    python -m curricle compile COURSE_ROOT --sidecar PATH [--out PATH]

Prints every issue; exits non-zero if any is an error. With --out, writes
the manifest YAML only when compilation is clean of errors.
"""

from __future__ import annotations

import argparse
import sys

import yaml

from .compiler import compile_course
from .sidecar import load_sidecar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="curricle")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compile", help="compile curriculum.md + sidecar to a manifest")
    c.add_argument("course_root", help="path to the course repo root")
    c.add_argument("--sidecar", required=True, help="path to course.yaml")
    c.add_argument("--out", help="write manifest YAML here (default: stdout summary only)")
    c.add_argument("--quiet", action="store_true", help="suppress warnings")
    args = parser.parse_args(argv)

    sidecar = load_sidecar(args.sidecar)
    manifest, issues = compile_course(args.course_root, sidecar)

    shown = [i for i in issues if not (args.quiet and i.level == "warning")]
    for issue in shown:
        print(issue, file=sys.stderr)

    if manifest is None:
        n_err = sum(1 for i in issues if i.level == "error")
        print(f"\nFAILED: {n_err} error(s), "
              f"{sum(1 for i in issues if i.level == 'warning')} warning(s)",
              file=sys.stderr)
        return 1

    pids = manifest.progress_ids()
    print(f"{manifest.course.id}: {len(manifest.phases)} phases, "
          f"{len(manifest.units)} units, {len(manifest.milestones)} milestone(s), "
          f"{len(manifest.materials)} materials, {len(manifest.resources)} resources, "
          f"{len(pids)} progress ids "
          f"({sum(1 for i in issues if i.level == 'warning')} warning(s))")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest.to_dict(), f, sort_keys=False,
                           allow_unicode=True, width=100)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
