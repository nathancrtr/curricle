## Phase 0 — Orientation

**0.1 (R)** Name the three stages of a tree-walking interpreter and what each hands to the next.
**Answer:** Lexer: characters → tokens. Parser: tokens → syntax tree. Evaluator: tree → values. Each stage's output is the next one's only input, which is what makes them separately testable.
**Note:** if they can name the stages but not the handoffs, that is the gap — ask what the parser would do if the lexer handed it raw characters.

**0.2 (W)** A tree-walking interpreter is slow. Why start here rather than with a bytecode VM?
**Answer:** Because the tree *is* the program's structure, so the evaluator reads as a direct statement of what each construct means. A VM adds a compilation step and an instruction set between you and that meaning — worth it for speed, not for learning what the semantics are.
**Note:** engineer's framing — this is the interpreted-vs-compiled trade in miniature, and the reasons are the familiar ones.

**0.3 (A)** Someone else's interpreter rejects `print("hi")` with `unexpected character '"'`. Which stage wrote that message, and how do you know before opening any file?
**Answer:** The lexer. It is the only stage that sees characters at all — by the time the parser runs, that quote is either inside a STRING token or the lexer already failed. The word *character* in an error message names its author.
**Note:** the transferable habit is reading an error for which layer's vocabulary it speaks. If they guess the parser, ask what a parser would even call that quote.

**0.4 (A)** You want to add a `%` operator. Name every stage you must edit, in order, and what each edit is.
**Answer:** Lexer: recognise `%` as a token kind. Parser: give it a binding power so `1 + 2 % 3` groups correctly. Evaluator: compute it, and decide what it does to non-numbers. Three stages, three small local edits — which is the payoff the split was bought for.
**Note:** if they name only two, ask which one they skipped and what would happen: a missing lexer case is an "unexpected character", a missing binding power is a parse error, a missing eval case is a crash on a valid program.

**0.5 (A)** Walk `let x = 1 # two` through the pipeline: what does each stage hand on?
**Answer:** Lexer: `LET`, `IDENT(x)`, `EQUAL`, `NUMBER(1)`, `EOF` — the comment is gone, and gone this early. Parser: a let-binding node with the name `x` and a literal `1` under it. Evaluator: binds `x` to `1` in the environment and produces no value worth printing.
**Note:** the comment vanishing at stage one is the thing to notice — every later stage is *simpler* because of what the lexer threw away, and that is what "separable stages" buys in practice.

**0.6 (W)** Phase 0 builds a REPL that only echoes. Why build it before there is anything to run?
**Answer:** Because it is the harness every later unit lands in. Its middle gets replaced once per phase — echo, then tokens, then a tree, then a value — so each unit ends in something you can type at rather than in a green test suite you have to take on trust.
**Note:** the instinct to skip this is the same one that defers wiring up a deployment until the code is "ready". Worth naming, because the answer is the same in both cases.
