# Curricle — a personalized-learning platform design

*Working name: "Curricle" (a light, fast two-wheeled carriage; same Latin root as "curriculum." Placeholder — rename freely.)*

*Design exploration, v0.1 — 2026-08-28. Distilled from rhyme-schemer, textual-flow, the learning/ monorepo, the course-builder skill family, and job-radar's architecture. Decisions recorded here were made in interview on 2026-08-28.*

> **On reading this in the open-source repository.** This is the architecture
> document curricle was built from, and it is vendored here so the repository
> is self-contained: the decisions it records are settled, and code that
> contradicts one is a bug in the code. It was written against a private
> corpus, so it cites courses (`textual-flow`, `rhyme-schemer`, `learning/ml-ai`)
> and skills (`course-builder`) that do not ship with curricle. Those citations
> are evidence for the design, not dependencies of it — `examples/tinylang/`
> is the course that ships, and it is the one to read the schema against.

---

## 1. What this document is

A vision-and-architecture document for a **learning management system built around deep per-learner calibration**: courses that are shaped by who the learner actually is — what they already know, what must be scaffolded from zero, how many hours they have, what domains make examples land — rather than one syllabus served to everyone.

The system already exists in embryo. Four courses have been built with a stable set of conventions (`~/.claude/skills/course-builder/` and friends), and they work. What they lack is software: progress lives in hand-wired localStorage, curricula exist in three parallel representations synced by vigilance, and the learner profile is a static prose file nothing ever updates. This document designs the platform those conventions imply.

**Scope decisions (from interview):**

| Question | Decision |
|---|---|
| Audience | Autodidact peers first; general consumers as the growth direction |
| Form factor | Standalone web app; Claude Code remains an authoring tool |
| LLM at learning time | **Fork B**: background jobs at defined moments only — never on a request path, never a chat endpoint — plus the Socratic layer *exported* to the learner's own assistant (§4.1) |
| Content economics | Undecided; the trade study in §4.2 is this doc's centerpiece |
| Exercises | In-browser execution (Pyodide-class) + a broadened non-code exercise vocabulary |
| Pedagogy | Code-first product; grader/milestone abstractions kept pedagogy-agnostic so non-code slots in later |
| Tenancy | Single-tenant deployment from day one, but multi-tenant *invariants* from day one (§7) |
| Deliverable now | This document. No code yet. |

---

## 2. What exists today (the corpus audit)

### 2.1 The spec lives in skills; the instances prove it

The generic layer is `~/.claude/skills/`:

- **`course-builder/SKILL.md`** — the pipeline: five stages (scope → resources → curriculum → interactive layer → assemble/support), three **course modes** (subject-driven, project-driven, research-driven), a canonical output tree, house-style rules, a quality checklist.
- **`course-builder/references/course-structure.md`** — anatomy of the two static documents (tiered resources with mandatory "why this one"; phased curriculum with checkpoint blocks, dependency map, capstone, dated version footers).
- **`course-builder/references/interactive-elements.md`** — five component types with a concept-shape → component decision table (spatial → widget; procedure → scaffolded exercise; misconception → quiz item; needs-talking-through → lesson guide; mid-reading recall → inline check), and hard constraints: single-file, offline, no CDN, localStorage never load-bearing, **no API-calling widgets** — "adaptivity is Claude in the loop."
- **`learner-profile/SKILL.md`** — the calibration model (decomposed in §5.1).
- **`curriculum-designer/`** (superseded predecessor) and **`reading-path/`** (an orthogonal HTML reading tracker whose entry schema duplicates the resource-list concept — a consolidation target).

Four instances, one per maturity generation:

| Course | Mode | Distinctive contribution |
|---|---|---|
| `learning/category-theory` | subject | Pre-course-builder era; static syllabus only — the drift baseline |
| `learning/ml-ai` | subject | Lazy phase-by-phase interactive generation ("don't front-load forty files"); canonical README shape |
| `rhyme-schemer/learning` | project | The course *is* the repo: units map to build order, the test suite is the grader, widgets port repo code verbatim. Real static-site generator (`build_site.py`) + design system (`style_source.py`) + corpus audits |
| `textual-flow/learning` | research | Pre-course exploration → convergence as first-class artifacts; `REVIEW.md` prior-art positioning; the only real **progress model** (localStorage hub); a second continuous track (Koine Greek) with its own stage ladder; non-cognitive milestones (contact a scholar, pre-register, publish); trainer-genre widgets |

