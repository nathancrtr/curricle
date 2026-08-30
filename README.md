# curricle

A personalized-learning platform for one person: compile a course from
markdown, serve it with real progress tracking, and let an LLM build its
interactive layer under a budget.

A **course manifest** is the single machine-readable source of truth for a
course's structure — phases, units, tracks, milestones, materials, resources,
and the derived progress-id contract. Markdown (`curriculum.md`) stays the
authoring format; this package compiles it, together with a small **sidecar**
(`course.yaml`) carrying what markdown doesn't, into a validated manifest that
everything else renders from.

The design and its decided trade-offs are in
[`docs/platform-design.md`](docs/platform-design.md); the schema is specified
in [`docs/platform-manifest.md`](docs/platform-manifest.md).

## Quickstart

Requires Python 3.12+. Nothing below needs a database.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Compile the example course, then render its three static pages
python -m curricle compile examples/tinylang --out build/tinylang.manifest.yaml
python -m curricle hub        examples/tinylang --out /tmp/tinylang/index.html
python -m curricle curriculum examples/tinylang --out /tmp/tinylang/curriculum.html
python -m curricle resources  examples/tinylang --out /tmp/tinylang/learning-resources.html
open /tmp/tinylang/index.html
```

[`examples/tinylang`](examples/tinylang/README.md) is a real, complete course —
build a small interpreted language over eight weeks — and it is the template to
copy when you want one of your own. It is deliberately small, but it exercises
every part of the schema: a parallel track, a milestone that is not a unit, all
four material kinds, a grader, tiered resources, and all four reference schemes
in the prose.

## Running the served app

The static pages keep their state in the browser. The served app keeps it in
Postgres as an append-only event ledger, adds the reader and the unit pages,
and is the mode the rest of the platform is built around. It needs a Postgres
you can reach and it binds to localhost — see [Security posture](#security-posture).

```bash
export CURRICLE_DATABASE_URL="postgresql+psycopg:///curricle"
alembic upgrade head
python -m curricle tenant create example
python -m curricle serve --course examples/tinylang --tenant example --port 8765
# then: http://localhost:8765/
```

Pass `--course` more than once to serve several courses from one front door.

## The learner profile

The profile is a fold over an evidence ledger, and the skill file every Claude
session reads is a **generated projection** of it — never hand-edited. Evidence
tiers come from provenance, not confidence: `attested` (the learner said it),
`demonstrated` (course activity proved it), `thin` (claimed, uncorroborated).
The agent proposes; the human publishes.

```bash
python -m curricle profile import-seed examples/example-profile-seed.yaml --tenant example
python -m curricle profile show   --tenant example
python -m curricle profile render --tenant example --out build/example-profile-SKILL.md
```

[`build/example-profile-SKILL.md`](build/example-profile-SKILL.md) is exactly
what those commands produce from the example seed. Point `--out` at
`~/.claude/skills/learner-profile/SKILL.md` once it is your own profile.

Checkpoint quizzes POSTed to the events API become *proposed* `demonstrated`
evidence, misses included, and wait on the `/profile` page until you accept
them.

## The course factory

The factory drafts a phase's interactive layer — lesson guide, widget,
exercise, quiz, question bank — calibrated by the derived profile and by
exemplars from the course's own earlier phases.

```bash
# Key from ANTHROPIC_API_KEY or gitignored local/anthropic-key
python -m curricle factory build-phase <course_root> --phase 2 \
    --tenant example --lesson u4 --widget u3 --exercise u3 [--dry-run]
