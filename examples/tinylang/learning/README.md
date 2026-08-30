# tinylang — the learning track

Build a small interpreted language, end to end, and understand every stage of
the pipeline that runs it. Four units, two phases, about eight weeks at four
hours a week.

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

- `lessons/` — Socratic guides, written for Claude rather than for you. Ask
  *"teach me Unit 1 interactively"* and the lesson runs.
- `widgets/` — things to poke at. Open them directly in a browser or reach
  them from the unit page.
- `exercises/` — stubs with failing tests. Green is the milestone.
- `quizzes/` — checkpoint quizzes that explain every option, right or wrong.
  Answers reported to the progress ledger become proposed profile evidence,
  misses included.

## Running it under curricle

From the curricle checkout:

```bash
# Static pages — no database, opens in a browser
python -m curricle hub examples/tinylang --out /tmp/tinylang/index.html

# Or the served app, with progress folded from Postgres
python -m curricle serve --course examples/tinylang --tenant example --port 8765
```

The curriculum reads perfectly well as plain markdown, too. The app adds
progress tracking, the reader, and the derived Interactive rows.
