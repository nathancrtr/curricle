# tinylang: Curriculum

Learn how interpreters work **by building tinylang** — a small dynamically-typed language with functions, closures, and a REPL — from raw characters through to a running program. For an experienced engineer at ~4 hrs/week; roughly 8 weeks, in phases that each stand alone.

This is the example course that ships with curricle. It is deliberately small — an orientation phase and two working phases, four numbered units — but it is a real course, not a fixture: it exercises every part of the manifest schema (tracks, milestones, materials, graders, all four reference schemes) and it compiles clean. Copy this directory and start editing when you want a course of your own.

---

## How this curriculum works

**The interpreter is the spine.** Every unit adds one stage to a pipeline that already runs end to end. By the end of Unit 1 you can turn source text into tokens; by the end of Unit 4 you can define a closure and call it. Nothing is scaffolding that gets thrown away.

**Each unit has:** Build (the implementation step) · Read (precise sources — see `learning-resources.md` for every citation) · Concepts · Exercise · Milestone, and sometimes a Key insight. The Interactive row is not written here — it is derived from the material registry in `course.yaml`, so a widget or a lesson appears on the unit page as soon as it is registered.

**Pacing.** One unit ≈ two weeks at four hours. Unit 2 (parsing) is the long one; Unit 3 is the one that suddenly feels like magic. Phases end with checkpoints; if a checkpoint feels shaky, camp there.

**Tests are your grader.** From Unit 1 onward you keep a test suite. The house style: test the shapes and the invariants rather than exact strings, so a change to error formatting doesn't turn twenty tests red at once.

**Working with your assistant.** *"Teach me Unit 2 interactively"* runs the Socratic lesson guide; *"quiz me on Phase 1"* draws from the checkpoint quiz.

---

## Phase 0 — Orientation (Week 0)

**Goal:** Understand the shape of the pipeline before building any of it, and get a project skeleton that runs its own tests.

- **Build:** Create the project skeleton — a `tinylang/` package, a `tests/` directory, and a single failing test. Wire up whatever runs your tests with one command. Then write `tinylang/repl.py`: read a line, echo it back, loop. It does nothing useful yet, and that is the point — you will replace its middle, once per phase, and watch the language grow.
- **Read:** [Crafting Interpreters](res:crafting), "A Map of the Territory" — the one chapter that shows the whole landscape at once. Skim, don't study: you want the vocabulary (scanning, parsing, evaluating) and the sense that these are separable stages.
- **Concepts:** why interpretation splits into stages at all; what a tree-walking interpreter is and what it gives up (speed) for what it buys (you can hold it in your head); source text → tokens → syntax tree → value as the through-line of the whole course.
- **Theory track:** start the ladder. What a *regular language* is, and the one-sentence version of why it is the right level of power for a lexer: no counting, no nesting, no memory beyond the current state.
- **Milestone:** `python -m tinylang.repl` starts, echoes, and exits cleanly on Ctrl-D; one test runs and passes.

> **Check yourself:** A lexer and a parser both "read the input and produce structure." Why are they two stages instead of one?
>
> <details><summary>Answer</summary>
>
> Because they answer questions at different scales, and merging them means answering both at once in one grammar. The lexer works over characters and asks *what is this piece* — this run of digits is one number, this quote starts a string, this whitespace is nothing. The parser works over tokens and asks *how do these pieces relate* — this expression is the left operand of that operator. Splitting them means the parser never thinks about whitespace and the lexer never thinks about precedence. Unit 2 is where you feel the payoff.
> </details>

### — Phase 0 Checkpoint —
Something runs, even if it only echoes. You can name the three stages of the pipeline and say what each one hands to the next. **Theory by now:** you have met the phrase "regular language" and can say, roughly, what it rules out. Nothing here is deep yet — the point of Phase 0 is to have a place to put Unit 1.

---

## Phase 1 — The front end (Weeks 1–4)

