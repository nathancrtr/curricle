# tinylang

A small dynamically-typed language with functions, closures, and a REPL —
built from scratch over eight weeks.

This is a **course repository**, and it is curricle's shipped example: the
thing a course looks like from the outside. The interesting content is under
[`learning/`](learning/README.md); the `tinylang/` package is seeded with
almost nothing on purpose, because writing it is the course.

```
tinylang/                 the language you are building (seeded: the token shape)
learning/
  curriculum.md           the course: phases, units, what to build and read
  learning-resources.md   every source, tiered, each with a "why this one"
  course.yaml             the sidecar — ids, glosses, materials, tracks
  interactive/
    lessons/              Socratic guides, written for Claude
    widgets/              things to poke at
    exercises/            stubs with failing tests
    quizzes/              checkpoint quizzes that explain themselves
```

## As a course to take

Read [`learning/curriculum.md`](learning/curriculum.md) and start at Phase 0.
It works as plain markdown. Under curricle it also gets progress tracking,
rendered unit pages, and the interactive materials attached to the units that
own them:

```bash
python -m curricle hub        examples/tinylang --out examples/tinylang/learning/index.html
python -m curricle curriculum examples/tinylang --out examples/tinylang/learning/curriculum.html
python -m curricle resources  examples/tinylang --out examples/tinylang/learning/learning-resources.html
python -m curricle theme                        --out examples/tinylang/learning/theme.css
# then open examples/tinylang/learning/index.html in a browser
```

The pages are rendered beside the course because their links are relative to
it, and `theme.css` is what styles the widget and the quiz when there is no
server to hand it out. All four are gitignored.

## As a template to copy

This course exists to be edited. It is small — an orientation phase and two
working phases, four numbered units — but it exercises every part of the
manifest schema: a parallel track with its own ladder, a milestone that is not
a unit, all four material kinds, a grader, both tiered and grouped resources,
and all four reference schemes (`res:`, `unit:`, `mat:`, `repo:`) in the
curriculum prose.

```bash
cp -r examples/tinylang ../my-course
python -m curricle compile ../my-course --out build/my-course.manifest.yaml
```

The compiler refuses rather than guesses, so edit until it stops complaining:
every error names a place you can act on. Start by changing `course.id` and the
phase headers, and work outward from there.
