# CLAUDE.md

curricle is the platform distilled from the learning-track corpus. Read
`docs/platform-design.md` (the architecture and its decided trade-offs) and
`docs/platform-manifest.md` (the schema spec) before changing anything
structural — decisions recorded there are settled unless the user reopens
them. Both are vendored copies of the originating design documents, so the
repository is self-contained; they cite a private corpus for evidence but
depend on none of it.

## Commands

```bash
source .venv/bin/activate
python -m unittest discover tests                    # full suite (fast)
python -m curricle compile <course_root> --out build/<id>.manifest.yaml   # sidecar: <root>/learning/course.yaml
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
- Content links by reference (`refs.py`): `res:`/`unit:`/`mat:`/`repo:`
  inside markdown link targets, validated at compile (dangling = error),
  resolved per medium by a `RefResolver` each renderer builds for its page.
  The `Interactive` row is derived from materials, never authored; the
  served `repo/` route hands out only manifest-blessed paths.
- `tests/test_corpus.py` runs against the sibling repos (`../textual-flow`,
  `../rhyme-schemer`) and skips when absent. The progress-id pin for
  textual-flow is a migration-safety contract — do not "fix" it to match
  code; fix code to match it, or consciously migrate.
- `examples/tinylang` is the shipped course: the compiler's integration
  coverage for anyone without the private corpus, and the thing people copy.
  `tests/test_example_course.py` never skips and holds it to **zero warnings**,
  not just zero errors. It is the one course that has to keep exercising every
  part of the schema — a track, a non-unit milestone, all four material kinds,
  a grader, and all four ref schemes — so add there when the schema grows.
  Its Unit 2 starter ships red on purpose and a test enforces that; solving it
  in the repo is the failure mode being guarded.
- Compiled manifests in `build/` are committed for inspection; regenerate
  them in the same commit as any compiler or sidecar change.
- The YAML `on:` key parses as boolean True (YAML 1.1); the sidecar loader
  normalizes it. Don't rename schema fields to dodge YAML quirks.

## The progress service

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
  `alembic upgrade head`, `python -m curricle serve --course … --tenant you`.
- `serve --host` defaults to `127.0.0.1` and the **default is the security
  posture**, not a convenience — this app has no auth, so widening the bind
  has to be something a person typed. `tests/test_serve_cli.py` pins both the
  default and that the flag reaches uvicorn. Don't change the default to
  "make containers easier"; the container narrows the *publish* instead.

## The container

- `Dockerfile` ships a **checkout at `/app`**, not just the wheel, with
  `CURRICLE_HOME=/app`. That is what keeps `models.yaml` and `roles/`
  operator-editable and `alembic upgrade head` runnable — the same reasoning
  that keeps them out of the package in the first place. Adding a new
  root-level file the runtime reads means adding a `COPY` for it.
- No `ENTRYPOINT`: `serve` and `work` are two processes from one image, and
  L1 is the reason (the app may never call a model, the worker is the only
  thing that may). Only the worker gets `ANTHROPIC_API_KEY`.
- `.dockerignore` excludes `local/`. That is a credential boundary, not
  tidiness — the image is published to a public registry.
- `.github/workflows/release.yml` publishes `ghcr.io/nathancrtr/curricle` on
  `v*` tags only, so a deployment can pin an exact version.
  `docs/self-hosting.md` is the reader-facing contract; keep it true.

## The profile pipeline

- The learner profile is a fold over `profile_events` (`profile.py`), and
  `~/.claude/skills/learner-profile/SKILL.md` is a **generated projection**
  (`profilerender.render_skill_md`) — never edit that file by hand; assert
  or propose evidence, then `python -m curricle profile render --tenant
  you --out ~/.claude/skills/learner-profile/SKILL.md`. The hand-authored
  original is backed up beside it as `SKILL.md.pre-curricle`.
- Every path that writes a profile event re-renders the projection, so
  nobody has to remember to: `serve --profile-skill-out PATH` for the web
  side, `--render-skill PATH` on `profile assert` and `profile import-seed`
  for the CLI. Both are off unless named — where the path should live
  persistently is onboarding-design.md §11's open question. All three
  writers (and `render --out`) go through `profilerender.write_skill_md`,
  which is atomic and 0600; a model reads this document, and a half-written
  one is a lie told mid-sentence.
- Evidence tiers come from provenance, never confidence: `attested` (the
  learner said it), `demonstrated` (course activity proved it), `thin`
  (claimed, uncorroborated). The agent proposes, the human publishes: only
  `assert` (the learner's own voice) skips review; every `propose` waits on
  /profile until accepted, and wire proposals must name a source.
- Checkpoint results POSTed to the course events API automatically become
  proposed `demonstrated` evidence, misses included.
- Claim identity is (field, key) and keys are forever; the field vocabulary
  is `profile.FIELDS` — grow it deliberately, renderers know the sections.
- The personal seed lives in gitignored `local/`; tests use synthetic
  fixtures only. The rendered personal projection is gitignored too
  (`build/learner-profile-SKILL.md`) — it is one person's evidence, not an
  artifact of this repository. What ships instead is
  `examples/example-profile-seed.yaml` (a fictional learner) and
  `build/example-profile-SKILL.md`, exactly what `import-seed` + `render`
  produce from it. Regenerate that pair together, never by hand.

## The course factory

- Every LLM call goes through `llm.Runner.run_role` — streams, carries a
  stage label (the role name), writes `token_ledger`, refuses past the
  stage's budget. There is no other path to the model; the web app never
  calls it (invariant L1: no LLM on a request path, ever).
- `models.yaml` is the only file naming a model or a price. Roles and code
  say cheap/frontier/premium. A price change is a YAML edit.
- `models.yaml` and `roles/` are operator-editable configuration, so they stay
  at the checkout root and are resolved per call by `llm.home()` —
  `CURRICLE_HOME` if set, else the directory above the package. That makes the
  factory a checkout-mode feature: an installed curricle has the compiler, the
  renderers, and the web app but no role contracts, and must say so
  (`FactoryConfigMissing`) rather than dying inside a YAML parse. Don't move
  these into the package to "fix" the install — burying them in site-packages
  defeats their purpose.
- Role contracts live in `roles/*.md` (frontmatter + system prompt). The
  factory prompt = derived learner profile + manifest phase context +
  exemplars from the course's own earlier phases. Calibration is the point.
- A course with no question bank gets one minted at
  `interactive/quizzes/question-bank.md` (house preamble + the generated
  section, registered as a `question-bank` material); a course that has one
  gets a section appended. The append is the only step in `promote` that is
  not a move, so it is guarded by its own text — it runs before the compile
  gate, and a retry after a refused gate would otherwise append twice.
- Outputs are refused, not reviewed: see the validators in `factory.py`.
  Generated exercise tests are executed against their stub — if they pass,
  the build fails. Drafts land in `interactive/.draft-pN/`; only
  `factory promote` touches the course, and it aborts unless the compile
  stays clean.
- The API key comes from `ANTHROPIC_API_KEY` or gitignored
  `local/anthropic-key`. Never commit, print, or read the key's value.
- Two curriculum dialects exist: `bullets` (textual-flow, rhyme-schemer)
  and `headings` (ml-ai) — sidecar `dialect:` field selects.
- Looking at the onboarding wizard never needs a key: `python -m curricle
  work --scripted` runs the real worker with the canned model in
  `scripted.py` (dials `--linger`, `--fail stage:reason`), and `python -m
  curricle faces --out build/wizard` renders every screen from synthetic
  state with no database at all (`faces.py`; output is gitignored). The
  scripted module is the one place the canned course lives — the factory
  and flow suites import it rather than keeping a copy.

## The design system

- `curricle/theme.py` is the single source of design tokens, base CSS,
  `WAYPATH_JS`, the wordmark and the milestone glyph. Renderers compose
  `theme.style(own_css)` and define no palette of their own — a module that
  composes the theme while keeping its own `:root` block overrides the whole
  system with its old palette. Every stylesheet is guarded: a new module spending tokens joins `SHEETS`
  in `tests/test_theme.py` or the suite fails.
- The waypath goes only where something is genuinely tracked. The profile
  page has no waypath because it tracks nothing; a gesture meaning "where you
  are on a path" is a lie on a page with no path.
- Evidence tiers and semantic chips carry their meaning in words — the tier
  or label is always printed. Color is reinforcement, never the message.
- `--faint` is decorative only: it computes 4.27 on light `--panel`, under
  the 4.5 text floor. Placeholder and every other line of copy takes
  `--muted`. `tests/test_theme.py` allowlists `--faint` per (stylesheet,
  selector, property); adding an entry means confirming the use is a mark.
- `theme.WAYPATH_JS` stays `%`-free and `BASE_CSS` is never `%`-formatted:
  three renderers concatenate the former into a `SCRIPT % {...}` template,
  and the latter is full of literal percents. Either mistake breaks the page.
- The contrast table in `DIRECTION.md` is the record; `CONTRAST_PAIRS` in
  `tests/test_theme.py` recomputes it from `theme.py` and asserts each floor.
  Changing a token means recomputing both.
- `build/*.html` are committed artifacts like the manifests: regenerate them
  in the same commit as any renderer change. The committed HTML has gone
  stale before.
- `DIRECTION.md` at the repo root is the design rationale — the gesture, the
  judgment calls, the contrast provenance, what was rejected and why.

## The tutor export

- `mcpserver.py` is the MCP server (`python -m curricle mcp --course …
  --tenant you`, stdio): read tools serve context (course, profile
  projection, progress, lesson guides, question bank), the trigger-phrase
  tools compose it (`teach_unit`, `quiz_me`, `review_exercise`,
  `whats_next`), and the two write tools go through the same validation as
  the web routes — `record_progress_event` (checkpoint results still
  auto-propose evidence) and `propose_profile_evidence`, which must name a
  source, may not claim `demonstrated`, and waits on /profile like every
  proposal.
- L1 applies here exactly as to the web app: the module never imports the
  model runner (guard test in `tests/test_mcp.py`); the learner's own
  assistant does the thinking, at their own inference cost (L3).
- The transport is stdlib-only newline-delimited JSON-RPC — no MCP SDK
  dependency; don't add one for a protocol this small.
- Content leaves through `refs.resolve_markdown` (the plain-markdown
  medium): `res:` links become their verified URLs, never `res:` hrefs.

## What this repo is not (yet)

No auth, no multi-tenant serving (single tenant per app instance, resolved
at startup), no background job queue (factory runs are CLI-invoked; the
queue arrives with multi-tenancy). Later phases per platform-design.md §9.
