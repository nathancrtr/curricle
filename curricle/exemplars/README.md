# House exemplars

The factory's reference voice for a course that has no earlier materials of its
own: one lesson, one widget, one exercise, the checkpoint quiz shell and a bank
section, shown to the roles when the course-native lookup comes up empty.

Curated from `examples/tinylang/learning/interactive/` — the lesson, widget,
exercise and checkpoint verbatim, `bank-section.md` its bank's first `##`
section; `tests/test_factory.py` compares each against its source and fails on
drift. Nothing here is transformed on the way in: an exemplar that has to be
edited to meet the bar is a source that does not meet it, which is the whole
reason the shipped set is held to the factory's own validators.

Changes belong upstream in `examples/tinylang` first — that course is the
reference instance, and editing a copy here would fork it.
