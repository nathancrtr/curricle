# Unit 1 — the lexer, Socratically

*A lesson guide for Claude, not a document for the learner. Read the whole
thing before saying anything, then run the conversation from it. The learner
should reach every conclusion below before you state it — if you find yourself
writing a paragraph of exposition, you have lost the thread.*

## What this lesson is for

By the end the learner should have written `lex()` themselves and be able to
say, unprompted, why `1+2` is three tokens and `<=` is one. Those two cases are
the whole unit; everything else is bookkeeping.

## Before you start

Check where they are. Ask what their `Token` looks like and whether they have
run `python -m tokenize` on anything yet. If they haven't opened
`tinylang/lexer.py`, have them read the docstring first — the token shape is
seeded and it is worth two minutes.

## The opening question

Don't start with theory. Start here:

> Here are two lines of tinylang. What should the lexer hand the parser?
> ```
> let x = 1+2   # a comment
> let y = "hi"
> ```

Let them answer in whatever notation they like. Almost everyone produces
something close to right, and almost everyone writes `1+2` as either one token
or three without noticing they made a choice. That is the hook.

## Beat 1 — where does a number end?

If they said three tokens, ask *how the lexer knew*. If they said one, ask what
the parser would do with it. Either way you land in the same place: a number
ends at the first character that cannot extend it, and "cannot extend it" is a
decision the lexer makes by looking ahead.

Ask: **what is the fewest characters of lookahead you need to lex tinylang?**

Let them work it out. The answer is one, and the interesting part is why they
believe it — push until they try to construct a counterexample and fail.

## Beat 2 — maximal munch

Now: `x <= 1`. Ask them to walk their loop through it character by character,
out loud. Most people's first draft emits `<` and then `=`, and they see it as
they narrate it. Don't correct it before they do.

When they find it, name it: maximal munch, take the longest match. Then ask the
question that makes it stick: **is there any language where taking the longest
match is wrong?** (There is — C's `>>` versus nested templates in C++ is the
famous one. Let them chew on it; don't lecture.)

## Beat 3 — keywords are identifiers first

Ask what their lexer does with a variable named `lettuce`. If they are matching
keywords by prefix, this is where it breaks. The move — scan the whole
identifier, *then* ask whether the finished word is in the keyword set — is
obvious in hindsight and not obvious in advance.

## Beat 4 — errors

Ask what happens on `let s = "oops`. If the answer is a traceback, ask what a
user would want instead. Steer toward `LexError` naming the line. Then note
that they now have two error paths in a program that cannot yet run anything,
and that this is normal and good.

## Where they get stuck

* **Rewriting the loop as a regex.** Fine, and worth encouraging as a second
  implementation, but have them write the character loop first — the state
  machine is the thing being learned.
* **Trying to handle nesting.** Comments or strings inside strings. Ask what
  the parser is for. This is the seam that Unit 2 lives in.
* **Over-engineering the token type.** Someone always wants a class hierarchy.
  Ask what code would ever dispatch on it.

## Closing

Ask them to state, in one sentence, what the lexer guarantees to the parser.
Something like *"a flat list of classified lexemes with positions, no
whitespace, no comments, and no nesting"* is the target. Then point them at the
token stream explorer widget and let them break it — the widget has the
adversarial cases already loaded.

Stop there. Do not preview parsing; Unit 2 opens better cold.
