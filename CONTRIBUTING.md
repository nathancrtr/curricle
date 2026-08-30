# Contributing

curricle is a single-person platform that happens to be open source. That
shapes what is useful: bug reports and focused fixes are welcome, and so are
new courses built on it. Large architectural changes are likely to bounce off
decisions already recorded in [`docs/platform-design.md`](docs/platform-design.md)
— read that first, and open an issue before writing the code.

## Getting set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
python -m unittest discover tests
```

The suite needs Postgres' server binaries — `initdb`, `pg_ctl`, `postgres` —
findable either on your `PATH` or in the usual install prefixes that
`tests/pg.py` checks (`brew install postgresql@16`, or your distribution's
`postgresql` package). It needs nothing else: it boots a throwaway cluster in a
temp directory on a unix socket, migrates it, and tears it down at exit. There
is no running server to start, no database URL to set, and by construction no
way to point the suite at a real database.

## Two things to know before you read a green run

**`tests/test_corpus.py` skips silently.** It compiles two private course repos
that live beside this one, and skips cleanly when they are absent — which is
everyone's situation but the author's. A skipped suite still prints `OK`, so if
you are changing the compiler, the parser, or the renderers, check that
`tests/test_example_course.py` is exercising your change. That one runs against
`examples/tinylang`, which is in the repository, and never skips.

**The progress-id list in `test_corpus.py` is not an assertion about current
behaviour.** It pins the exact `localStorage` keys of a hand-built course hub
whose real learner state was migrated into the ledger. It is a migration-safety
contract. If your change makes it fail, the change is wrong, or it needs a
deliberate migration — do not edit the list to match your output.

## House rules

These are enforced by tests, and they are the ones people trip on:

- **`schema.py` is the contract.** Strict decoding: unknown keys raise, with a
  path a human can act on. Vocabularies are enumerated. Frozen dataclasses.
- **Derived data is computed, never stored.** Progress ids, tag chips, the
  `Interactive` row. If you find yourself persisting something derivable, stop.
- **The compiler refuses rather than guesses.** New house rules become new
  `Issue`s — errors block emission, warnings print — and every issue carries a
  `where`.
- **`db.py` is the only module that may spell `progress_events`,** and every
  table is classified `TENANT_SCOPED` or `TENANT_LESS` at import. Adding a
  table means classifying it or the module refuses to load. Guard tests
  enforce both.
- **The ledger is append-only and the fold is pure,** ordered by row id and
  never by timestamp. Anything stored beside the ledger is a projection; a
  disagreement is a bug in the projection, never in the fold.
- **No LLM call on a request path, ever.** A grep test enforces it.
- **Schema changes go through Alembic**, never `create_all`. Migration
  docstrings explain what and why, essay-style.
- **Renderers spend design tokens from `theme.py` and define no palette of
  their own.** A new stylesheet joins `SHEETS` in `tests/test_theme.py` or the
  suite fails. The rationale and the contrast table are in
  [`DIRECTION.md`](DIRECTION.md).

## Committed artifacts

`build/` holds compiled manifests and rendered pages, committed for inspection.
Regenerate them in the same commit as any change upstream of them:

```bash
python -m curricle compile    examples/tinylang --out build/tinylang.manifest.yaml
python -m curricle hub        examples/tinylang --out build/tinylang.hub.html
python -m curricle curriculum examples/tinylang --out build/tinylang.curriculum.html
python -m curricle resources  examples/tinylang --out build/tinylang.resources.html
```

`build/example-profile-SKILL.md` is regenerated from
`examples/example-profile-seed.yaml` through `profile import-seed` and `profile
render`. It is a projection — never edit it by hand.

## Changing the example course

`examples/tinylang` is what people copy, so it is held to **zero warnings**,
not just zero errors, and `tests/test_example_course.py` enforces that along
with its shape and its progress-id ordering. It is also the one course expected
to keep exercising every part of the schema, so when the schema grows, grow the
example with it.

Its Unit 2 starter ships failing against its stub, and a test enforces that
too. Do not solve it.

## Style

Python 3.12+, standard library plus the declared dependencies. No ORM, no
framework in the manifest layer. Match the surrounding code: this repository
comments to explain *why*, at some length, and prefers a paragraph that saves
the next reader an hour over a terse note that doesn't.
