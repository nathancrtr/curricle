# House exemplars

The factory's reference voice for a course that has no earlier materials of its
own: one lesson, one widget, one exercise, the checkpoint quiz shell and a bank
section, shown to the roles when the course-native lookup comes up empty.

Curated from `examples/tinylang/learning/interactive/` — the lesson, widget and
exercise verbatim, `bank-section.md` its bank's first `##` section, and
`quiz-shell.html` its checkpoint with the quiz data renamed into the dialect
`validate_quiz` emits (`QUIZ_DATA` / `options` / `text` / `correct`);
`tests/test_factory.py` recomputes all of that and fails on drift.

Changes belong upstream in `examples/tinylang` first — that course is the
reference instance, and editing a copy here would fork it.