**Goal:** Turn source text into a syntax tree you can print, test, and trust. By the end of this phase nothing evaluates yet, but everything parses.

### Unit 1 — Characters to tokens
- **Build:** A hand-written lexer in `tinylang/lexer.py`. Scan a source string into a list of `Token(kind, text, line)`: numbers, strings, identifiers, keywords, operators, and a final `EOF`. Handle whitespace and `#` comments by skipping them. Report an unterminated string as an error that names the line, not as a crash.
- **Read:** [this unit's chapter](mat:chapter-u1) first. Then [Crafting Interpreters](res:crafting), the "Scanning" chapter, all of it — it is the closest thing to a canonical treatment. Then look at [Python's `tokenize` module](res:tokenize) output for a small Python file (`python -m tokenize somefile.py`) to see what a production lexer emits and how much more of it there is than you expected.
- **Concepts:** lexeme vs. token vs. token kind; maximal munch, and why `<=` must be one token rather than two; why keywords are recognised *after* identifiers rather than during; the lookahead question — how far ahead must you peek, and why one character is almost always enough.
- **Theory track:** finish regular languages. Write the regular expression your number scanner is really implementing, then find the thing it cannot express — balanced parentheses — and notice that this is exactly the job you hand to the parser in [Unit 2](unit:u2).
- **Exercise:** Extend your lexer with a `--tokens` flag on the REPL that prints the token stream instead of evaluating. You will use it for debugging in every remaining unit, so make the output readable.
- **Milestone:** `lex()` with tests over a fixture of tricky inputs — an empty string, a string containing a `#`, a number touching an operator (`1+2`), an unterminated string.
- **Key insight:** A lexer is a state machine you happen to be writing as a loop with a `switch`. You have written this shape before, without the name — every protocol parser and every log-line splitter is the same animal. What the name buys you is the literature: once you call it a lexer, decades of accumulated technique become searchable.

### Unit 2 — Tokens to a tree
- **Build:** A recursive-descent parser in `tinylang/parser.py` producing an AST: literals, unary and binary operations, grouping, and variable references. Implement precedence with Pratt parsing (a binding-power table) rather than one function per precedence level — it is fewer lines and it extends without restructuring. Add a `__repr__` on your nodes that prints the tree as parenthesised prefix notation, so `1 + 2 * 3` prints as `(+ 1 (* 2 3))` and a wrong precedence is visible at a glance.
- **Read:** [Crafting Interpreters](res:crafting), the "Parsing Expressions" chapter for the recursive-descent frame, then [Pratt Parsers: Expression Parsing Made Easy](res:pratt) for the binding-power technique that replaces its precedence cascade. Read them in that order — the second is an optimisation of the first, and it doesn't land until you have felt the repetition it removes. [The Go interpreter book](res:interpreterbook) covers the same ground at book length if you want a second pass in another voice.
- **Concepts:** grammars as a specification vs. code as an implementation; left- and right-associativity as a *choice*, expressed as a one-line asymmetry in binding power; why `1 + + 2` must be a syntax error and where in your code that decision lives; error recovery — synchronising to the next statement boundary so one mistake doesn't cascade into fifty.
- **Theory track:** context-free grammars. Write tinylang's expression grammar in BNF, then write the same grammar left-recursively and watch it hang your parser — the reason the textbook grammar and the implementable grammar differ is worth an hour.
- **Exercise:** [The Unit 2 starter](mat:ex-u2) — a stub with failing tests over a fixture of expressions and their expected parenthesised forms. Make them pass, then point the same parser at the tokens coming out of [your lexer](repo:tinylang/lexer.py).
- **Milestone:** Green tests; `1 + 2 * 3` and `(1 + 2) * 3` produce visibly different trees; a syntax error names the line and the offending token.

