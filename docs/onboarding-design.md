# Curricle onboarding — from empty tenant to first learnable course

*Design v0.1 — 2026-08-30. Decisions recorded here were made in interview on
2026-08-30, informed by a survey of job-radar's onboarding pipeline (the prior
art named in [platform-design.md](platform-design.md) §4.1) and an audit of
curricle's own cold-start path. Like the platform document, decisions recorded
here are settled unless reopened in interview.*

> **On reading this in the open-source repository.** This is the design
> document the onboarding wizard was built from, and it is vendored here so
> the repository is self-contained: the decisions it records are settled, and
> code that contradicts one is a bug in the code. It cites `job-radar` — a
> private project whose onboarding pipeline was the prior art — and §2
> describes the state of curricle *before* the wizard existed. That section is
> history explaining the design, not a description of the product you have.

---

## 1. What this document is

The design for **onboarding**: the flow that takes a person from an empty
tenant to a learnable, phase-1-complete course. platform-design.md names this
work twice — §6.5 lists "onboarding flow (draft→review→promote of the
profile)" among the web views, and Phase 5's exit criterion is "onboarding
end-to-end" — but never designs it. This document does.

**The persona is a stranger.** Not the original author with a checkout and a
head full of conventions, but someone who cloned the newly public repository
and wants to use the product. Everything below is designed to be
self-explanatory to a person who has read the README and nothing else.

