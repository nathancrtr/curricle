"""The lexer — Unit 1.

Seeded with the token shape and left otherwise empty on purpose. The one
decision made for you is what a token *is*, because the parser in Unit 2 and
the exercise starter both depend on that shape, and a course where every
downstream fixture drifts with your naming choices is a course that spends its
time on merge conflicts instead of on interpreters.

Everything else is yours. `lex()` is the whole of Unit 1.
"""

from __future__ import annotations

from dataclasses import dataclass

# The token kinds tinylang needs. Add to this as the language grows — Unit 4
# will want FN and RETURN — but resist inventing kinds you don't yet parse.
KINDS = (
    "NUMBER", "STRING", "IDENT", "KEYWORD",
    "OP", "LPAREN", "RPAREN", "EOF",
)

KEYWORDS = frozenset({"let", "true", "false", "nil", "print"})


@dataclass(frozen=True)
class Token:
    """A lexeme, classified, with enough context to report an error about it.

    `line` is 1-based and exists so that error messages can name a location.
    A lexer that discards position information is a lexer whose parser can
    only ever say "syntax error" — you will regret it by Unit 2.
    """

    kind: str
    text: str
    line: int

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown token kind {self.kind!r}")


class LexError(Exception):
    """Raised on input that cannot be tokenised at all.

    Distinct from a parse error: this one means the characters don't even form
    words. An unterminated string is the canonical case.
    """


def lex(source: str) -> list[Token]:
    """Scan `source` into a list of tokens, ending with a single EOF token.

    Unit 1's build step. Handle, at minimum: integer and decimal numbers;
    double-quoted strings; identifiers and the keywords above; the operators
    `+ - * / == != < <= > >= =`; parentheses; `#` line comments; and
    whitespace, including newlines, which advance the line counter and are
    otherwise discarded.

    Two cases separate a working lexer from a nearly-working one:

    * `1+2` must produce three tokens, not one. Numbers end where a non-digit
      begins, and nothing about that is automatic.
    * `<=` must produce one token, not two. Take the longest match at each
      position ("maximal munch"), which in practice means peeking one
      character ahead before committing to a single-character operator.

    Raise `LexError` — naming the line — rather than crashing, on input you
    cannot classify.
    """
    raise NotImplementedError("Unit 1: this is the exercise")
