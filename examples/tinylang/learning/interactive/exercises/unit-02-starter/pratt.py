"""Unit 2 starter — a Pratt parser for tinylang expressions.

`tokenize` is given. `parse` and `sexpr` are yours; the tests in
`test_pratt.py` assert on the rendered form, so the tree's node shape is
entirely your choice.
"""

from __future__ import annotations

from dataclasses import dataclass


class ParseError(Exception):
    """Raised on input that tokenises but does not form an expression."""


@dataclass(frozen=True)
class Token:
    kind: str      # NUMBER | IDENT | OP | LPAREN | RPAREN | EOF
    text: str
    pos: int       # 0-based character offset, for error messages


# --------------------------------------------------------------------------
# Given: a lexer, so that this exercise is only about parsing.
#
# Once the tests are green, delete this and feed `parse` the tokens from your
# own tinylang/lexer.py instead — that swap is the last step of the unit.
# --------------------------------------------------------------------------

# Longest first: the scan takes the first match, so this ordering is what
# implements maximal munch.
_OPS = ("==", "!=", "<=", ">=", "+", "-", "*", "/", "^", "<", ">")


def tokenize(src: str) -> list[Token]:
    toks: list[Token] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit():
            start = i
            while i < len(src) and src[i].isdigit():
                i += 1
            toks.append(Token("NUMBER", src[start:i], start))
            continue
        if c.isalpha() or c == "_":
            start = i
            while i < len(src) and (src[i].isalnum() or src[i] == "_"):
                i += 1
            toks.append(Token("IDENT", src[start:i], start))
            continue
        if c == "(":
            toks.append(Token("LPAREN", "(", i))
            i += 1
            continue
        if c == ")":
            toks.append(Token("RPAREN", ")", i))
            i += 1
            continue
        for op in _OPS:
            if src.startswith(op, i):
                toks.append(Token("OP", op, i))
                i += len(op)
                break
        else:
            raise ParseError(f"unexpected character {c!r} at {i}")
    toks.append(Token("EOF", "", len(src)))
    return toks


# --------------------------------------------------------------------------
# Yours.
# --------------------------------------------------------------------------

def parse(tokens: list[Token]):
    """Parse a token list into an expression tree.

    Precedence, loosest to tightest:

        ==  !=              comparison, left-associative
        <  <=  >  >=        comparison, left-associative
        +  -                additive, left-associative
        *  /                multiplicative, left-associative
        ^                   exponent, RIGHT-associative
        -x                  unary minus, tighter than any infix operator
        (…)                 grouping

    Raise `ParseError` on input that cannot form an expression — an operator
    where an operand belongs, an unclosed parenthesis, or trailing tokens
    after a complete expression. The message should name the position.
    """
    raise NotImplementedError("Unit 2: this is the exercise")


def sexpr(node) -> str:
    """Render a tree as parenthesised prefix notation.

        1 + 2 * 3     ->  (+ 1 (* 2 3))
        (1 + 2) * 3   ->  (* (+ 1 2) 3)
        -x + 1        ->  (+ (- x) 1)

    Numbers and identifiers render as their own text. Every operator node
    renders as `(op operand …)` with single spaces and no other whitespace.
    """
    raise NotImplementedError("Unit 2: this is the exercise")


def parse_text(src: str) -> str:
    """Convenience used by the tests: source in, s-expression out."""
    return sexpr(parse(tokenize(src)))
