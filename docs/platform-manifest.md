# The course manifest — schema sketch v0.1

*Companion to [platform-design.md](platform-design.md) §5.5. Drafted 2026-08-28 against the three live representations: rhyme-schemer's `build_site.py` (`PHASES`/`UNITS` dicts), textual-flow's `curriculum.html` (`PHASES→entries→rows` data) and `index.html` (hub ids + `GREEK` ladder), and the `curriculum.md` markdown conventions both compile from.*

> **This is the spec; `curricle/schema.py` is the contract.** Where the two
> disagree, the code is what runs — the sketch predates the implementation and
> §8 records where the first build corrected it. Read this for *why* the schema
> has the shape it has, read `schema.py` for what the compiler will actually
> accept, and read `examples/tinylang/learning/course.yaml` for a sidecar that
> compiles clean today.

---

## 1. Purpose and position

One machine-readable document per course that is the **single source of truth for course structure** — everything that is currently triplicated across canonical markdown, hand-mirrored HTML, and JS arrays in build scripts and hub pages. Renderers (static site, hub, curriculum view, MCP tutor context, progress service) consume only the manifest. Markdown remains the **authoring** format for prose; a compiler ingests the existing `curriculum.md` conventions plus a small sidecar and emits the manifest.

What the manifest holds: **structure, identity, references.** What it does not hold: prose bodies (lesson guides, task.md narratives, checkpoint paragraphs beyond a few lines — these stay in markdown files the manifest points at) and learner state (that's the progress ledger, which *references* manifest ids).

## 2. Design rules

1. **IDs are forever.** Every progress-bearing thing has an id; once an id has appeared in a published manifest it may never be reused or repurposed. `num` is display order and may change on revision; `id` may not. A removed unit gets a **tombstone** (`retired:`), never deletion — progress events reference ids indefinitely (job-radar's `RETIRED_FIELDS` move).
2. **Attachment is declared once.** A material (lesson, widget, quiz, exercise…) declares which unit owns it; unit chip-rows, hub tags, and README file tables are all *derived*. This retires textual-flow's three-place registration rule.
3. **Tags are computed, never typed.** The hub's `lesson`/`widget`/`tests` chips derive from attached material kinds and grader types.
4. **Links are references, not URLs.** Prose content uses reference schemes (`res:`, `unit:`, `mat:`, `repo:`) resolved by each renderer for its medium. This generalizes rhyme-schemer's `LINK_MAP` and textual-flow's `L` table, and makes "resource URLs only from the verified resource list" structural instead of disciplinary.
5. **Steps subsume composites.** A unit may declare `steps` — finer-grained checklist items. Progress attaches to the finest grain present. This retires the `p0` ↔ `p0-run/p0-read/p0-para` composite-id mapping hack.
6. **Fixed core, open extension.** Unit rows are `{label, content}` pairs: the core vocabulary (Build/Read/Concepts/Exercise/Milestone) is enumerated, but courses may add rows (Greek track, Key insight, Caveat) without schema changes — matching how every real course already extends the template.
7. **Everything progress-bearing is enumerable.** The set of valid progress ids (units, steps, milestones, track stages) is a pure function of the manifest; the progress service validates events against it.
8. **Provenance on every unit.** `spine | overlay | fork | bespoke` — so Model C (fork-on-divergence) is a data migration, not a schema change. Existing courses compile as `bespoke`.
9. **Serialization: YAML**, committed to the repo beside its sources. Human-diffable in review (the corpus commits generated artifacts deliberately; same posture), trivially loaded as data. A JSON Schema validates it in CI.

## 3. The schema

Annotated YAML. `?` marks optional fields.

### 3.1 Course header

```yaml
manifest_version: 1
course:
  id: textual-flow                  # stable slug; also the progress namespace
  title: "Textual criticism & computational philology"
  mode: research                    # subject | project | research
  version:
    rev: "1.1"                      # the dated-footer convention, structured
    date: 2026-08-28
    note?: "interactive layer v1.1"
  pacing:
    hours_per_week: [3, 5]
    cadence?: "one unit ≈ one week; Units 3 and 12 run long, 5 and 14 short"
  profile_line?: >                  # the italic header line; Model B courses
    For a senior software engineer who learns by implementing…   # omit it
  docs:                             # repo-relative pointers, all optional
    readme?: learning/README.md
    resources_doc?: learning/learning-resources.md
    curriculum_doc?: learning/curriculum.md   # the authoring source
    review?: REVIEW.md
    exploration?: exploration/
  out_of_scope?: [ "...", "..." ]
  capstone?: u22                    # unit id
```

### 3.2 Tracks

The primary track is implicit (every phase entry belongs to it). Secondary tracks are ordered stage ladders with their own cadence — textual-flow's Greek track, side-quest lanes.

```yaml
tracks:
  - id: greek
    name: "Koine Greek"
    cadence?: "1.5–2 hrs/wk, near-daily beats weekly"
    stages:                         # ordered; each stage is progress-bearing
      - { id: g-alpha, label: "alphabet" }
      - { id: g-nouns, label: "nouns & articles" }
      - { id: g-verbs, label: "verbs arrive" }
      - { id: g-1john, label: "reading 1 John" }
      - { id: g-app,   label: "apparatus literate" }
      - { id: g-mark,  label: "Mark with helps" }
```

### 3.3 Resources

The tiered resource list, entries keyed exactly as textual-flow's `L` table already keys them. `key` is the reference target for `res:` links.

```yaml
resources:
  - key: wg
    title: "Wasserman & Gurry, *A New Approach to Textual Criticism*"
    url: "https://cart.sbl-site.org/books/060399P"
    formats: [TEXT]                 # TEXT | CODE | VIDEO | PAPER | TOOL | DATA
    tier: 1                         # tiers by role, per course-structure.md
    cost?: "~$20 print"
    why_this_one: "…ties back to the learner profile…"
    covers?: "…"
    verified: { at: 2026-08-27, method?: web }
    access_note?: "…licensing / paywall caveats…"
```

### 3.4 Phases

```yaml
phases:
  - id: p1
    num: 1
    title: "The CBGM from the inside"
    weeks?: [3, 10]
    goal: "Understand the method by reimplementing its core…"
    entries: [u1, u2, u3, u4]       # unit and milestone ids, in order
    checkpoint:
      prose: >                      # the "— Phase N Checkpoint —" paragraph
        `rhyme_score` exists and works: …
      quiz?: q-phase-1              # material id of the checkpoint quiz
      track_goals?:                 # the "Greek by now:" convention
        greek: "…parsing nouns and articles in 1 John 1…"
```

### 3.5 Units

```yaml
units:
  - id: u1                          # forever; "u{num}" by convention, not rule
    num: 1
    phase: p1
    title: "Witnesses, variants, and the shape of the data"
    gloss?: >                       # one-line summary (hub rows, gallery cards)
      Parse the ECM's TEI into your own data model — and meet the apparatus
      as a sparse matrix with an opinionated schema.
    provenance: bespoke             # spine | overlay | fork | bespoke
    depends_on?: [p0]               # the ASCII dependency map, structured
    load_bearing?: true             # vs. safe-to-skim; renders the map's marks
    skippable_note?: "…if it clicks…"
    condition?:                     # gated units (textual-flow u17)
      on: "INTF licensing answer"
      state: pending                # pending | open | closed
    steps?:                         # optional finer progress grain (§2.5)
      - { id: p0-run,  label: "open-cbgm built & run on 3 John" }
      - { id: p0-read, label: "W&G front matter + fast skim; README + REVIEW" }
    rows:                           # ordered; content is markdown w/ ref links
      - { label: Build,   content: "Clone and build [open-cbgm](res:opencbgm)…" }
      - { label: Read,    content: "[W&G](res:wg) ch. 1 carefully this time…" }
      - { label: Concepts, content: "Witness, reading, variation unit, lacuna…" }
      - { label: Exercise, content: "Answer from your parser, with code: …" }
      - { label: Milestone, content: "`parse_collation()` with tests; …" }
      - { label: "Key insight", kind: key,
          content: "A critical apparatus is a *sparse matrix with an opinionated schema*…" }
      - { label: "Greek track", track: greek,
          content: "[Decker](res:decker) chs. 1–2; the [alphabet trainer](mat:t-alphabet)…" }
    check?:                         # inline "Check yourself" comprehension check
      q: "…what *does* the CBGM claim to reconstruct, if not a stemma?"
      ans: "Relationships between the *texts* carried by witnesses, not the manuscripts…"
    note?: >                        # rhyme-schemer's lesson_note escape hatch
      This unit's guide is the scanner walkthrough — written **during** the build…
```

Core row labels (enumerated so renderers can style them; extension rows allowed): `Build, Read, Concepts, Exercise, Milestone, Key insight, Interactive, Caveat`. The `Interactive` row is **derived from material attachments** at render time — never authored (rule 2). `kind: key` marks the highlighted-callout treatment; `track:` scopes a row to a secondary track.

### 3.6 Milestones (non-unit phase entries)

The taxonomy from platform-design.md §5.2, covering textual-flow's contact/pre-registration/side-quest entries.

```yaml
milestones:
  - id: p2-mail
    phase: p2
    kind: contact                   # contact | preregistration | publication
                                    # | artifact | side-quest | external
    label: "📮 Contact milestone: INTF + McCollum emails sent"
    detail?: "Drafts happen with Claude; sending is the learner's own act."
    hours_per_month?: 4             # side-quest kind only
    gate_for?: [u17]                # units this milestone's outcome may unblock
```

### 3.7 Materials

Declared once, owning unit on the material (rule 2). `also_units` covers genuine reuse (rhyme-schemer's rhyme-score sandbox appears in Units 7 *and* 9).

```yaml
materials:
  - id: l-u01
    kind: lesson                    # lesson | widget | quiz | trainer
                                    # | exercise | companion | question-bank
    title: "The collation data model"
    path: interactive/lessons/unit-01-collation-data-model.md
    unit: u1
  - id: x-u01
    kind: exercise
    title: "unit-01-starter"
    path: interactive/exercises/unit-01-starter/
    unit: u1
    grader:                         # typed union, platform-design.md §4.3
      type: unit-test               # unit-test | property-test | oracle
                                    # | drill | annotation | artifact | external
      runner?: python-unittest
      oracle?: "must equal unit-02-starter/fixture.json exactly"
  - id: t-alphabet
    kind: trainer
    title: "Greek alphabet trainer"
    path: interactive/quizzes/greek-alphabet-trainer.html
    track: greek                    # track-scoped material, no owning unit
  - id: c-phonetics
    kind: companion                 # on-ramp lessons: attached, not owned —
    title: "How speech works: a phonetics refresher"
    path: interactive/lessons/phonetics-primer.md
    also_units: [u1]                # Model B overlays attach these per-learner
  - id: q-phase-1
    kind: quiz
    title: "Phase 1 checkpoint"
    path: interactive/quizzes/phase-1-checkpoint.html
    phase: p1                       # checkpoint quizzes attach to the phase
```

Derived, never stored: a unit's tag chips (`lesson` if a lesson is attached; `widget`; `tests` if an exercise with a test-type grader; `quiz` if a quiz/checkpoint touches it), the hub's file table, the README's material inventory.

### 3.8 Link reference schemes

In any `content` markdown field:

| Scheme | Resolves to | Replaces |
|---|---|---|
| `res:wg` | resource entry `wg` → its verified URL | textual-flow's `L` table; the "verified URLs only" rule |
| `unit:u8` | the unit's page in the current medium | rhyme-schemer's `LINK_MAP` |
| `mat:t-alphabet` | the material's page/file | ad-hoc relative links |
| `repo:README.md` | repo-relative file | ad-hoc `../README.md` links |

A bare `http(s):` URL in content is a **compile error** outside `resources:` — the rule the corpus enforces by review becomes one the compiler enforces by refusal.

### 3.9 Tombstones

```yaml
retired:
  - id: u9-old
    at: 2026-09-15
    reason: "merged into u9 on revision 1.2"
    superseded_by?: u9
```

## 4. Derived progress-id contract

The set of valid progress ids for a course is exactly:

```
{ unit.id        for units without steps }
∪ { step.id      for every step }            # a stepped unit's own id is a rollup,
∪ { milestone.id }                           #   derived, not directly checkable
∪ { stage.id     for every track stage }
```

The progress service rejects events naming any other id; renderers compute `%complete` and `next_up` (first unfinished entry in phase order — textual-flow's `refresh()` logic) from the same enumeration. Quiz and drill results are **events, not checkboxes**: `checkpoint_result` / `drill_result` events reference `material` ids and carry payloads; they feed the profile evidence fold and never gate `unit_done` (the corpus's deliberate "quizzes don't persist as progress" stance, preserved).

## 5. Compiler contract

**Inputs:** `curriculum.md` (canonical prose + structure) + `course.yaml` sidecar (what markdown doesn't carry) + the `interactive/` tree (existence checks).

Parsed from the markdown conventions, which are regular across all four courses:

| Markdown convention | Manifest field |
|---|---|
| `## Phase N — Title (Weeks A–B)` + `**Goal:**` | `phases[].num/title/weeks/goal` |
| `### Unit N — Title` | `units[].num/title` (id minted `u{N}` on first compile, then pinned) |
| `- **Label:** …` bullets | `units[].rows[]` (labels matched case-insensitively; unknown labels pass through as extension rows) |
| `### — Phase N Checkpoint —` + paragraph | `checkpoint.prose`; a trailing `**Greek by now:**` line → `track_goals` |
| `> **Check yourself:** … <details>` | `units[].check` |
| Dependency-map section | validated against `depends_on` (authored in sidecar until the ASCII map grows a parseable syntax) |
| Dated version footer | `course.version` |
| Inline links to files under `interactive/` | material attachment cross-check (must agree with `materials:` or fail) |

The **sidecar** carries what the markdown legitimately doesn't: ids that deviate from `u{N}`, glosses, steps, track stage ladders, milestone entries, material registry, `depends_on`/`load_bearing`, resource keys. First-compile migration note: several of these currently live only in the HTML twins (glosses and `rows` HTML in `curriculum.html`, hub composites in `index.html`) — they are harvested **once** into the sidecar, after which the HTML twins are deleted and regenerated (the Phase 0 exit criterion).

**Validation (compile fails loudly, job-radar style):** unique ids; every phase entry resolves; every material path exists on disk; every `res:`/`unit:`/`mat:` reference resolves; no bare URLs in content; every unit belongs to exactly one phase; steps only on units, ids globally unique; against the *previous committed manifest*: no id vanished without a tombstone, no id changed meaning (title similarity heuristic, warn-level). Drift detection for free: compiling category-theory (pre-course-builder generation) should emit warnings, not silence — that's the test case.

## 6. Renderer contract

Every current surface becomes a pure function of `(manifest, progress-fold, prose files)`:

| Surface | Consumes | Parity target (Phase 0 exit) |
|---|---|---|
| Static site / unit pages | manifest + lesson/task prose | rhyme-schemer's `site/` to visual equivalence |
| Hub | manifest + progress fold | textual-flow `index.html` incl. Greek ladder |
| Curriculum view | manifest + progress + notes | textual-flow `curriculum.html` incl. remaining-filter |
| Resource tracker | `resources:` + acquisition events | `learning-resources.html` (separate state, preserved) |
| MCP tutor context | manifest + progress + profile | n/a (new) |
| README file table | `materials:` | each course README's table |

## 7. Open questions (flagged, not blocking)

1. **Row content format**: markdown-with-ref-schemes is the sketch; worth confirming the compiler round-trips the corpus's heavy inline formatting (bold labels inside content, `<code>`, entities) cleanly before freezing.
2. **Where the sidecar lives**: `learning/course.yaml` beside `curriculum.md` is the natural spot; alternatively the manifest itself is hand-maintained and the compiler only *validates* against the markdown. Current lean: compile+sidecar, because prose editing should stay a markdown-only act.
3. **Per-enrollment manifests** (Model B): sketch assumes one manifest per course; an enrollment adds an overlay document that *patches* it (attach companions, flip skip flags, reorder resources). Overlay-as-JSON-merge-patch vs. overlay-as-first-class-schema is deferred until the profile pipeline exists.
4. **Question banks**: currently one markdown file per course with R/A/W-tagged items; whether items get individual ids (so miss-events can cite them) is a Phase 2 decision — leaning yes, ids minted per item at compile.

---

## 8. Field notes from the first implementation (v0.2)

The compiler exists in this repository (schema, parser, compiler, sidecars, tests). Both mature courses compile clean. What the spike taught:

1. **Open question 1 is answered: row fidelity holds.** Unit rows survive verbatim — inline markdown, entities, em-dashes — with no round-trip loss. The label-bullet convention is more regular than feared.
2. **Phase-body units are a real, recurring shape.** *Both* courses open with label-bullets under Phase 0 with no unit header; the sidecar's `phase_body: true` unit claims them. The phase-body unit takes id `u0`, not `p0` — a unit sharing its phase's id violates global id uniqueness, and since textual-flow's localStorage only ever stored the step ids, the rename is migration-safe.
3. **Week ranges have three syntaxes**: `(Weeks 11–15)`, `(Week 0)` → `(0,0)`, `(Weeks 23+)` → `(23, null)` open-ended. `Phase.weeks` end is now nullable.
4. **Track goals are inline, not line-level**: "**Greek by now:**" sits mid-paragraph inside checkpoint prose; the parser splits inline labeled spans. Tracks declare `row_labels` and `checkpoint_labels` so attribution stays subject-agnostic.
5. **`coverage_ignore`** joined the sidecar: support files under `interactive/` (data generators) that are not materials.
6. **YAML's Norway problem**: a bare `on:` key (in `condition:`) parses as boolean True; the loader normalizes rather than renaming the field.
7. **Derived tags caught real drift on day one**: the hub hand-types a `quiz` chip on textual-flow's u14, but no phase-4 checkpoint quiz exists — the chip references a planned artifact. Derivation refuses to reproduce it. Also codified: a phase's checkpoint quiz contributes a `quiz` chip to the phase's *last unit* (the hub's implicit convention, now computed).
8. **Migration safety is a test**: textual-flow's derived progress-id enumeration is pinned to the hub's exact localStorage ids (26 program + 6 Greek).

9. **The Resource schema grew to what the hand-built page proved it needed**: `cite`, `group`, `free`, labeled multi-`links`, plus `resource_tiers` (name, role, `compact`) and course-level `resources_intro`/`reading_order`. Chips derive from formats + cost/free; an identifier-only URL (`urn:isbn:`) satisfies "every resource has a URL" without rendering as a dead link.
10. **The swap happened 2026-08-28**: textual-flow's three hand-built pages are now curricle-generated from `curriculum.md` + `learning/course.yaml` (the sidecar's canonical home is the course repo; the CLI defaults to it). All localStorage keys/ids preserved; the three-place registration rule is retired from its CLAUDE.md. **Phase 0's exit criterion is met.**

*v0.1 — 2026-08-28: initial sketch. v0.2 — 2026-08-28: field notes after the compiler landed in this repository. v0.3 — 2026-08-28: resources model; the textual-flow swap.*
