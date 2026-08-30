# tinylang — Question Bank

Pool for live quizzing ("quiz me on Phase 1"). A mix of recall, application,
and explain-why; the *explain-why* answers reveal understanding best, so prefer
them. Each entry carries the answer plus a teaching note for what to do with a
wrong one — the note is the point, because a bank that only marks is a bank
that teaches nothing.

## Phase 0 — Orientation

**Q:** Name the three stages of a tree-walking interpreter and what each hands to the next.
**A:** Lexer: characters → tokens. Parser: tokens → syntax tree. Evaluator: tree → values. Each stage's output is the next one's only input, which is what makes them separately testable.
*Teaching note:* if they can name the stages but not the handoffs, that is the gap — ask what the parser would do if the lexer handed it raw characters.

**Q (explain-why):** A tree-walking interpreter is slow. Why start here rather than with a bytecode VM?
**A:** Because the tree *is* the program's structure, so the evaluator reads as a direct statement of what each construct means. A VM adds a compilation step and an instruction set between you and that meaning — worth it for speed, not for learning what the semantics are.
*Teaching note:* engineer's framing — this is the interpreted-vs-compiled trade in miniature, and the reasons are the familiar ones.

## Unit 1 — Characters to tokens

**Q:** Why is `1+2` three tokens rather than one?
**A:** Because a number ends at the first character that cannot extend it. Finding that boundary requires looking ahead one character before consuming it; a scanner that consumes greedily without checking produces one NUMBER.
*Teaching note:* if they say "because of the spaces," that is the misconception — there are none. Have them run the case.

**Q:** Why must `<=` be a single token?
**A:** Maximal munch: at each position take the longest match. Two tokens would leave the parser trying to read a comparison followed by an assignment.
*Teaching note:* if they propose that the parser recombine them, ask what the parser would have to know about characters — the answer reveals the layering violation.

**Q (explain-why):** Why are keywords recognised *after* an identifier is scanned rather than during?
**A:** Because keywords are identifiers that happen to be reserved. Scan the whole word, then ask whether the finished word is in the keyword set. Matching by prefix classifies `lettuce` as `let` + `tuce`.
*Teaching note:* if they suggest sorting the keyword list longest-first, offer `letter` — ordering does not fix a boundary problem.

**Q:** What does the lexer guarantee to the parser?
**A:** A flat list of classified lexemes with positions — no whitespace, no comments, no nesting.
*Teaching note:* the word to listen for is *flat*. Nesting is precisely what the parser is for, and hearing that distinction is the unit landing.

## Unit 2 — Tokens to a tree

**Q:** What does a binding power encode that a precedence number alone does not?
**A:** Associativity. A left and a right power per operator: recurse with the operator's own power for left associativity, with slightly less for right. One asymmetry, both behaviours.
*Teaching note:* if they only say "precedence," ask how they would make `^` right-associative — the answer is where the second number earns its place.

**Q (explain-why):** Why do the textbook grammar and the implementable grammar often differ?
**A:** Left recursion. `expr → expr "+" term` is the natural way to state left associativity and it sends a recursive-descent parser into infinite regress, because the first thing it does is call itself with no input consumed.
*Teaching note:* have them trace two steps by hand. The hang is obvious once traced and mysterious until then.

**Q:** Your parser accepts `1 + + 2`. Where is the bug?
**A:** In the prefix position — something is treating `+` as a legitimate start of an expression. After the infix `+` is consumed, the parser asks for an operand and should find no prefix handler for `+`.
*Teaching note:* if they go looking in the binding-power table, redirect: no number in that table makes `+ 2` a well-formed operand.

**Q:** Why print the AST as `(+ 1 (* 2 3))` rather than as the source text?
**A:** Because it makes grouping visible. A tree that prints back as what you typed can hide a wrong shape indefinitely.
*Teaching note:* worth connecting to their own debugging habits — this is the same instinct as logging a parsed structure rather than the raw request.

## Unit 3 — Walking the tree

**Q:** Why is an environment a chain of scopes rather than one flat dictionary?
**A:** Because shadowing and scope exit both need the inner scope to be *separable*. A flat map cannot restore an outer binding that an inner one overwrote.
*Teaching note:* the three-line shadowing program from the unit's exercise is the fastest way to make this concrete.

**Q (explain-why):** Why do runtime errors and syntax errors need different reporting paths?
**A:** They are known at different times and have different context. A syntax error has a token and a position and no program state; a runtime error has state and a call chain but the program was well-formed. Collapsing them produces messages that are wrong about one case or the other.
*Teaching note:* connect to the distinction between a request that failed to parse and one that parsed and then failed.

**Q:** Truthiness — is that a discovery or a decision?
**A:** A decision. Whether `0` or `""` is falsy is a choice the language designer makes, and reasonable languages disagree.
*Teaching note:* this is often the first moment a learner feels like a language *designer* rather than an implementer. Let that land.

## Unit 4 — Functions and closures

**Q:** What is a closure, in one sentence?
**A:** A function together with the environment it was defined in.
*Teaching note:* if the sentence includes the word "later" or "remembers," that is fine but push for the structural version — the pair is what the implementation actually stores.

**Q (explain-why):** Two counters from the same factory share state. What went wrong?
**A:** The function value captured the wrong environment — most likely the environment at *call* time rather than at *definition* time, or one shared environment rather than a fresh one per call.
*Teaching note:* this is dynamic scope reintroduced by accident, which is a good moment to ask why dynamic scope is easier to implement and almost always wrong.

**Q:** Why implement `return` by raising and catching an exception?
**A:** Because a return has to unwind an arbitrary depth of evaluator recursion, and exceptions are exactly the mechanism for non-local exit. It is a legitimate technique, not a hack.
*Teaching note:* if they are uneasy, ask how they would do it otherwise — threading a return flag through every eval call is the alternative, and stating it is usually enough.

**Q (explain-why):** Recursion works as soon as functions can see their own name. Why does that fall out for free?
**A:** Because the name is bound in the environment the function captures, so the body's lookup finds it. Nothing recursion-specific is implemented.
*Teaching note:* a satisfying moment — worth pausing on rather than moving straight to the capstone.
