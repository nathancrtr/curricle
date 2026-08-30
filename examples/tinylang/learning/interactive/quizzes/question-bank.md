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
