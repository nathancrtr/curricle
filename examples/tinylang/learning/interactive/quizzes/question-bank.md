# tinylang — Question Bank

Pool for live quizzing ("quiz me on Phase 1"). A mix of recall, application and
explain-why, tagged `N.M (R|A|W)` — N the unit, M the item within it; the
*explain-why* answers reveal understanding best, so prefer them. Each entry
carries the answer plus a note for what to do with a wrong one — the note is
the point, because a bank that only marks is a bank that teaches nothing.

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

## Unit 1 — Characters to tokens

**1.1 (W)** Why is `1+2` three tokens rather than one?
**Answer:** Because a number ends at the first character that cannot extend it. Finding that boundary requires looking ahead one character before consuming it; a scanner that consumes greedily without checking produces one NUMBER.
**Note:** if they say "because of the spaces," that is the misconception — there are none. Have them run the case.

**1.2 (W)** Why must `<=` be a single token?
**Answer:** Maximal munch: at each position take the longest match. Two tokens would leave the parser trying to read a comparison followed by an assignment.
**Note:** if they propose that the parser recombine them, ask what the parser would have to know about characters — the answer reveals the layering violation.

**1.3 (W)** Why are keywords recognised *after* an identifier is scanned rather than during?
**Answer:** Because keywords are identifiers that happen to be reserved. Scan the whole word, then ask whether the finished word is in the keyword set. Matching by prefix classifies `lettuce` as `let` + `tuce`.
**Note:** if they suggest sorting the keyword list longest-first, offer `letter` — ordering does not fix a boundary problem.

**1.4 (R)** What does the lexer guarantee to the parser?
**Answer:** A flat list of classified lexemes with positions — no whitespace, no comments, no nesting.
**Note:** the word to listen for is *flat*. Nesting is precisely what the parser is for, and hearing that distinction is the unit landing.

**1.5 (A)** Your lexer handles `# comment` by skipping to the end of the line. A test feeds it `# note\nlet x = 1` and every token comes back with `line` 1. What did you miss?
**Answer:** Skipping the comment consumed the newline without counting it. Whitespace and comments are discarded, but the position bookkeeping they carry is not — it is the other half of what the lexer owes the parser, and the only reason a syntax error can name a line.
**Note:** if they say the line number does not matter yet, point at Unit 2's milestone: "a syntax error names the line and the offending token" is unachievable from here if this is wrong, and it will look like a parser bug.

## Unit 2 — Tokens to a tree

**2.1 (R)** What does a binding power encode that a precedence number alone does not?
**Answer:** Associativity. A left and a right power per operator: recurse with the operator's own power for left associativity, with slightly less for right. One asymmetry, both behaviours.
**Note:** if they only say "precedence," ask how they would make `^` right-associative — the answer is where the second number earns its place.

**2.2 (W)** Why do the textbook grammar and the implementable grammar often differ?
**Answer:** Left recursion. `expr → expr "+" term` is the natural way to state left associativity and it sends a recursive-descent parser into infinite regress, because the first thing it does is call itself with no input consumed.
**Note:** have them trace two steps by hand. The hang is obvious once traced and mysterious until then.

**2.3 (A)** Your parser accepts `1 + + 2`. Where is the bug?
**Answer:** In the prefix position — something is treating `+` as a legitimate start of an expression. After the infix `+` is consumed, the parser asks for an operand and should find no prefix handler for `+`.
**Note:** if they go looking in the binding-power table, redirect: no number in that table makes `+ 2` a well-formed operand.

**2.4 (W)** Why print the AST as `(+ 1 (* 2 3))` rather than as the source text?
**Answer:** Because it makes grouping visible. A tree that prints back as what you typed can hide a wrong shape indefinitely.
**Note:** worth connecting to their own debugging habits — this is the same instinct as logging a parsed structure rather than the raw request.

**2.5 (A)** Add `^` to your table: tighter than `*`, and right-associative. Give the two binding powers relative to `*` at (5, 6), and say how the printed tree tells you if you got associativity backwards.
**Answer:** Something like (8, 7): the left power above `*`'s so `2 * 3 ^ 2` groups as `(* 2 (^ 3 2))`, and the right power *below* its own left so a second `^` at equal precedence is captured by the recursion rather than ending it. `2 ^ 3 ^ 2` prints `(^ 2 (^ 3 2))` when right, `(^ (^ 2 3) 2)` when backwards.
**Note:** the exact numbers do not matter and the asymmetry does — if they give equal powers, have them run `2 ^ 3 ^ 2` and read the tree. This is 2.1 made concrete and 2.4 earning its keep.

