# curricle

The manifest layer of a personalized-learning platform — Phase 0 of the design
in [`~/repos/learning/platform-design.md`](../learning/platform-design.md), with
the schema specified in [`platform-manifest.md`](../learning/platform-manifest.md).

A **course manifest** is the single machine-readable source of truth for a
course's structure: phases, units, tracks, milestones, materials, resources,
and the derived progress-id contract. Markdown (`curriculum.md`) remains the
authoring format; this package compiles it, together with a small **sidecar**
(`course.yaml`) carrying what markdown doesn't (ids, glosses, steps, the
material registry), into a validated manifest.

## Usage

```bash
source .venv/bin/activate
python -m curricle compile ~/repos/textual-flow --out build/textual-flow.manifest.yaml
python -m curricle hub ~/repos/textual-flow --out .../index.html          # static pages
python -m unittest discover tests   # incl. integration vs. the real courses and a
                                    # throwaway Postgres cluster (never a real DB)

# The progress service (Phase 1): Postgres event ledger + web app
export CURRICLE_DATABASE_URL="postgresql+psycopg:///curricle"
alembic upgrade head
python -m curricle tenant create nathan
python -m curricle serve --course ~/repos/textual-flow \
    --course ~/repos/rhyme-schemer --tenant nathan --port 8765
# then: http://localhost:8765/ — same three pages, state server-side

# One-time import of browser localStorage state (run the JS below in the
# static page's console, paste the copied JSON):
#   copy(JSON.stringify({progress: localStorage.getItem("tf-progress"),
#     curriculum_notes: localStorage.getItem("tf-curriculum-notes"),
#     resources: localStorage.getItem("tf-resources")}))
python -m curricle import-progress ~/repos/textual-flow --tenant nathan --json '<paste>'
```

## Layout

- `curricle/schema.py` — the manifest data model. **This module is the contract**:
  strict decoding, enumerated vocabularies, derived data (`progress_ids()`,
  `tags_for_unit()`) computed rather than stored.
- `curricle/mdparse.py` — parser for the corpus's `curriculum.md` house format
  (phases, unit rows, checkpoints, check-yourself blocks, version footers).
- `curricle/sidecar.py` — strict loader for `course.yaml`.
- `curricle/compiler.py` — merge + validate + refuse. House rules the corpus kept
  by discipline are errors or warnings here (dangling refs, unregistered files,
  bare URLs in prose, vanished ids).
- `curricle/db.py` — tables, tenancy invariants (T1–T5) satisfied by
  construction: classification asserted at import, `TenantScope` as the only
  path to scoped rows, purge/export derived from the classification.
- `curricle/progress.py` — the event ledger's pure fold and append-time
  validation against the manifest.
- `curricle/webapp.py` — FastAPI app serving the three views in server mode
  (state folded from Postgres, writes POSTed as events).
- `migrations/` — Alembic; the schema changes by migration only.
- `build/` — compiled manifests, committed for inspection. Sidecars live in
  the course repos (`<course>/learning/course.yaml`).

## Invariants (enforced, not aspirational)

- Ids are forever: `num` may change, `id` may not; removal requires a tombstone.
- Attachment is declared once (on the material); tags and file tables derive.
- Everything progress-bearing is enumerable, and for textual-flow the enumeration
  is pinned by test to the exact localStorage ids of the hand-built hub —
  migration safety for the one learner with real state.
