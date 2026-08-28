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
python -m curricle compile ~/repos/textual-flow \
    --sidecar courses/textual-flow.course.yaml \
    --out build/textual-flow.manifest.yaml
python -m unittest discover tests        # includes integration vs. the real courses
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
- `courses/` — the sidecars for the existing courses.
- `build/` — compiled manifests, committed for inspection.

## Invariants (enforced, not aspirational)

- Ids are forever: `num` may change, `id` may not; removal requires a tombstone.
- Attachment is declared once (on the material); tags and file tables derive.
- Everything progress-bearing is enumerable, and for textual-flow the enumeration
  is pinned by test to the exact localStorage ids of the hand-built hub —
  migration safety for the one learner with real state.
