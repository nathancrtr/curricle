# Unit 1 — Characters to tokens

*What a lexer is for, why `<=` is one token and `1+2` is three, and how far ahead a scanner ever needs to look.*

> [!NOTE] Before you start
> Phase 0 done: the project skeleton runs its own (empty) tests. Have `tinylang/lexer.py` open. Twenty minutes to read; the Build takes the rest of the week.

## What you will be able to do

- Say what a lexeme, a token, and a token kind are, and which of the three the parser sees.
- Explain maximal munch and give the case that breaks a lexer without it.
- Write a scanner loop with one character of lookahead and know why one is enough here.

## 1. Start with the text

Here are two lines of tinylang and what the lexer should hand the parser.

```
let x = 1+2   # a comment
let y = "hi"
```

| lexeme | kind | line |
|---|---|---|
| `let` | KEYWORD | 1 |
| `x` | IDENT | 1 |
| `=` | OP | 1 |
| `1` | NUMBER | 1 |
| `+` | OP | 1 |
| `2` | NUMBER | 1 |
| `let` | KEYWORD | 2 |
| `y` | IDENT | 2 |
| `=` | OP | 2 |
| `"hi"` | STRING | 2 |
| | EOF | 2 |

The comment vanished; so did every space. The parser never sees either. A **lexeme** is the slice of source text (`let`); a **token** is the lexeme plus its classification and position; the **kind** is the classification alone, and it is the kind the parser dispatches on.[^crafting-scanning]

## 2. Maximal munch

Given `<=`, a lexer could emit `<` then `=`. Every real lexer instead takes the longest lexeme that matches at the current position — the rule Nystrom calls maximal munch.[^crafting-scanning] The consequence for you: check two-character operators before one-character ones, or `<=` becomes two tokens and `a <= b` parses as `a < (= b)`, which is nonsense the parser will report a long way from the actual bug.

<details>
<summary>Check yourself: why are keywords recognised after identifiers, not before?</summary>

Because `letter` starts with `let`. Scan the whole identifier first, then ask whether that identifier is a keyword. Recognising keywords by prefix would break every identifier that happens to begin with one.

</details>

## 3. How far ahead to look

The scanner in this course peeks at most one character beyond the current one. That is enough because every tinylang token is decided by its first character plus at most one more (`<` vs `<=`, `!` vs `!=`, `/` vs a comment marker). Python's production tokenizer works the same way for operators; run `python -m tokenize` on any file and look at how much it emits that you never think about — `NEWLINE`, `INDENT`, `NL`.[^py-tokenize]

> [!TIP]
> An unterminated string is an error that names its line. It is not an exception that escapes the lexer.

## What this sets up

The token list is the input to [Unit 2](unit:u2)'s parser. Nothing the parser does can recover from a lexer that merged or split a token, which is why the Unit 1 tests check shapes and kinds rather than exact strings.

## How this chapter was checked

| Claim | Checked against | Result |
|---|---|---|
| Lexeme / token / kind vocabulary; maximal munch | Crafting Interpreters, "Scanning" chapter, online text | verified |
| `python -m tokenize` output includes NEWLINE, INDENT, NL | Python docs, `tokenize` module | verified |

## Sources

[^crafting-scanning]: Robert Nystrom, [Crafting Interpreters](res:crafting), chapter "Scanning" (online edition).
[^py-tokenize]: [Python's `tokenize` module](res:tokenize) documentation, "Command-line usage".
