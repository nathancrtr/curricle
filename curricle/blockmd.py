"""Block markdown → HTML, for lesson guides and other course documents.

This module exists to answer one question: can the platform render lesson
markdown as themed pages without taking a markdown dependency (the layer is
stdlib + PyYAML only)? The corpus's lesson/task/question-bank files use a
small, regular subset: ATX headings, paragraphs, bullet lists (one nesting
level), ordered lists, blockquotes, pipe tables, indented code, and the
inline set `inlinemd` already covers. That subset is rendered here;
anything outside it falls back to a paragraph, never to silent loss. The
answer was yes, and it stays small on purpose: like `inlinemd`, this is a
deliberately small renderer of the corpus's actual dialect, not a general
markdown engine — if authored materials outgrow it, the answer is a
decision (grow the dialect or take the dependency), not quiet guessing.
"""

from __future__ import annotations

import html
import re

from .inlinemd import inline_html as _inline_html
from .refs import RefResolver

_HEADING = re.compile(r"^(#{1,6}) +(.*)$")
_BULLET = re.compile(r"^([ \t]*)[-*] +(.*)$")
_ORDERED = re.compile(r"^([ \t]*)\d+\. +(.*)$")
_TABLE_SEP = re.compile(r"^\|?[\s:|-]+\|[\s:|-]*$")


def _close(out: list[str], stack: list[str]) -> None:
    while stack:
        out.append(f"</{stack.pop()}>")


def block_html(text: str, resolver: RefResolver | None = None) -> str:
    # Every inline span in this document resolves refs against the same page.
    def inline_html(t: str) -> str:
        return _inline_html(t, resolver)

    lines = text.splitlines()
    out: list[str] = []
    lists: list[str] = []          # open list tags, outermost first
    para: list[str] = []
    quote: list[str] = []
    code: list[str] | None = None  # inside a fenced block when not None

    def flush_para() -> None:
        if para:
            out.append(f"<p>{inline_html(' '.join(para))}</p>")
            para.clear()

    def flush_quote() -> None:
        if quote:
            out.append("<blockquote>"
                       f"<p>{inline_html(' '.join(quote))}</p></blockquote>")
            quote.clear()

    def flush_all() -> None:
        flush_para()
        flush_quote()
        _close(out, lists)

    i = 0
    while i < len(lines):
        line = lines[i]

        if code is not None:                      # inside a fence
            if line.startswith("```"):
                out.append(f"<pre><code>{html.escape('\n'.join(code))}"
                           "</code></pre>")
                code = None
            else:
                code.append(line)
            i += 1
            continue

        if line.startswith("```"):
            flush_all()
            code = []
            i += 1
            continue

        if not line.strip():
            flush_all()
            i += 1
            continue

        if m := _HEADING.match(line):
            flush_all()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline_html(m.group(2))}</h{level}>")
            i += 1
            continue

        if line.startswith("    ") and not para and not lists and not quote:
            flush_all()
            block = []
            while i < len(lines) and (lines[i].startswith("    ")
                                      or not lines[i].strip()):
                if not lines[i].strip() and not (
                        i + 1 < len(lines) and lines[i + 1].startswith("    ")):
                    break
                block.append(lines[i][4:])
                i += 1
            out.append(f"<pre><code>{html.escape('\n'.join(block))}</code></pre>")
            continue

        if line.lstrip().startswith(">"):
            flush_para()
            _close(out, lists)
            quote.append(line.lstrip()[1:].lstrip())
            i += 1
            continue

        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush_all()
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip()
                             for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append('<div class="tablewrap"><table><thead><tr>'
                       + "".join(f"<th>{inline_html(c)}</th>" for c in head)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(
                           f"<td>{inline_html(c)}</td>" for c in r) + "</tr>"
                           for r in rows)
                       + "</tbody></table></div>")
            continue

        if m := (_BULLET.match(line) or _ORDERED.match(line)):
            flush_para()
            flush_quote()
            tag = "ul" if _BULLET.match(line) else "ol"
            depth = 2 if m.group(1) else 1        # one nesting level suffices
            while len(lists) > depth:
                out.append(f"</{lists.pop()}>")
            while len(lists) < depth:
                lists.append(tag)
                out.append(f"<{tag}>")
            # A list item's continuation lines are absorbed by the paragraph
            # branch below only after a blank; the corpus writes items on one
            # line, so an item is a line.
            out.append(f"<li>{inline_html(m.group(2))}</li>")
            i += 1
            continue

        if line.strip() in ("---", "***"):
            flush_all()
            out.append("<hr>")
            i += 1
            continue

        if lists and line.startswith(("  ", "\t")):
            # a wrapped list item continues its <li>
            prev = out.pop()
            out.append(prev[:-5] + " " + inline_html(line.strip()) + "</li>")
            i += 1
            continue

        flush_quote()
        _close(out, lists)
        para.append(line.strip())
        i += 1

    if code is not None:                          # unterminated fence
        out.append(f"<pre><code>{html.escape('\n'.join(code))}</code></pre>")
    flush_all()
    return "\n".join(out)
