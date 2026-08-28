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

## What this repo is not (yet)

No web app, no database, no LLM calls. Those are later phases
(platform-design.md §9); resist pulling them forward into this layer.
