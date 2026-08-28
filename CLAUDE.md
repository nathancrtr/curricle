# CLAUDE.md

curricle is the platform distilled from the learning-track corpus. Read
`~/repos/learning/platform-design.md` (the architecture and its decided
trade-offs) and `~/repos/learning/platform-manifest.md` (the schema spec)
before changing anything structural — decisions recorded there are settled
unless the user reopens them.

## Commands

```bash
source .venv/bin/activate
python -m unittest discover tests                    # full suite (fast)
python -m curricle compile <course_root> --sidecar courses/<id>.course.yaml --out build/<id>.manifest.yaml
```

## Conventions

- Python 3.12+, stdlib + PyYAML only. No ORM, no framework in this layer.
- `schema.py` is the contract: strict decoding (unknown keys raise, with a
  path context), enumerated vocabularies, frozen dataclasses. Derived data
  (progress ids, tag chips) is computed in methods, never stored — if you
  find yourself persisting something derivable, stop.
- The compiler refuses rather than guesses. New house rules become new
  `Issue`s: errors block emission, warnings print. Every issue carries a
  `where` a human can act on.
- `tests/test_corpus.py` runs against the sibling repos (`../textual-flow`,
  `../rhyme-schemer`) and skips when absent. The progress-id pin for
  textual-flow is a migration-safety contract — do not "fix" it to match
  code; fix code to match it, or consciously migrate.
- Compiled manifests in `build/` are committed for inspection; regenerate
  them in the same commit as any compiler or sidecar change.
- The YAML `on:` key parses as boolean True (YAML 1.1); the sidecar loader
  normalizes it. Don't rename schema fields to dodge YAML quirks.

## The progress service (Phase 1)

- `db.py` is the only module that may spell `progress_events` — a guard test
  enforces it. Tenant-scoped rows are reached only through `TenantScope`,
  built from an explicit tenant id. There is no default tenant anywhere:
  an unconfigured caller gets an exception, not tenant 0.
- Every table is classified `TENANT_SCOPED` or `TENANT_LESS` in `db.py`,
  asserted at import; purge/export registries derive from the classification.
  Adding a table means classifying it or the module refuses to load.
- The event ledger is append-only; the fold (`progress.fold`) is pure and
  orders by row id, never timestamp. Anything stored beside the ledger is a
  projection — a disagreement is a bug in the projection, never the fold.
- New event kinds are a migration (the `known_kind` CHECK) plus
  `db.EVENT_KINDS` plus fold handling — deliberately ceremonious.
- Schema changes go through Alembic (`migrations/`), never `create_all` in
  production paths. Migration docstrings explain what and why, essay-style.
- Tests bring their own Postgres: `tests/pg.py` boots a throwaway initdb
  cluster per process (unix socket, temp dir, torn down at exit) and runs
  the migration chain. The suite never reads a database URL from the
  environment and so cannot be pointed at a real database. Never "fix" that.
- Dev runbook: `export CURRICLE_DATABASE_URL=postgresql+psycopg:///curricle`,
  `alembic upgrade head`, `python -m curricle serve --course … --tenant nathan`.

## What this repo is not (yet)

No LLM calls, no auth, no multi-tenant serving (single tenant per app
instance, resolved at startup). Those are later phases (platform-design.md
§9); resist pulling them forward into this layer.
