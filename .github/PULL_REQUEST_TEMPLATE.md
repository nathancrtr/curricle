## What this changes, and why

<!-- Essay-style, like the commit messages: what was wrong, what this does,
     what it deliberately does not do. -->

## Checklist

- [ ] `python -m unittest discover tests` is green (the suite brings its own Postgres).
- [ ] Every new rule has a test that fails without it; copy pinned by a test kept its intent.
- [ ] `examples/tinylang` still compiles with **zero warnings**.
- [ ] Anything under `build/` that renders from what I changed is regenerated in the same commit.
- [ ] Schema changes are an Alembic migration with an essay-style docstring, never `create_all`.
- [ ] No model, price or budget is named anywhere but `models.yaml`; no LLM call on a request path.
- [ ] Design tokens changed → `CONTRAST_PAIRS` and the table in `DIRECTION.md` recomputed.
- [ ] Nothing personal: no keys, no home paths, no learner data.