python -m curricle factory promote <course_root> --phase 2
```

**This spends your own money.** Every call goes through a metered runner that
writes a token ledger and refuses once a stage passes its budget; the budgets
and the only mention of any model or price live in
[`models.yaml`](models.yaml), so changing either is a YAML edit. Start with
`--dry-run`, which assembles the prompts and reports their sizes without
calling the API.

Outputs are refused rather than reviewed: generated exercise tests are executed
against their stub, and if they pass, the build fails. Drafts land in
`interactive/.draft-pN/` and only `factory promote` touches the course — and it
aborts unless the compile stays clean.

## Layout

- `curricle/schema.py` — the manifest data model. **This module is the contract**:
  strict decoding, enumerated vocabularies, derived data (`progress_ids()`,
  `tags_for_unit()`) computed rather than stored.
- `curricle/mdparse.py` — parser for the `curriculum.md` house format (phases,
  unit rows, checkpoints, check-yourself blocks, version footers). Two dialects:
  `bullets` and `headings`.
- `curricle/sidecar.py` — strict loader for `course.yaml`.
- `curricle/compiler.py` — merge + validate + refuse. House rules become errors
  or warnings here: dangling refs, unregistered files, bare URLs in prose,
  vanished ids. Every issue names a place you can act on.
- `curricle/refs.py` — the `res:` / `unit:` / `mat:` / `repo:` link schemes,
  validated at compile and resolved per medium at render.
- `curricle/db.py` — tables and the tenancy invariants, satisfied by
  construction: every table classified at import, `TenantScope` the only path
  to scoped rows, purge and export derived from the classification.
- `curricle/progress.py` — the event ledger's pure fold and append-time
  validation against the manifest.
- `curricle/profile.py`, `profilerender.py` — the evidence ledger and its
  projections (the skill file, the review page).
- `curricle/llm.py`, `factory.py` — the metered runner and the course factory.
  No LLM call is ever on a request path.
- `curricle/theme.py` — the design system: one set of tokens, the shared
  stylesheet, the waypath. Renderers compose `theme.style(own_css)` rather than
  carrying palettes of their own. Rationale and the computed contrast table are
  in [`DIRECTION.md`](DIRECTION.md).
- `curricle/webapp.py` — the FastAPI app serving the views in server mode.
- `migrations/` — Alembic; the schema changes by migration only.
- `build/` — compiled manifests and rendered pages, committed for inspection
  and regenerated in the same commit as any change upstream of them.
- `examples/` — the tinylang course and the example profile seed.

## Tests

```bash
python -m unittest discover tests
```

The suite brings its own Postgres: a throwaway `initdb` cluster per process on
a unix socket in a temp directory, migrated and torn down at exit. It never
reads a database URL from the environment and so cannot be pointed at a real
database.

Two things worth knowing before you read a green run as full coverage:

- `tests/test_corpus.py` runs against private sibling course repos and
  **skips cleanly when they are absent**, which is the normal case for anyone
  but the author. `tests/test_example_course.py` covers the same ground against
  `examples/tinylang` and never skips.
- The progress-id list pinned in `test_corpus.py` is a migration-safety
  contract against real learner state, not an assertion about current
  behaviour. Don't "fix" it to match the code; fix the code to match it, or
  migrate deliberately.

## Security posture

curricle is **single-tenant by instance** and has no authentication. The tenant
is resolved once at startup, there is no default tenant anywhere (an
unconfigured caller gets an exception, never tenant 0), and `serve` binds
`127.0.0.1`. That is the design for one person on their own machine, not an
oversight.

It is not built to be exposed to a network. Anyone who can reach the port is
the tenant. If you put it behind a public address, you are the one adding
authentication.

The `repo/` route hands out only manifest-blessed paths and every file-serving
route resolves and prefix-checks against its root, so a course repo's
gitignored `local/` — seeds, API keys — is not reachable through the app.

## Invariants (enforced, not aspirational)

- Ids are forever: `num` may change, `id` may not; removal requires a tombstone.
- Attachment is declared once, on the material; tags and file tables derive.
- Derived data is computed, never stored. If something derivable is being
  persisted, that is the bug.
- The event ledger is append-only and the fold is pure, ordered by row id and
  never by timestamp. Anything stored beside the ledger is a projection, and a
  disagreement is a bug in the projection.
- No LLM call on a request path, ever.

## Status

Phases 0–4 are built: the manifest compiler, the progress service, the profile
pipeline, the course factory, and the design system. What is not here yet: auth,
multi-tenant serving, and a background job queue — the factory runs from the
CLI. See [`docs/platform-design.md`](docs/platform-design.md) §9 for the
roadmap.

## License

[Apache License 2.0](LICENSE).
