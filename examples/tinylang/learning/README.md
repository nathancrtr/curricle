# tinylang — the learning track

Build a small interpreted language, end to end, and understand every stage of
the pipeline that runs it. An orientation phase and two working phases, four
numbered units, about eight weeks at four hours a week.

## The documents

- **[`curriculum.md`](curriculum.md)** — the course itself: phases, units, and
  what to build, read, and prove at each step. Start here.
- **[`learning-resources.md`](learning-resources.md)** — every source the
  curriculum cites, tiered by role, each with a note on why *this* one.
- **`course.yaml`** — the sidecar. Ids, glosses, the material registry, the
  track ladder, resource keys: what the markdown legitimately doesn't carry.
  You read this only when editing the course, never when taking it.

## Working the course

Everything under `interactive/` is registered in `course.yaml` and shows up on
the unit pages automatically:

- `lessons/` — Socratic guides, written for your tutor — the assistant the
  course is exported to — rather than for you. Ask *"teach me Unit 1
  interactively"* and the lesson runs.
- `widgets/` — things to poke at. Reach them from the unit page, or open them
  in a browser: they are styled by the `theme.css` a static render puts beside
  the course, or by the app when it is served, and work unstyled without
  either.
- `exercises/` — stubs with failing tests. Green is the milestone.
- `quizzes/` — checkpoint quizzes that explain every option, right or wrong.
  Answers reported to the progress ledger become proposed profile evidence,
  misses included.

## Running it under curricle

From the curricle checkout:

```bash
# Static pages — no database. They land beside the course because their links
# are relative to it, and theme.css is what styles the widget and the quiz
# with no server to hand it out. All four are gitignored.
python -m curricle hub        examples/tinylang --out examples/tinylang/learning/index.html
python -m curricle curriculum examples/tinylang --out examples/tinylang/learning/curriculum.html
python -m curricle resources  examples/tinylang --out examples/tinylang/learning/learning-resources.html
python -m curricle theme                        --out examples/tinylang/learning/theme.css
# then open examples/tinylang/learning/index.html in a browser

# Or the served app, with progress folded from Postgres
python -m curricle serve --course examples/tinylang --tenant example --port 8765
```

The curriculum reads perfectly well as plain markdown, too. The app adds
progress tracking, the reader, and the derived Interactive rows.