**The baseline is a running instance.** The design starts at "`python -m
curricle serve` is up against a migrated database with a provisioned tenant
and an API key in place." Environment setup — Postgres, `alembic upgrade
head`, `tenant create`, the key — remains the README runbook, out of scope
here. Onboarding is *what the browser shows on first visit*, not what the
terminal demands before it.

**Scope: the two creative acts.** (1) Bootstrapping a learner profile from
nothing, and (2) creating a new course through phase-1 materials. Ongoing
profile evolution already has its surfaces (`/profile`, the checkpoint→
evidence pipe, the MCP write tools) and is not redesigned. Tenant lifecycle,
auth, and invites stay in Phase 5+ per the roadmap.

### Decisions from interview

| Question | Decision |
|---|---|
| Persona | A stranger adopting curricle, not the author's own re-runs |
| Surface | Web forms with review gates — no chat panel, no CLI wizard |
| Scope | Profile bootstrap + course creation; setup and re-onboarding excluded |
| Prior art posture | Steal job-radar's patterns; implement in curricle's idioms |
| L1 vs. LLM-heavy onboarding | L1 holds; a minimal local worker process runs the factory stages |
| Profile input | Guided forms per field → `assert` events; **no LLM in the profile path** |
| Course depth | All the way through phase-1 materials — the learner lands on a usable course |
| First-course exemplars | A shipped house exemplar set curated from `examples/tinylang` |
| Course home | A managed courses directory with runtime registration after clean compile |
| Ordering | Profile first, hard gate — no course creation on an uncalibrated tenant |
| This document | A peer of platform-design.md in `docs/` |

---

## 2. The gap, audited

This is the state of the checkout on 2026-08-30, before any of the below was
built. What "create a profile and a course" actually took then, in order:

1. Hand-author a ~200-line seed YAML against a twelve-word field vocabulary
   nothing documents outside `profile.FIELDS`, then `profile import-seed`.
2. `profile render --out ~/.claude/skills/learner-profile/SKILL.md` — and
   remember to re-run it by hand after every accepted proposal, forever.
3. Copy `examples/tinylang` and "edit until it stops complaining" — the
   compiler is an excellent reviewer and a nonexistent author.
4. The factory can only **extend** a course: every role's prompt feeds on the
   course's own earlier materials as exemplars, and `quiz-author` literally
   requires an existing quiz HTML shell to rewrite. A brand-new course has
   neither. The upstream stages of §6.2's pipeline — `scope`,
   `curate_resources`, `design_curriculum` — were never built; Phase 3
   shipped `build_phase` alone and proved it against a course that already
   existed.
5. Restart `serve`, because courses are `--course` flags resolved at startup.

Nothing links steps 1 and 3, which is the deepest gap: the profile that
calibrates the factory and the course the factory extends are both
hand-authored artifacts with no flow between them. "Calibration is the point"
is true of every factory prompt and false of everything upstream of the
factory.

---

## 3. Prior art: what job-radar settles, and what we decline

job-radar's onboarding is a web wizard over an append-only event ledger:
`STAGE_SEQUENCE = (ingest, mine, generate, reconcile, review, promote)`,
folded to a state; one URL whose current screen is derived from the ledger;
"the agent proposes, the human publishes" enforced in the domain layer. It is
well-argued rather than proven — its own end-to-end exit criterion is still
open — but the patterns are exactly the ones this platform already imported
for progress and profile, applied one level up.

**Stolen** (pattern, not code):

- **Ledger → fold → derived screen.** Onboarding position is rows, not a
  cookie or a query parameter; a reload can never put the wizard behind work
  already done.
- **Stage sequence as one tuple** with typed classifications: which stages
  are a human's turn, which are a worker's, which refuse to run without
  source material.
- **Draft mirrors live.** Generated course content lands in a draft namespace
  whose layout is exactly the promoted layout, so promotion is a copy plus an
  event, never a translation.
- **The spend gate before the expensive stage.** job-radar gates promotion on
  review; we additionally gate *generation* on an approved outline, because
  our expensive stage is the build itself (platform-design §6.2 already
  promised this: "the learner-as-reviewer sees a course outline to approve
  before the phase-1 build spends real tokens").
- **Typed skips and wording tables.** Every machine reason a screen can
  surface gets a human sentence keyed by `(stage, reason)`, with a test that
  fails when a reason lacks one. Exception text never reaches a screen.
- **Elapsed, never a forecast.** Progress shows time since the last ledger
  event; no percent bars over LLM calls, no ETAs. Polling stops when nothing
  is in flight.
- **One rewrite, then refuse.** A generated artifact that fails validation
  gets exactly one retry with the validator's own findings in the prompt; a
  second failure fails the stage loudly and keeps nothing.

**Declined**, deliberately:

- **Evidence ingestion for the profile.** job-radar's core move — upload
  documents, mine repositories, generate a draft identity, reconcile — is
  right for careers, where the evidence *is* documents and self-description
  is the thing to distrust. A learner profile is the opposite case: its
  substance is self-knowledge (what to skip, what to scaffold, what examples
  land), the learner is the authority, and the schema already encodes that —
  `assert` is "the learner's own voice" and renders without review. Guided
  forms writing `assert` events are truer to the tier model than an LLM
  paraphrasing the learner back to themselves, and they take the entire
  upload/scan/parse apparatus — sandbox, classifier, quarantine — off the
  table. The `demonstrated` tier keeps its integrity by exclusion: no form
  can author it; only course activity proposes it.
- **The interview.** platform-design.md's Phase 2 entry deferred "the
  LLM-driven onboarding interview" to Phase 3; it never landed there — Phase
  3 became the factory — and the survey found job-radar
  never built one either — four typed ask-mechanisms, no conversation. We
  take the hint. Forms with strong examples, review gates where judgment
  enters. If an interview ever arrives it is the tutor's job over MCP (L3:
  the learner's assistant, their inference bill), not a chat panel in the
  web app.
- **Reconciliation, the sandbox, the invite gate.** Career-shaped or
  cost-control-shaped; nothing here needs them.

---

## 4. The flow, stop by stop

One URL, `/onboarding/`. The screen shown is a function of the onboarding
fold, never of navigation. A tenant with no published profile and no course
is redirected here from every learner-facing route (the front door included);
`/profile` and the export/delete surface stay reachable — no state of your
account is a state where your data is hostage.

### Stop 0 — Welcome

What onboarding will do (a profile, then a course), what it costs (the two
LLM stages, with the standing budget), and what it never does — stated above
the ask, not in a footer: *the profile page is the only authority on what the
system believes about you; nothing you type here is sent anywhere but your
own database and, later, the model calls that build your course; every
dollar of model spend is approved by you on a screen that shows the number
first.*

### Stops 1–4 — Profile forms

Four screens over `profile.FIELDS`, each field with a one-line explanation
and two real example claims (drawn from `examples/example-profile-seed.yaml`,
which becomes UI copy as well as a fixture):

1. **Who you are** — `background`, `education`, `tracks`, and the `meta`
   description line.
2. **How you learn** — `style`, `domain_bias`, `pacing`.
3. **Calibration** — `calibration`, `skip`, `scaffold`. The screen says
   plainly why these three are the product: they are the difference between
   a course that re-explains your degree and one that builds only what you
   lack.
4. **Subjects** — `subject_adapters`.

Each field takes a list of short free-text claims. Saving a screen appends
one `assert` event per claim — the learner's own voice, tier `attested`,
rendered immediately, no review loop, no model call anywhere in the path.
Keys are minted `{field}-{nn}` at first assert and never renumbered; editing
a claim re-asserts its key, deleting one emits `retract` — which finally
gives `retract` a producer (today it exists in the fold and nowhere else).

`demonstrated` never appears on a form. Its absence is the tier system
working: that field is written only by course activity, through the existing
checkpoint→propose pipe.

**The gate:** all four screens saved, with at least one claim in each of
`background`, `style`, `pacing`, and `calibration` — the fields every
factory prompt leans on. The other fields may be empty; an empty field is an
omitted line in the prompt, not filler. (Rejected: gating on every field —
forced text in `subject_adapters` from someone who doesn't yet know what the
field means is worse than silence. Rejected: no gate — a course generated
against an empty profile is the product's thesis, disproven, on the
learner's first day.)

### Stop 5 — Profile review

The rendered projection (`render_skill_md`) shown whole, captioned: *this
exact document rides along on every model call that builds your course.*
Edit loops back to the forms; confirm marks the profile published in the
onboarding ledger. As a side effect of this design, rendering becomes a
hook: any change to the profile fold re-renders the projection to its
configured install path, retiring the remember-to-re-render step for
everyone, wizard or CLI.

### Stop 6 — Course scope

The `scope` stage of §6.2's pipeline turns out not to be an LLM stage at
all: it is a form. Subject and working title, mode (`subject | project |
research`, each explained in a sentence), `hours_per_week`, cadence, what
done looks like, explicit out-of-scope lines, and prior exposure to this
subject specifically. Deterministic; saving appends the scope to the ledger.
Course id is minted from the title, collision-checked against the courses
directory.

### Stop 7 — The outline build (worker)

The first factory-side stage: two new roles, `curriculum-designer` and
`resource-curator`, drafted from the course-builder skill's stages 2–3
exactly as the five existing roles were drafted from its stage 4. Inputs:
the rendered profile, the scope, and the house dialect documentation.
Outputs: `curriculum.md` (bullets dialect), `course.yaml`, and
`learning-resources.md` with the mandatory why-this-one essays — written to
`<courses_dir>/<id>/.draft-onboarding/`, a draft tree whose layout is
exactly the course layout.

The validator is the compiler. The draft is compiled in place; issues are
the same `Issue` objects a human author gets, and on errors the role gets
one rewrite with the compiler's own `where`-bearing findings in the prompt.
A second failure fails the stage — refused, not reviewed — and the screen
says so in a human sentence, with retry safe because nothing partial was
kept. The house rule generalizes: **a generated course artifact that does
not compile clean was not generated.**

While the worker runs, the screen shows the stage name, elapsed time since
the last ledger event, and nothing else it would have to invent.

### Stop 8 — The outline gate

The learner-as-reviewer moment platform-design §6.2 and §10 both promise.
Rendered from the draft manifest: phases with goals, units with glosses, the
resource shelf with its essays, the track ladder if one was designed. Below
it, the spend decision: the phase-1 build plan (which units get a lesson, a
widget, an exercise; the quiz; the bank) and a cost estimate computed from
`models.yaml` prices and per-role budgets — the number first, then the
button. Approving appends the approval *carrying the estimate shown* to the
ledger; nothing that costs tokens runs without such a row upstream.
Rejecting with a note re-runs Stop 7 with the note in the prompt; the note
is a ledger row too.

**Two numbers, and a receipt for both.** The estimate alone turned out to
be the wrong shape for this decision: a display-size figure with cents on it
reads as a price, and the first live walk came in at $2.02 against "$1.70
estimated" — an honest 19% over that nonetheless read as a wrong price. So
the gate shows the estimate *and* the **headroom**, each under the word that
says which it is: the estimate is an expectation at today's rates, the
headroom is what these roles have left to spend before one of them refuses.
They are not the same size — the estimate keeps display size and the
headroom steps down one — because two figures at equal weight put the one
that is *not* the cost where the eye lands first.

Headroom, not "the ceiling", and the distinction is the whole of why this
number is trustworthy. `models.yaml` budgets are per tenant per *stage* for
the life of an account, and `Runner.run_role` compares a role's entire
ledger history against its budget before every call. The sum of the budgets
is therefore not a cap on *this* build — a learner on their second course
has already eaten into every one of them, and a gate printing the sum would
put a number on screen that the next call could refuse to honour, with the
approval row recording it forever. What the worker writes into the
`outline_ready` payload is `sum(max(0, budget − spent(role)))` over the
roles the plan will actually run, read at the moment the outline becomes
ready; the wizard still reads no prices of its own. It is a stopping line
rather than a hard cap and the copy says so: the check happens before a
call, so a call already under way can carry its role a little past its
budget. When the headroom will not cover the estimate the gate says that
above the button, in a sentence, and still offers the button — it is the
learner's account and their decision, and a build that stops partway keeps
what it finished.

The approval row echoes *both* figures, so O3's "the number the learner was
shown" is the whole of what they were shown. The gate also prints what
drafting has cost so far — across every draft, when a rejection bought more
than one — from `token_ledger` (a database read; L1 is about model calls,
not queries), because that money was spent on the strength of an aside
calling it the cheap stage and no screen had ever named it. The landing
closes the loop with the receipt: total, split into draft and build, beside
the estimate the build was approved at. Two-decimal precision belongs there,
where it is a bill, rather than on an estimate, where it is a claim the
system cannot keep.

(Rejected: a second human gate on the generated materials themselves. The
outline is where a human's five minutes change the outcome; the materials
are guarded by the existing refusal-grade validators — exercise tests
executed against their stubs, quiz `why` fields required, widgets
offline-checked — and by the fact that everything lands in a draft the
learner can regenerate. A review step that gates the first usable course on
proofreading five artifacts would be depth theater; job-radar's WEB-35 made
the same call.)

### Stop 9 — Phase-1 build (worker)

The existing `factory.build_phase`, with one change: **the exemplar
fallback.** Where today's prompt assembly reaches for the course's smallest
existing lesson/widget/exercise and the existing quiz shell, a new course
has none — so the factory falls back to a shipped exemplar set,
`curricle/exemplars/`, curated from `examples/tinylang`'s materials (one
lesson, one widget, one exercise, the quiz shell, a bank section). tinylang
already exists to be the schema's reference instance; this promotes its
materials to the factory's reference voice. Course-native exemplars take
over from phase 2 on, exactly as today. (Rejected: seeding every new course
as a tinylang copy — placeholder content in a learner's course is residue
someone must clean; a fallback at prompt-assembly time leaves the course
tree honest. Rejected: exemplar-free role variants — the calibration thesis
says the exemplar *is* load-bearing; going without one on the highest-stakes
build, the learner's first, is the wrong place to run that experiment.)

Build output lands in the draft tree's `interactive/.draft-p1/` with the
existing checkpointing, resume-on-retry, budgets, and ledger rows.

### Stop 10 — Promote and land

The existing `factory.promote` mechanics, then the draft tree moves whole
into `<courses_dir>/<id>/`, the final compile-clean gate runs, the running
app registers the course, the ledger records promotion, and the learner is
redirected to the course hub — done marks at zero, next-up pointing at
unit 1, and a closing card that offers the two onward paths: work in the
browser, or connect the MCP tutor (with the config snippet printed, which
the repo currently never commits anywhere).

Creating a *second* course re-enters at Stop 6; the profile stops 1–5 never
re-gate a tenant who has published one. That re-entry is the `enroll` verb
of §6.2's pipeline, arrived at from the side.

---

## 5. The state machine

A new tenant-scoped `onboarding_events` table (migration 0004), append-only,
same discipline as the other two ledgers: `profile_published`,
`scope_saved`, `outline_requested / outline_ready / outline_failed{reason}`,
`outline_approved{estimate} / outline_rejected{note}`, `build_requested /
build_progress{artifact} / build_ready / build_failed{reason}`,
`promoted{course_id}`. (`build_progress` arrived with migration 0006: one
row per artifact as the build lands it — a count the worker holds, so a
fact for the ledger and a stone on the build screen; the elapsed-never-
forecast rule forbids estimates, not counts of finished things.) A pure fold
(`onboarding.fold`) orders by row id and yields the current stop; the wizard
route renders whatever the fold says. Stage classification follows
job-radar's vocabulary:

```python
STAGE_SEQUENCE = ("profile", "scope", "outline", "outline_gate", "build", "promote")
HUMAN_STAGES   = frozenset({"profile", "scope", "outline_gate"})
WORKER_STAGES  = frozenset({"outline", "build", "promote"})
```

The profile stop's *content* still comes from the profile fold — the
onboarding ledger records only that publishing happened, never duplicating a
claim. Two ledgers, two folds, one derived screen; a disagreement between
the onboarding ledger and the profile fold is a bug in whichever one is
acting as a projection of the other, and it is always the onboarding ledger.

Screens distinguish `pending` (a machine's turn — show elapsed) from
`waiting` (your turn — show the ask), always icon *and* word. Every
`*_failed` reason has a sentence in a wording table keyed by
`(stage, reason)`, and a test fails when one doesn't.

---

## 6. The worker

`python -m curricle work` — a separate process beside `serve`, sharing the
database and nothing else. It polls a `factory_runs` table (same migration:
tenant-scoped, `stage`, `payload`, `status`, `claimed_at`, `finished_at`,
`reason`) with `SELECT … FOR UPDATE SKIP LOCKED`, runs the requested stage
through the existing `llm.Runner` — budgets, stage labels, and the token
ledger all intact — and appends the outcome to the onboarding ledger. The
web app writes request rows and reads outcome rows; it never imports `llm`
or `factory`, and the existing grep guard grows one filename to keep it
that way.

This is deliberately a thin slice of the queue platform-design §6.1 already
plans (procrastinate, "the queue arrives with multi-tenancy"), not a rival
to it: the table's shape is a procrastinate job's shape, so the migration
path is "point the same callers at the real queue," not a redesign. One
process, one claim at a time, no retry scheduler beyond "a failed stage can
be requested again" — the wizard's retry button *is* the scheduler.
(Rejected: relaxing L1 for onboarding routes — reopening a settled
invariant to avoid one small process is a bad trade, and the invariant's
guard tests would all need carve-outs. Rejected: building the full queue
now — nothing about a single tenant clicking one wizard needs
prioritization, lanes, or horizontal workers.)

L1 gains its runbook corollary: onboarding requires `serve` and `work` both
running. The welcome screen checks and says so — a wizard that would wait
forever on a worker nobody started must say "the worker isn't running"
before the first form, not after it.

---

## 7. The courses directory and runtime registration

A managed courses home — `CURRICLE_COURSES_DIR`, no default, same
explicit-configuration posture as the database URL — holding one directory
per wizard-created course. `serve` loads it at startup alongside any
`--course` flags (which keep working unchanged for checkout-mode users and
the existing corpus courses), and gains one runtime operation: **register a
course after promotion**, which compiles it and adds it to the running
app's course map only when the compile is clean. The startup invariant —
never serve a course that doesn't compile — is preserved exactly; what
changes is only *when* the check can happen. A course that was registered
at runtime is loaded the same way on the next start, because it is simply
a directory in the courses home. (Rejected: end the wizard with "restart
serve with `--course …`" — a flow built so a stranger never touches the
terminal cannot end by handing them a terminal command.)

---

## 8. Invariants, kept and added

Kept, with the onboarding-shaped consequence:

- **L1** — no LLM on a request path: the worker exists; the guard test
  extends to the wizard's modules.
- **L2** — every call metered and budgeted: the outline and build stages run
  through `run_role` unchanged; onboarding adds stage labels, not paths.
- **T1** — tenant explicit everywhere: the wizard operates on the tenant
  `serve` resolved at startup; no route takes a tenant parameter.
- **Agent proposes, human publishes** — the outline gate for generation; the
  profile needs no gate because forms write in the learner's own voice, which
  is precisely what `assert` means.
- **The compiler refuses rather than guesses** — extended to generation: one
  rewrite against the compiler's findings, then loud failure.

Added:

- **O1.** The wizard's current screen is a pure function of the ledgers.
  Navigation can reach at most the screens a fold says are open.
- **O2.** No machine reason without a human sentence — the `(stage, reason)`
  wording table is test-enforced complete.
- **O3.** No token is spent without an upstream ledger row recording the
  learner's approval and the estimate they were shown.

---

## 9. New machinery, inventoried

| Piece | Shape |
|---|---|
| Migration 0004 | `onboarding_events` + `factory_runs`, both `TENANT_SCOPED` |
| `curricle/onboarding.py` | events vocabulary, fold, stage classification |
| `curricle/worker.py` + `work` CLI verb | claim → run stage → append outcome |
| `roles/curriculum-designer.md`, `roles/resource-curator.md` | from course-builder stages 2–3; premium tier to start, per the models.yaml comment's own doctrine |
| Compile-retry loop in `factory.py` | issues → one rewrite → refuse |
| `curricle/exemplars/` | curated from tinylang; prompt-assembly fallback when a course has no phase-N−1 materials |
| `CURRICLE_COURSES_DIR` + runtime registration | §7 |
| Wizard routes + templates + gate | one URL, fold-derived screens, `(stage, reason)` wording tables |
| Profile projection hook | any profile-fold change re-renders SKILL.md to its configured path |
| MCP config snippet | printed on the landing card; committed as a doc |

Everything else the flow touches — the profile ledger and `/profile`, the
factory's validators, budgets, draft checkpointing, promote's compile gate,
the progress service the finished course lands on — already exists and is
used unchanged. That ratio is the design's main argument for itself.

---

## 10. Build order

Sliced so each lands separately and is used in anger before the next:

1. **Worker + ledgers + courses dir.** Migration, fold, `work`, runtime
   registration. Provable with a no-op stage before any new role exists.
2. **Profile wizard.** Stops 0–5 plus the projection hook. Independently
   valuable: it replaces the hand-authored seed YAML for everyone.
3. **Outline stages.** The two roles, the compile-retry loop, the scope
   form, the outline gate with real estimates. Exit test: a scope form
   filled against the example profile yields a compiling course outline.
4. **Exemplar fallback + build + promote.** Stops 9–10; tinylang materials
   curated into `exemplars/`.

**Exit criterion for the whole:** a person who has never seen curricle
follows the README to `serve` + `work` on an empty tenant, and from there —
browser only, terminal never — reaches a phase-1-complete course hub whose
token ledger shows every model call, each within budget, each downstream of
an approval row carrying the estimate that was on the screen.

---

## 11. Open questions

- **Where the projection's install path lives.** The SKILL.md render target
  (`~/.claude/skills/learner-profile/SKILL.md` today) is per-machine, not
  per-tenant; a config row is probably right, but tenant config as rows is
  Phase-5+ machinery. Interim: a `serve`/`work` flag, defaulting to off.
- **Resource verification at generation time.** `resource-curator` will
  emit URLs; the platform's own risk register calls resource rot a standing
  problem. Does the onboarding build verify liveness (a slow, flaky stage)
  or stamp `verified_at: never` and leave it to the recurring job
  platform-design §10 imagines? Leaning: the latter, honestly labeled.
- **The second learner's first course in Model B.** This design is pure
  Model A (bespoke generation), which is correct for the modes that need it
  and for proving the flow — but Phase 5 pairs "onboarding end-to-end" with
  "a Model B spine for one subject," and enrolling *into a spine* is a
  different Stop 6–10 (overlay selection, no build). The stage machine is
  built so those stops swap; the overlay flow is deliberately not designed
  here.
- **Widget variance.** The known highest-variance artifact class now gets
  generated on a stranger's first click. The component-library mitigation
  (§10 of the platform doc) becomes more urgent the day this ships; until
  then the outline gate's build plan could offer "skip the widget" as a
  per-unit choice.

---

*v0.1 — 2026-08-30. Interview decisions: stranger persona; web forms +
review gates; profile via guided forms (no LLM), course through phase-1
materials; L1 kept via a minimal worker; shipped tinylang exemplars; managed
courses dir with runtime registration; profile-first hard gate.*