### 2.2 The stable conventions (the platform's inherited genome)

1. Fixed layout: `README / learning-resources.md / curriculum.md / interactive/{lessons,widgets,quizzes,exercises}`.
2. Hierarchy: **Course → Phase → Unit**, plus an orthogonal **Track** (ml-ai's internals/engineering; textual-flow's program/Greek).
3. Unit schema: core fields **Build · Read · Concepts · Exercise · Milestone** plus per-course extension rows — already modeled as `rows: [{label, html}]` in textual-flow's curriculum page.
4. Quizzes where **every option carries a "why"** — distractors target named misconceptions, so a wrong click is diagnostic.
5. Exercises as `task.md` + typed stub + failing tests; "green bar = done."
6. Lesson guides as **Socratic playbooks for a model**, not prose: diagnostic opener with branches, staged PAUSE reveals, formalize last, one question per turn.
7. Question banks with a **recall / application / explain-why** taxonomy, designed for live drawing.
8. Markdown canonical, HTML derived; widgets port real code verbatim and are verified against the source's own tests; dated version footers; per-repo `CLAUDE.md` as runtime contract; trigger phrases ("Teach me Unit N interactively") as the runtime API.

### 2.3 The gaps — i.e., the platform's job description

1. **No progress model.** The only implementation anywhere is `textual-flow/learning/index.html`: a flat `{unitId: bool}` in localStorage, ids typed in three places, integrity maintained by a documented manual rule. Binary, browser-local, no history, no cross-course view, no link from assessment results to anything.
2. **No single source of truth for curriculum.** Canonical `.md`, mirrored `.html`, and JS arrays inside build scripts/hub pages — three representations, hand-synced. rhyme-schemer automated the sync with a generator; textual-flow regressed to hand-mirroring because the generator was never extracted.
3. **The profile is a hand-authored singleton with no feedback loop.** It explicitly disclaims knowing unit completion; nothing updates it from quiz misses, exercise reviews, or actual pacing.
4. **The site builder is per-course copy-paste**, not a shared package.
5. **No cross-course anything**: no shared learner view, no drift detection between course generations, no shared component library.

---

## 3. Product definition

**Thesis.** The differentiating asset is not course content — the internet is drowning in courses. It is the **calibration loop**: a rich, evidence-fed learner model, and a course factory that consumes it. rhyme-schemer's magic is that it never explains what a phoneme is (the learner has a linguistics BA) while building mathematical notation from scratch (no formal math past calculus). That precision, industrialized, is the product.

**Who it's for.** First: technical autodidacts — people who would bring their own subjects, tolerate rough edges, and *feel* the calibration. Later: general consumers willing to learn by doing, for whom onboarding polish and non-code subjects matter.

**What it is.** A web app where a learner: (1) builds a profile through an onboarding flow that ingests evidence, not just self-description; (2) enrolls in a subject and receives a course calibrated to that profile; (3) works through phases with interactive materials — widgets, auto-checking quizzes, in-browser exercises, drills; (4) accrues progress that is real data, which feeds back into the profile; (5) optionally connects their own AI assistant to the course for live Socratic tutoring, at their own inference cost.

**What it is not.** Not a chatbot tutor (see §4.1). Not a content marketplace. Not credentialing. Not, in v1, a place for human instructors — though the multi-tenant design should not preclude a cohort/educator tenant type later.

---

## 4. The three central design decisions

### 4.1 LLM runtime posture: background jobs at defined moments, tutoring as export

The corpus's current runtime is Claude Code itself: lesson guides are playbooks *for the model*, question banks are drawn live, trigger phrases are the API. A standalone web app must either replace that runtime, drop it, or relocate it. Decision: **relocate the factory, export the tutor.**

