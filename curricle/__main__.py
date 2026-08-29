"""CLI: compile a course manifest.

    python -m curricle compile COURSE_ROOT --sidecar PATH [--out PATH]

Prints every issue; exits non-zero if any is an error. With --out, writes
the manifest YAML only when compilation is clean of errors.
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

from .compiler import compile_course
from .sidecar import load_sidecar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="curricle")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compile", help="compile curriculum.md + sidecar to a manifest")
    c.add_argument("course_root", help="path to the course repo root")
    c.add_argument("--sidecar", help="path to course.yaml "
                                     "(default: <course_root>/learning/course.yaml)")
    c.add_argument("--out", help="write manifest YAML here (default: stdout summary only)")
    c.add_argument("--quiet", action="store_true", help="suppress warnings")
    for name, helptext in (("hub", "render the course hub page from the manifest"),
                           ("curriculum", "render the curriculum view from the manifest"),
                           ("resources", "render the resources view from the manifest")):
        h = sub.add_parser(name, help=helptext)
        h.add_argument("course_root", help="path to the course repo root")
        h.add_argument("--sidecar", help="path to course.yaml "
                                         "(default: <course_root>/learning/course.yaml)")
        h.add_argument("--out", required=True, help="write the HTML here")
        h.add_argument("--quiet", action="store_true", help="suppress warnings")
    t = sub.add_parser("tenant", help="manage tenants")
    tsub = t.add_subparsers(dest="tenant_command", required=True)
    tc = tsub.add_parser("create", help="provision a tenant")
    tc.add_argument("slug")

    s = sub.add_parser("serve", help="run the web app over the progress service")
    s.add_argument("--course", action="append", required=True, dest="courses",
                   help="course repo root (repeatable)")
    s.add_argument("--tenant", required=True, help="tenant slug (no default — T1)")
    s.add_argument("--port", type=int, default=8765)

    imp = sub.add_parser("import-progress",
                         help="import browser localStorage state as ledger events")
    imp.add_argument("course_root", help="path to the course repo root")
    imp.add_argument("--tenant", required=True)
    imp.add_argument("--json", required=True,
                     help="JSON: {progress:{}, curriculum_notes:{}, "
                          "resources:{inhand:{},notes:{}}} — values may also be "
                          "the raw localStorage strings")

    p = sub.add_parser("profile", help="the learner-profile evidence ledger")
    psub = p.add_subparsers(dest="profile_command", required=True)
    ps = psub.add_parser("show", help="print the folded profile")
    ps.add_argument("--tenant", required=True)
    pr = psub.add_parser("render", help="render the SKILL.md projection")
    pr.add_argument("--tenant", required=True)
    pr.add_argument("--out", help="write here (default: stdout)")
    pi = psub.add_parser("import-seed", help="assert claims from a seed YAML")
    pi.add_argument("seed", help="YAML file: {claims: [{field, key, text, tier?, source?}]}")
    pi.add_argument("--tenant", required=True)
    pa = psub.add_parser("assert", help="assert one claim in the learner's voice")
    pa.add_argument("--tenant", required=True)
    pa.add_argument("--field", required=True)
    pa.add_argument("--key", required=True)
    pa.add_argument("--text", required=True)
    pa.add_argument("--tier", default="attested")
    pa.add_argument("--source")

    f = sub.add_parser("factory", help="the course factory (metered LLM jobs)")
    fsub = f.add_subparsers(dest="factory_command", required=True)
    fb = fsub.add_parser("build-phase", help="build a phase's interactive layer into a draft")
    fb.add_argument("course_root")
    fb.add_argument("--phase", required=True, type=int)
    fb.add_argument("--tenant", required=True)
    fb.add_argument("--lesson", help="unit id for the Socratic lesson guide")
    fb.add_argument("--widget", help="unit id for the widget")
    fb.add_argument("--widget-concept", help="what the widget makes manipulable")
    fb.add_argument("--exercise", help="unit id for the scaffolded exercise")
    fb.add_argument("--no-quiz", action="store_true")
    fb.add_argument("--no-bank", action="store_true")
    fb.add_argument("--dry-run", action="store_true",
                    help="assemble prompts and report sizes; no API calls")
    fp = fsub.add_parser("promote", help="apply a reviewed draft to the course")
    fp.add_argument("course_root")
    fp.add_argument("--phase", required=True, type=int)

    args = parser.parse_args(argv)

    if args.command == "tenant":
        return _tenant(args)
    if args.command == "profile":
        return _profile(args)
    if args.command == "factory":
        return _factory(args)
    if args.command == "serve":
        return _serve(args)
    if args.command == "import-progress":
        return _import_progress(args)

    sidecar_path = args.sidecar or default_sidecar_path(args.course_root)
    sidecar = load_sidecar(sidecar_path)
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

    if args.command in ("hub", "curriculum", "resources"):
        if args.command == "hub":
            from .hubrender import render_hub as render
        elif args.command == "curriculum":
            from .currender import render_curriculum as render
        else:
            from .resrender import render_resources as render
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(render(manifest))
        print(f"wrote {args.out}")
        return 0

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


def default_sidecar_path(course_root: str) -> str:
    """learning/course.yaml by convention; course.yaml for courses whose
    content lives at the repo root (ml-ai)."""
    preferred = os.path.join(course_root, "learning", "course.yaml")
    if os.path.exists(preferred):
        return preferred
    return os.path.join(course_root, "course.yaml")


def _tenant(args) -> int:
    from . import db
    engine = db.make_engine()
    with engine.begin() as conn:
        tenant_id = db.create_tenant(conn, args.slug)
    print(f"tenant {args.slug!r} created (id {tenant_id})")
    return 0


def _profile(args) -> int:
    from . import db, profile

    engine = db.make_engine()
    with engine.begin() as conn:
        scope = db.for_tenant(db.tenant_id_for(conn, args.tenant))

        if args.profile_command == "import-seed":
            with open(args.seed, encoding="utf-8") as f:
                seed = yaml.safe_load(f)
            n = profile.import_seed(conn, scope, seed["claims"])
            print(f"asserted {n} claim(s) for tenant {args.tenant!r}")
            return 0

        if args.profile_command == "assert":
            profile.append_profile_event(
                conn, scope, "assert", args.field, args.key,
                {"text": args.text, "tier": args.tier, "source": args.source})
            print(f"asserted {args.field}/{args.key}")
            return 0

        state = profile.load_profile(conn, scope)

    if args.profile_command == "show":
        for field in profile.FIELDS:
            claims = state.field_claims(field)
            if not claims:
                continue
            print(f"\n[{field}]")
            for c in claims:
                src = f"  ({c.source})" if c.source else ""
                print(f"  {c.key} [{c.tier}]{src}\n    {c.text[:100]}")
        if state.pending:
            print(f"\n{len(state.pending)} proposal(s) awaiting review "
                  "(accept on /profile or via the API)")
        return 0

    if args.profile_command == "render":
        from .profilerender import render_skill_md
        text = render_skill_md(state)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {args.out}")
        else:
            print(text)
        return 0
    return 1


def _factory(args) -> int:
    from . import db, factory, profile
    from .compiler import compile_course

    sidecar_path = default_sidecar_path(args.course_root)
    sidecar = load_sidecar(sidecar_path)
    manifest, issues = compile_course(args.course_root, sidecar)
    if manifest is None:
        for i in issues:
            print(i, file=sys.stderr)
        return 1
    curriculum_rel = sidecar.course.docs.curriculum_doc or "learning/curriculum.md"
    content_root = os.path.join(args.course_root,
                                os.path.dirname(curriculum_rel))
    phase_id = f"p{args.phase}"

    if args.factory_command == "promote":
        moved = factory.promote(args.course_root, content_root,
                                sidecar_path, phase_id)
        for m in moved:
            print(f"promoted: {m}")
        print("compile clean; draft removed. Remember to add the new "
              "materials to the owning units' Interactive sections in "
              "the curriculum prose.")
        return 0

    spec = factory.BuildSpec(
        phase_id=phase_id, lesson_unit=args.lesson, widget_unit=args.widget,
        widget_concept=args.widget_concept, exercise_unit=args.exercise,
        quiz=not args.no_quiz, bank=not args.no_bank)

    engine = db.make_engine()
    with engine.begin() as conn:
        scope = db.for_tenant(db.tenant_id_for(conn, args.tenant))
        prof = profile.load_profile(conn, scope)

    from .llm import Runner, load_models_config
    config = load_models_config()

    if args.dry_run:
        from .profilerender import render_skill_md
        profile_len = len(render_skill_md(prof))
        phase = next(p for p in manifest.phases if p.id == phase_id)
        ctx_len = len(factory.phase_md(manifest, phase))
        n_calls = sum([bool(args.lesson), bool(args.widget),
                       bool(args.exercise), not args.no_quiz, not args.no_bank])
        print(f"dry run: {n_calls} role call(s) on "
              f"{config.tiers[config.roles['lesson-writer']]}; "
              f"profile {profile_len}ch + phase context {ctx_len}ch per call; "
              f"budget ${config.budgets['default']:.2f}/stage; "
              f"rough cost ~${n_calls * 0.35:.2f}")
        return 0

    runner = Runner(engine, scope, config)
    report = factory.build_phase(runner, manifest, prof, content_root, spec)
    print(f"draft written to {report.draft_dir}")
    for a in report.artifacts:
        print(f"  {a.role:16s} -> {a.rel_path or a.note}")
    for role, cost in report.costs.items():
        print(f"  {role:16s} {cost}")
    print("Review the draft, then: python -m curricle factory promote "
          f"{args.course_root} --phase {args.phase}")
    return 0


def _serve(args) -> int:
    import uvicorn
    from .webapp import create_app
    app = create_app(args.courses, tenant_slug=args.tenant)
    print(f"serving tenant {args.tenant!r} on http://localhost:{args.port}/")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _import_progress(args) -> int:
    import json

    from . import db, progress
    from .compiler import compile_course

    sidecar_path = os.path.join(args.course_root, "learning", "course.yaml")
    manifest, issues = compile_course(args.course_root, load_sidecar(sidecar_path))
    if manifest is None:
        for i in issues:
            print(i, file=sys.stderr)
        return 1

    blob = json.loads(args.json)
    def maybe_parse(v):
        return json.loads(v) if isinstance(v, str) else (v or {})
    prog = maybe_parse(blob.get("progress"))
    notes = maybe_parse(blob.get("curriculum_notes"))
    res = maybe_parse(blob.get("resources"))

    engine = db.make_engine()
    imported, skipped = 0, []
    with engine.begin() as conn:
        scope = db.for_tenant(db.tenant_id_for(conn, args.tenant))
        def emit(kind, subject, payload):
            nonlocal imported
            try:
                progress.append_event(conn, scope, manifest, kind, subject, payload)
                imported += 1
            except progress.InvalidEvent as exc:
                skipped.append(str(exc))
        for sid, done in prog.items():
            emit("mark", sid, {"done": bool(done)})
        for sid, text in notes.items():
            if text:
                emit("note", sid, {"text": text})
        for key, inhand in (res.get("inhand") or {}).items():
            emit("resource_mark", key, {"inhand": bool(inhand)})
        for key, text in (res.get("notes") or {}).items():
            if text:
                emit("resource_note", key, {"text": text})
    print(f"imported {imported} event(s) for tenant {args.tenant!r}, "
          f"course {manifest.course.id!r}")
    for s in skipped:
        print(f"skipped: {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
