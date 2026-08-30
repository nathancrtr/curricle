## Phase 0 — Orientation

**Q:** Name the three stages of a tree-walking interpreter and what each hands to the next.
**A:** Lexer: characters → tokens. Parser: tokens → syntax tree. Evaluator: tree → values. Each stage's output is the next one's only input, which is what makes them separately testable.
*Teaching note:* if they can name the stages but not the handoffs, that is the gap — ask what the parser would do if the lexer handed it raw characters.

**Q (explain-why):** A tree-walking interpreter is slow. Why start here rather than with a bytecode VM?
**A:** Because the tree *is* the program's structure, so the evaluator reads as a direct statement of what each construct means. A VM adds a compilation step and an instruction set between you and that meaning — worth it for speed, not for learning what the semantics are.
*Teaching note:* engineer's framing — this is the interpreted-vs-compiled trade in miniature, and the reasons are the familiar ones.