**The rule (a platform invariant, styled after job-radar's T-rules):**

> **L1.** The LLM runs only inside background jobs, each tied to a discrete course event. There is no request-path inference and no open-ended conversational endpoint.
> **L2.** Every LLM call carries a stage label and is metered to a per-tenant token ledger with per-stage budgets enforced at the queue.
> **L3.** Anything conversational happens on the learner's own assistant, against exported course context — their inference bill, not ours.

**The defined moments** (each already has a seam in the corpus):

| Moment | Trigger | Corpus precedent |
|---|---|---|
| Onboarding calibration | signup / profile update | `learner-profile` skill; job-radar's onboarding pipeline |
| Course generation | enrollment | `course-builder` stages 1–3 |
| Lazy phase build | learner nears phase N+1 | ml-ai's "Build the Phase 2 interactive layer" convention |
| Exercise feedback | submission | "Review my code for Unit N" trigger phrase |
| Re-planning | pace/plan divergence; profile change | dated version footers; "revised against review" convention |

Why the economics work: cost is proportional to learner **milestones**, not learner **chattiness**. You can only finish a phase so often. Every moment is batchable (Anthropic Batch API, −50%), budgeted, and rate-limited by the course's own structure. The abuse surface of a chat endpoint simply doesn't exist.

**The tutor export.** The lesson-guide format is model-agnostic by design. The platform exposes an **MCP server** (per-learner, authenticated) serving: the profile, the course manifest, current progress, the active unit's lesson guide, and the question bank. The trigger-phrase protocol becomes MCP tools: `teach_unit(n)`, `quiz_me(phase)`, `review_exercise(path)`, `whats_next()`. An autodidact connects Claude (or anything) and gets the full Socratic experience; a consumer who skips it still has a complete course, because guides are dual-rendered as reader-facing "think-first" prose — a transform `build_site.py` already performs (PAUSE blockquotes → think-first boxes). A hosted, metered tutor remains a possible premium tier, deliberately unplanned.

### 4.2 Content economics: where personalization lives (the trade study)

Today every course is a **frozen per-learner projection of the profile** — regenerate to re-personalize. At one learner that's fine. At consumer scale it's the dominant cost. Three models:

**Model A — bespoke: per-learner generation (status quo).**
Every enrollment runs the full factory. Rough sizing, from the corpus: a mature course is ~15–22 units, a resources doc with live-verified URLs, 7–16 lesson guides, 3–8 widgets (each a small app), quizzes, exercise scaffolds. As agentic work: order 5–20M tokens end-to-end. At Sonnet-class batch pricing, order **$15–60 per full course**; lazy phase generation defers ~60–70% of it and never spends it on learners who stall in Phase 1 (most learners, realistically — stall-heavy funnels are the genre's defining statistic).
*Pro:* maximum calibration — the course can be built around the learner's own project or research question; this is the rhyme-schemer/textual-flow magic, and it is the product's soul.
*Con:* cost scales with signups × subjects; quality variance at generation scale becomes a real QA problem (every learner gets a course nobody has proofread); no network effects between learners of the same subject.

**Model B — shared spine + personalization overlays.**
A subject's course is authored once (LLM-drafted, human-reviewed — expensive, amortized). Personalization becomes structured **overlay parameters** applied at render/plan time: which resources are picked (profile-driven selection from the tiered list), which exercise domain-variants are served, per-unit skip/scaffold flags, pacing plan, which **on-ramp companions** attach (rhyme-schemer's `phonetics-primer` pattern — companions are already modular by design), plus small bounded generations: per-learner "key insight" bridge lines, analogy swaps. Marginal cost per enrollment: order **$0.10–$2**.
*Pro:* consumer-viable unit economics; spine quality is auditable once; fixes propagate to everyone.
*Con:* calibration depth is capped by the overlay vocabulary; project- and research-driven modes are impossible (there is no shared spine for *your* research question); the profile's most interesting fields (known/unknown sets) get flattened into skip flags.

**Model C — tiered: template → fork.**
Enrollment instantiates from the spine; units are **regenerated per-learner only where the profile diverges** from the spine's assumed learner, and the fork deepens as evidence accumulates (a failed checkpoint forks a remedial variant; a domain preference forks the exercises). Cost sits between A and B and — crucially — is proportional to *divergence*, which is proportional to how engaged the learner is. Engaged learners are the ones generating revenue.
*Con:* the hardest engineering — content versioning, spine-update propagation into forks, provenance tracking per unit.

**Recommendation: the model is a property of the course mode, not the platform.**

| Course mode | Content model | Rationale |
|---|---|---|
| Subject-driven (ml-ai, category-theory) | **B now, C later** | Subjects repeat across learners; spines amortize. C's fork-on-divergence is B's natural upgrade path, so build B's overlay vocabulary as the fork boundary from day one. |
| Project-driven (rhyme-schemer) | **A, always** | The course is the learner's own build; no spine can exist. Priced accordingly — this is the premium/autodidact tier. |
| Research-driven (textual-flow) | **A, always** | Ditto, plus the exploration phase. Flagship-expensive, flagship-differentiating. |

This resolves the audience split too: consumers live in subject-driven/Model B; autodidact peers pay for A. The corpus already told us this — the *graduation rule* (a track leaves the monorepo when it becomes project- or research-driven) is the same boundary.

**Design consequence:** every schema in §5 must record, per unit, whether it came from a spine, an overlay, or a fork — so Model C is a migration, not a rewrite.

### 4.3 Pedagogy scope: code-first, abstract graders

The exercise vocabulary generalizes now, even though v1 ships code-first. The corpus already contains the abstraction, unnamed:

| Grader type | "Done" is decided by | Corpus precedent |
|---|---|---|
| `unit-test` | tests pass (in-browser, Pyodide-class) | every exercise dir |
| `property-test` | invariants hold over seeds | textual-flow unit 8 |
| `oracle` | output matches reference implementation | open-cbgm cross-validation |
| `drill` | streak/score threshold | Greek alphabet & apparatus trainers |
| `annotation` | structured artifact produced | rhyme-schemer's gold-annotator (learner output feeds the real eval harness) |
| `artifact` | written deliverable exists (self-attested or reviewed) | textual-flow write-up units, contact milestones, pre-registration |
| `external` | out-of-band event confirmed | conditional Unit 17, gated on a licensing answer |

`Exercise.grader` is a typed union from day one. Non-code subjects arrive by adding grader types, not by rearchitecting.

---

## 5. Domain model

Provenance notes in parentheses; nearly every entity is a formalization of something the corpus does by hand.

### 5.1 Learner & Profile

```
Learner        id, auth identity, settings
Profile        versioned document per learner:
  background[]           # professional history, treated as bridging assets
  known[]                # "do not scaffold" — the skip-list
  unknown[]              # "build from zero" — the scaffold-list
  style                  # implementation-first, intuition→formalism, wants-why, tone
  domain_bias[]          # exercise domains that land (parsers, DSLs, corpora…)
  hours_per_week         # the sizing constant every unit is scoped against
  subject_adapters{}     # how the profile translates per subject class
ProfileEvidence  append-only ledger:
  {kind: attested | demonstrated | thin, source, claim, at}
```

(The field set is the `learner-profile` skill decomposed. The evidence tiers are job-radar's `evidence_tier()` translated: *demonstrated* = we ran your code / you passed the checkpoint; *attested* = you told us / uploaded it; *thin* = a syllabus claims it. The profile becomes **derived, not authored**: a fold over the evidence ledger, with a draft→review→promote loop for LLM-proposed updates — the learner always ratifies what the system believes about them. job-radar's rule applies verbatim: *the agent proposes, the human publishes.*)

### 5.2 Course structure

```
Subject         slug, description, mode: subject | project | research
CourseSpine     per subject (Model B): versioned; phases[], units[], resources[]
Enrollment      learner × subject:
  content_model: spine | bespoke
  overlay        # Model B: resource picks, skip/scaffold flags, pacing plan,
                 # exercise variants, attached companions, bridge lines
  forks[]        # Model C, later: per-unit regenerated variants + provenance
Phase           num, title, goal, week_range, checkpoint{prose, per-track goals}
Unit            num, phase, title, gloss, tags[],
  rows[]         # {label, content} — fixed core (Build/Read/Concepts/Exercise/
                 # Milestone) + per-course extensions (textual-flow's curriculum.html
                 # already models it exactly this way)
  depends_on[], load_bearing: bool        # the ASCII dependency map, structured
  provenance: spine | overlay | fork | bespoke
Track           orthogonal ordered stage ladder (Greek track, side quests)
Milestone       typed: grader-backed | artifact | contact | preregistration |
                publication | conditional(gate) | side-quest(hours/month)
```

### 5.3 Materials

```
Lesson       Socratic playbook (objective, prereq checks, diagnostic opener with
             branches, staged PAUSE reveals, formalize-last, confusions, exit check)
             — dual-rendered: (a) reader-facing think-first prose, (b) MCP export
Widget       single-file HTML, offline, deterministic, no network (constraint kept:
             it's what makes widgets cacheable, shareable, and safe)
Quiz         [{q, options: [{text, correct, why}]}] — every option explains itself
QuestionBank items tagged recall | application | explain-why; drill generators
Exercise     task.md narrative + stub + grader (typed union, §4.3)
Resource     url, format, cost, tier-by-role, why_this_one, verified_at
             — one schema unifying learning-resources.md and the reading-path
             tracker (they are the same object built twice)
```

### 5.4 Progress — the platform's first real addition

```
ProgressEvent  append-only: {learner, course, subject_id, kind, payload, at}
               kinds: unit_done, checkpoint_result{score, misses[]},
                      exercise_result{grader, passed, attempts},
                      drill_result{mode, streak}, resource_acquired,
                      milestone_hit, session_note
ProgressState  pure fold over events → per-unit state, per-phase rollup,
               per-track ladder position, %complete, next_up
```

(Pattern lifted whole from job-radar: **event ledger + pure fold + projected state**, where any status column is explicitly a projection and a disagreement is a bug in the column, never the fold. This one change retires localStorage, the three-place registration rule, and the composite-id hack simultaneously. Two corpus principles preserved: resource acquisition is not course progress — separate event kind, separate rollup; and checkpoint *misses* are recorded per-option, because distractors target named misconceptions — making quiz results legible evidence for the profile fold and for Model C fork triggers.)

### 5.5 The Manifest (killing the three-representation problem)

One machine-readable **course manifest** (schema above, serialized) is the single source of truth per course/enrollment. Markdown remains the *authoring* format — a compiler ingests the existing `curriculum.md` conventions (they're regular enough; rhyme-schemer's `curriculum_extract()` already parses them) and emits the manifest. Renderers consume only the manifest: web views, the static-site export, the MCP tutor context, progress hub. `build_site.py` + `style_source.py` are the seed of the renderer; the manifest compiler is the platform's very first component because it is **immediately useful to the existing courses, before any web app exists** (§9, Phase 0).

> Schema sketch: [platform-manifest.md](platform-manifest.md) (v0.1, 2026-08-28).

---

## 6. System architecture

### 6.1 Shape and stack

A **server-rendered monolith + background worker**, deliberately boring, inheriting job-radar's proven choices unless a reason appears to deviate:

- Python 3.12, FastAPI + Jinja2 + HTMX (no SPA, no build step)
- SQLAlchemy **Core** (not ORM) + Alembic, Postgres
- **procrastinate** (Postgres-backed queue — no Redis) for all LLM/factory jobs
- Object store (R2/S3) for blobs under `tenants/{id}/…` — with job-radar's rule: *blobs are written by workers and parsed at most once; everything the app reads to answer a question is a row*
- One-way layering enforced by test: `engine/` (course factory, folds, schemas — no framework imports) never imports `webapp/`

Why inherit: the patterns aren't just compatible, they were *built for* the same single→multi-tenant trajectory, and the test-enforced-convention culture ("a helper nothing forces you to use is a suggestion") is the part most worth keeping.

### 6.2 The course factory (the LLM subsystem)

The `course-builder` skill pipeline, translated from prose-for-Claude-Code into worker stages:

```
scope → curate_resources → design_curriculum → [enroll]
      → build_phase(n)  (lazy, triggered by progress events)
      → exercise_feedback(submission)
      → replan(divergence | profile change)
```

Mechanics, all inherited from job-radar:
- **Role contracts as markdown + frontmatter** (`roles/*.md`): mission, inputs, output shape, invariants. The executor is an adapter; the course-builder skill files are literally the first drafts of these roles.
- **Tier indirection**: roles name `cheap/frontier/premium`; only `models.yaml` names models and prices.
- **One metered executor**: every call streams, carries a stage label, writes the token ledger. Per-tenant, per-stage budgets enforced at the queue (invariant L2).
- **Batch API** for enrollment-scale generation; queue-lane discipline (factory jobs never share a lane with anything user-facing).
- **Strict schema contracts** for factory outputs (`from_dict` that raises on unknown keys), because generated artifacts are parsed by code, and a quiz missing its `why` fields should fail generation, not ship silently. Every generated widget/quiz runs a smoke check before promotion.
- **Draft→review→promote**: generated course content lands in a draft namespace mirroring live keys; promotion is a key rewrite in one transaction. For Model A courses the learner-as-reviewer sees a course outline to approve before the phase-1 build spends real tokens.

### 6.3 Exercise runtime

- **In-browser**: Pyodide (Python-in-WASM) runs stub + tests client-side. Zero server cost, zero abuse surface, keeps "the test bar is your grader" intact. Language menu constrained by WASM availability — acceptable for a code-first product whose corpus is entirely Python.
- **Local-repo path retained** for project/research-mode learners (it's how the mode works — exercises import the real package), with progress synced via a tiny CLI or manual check-off. Not a consumer path.
- **Non-code graders** (drill, annotation, artifact, external) run entirely client-side or as plain form submissions — no runtime needed.
- Server-side sandboxed execution: explicitly deferred. If ever needed, job-radar's no-egress sandbox worker is the template.

### 6.4 Tutor export (MCP)

A per-learner authenticated MCP server exposing read tools (`get_profile`, `get_course`, `get_progress`, `get_lesson_guide(unit)`, `get_question_bank(phase)`) and write tools (`record_progress_event`, `propose_profile_evidence` — landing in the evidence ledger as *attested*, never auto-promoted). The trigger-phrase protocol from every course README becomes this tool surface. The learner's assistant executes lesson guides exactly as Claude Code does today; the platform's job is only to serve context and accept evidence.

### 6.5 The web app

Learner-facing views, all renderers over manifest + progress fold: hub (per-course %complete, next-up, track ladders — textual-flow's `index.html`, made real), curriculum view with notes and remaining-filter, unit pages (syllabus row + lesson prose + materials chips — rhyme-schemer's `build_unit_pages()` layout), resource tracker (the unified Resource schema; acquisition state separate from progress), widget/quiz/exercise embeds, onboarding flow (draft→review→promote of the profile), and a plain settings/export/delete surface (§7 makes export/delete a derived registry, not an afterthought).

---

## 7. Single-tenant now, multi-tenant by construction

job-radar's central lesson, adopted wholesale: **isolation is a property of construction, not vigilance** — and the invariants never change across the transition; what changes is whether they're satisfied by construction or by coincidence. Its single-tenant era's conveniences (tenant id defaulting to `"0"`, config from env, module-level caches) each became a bug. Therefore, from the first commit:

- **T1.** Tenant context is an ordinary function argument, never ambient state. No default tenant.
- **T2.** Every table is classified `TENANT_SCOPED` or `TENANT_LESS`, asserted at import; an AST guard test walks query chains for unscoped access to scoped tables.
- **T3.** Blob keys are minted under `tenants/{id}/` by a storage object that cannot spell another tenant's prefix.
- **T4.** Export and purge lists are *derived* from the table classification and asserted complete at import — a purge is unrepeatable, so nothing may be missable.
- **T5.** The test suite provisions **two** tenants from day one ("a single-tenant fixture passes whether or not the scope does anything — it has nothing to leak toward").

**The shared/scoped split maps cleanly:** course spines, subjects, the shared resource corpus, and widget/component libraries are `TENANT_LESS` (job-radar's tenant-less `postings` table — no tenant column *at all*, because "a shared table with an unused tenant column is a table somebody eventually filtered by mistake"). Profiles, enrollments, overlays, forks, evidence and progress ledgers, token ledger are `TENANT_SCOPED`. Note the recorded warning for the day a private store becomes shared: every query that treated it as private changes meaning, even the reads.

Auth (later, when multi-tenant activates): Clerk-style hosted identity behind one seam; provisioning order *lookup → gate → create*; staff as a property of the user, orthogonal to tenancy; non-staff ops routes 404, not 403. Until then the single tenant is a real row created by real provisioning code — never a hardcoded default.

**SaaS posture notes for later, cheap to leave stubs for now:** per-tenant config as rows with text-as-authority + optimistic version column; the token ledger as the seed of usage-based pricing; Model B spines as the marginal-cost story that makes a free tier thinkable.

---

## 8. Migration of the existing corpus

The four existing courses are the platform's fixtures and its first QA suite:

1. **Manifest compiler ingests them as-is.** The markdown conventions are regular; parity check: compiled manifest → renderer must reproduce rhyme-schemer's `site/` and textual-flow's hub to visual equivalence.
2. **textual-flow's localStorage state** hand-converts to seed progress ledgers (one afternoon; it's `{id: bool}` × three namespaces).
3. **The learner-profile skill** becomes profile v1 for tenant #1, its claims entered as *attested* evidence.
4. **category-theory** is the drift test: a generation-behind course the compiler should flag, not silently accept.
5. The skills remain the authoring interface — Claude Code sessions produce/edit markdown, the compiler promotes it. The platform replaces none of the authoring workflow initially; it replaces the *delivery and state* layers.

---

## 9. Build roadmap

Each phase produces something used in anger before the next starts.

- **Phase 0 — Manifest + renderer extraction.** Manifest schema; compiler over the existing `curriculum.md` conventions; `build_site.py`/`style_source.py` generalized into a shared renderer package. *Exit: textual-flow's hand-mirrored HTML is deleted and regenerated; the three-place registration rule is retired.* Valuable with zero web app. **✅ Done 2026-08-28** — `~/repos/curricle`: schema, compiler, hub/curriculum/resources renderers, 44 tests; textual-flow swapped to generated pages with all learner state preserved. (rhyme-schemer's `site/` renderer generalization deferred to when that course swaps.)
- **Phase 1 — Progress service.** Postgres, event ledger + fold, hub/curriculum/unit views over it; T1–T5 in place; migrate localStorage state. *Exit: current courses driven day-to-day from the web app.* **🔨 Infrastructure complete 2026-08-28** — event ledger with append-time validation + pure fold, T1/T2/T4/T5 by construction (classification asserted at import, scope-guard test, derived purge/export, two-tenant fixtures, throwaway-Postgres test harness), Alembic chain, and the web app serving all three views in server mode with both courses loaded; `import-progress` CLI ready for the localStorage state. Exit criterion (daily driving) begins now.
- **Phase 2 — Profile pipeline.** Evidence ledger, draft→review→promote onboarding, checkpoint misses flowing in as evidence. *Exit: the learner-profile skill file is a generated projection, not a source.* **✅ Done 2026-08-28** — `profile_events` ledger (assert/propose/accept/reject/retract; tiers from provenance), pure fold, /profile review page ("the system proposes, you publish"), checkpoint results auto-proposing `demonstrated` evidence, and the skill file installed as a projection (round-trip diff vs. the hand-authored original: two deliberate lines). The LLM-driven onboarding *interview* remains Phase 3 territory.
- **Phase 3 — Course factory.** Roles, metered executor, token ledger, budgets; lazy phase-build jobs; exercise feedback. *Exit: ml-ai's Phase 2 interactive layer is built by the factory, not a Claude Code session.* **✅ Done 2026-08-28** — five role contracts, tier indirection via models.yaml, metered executor with per-stage budgets and token_ledger (migration 0003), refusal-grade output validation (generated exercise tests are executed against their stubs), draft→promote with compile-clean gate, and the parser's "headings" dialect bringing ml-ai into the fold. **Exit criterion met**: ml-ai's Phase 2 interactive layer (lesson guide, BPE merge lab, scaffolded exercise, checkpoint quiz, question-bank section) was built by the factory for $1.49 across five opus-5 calls, reviewed in draft, and promoted — with the derived profile visibly steering output (Latin-paradigm and parser corpora in the widget; "phonotactics" as the bank's tokenizer example). A mid-build credit outage proved the resume path: checkpointed build manifests merge across runs. Open items for later: exercise-feedback jobs, queue-based lazy triggers.
- **Phase 4 — Tutor export.** MCP server over manifest/profile/progress. *Exit: a fresh Claude session teaches a unit through MCP with no repo checkout.* **✅ Done 2026-08-30** — `curricle/mcpserver.py`: stdio MCP (stdlib JSON-RPC, no SDK dependency), read tools (`get_course/get_profile/get_progress/get_lesson_guide/get_question_bank`), the trigger-phrase protocol as tools (`teach_unit/quiz_me/review_exercise/whats_next` — each a complete briefing: contract + unit + guide + profile), and both write tools (`record_progress_event` with checkpoint→evidence intact; `propose_profile_evidence` source-required, `demonstrated` refused over the wire, pending /profile). L1 guarded by test, same as the web app. **Exit criterion met**: a fresh `claude -p` session in an empty directory, `--strict-mcp-config`, reported next-up from the live ledger and opened Unit 2 with the lesson guide's own diagnostic question, then stopped at the contract's first wait.
- **Phase 5 — Second learner.** Invite a real person; Model B spine for one subject; onboarding end-to-end. *Exit: the two-tenant fixture describes production.*
- **Phase 6 — Pyodide exercise runtime; consumer onboarding polish.** Sequenced by what Phase 5's learner actually hits.

