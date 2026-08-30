# tinylang: Learning resources

**Tier 1** is the core path, worked through in curriculum order. **Tier 2** is a
second voice on the same material, for when one explanation doesn't land.
**Tier 3** is reference — looked up in, not read. Every entry says *why this
one*, because a reading list without that is just a search result.

The core path is free. The single paid entry is optional and labelled as such.

---

## Tier 1 — Core path

### Crafting Interpreters
*Robert Nystrom · Genever Benning · 2021 · free online*
→ <https://craftinginterpreters.com/>

The spine of this course, and the rare technical book that is both complete and
enjoyable. It builds two full interpreters — a tree-walker and a bytecode VM —
with every line of code on the page and every design decision argued rather
than asserted. The whole of Phases 0–2 hangs off its first half.

**Access:** free in full online; the print and ebook editions are the same text
if you prefer paper.

**Read it as:** Unit 0 wants "A Map of the Territory" only, and only as a skim.
Units 1–4 each take the corresponding chapter properly.

### "Pratt Parsers: Expression Parsing Made Easy"
*Robert Nystrom · journal.stuffwithstuff.com · 2011 · free*
→ <https://journal.stuffwithstuff.com/2011/03/19/pratt-parsers-expression-parsing-made-easy/>

Unit 2's technique, in one sitting. Recursive descent handles precedence with a
cascade of near-identical functions; Pratt parsing replaces the cascade with a
table of binding powers that you extend by adding a row.

**Read it as:** *after* the recursive-descent chapter, not before. The argument
is that it removes a repetition, and that doesn't land until you have felt the
repetition.

---

## Tier 2 — Depth on demand

### Writing an Interpreter in Go
*Thorsten Ball · 2018 · paid, ~$35 with its sequel*
→ <https://interpreterbook.com/>

The same journey in a different voice and a different language, at a gentler
slope. Useful precisely when the primary source doesn't land: hearing the
second explanation of an environment chain is often what makes the first one
make sense.

**Access:** paid, and genuinely optional — nothing in the curriculum depends on
it. Skip it unless a Tier 1 explanation has failed you.

---

## Tier 3 — Reference

### Python: the `tokenize` module
*Python documentation · free*
→ <https://docs.python.org/3/library/tokenize.html>

A production lexer you can run against your own files (`python -m tokenize
file.py`) and compare with yours. Its token kinds are a checklist of the cases
a real language has to handle and a toy one gets to skip.

### Python: the `ast` module
*Python documentation · free*
→ <https://docs.python.org/3/library/ast.html>

A real syntax tree to compare your node design against.
`ast.dump(ast.parse("1 + 2 * 3"))` in the REPL is the fastest way to see how a
grown-up language shapes the same tree you are building in Unit 2.

---

## Reading order

1. Crafting Interpreters, chapter by chapter alongside Units 0–4 (the spine)
2. Pratt's binding-power article, once Unit 2's precedence cascade starts to itch
3. Python's `tokenize` and `ast` docs, as reference, from Unit 1 onward
4. *Writing an Interpreter in Go*, optionally, as a second pass in another voice

---

*Resources v1.0 — 2026-08-30. Every entry verified reachable at that date.*
