# Spike: the one-stop-shop

*2026-08-29 · branch `worktree-spike-one-stop-shop` · companion branch
`spike/curricle-native-materials` in textual-flow*

**The question.** Can curricle become the place where the learning actually
happens — click a unit on the curriculum and the lesson, widgets, quizzes,
and exercise briefs open right there in the browser — without violating the
platform's settled invariants? **Answer: yes, cheaply.** The prototype on
this branch is a working end-to-end proof; every risky bit was exercised
against textual-flow on a live server with a real (throwaway) Postgres.

## What was already true

More was in place than the phrase "one-stop-shop" suggested. The manifest
already models materials with kinds, paths, and owning units
(`materials_for_unit` existed, unused by any page). The served app already
had a guarded content route that happily serves widget HTML. The server
side of quiz reporting was *completely finished*: `checkpoint_result` is a
validated event kind, and `profile.propose_from_checkpoint` already turns
one into proposed `demonstrated` evidence, misses included. Nothing posted
to it. The gaps were exactly four: units linked to nothing, markdown
arrived as `text/plain`, materials wore pre-curricle styling, and no
material reported into the ledger.

## Decisions taken with the operator (recorded, not reopened)

- **Scope:** rendered lessons, native widgets/quizzes, readable exercise
  briefs. No Pyodide — the exercise *runtime* stays Phase 6.
- **The click target is a per-unit page**, linked from the curriculum.
- **Materials go native**: restyled onto theme tokens, and **server-required
  is accepted** — materials may link served assets and stop working as
  standalone files. The static-site export must bundle `theme.css` beside
  them when it arrives.
- **Quizzes must report**; the wiring mechanism was the spike's to choose
  (chosen below).
- **Serve what exists.** Gap-filling generation is the factory's business,
  later, on demand.

## What the prototype proves

1. **Markdown without a dependency is a ~160-line problem, not a project.**
   A census of every lesson, task, and question-bank file found a small,
   regular dialect (ATX headings, bullets one level deep, short ordered
   lists, blockquotes, one pipe table, a few indented code lines).
   `blockmd.py` renders all eleven corpus documents cleanly, falls back to
   paragraphs rather than losing text, and — like `inlinemd` — claims only
   the corpus's dialect, refusing to become a markdown engine.
2. **The unit page needed zero schema changes.** `unitrender.py` renders
   goal, rows, steps (live checkboxes on the events API), material cards
   with kind chips, check-yourself, and the phase checkpoint block, all
   from the existing manifest. Route: `/c/{slug}/unit/{id}.html`; the
   curriculum's unit rows gained a served-only "Unit page →" action
   (standalone renders are byte-identical but for the inert template line).
3. **The theme travels as one stylesheet.** `/c/{slug}/theme.css` serves
   `theme.style("")`; the migrated flow-explorer and phase-1 checkpoint
   deleted their `:root` palettes, linked it, and got both light and dark
   for free. The sheet is guarded like every other (`SHEETS` in
   `tests/test_theme.py`).
4. **The reporting loop closes.** `/c/{slug}/material.js` exposes
   `curricle.checkpoint(id, {score, total, misses})`, deriving the API base
   from the page's own path. The migrated quiz calls it once, on the last
   answer. Verified end-to-end from a real browser click-through: the event
   landed in `progress_events` and became a proposed profile evidence row,
   misses attached, awaiting /profile — the exact pipeline Phase 2
   promised.
5. **Lessons render honestly.** `/c/{slug}/read/{path}` renders any
   in-root markdown inside the theme (raw file stays served at its own
   path). A lesson gets a banner saying what it is — **a dialogue script
   written for a tutor to run** — because an in-browser tutor would put an
   LLM on a request path, and L1 is settled. The reader presents the
   script; Claude-in-the-repo runs it.

## The quiz-wiring decision

Three candidates were weighed:

- **Serve-time injection** (the app rewrites quiz HTML on the way out):
  rejected. What runs would no longer be what's committed — the same
  dishonesty this repo keeps refusing in other clothes, and a rewriter on
  the content route is a standing invitation to parse HTML with regexes.
- **Factory contract only** (regenerate all materials with reporting built
  in): right for *future* materials, wasteful for the eight that exist.
- **Explicit convention, shared machinery** — chosen. A material links
  `theme.css` and `material.js` and makes one visible call with its own
  material id; the server validates the id against the manifest, so a typo
  is a 422, not silent data loss. Migration is a hand edit per file
  (~30–45 minutes each, measured), and the factory's material roles adopt
  the same three lines as a contract for everything they generate next.

## Found along the way

- `inlinemd`'s bold pattern choked on `**bold with *italics* inside**`
  (the Unit 4 lesson does this); fixed here, with a test.
- Migrated widgets surface a real vocabulary question: **data ink**. The
  flow-explorer's three reading tints are content, not chrome — they stay
  material-local, defined per theme like token pairs. Theme has no `--warn`
  bare-color token (only `-text`/`-soft`); the widget aliases it. A short
  "material palette" section in DIRECTION.md should settle this properly.
- Port 8765 was taken on the dev machine; the demo ran on 8791.

## What productionization needs (beyond this branch)

- Migrate the remaining textual-flow materials (2 widgets, 1 quiz,
  2 trainers — trainers validate for `checkpoint_result` already) and
  rhyme-schemer's; decide hand vs. factory-role per file.
- Hub material cards and resource-page links should route markdown through
  `read/` too (they still link raw paths).
- The unit page could carry `also_units` materials and a link to session
  notes; deliberately skipped here.
- Static export: bundle `theme.css`/`material.js` beside exported content
  (the export is not built yet; this is a note for its author).
- DIRECTION.md: record the unit page, the reader, and the material-palette
  rule; recompute nothing — no token changed.

Total estimate: a focused day, most of it material migration.

## Not done, on purpose

No Pyodide, no generation of missing lessons, no restyling beyond the two
proof materials, no waypath on the unit page (it tracks one unit's mark and
steps; a path gesture there would claim more than the page tracks — the
mark pill and step checkboxes are the honest amount of liveness).