---

## 10. Risks and open questions

- **Generated-course QA at scale** (Model A): every bespoke course ships unproofread. Mitigations: strict output schemas that fail generation loudly; smoke-tested widgets; learner-as-reviewer at the outline stage; the corpus's own audit pattern (`learning/audits/`) generalized into factory self-checks. Still the biggest open problem.
- **Resource rot and licensing**: "why this one" lists depend on live third-party URLs and priced books. Verification is a recurring background job, not a one-time footer; licensing constraints (textual-flow's INTF gate) need first-class representation (the `conditional` milestone already models it).
- **Widget generation reliability**: widgets are the highest-variance artifact class. The mitigation is a component library harvested from the existing sixteen — trainers, explorers, simulators are already recognizable genres — so the factory parameterizes proven shells more often than it free-codes.
- **Pyodide limits**: no threads, package gaps, slow cold start. Fine for the corpus's exercise style (pure functions, small data); a constraint to design exercises *for*, not fight.
- **The profile flattening risk** (Model B): overlays may lose exactly the calibration depth that is the product's thesis. The counter-metric: every overlay decision must be traceable to a profile field; if the overlay vocabulary can't express a profile distinction that matters, that's the signal to fork (Model C) — instrument for it from the start.
- **Consumer identity**: "code-first, door open" defers but does not answer whether non-implementing learners ever become the market. The grader abstraction keeps the door open cheaply; walking through it is a product decision for post-Phase-5 evidence.
- **Naming, pricing, and everything commercial**: out of scope for v0.1, deliberately.

---

## Appendix A — provenance map (pattern → source)

| Platform concept | Lifted from |
|---|---|
| Course modes, five-stage pipeline, component decision table | `~/.claude/skills/course-builder/` |
| Profile field decomposition, skip/scaffold lists, subject adapters | `~/.claude/skills/learner-profile/SKILL.md` |
| Unit `rows[]` schema, curriculum-as-data | `textual-flow/learning/curriculum.html` |
| Progress ids, %complete, next-up, second-track ladder | `textual-flow/learning/index.html` |
| Manifest renderer seed, PAUSE→think-first transform, unit page layout | `rhyme-schemer/learning/build_site.py` |
| Design-system-as-code, palette provenance | `rhyme-schemer/learning/style_source.py` |
| Lazy phase generation | `learning/ml-ai/README.md` |
| Grader taxonomy | exercises across all four courses (§4.3 table) |
| Milestone taxonomy beyond code | `textual-flow/learning/curriculum.md` |
| Event ledger + pure fold + projected status | job-radar `pipeline/onboard/eventlog.py`, `state.py` |
| Evidence tiers from provenance | job-radar `schemas.evidence_tier()` |
| Draft→review→promote; agent proposes, human publishes | job-radar onboarding pipeline |
| T1–T5 tenancy invariants, table classification, two-tenant fixture | job-radar `pipeline/tenant.py`, `db.py`, `docs/deep-dives/06` |
| Role contracts, tier indirection, metered executor, token ledger | job-radar `roles/`, `models.yaml`, `pipeline/roles/runner.py` |
| Blobs-once/rows-always; queue lane discipline; no-egress sandbox | job-radar `PRODUCT-ARCHITECTURE.md`, `pipeline/queue.py`, `sandbox/` |
| Conventions-as-tests culture | job-radar throughout |

*v0.1 — 2026-08-28. Interview decisions: audience (autodidacts + consumers), Fork B + tutor export, mode-dependent content model (B/A/A) with trade study, in-browser + non-code exercises, code-first pedagogy with abstract graders.*