### — Phase 1 Checkpoint —
You can turn source text into a syntax tree and print it. You can explain, without hedging, why lexing and parsing are separate stages, and you can add a new binary operator at the right precedence in under five minutes. **Theory by now:** regular languages and context-free grammars are distinct in your head, and you can say which of your two stages needs which — and why that is a statement about power, not about style. A good sign that this has landed: you find yourself annoyed that the tree doesn't *do* anything yet. That is Phase 2.

---

## Phase 2 — Making it run (Weeks 5–8)

**Goal:** Walk the tree and produce values. By the end of this phase tinylang is a language you can write small programs in.

### Unit 3 — Walking the tree
- **Build:** A tree-walking evaluator in `tinylang/interp.py`. Evaluate literals, arithmetic, comparison, and truthiness; add `let` bindings backed by an `Environment` that maps names to values. Wire it into the REPL so a typed expression prints its value. Delete the echo from Unit 0 — you have earned it.
- **Read:** [Crafting Interpreters](res:crafting), the "Evaluating Expressions" and "Statements and State" chapters. Read the environment section twice: the chaining it introduces is what [Unit 4](unit:u4) turns into closures, and a fuzzy understanding here becomes a real bug there.
- **Concepts:** the visitor pattern, and why a dispatch table or `match` is the same idea with less ceremony in Python; environments as a linked list of scopes rather than one flat dictionary; runtime errors vs. syntax errors, and why the two need different reporting paths; truthiness as a *language design decision* you are making, not a fact you are discovering.
- **Theory track:** semantics. Write down, in English precise enough to argue with, what your evaluator computes for a binary expression. You have just written a small-step operational semantics; the notation comes later, and it will look familiar when it does.
- **Exercise:** Add a `print` statement and string concatenation. Then find the smallest program that reveals whether your `Environment` chains correctly — a variable shadowed in an inner scope and read again in the outer one, in three lines.
- **Milestone:** The REPL evaluates arithmetic, comparisons, and `let` bindings across lines; an undefined variable produces a clean error naming the variable rather than a `KeyError` traceback.
- **Key insight:** The evaluator is smaller than the parser, and that surprises everybody. Nearly all the difficulty in a language front end is in deciding *what the program says*; once that is a tree, saying what it *means* is mostly recursion.

### Unit 4 — Functions and closures
- **Build:** Function declarations, calls, and returns. Represent a function as a value that carries its own defining environment — that captured environment is the whole trick. Implement `return` by raising and catching a control-flow exception, then write a comment explaining why that is a legitimate technique rather than a hack. Verify the classic counter: a function that returns a function that increments a captured variable.
- **Read:** [Crafting Interpreters](res:crafting), the "Functions" and "Closures" chapters. If you have time for only one, take "Closures" slowly — it is the conceptual summit of this course.
- **Concepts:** call frames and the environment stack; closures as "a function plus the environment it was born in"; why dynamic scope is easier to implement and almost always wrong; recursion falling out for free once functions can see their own name; the beginnings of tail calls, and why you are not doing them today.
- **Theory track:** close the ladder. State what a closure *is* semantically — a pair of a function body and an environment — and convince yourself that this one sentence explains both the counter exercise and every scoping bug you have ever shipped.
- **Exercise:** Write `make_counter` in tinylang itself and show that two counters made from the same factory are independent. If they share state, your closure is capturing the wrong environment — the failure is exactly the one [Unit 3](unit:u3) warned about.
- **Milestone:** **Capstone.** A recursive `fib` and an independent-counters program both run under `python -m tinylang.repl < program.tl`. Write a paragraph on what your language cannot do — no classes, no modules, no error handling — and pick which one you would build next.

### — Phase 2 Checkpoint —
tinylang runs. You have written a lexer, a parser, and an evaluator, and you can explain what each stage is responsible for and how a change in one propagates through the others. **Theory by now:** you can state what your evaluator computes precisely enough that someone could disagree with it, which is the whole point of writing a semantics down. A good sign that this has landed: the next language you read the source of feels navigable, because you now know which file to open first.

---

*Curriculum v1.0 — 2026-08-30: initial version, written as curricle's shipped example course.*
