# Unit 2 starter — the Pratt parser

A stub and a failing test suite. Your job is `parse()` and `sexpr()` in
`pratt.py`; everything else in this directory is given.

```
python -m unittest discover learning/interactive/exercises/unit-02-starter
```

Fifteen tests, all red. They stay red until precedence, associativity, and
error reporting are all right — and they go green in roughly that order, so the
suite doubles as a worklist.

## What is given

`tokenize()` is written for you. This exercise is about parsing, and debugging
someone else's lexer bug while learning Pratt parsing is one thing too many. It
is deliberately close to what your own Unit 1 lexer produces, so when the tests
pass you can delete it and point `parse()` at
[`tinylang/lexer.py`](../../../../tinylang/lexer.py) instead — which is the
last line of the unit's exercise.

## What you write

**`parse(tokens)`** returns a tree. The node shape is yours; nothing in the
tests inspects it directly.

**`sexpr(node)`** renders that tree as parenthesised prefix notation — `1 + 2 *
3` becomes `(+ 1 (* 2 3))`. This is what the tests assert against, and it is
the reason the exercise can leave your node design entirely free.

## The technique

Give every infix operator a binding power. Parse a prefix token, then loop:
while the next operator binds more tightly than the power you were called with,
consume it and recurse for its right-hand side.

Associativity is the asymmetry in that recursion. Recurse with the operator's
own power and you get left associativity (`1 - 2 - 3` groups as `(- (- 1 2)
3)`); recurse with slightly less and you get right (`2 ^ 3 ^ 4` groups as `(^ 2
(^ 3 4))`). One line, both behaviours — which is the whole argument for doing it
this way rather than as a cascade of functions.

## If you are stuck

The tests are ordered from easiest to hardest, so work top to bottom and run
the suite constantly. The two that catch nearly everyone:

* `test_left_associative_subtraction` — passing if you recursed with the wrong
  power, and invisible in any expression that only uses `+` and `*`.
* `test_unary_minus_binds_tighter_than_multiplication` — prefix operators need
  their own binding power, separate from the infix table.

If the shape of the loop itself is not landing, reread the Pratt article; it is
short, and it is short on purpose.