## Unit 3 — Walking the tree

**3.1 (W)** Why is an environment a chain of scopes rather than one flat dictionary?
**Answer:** Because shadowing and scope exit both need the inner scope to be *separable*. A flat map cannot restore an outer binding that an inner one overwrote.
**Note:** the three-line shadowing program from the unit's exercise is the fastest way to make this concrete.

**3.2 (W)** Why do runtime errors and syntax errors need different reporting paths?
**Answer:** They are known at different times and have different context. A syntax error has a token and a position and no program state; a runtime error has state and a call chain but the program was well-formed. Collapsing them produces messages that are wrong about one case or the other.
**Note:** connect to the distinction between a request that failed to parse and one that parsed and then failed.

**3.3 (R)** Truthiness — is that a discovery or a decision?
**Answer:** A decision. Whether `0` or `""` is falsy is a choice the language designer makes, and reasonable languages disagree.
**Note:** this is often the first moment a learner feels like a language *designer* rather than an implementer. Let that land.

**3.4 (A)** The three-line shadowing program should print `1`, `2`, `1`. Yours prints `1`, `2`, `2`. Which line of your `Environment` is wrong?
**Answer:** The one that leaves the inner scope. Either the inner binding was written into the outer environment instead of a fresh child, or the child was never discarded on exit — both make the outer `x` unrecoverable, which is precisely what a chain exists to prevent.
**Note:** have them print the chain's depth at each of the three lines. A depth that never goes back down is the bug in one line of output.

**3.5 (A)** `let x = y + 1` with no `y` bound gives them `KeyError: 'y'` and a traceback. What should happen instead, and where does the fix go?
**Answer:** A runtime error naming `y` and the line, caught by the REPL so the session survives. The fix belongs in the environment's lookup, not in the binary-operation case — the failure is a failed lookup, and putting it in the operator would leave every other reader of a name still crashing.
**Note:** "where does the fix go" is the half worth pressing on. A learner who patches the call site has fixed one program; a learner who patches the lookup has fixed the language.

## Unit 4 — Functions and closures

**4.1 (R)** What is a closure, in one sentence?
**Answer:** A function together with the environment it was defined in.
**Note:** if the sentence includes the word "later" or "remembers," that is fine but push for the structural version — the pair is what the implementation actually stores.

**4.2 (W)** Two counters from the same factory share state. What went wrong?
**Answer:** The function value captured the wrong environment — most likely the environment at *call* time rather than at *definition* time, or one shared environment rather than a fresh one per call.
**Note:** this is dynamic scope reintroduced by accident, which is a good moment to ask why dynamic scope is easier to implement and almost always wrong.

**4.3 (W)** Why implement `return` by raising and catching an exception?
**Answer:** Because a return has to unwind an arbitrary depth of evaluator recursion, and exceptions are exactly the mechanism for non-local exit. It is a legitimate technique, not a hack.
**Note:** if they are uneasy, ask how they would do it otherwise — threading a return flag through every eval call is the alternative, and stating it is usually enough.

**4.4 (W)** Recursion works as soon as functions can see their own name. Why does that fall out for free?
**Answer:** Because the name is bound in the environment the function captures, so the body's lookup finds it. Nothing recursion-specific is implemented.
**Note:** a satisfying moment — worth pausing on rather than moving straight to the capstone.

**4.5 (A)** Write the smallest tinylang program that proves your functions capture at definition time rather than at call time, and say what it would print under dynamic scope.
**Answer:** Bind a name, define a function that reads it, then call that function from inside a scope that rebinds the same name — four lines. Lexical scope prints the outer value, because the function captured the environment it was defined in; dynamic scope prints the inner one, because it would look the name up in whatever environment happened to be live at the call.
**Note:** the two-line difference in output is the whole of the closure decision, which is why this is the test to write before the counter and not after. If their program has the rebinding in the same scope as the definition, it cannot tell the two apart — that is the thing to catch.
