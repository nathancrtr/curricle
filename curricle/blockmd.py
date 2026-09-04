"""Block markdown → HTML, for lesson guides, chapters, and other course documents.

This module exists to answer one question: can the platform render course
markdown as themed pages without taking a markdown dependency (the layer is
stdlib + PyYAML only)? The corpus's lesson/task/question-bank files use a
small, regular subset: ATX headings, paragraphs, bullet lists (one nesting
level), ordered lists, blockquotes, pipe tables, indented code, and the
inline set `inlinemd` already covers. That subset is rendered here;
anything outside it falls back to a paragraph, never to silent loss.

Chapters (docs/chapter-pattern.md) grew the dialect by exactly three
constructs, each chosen because GitHub renders it too, so the file reads
the same in the repo and in the app:

- footnotes — `[^3]` in prose, `[^3]: the source` as a definition line
  (continuation lines indented); numbered in order of first reference and
  gathered into a footnotes section at the end of the document;
- collapsibles — raw `<details>`, `<summary>…</summary>`, `</details>`
  lines pass through (all other HTML stays escaped); the summary takes
  inline markup and the body is ordinary block markdown;
- callouts — a blockquote whose first line is `[!NOTE]`, `[!TIP]`,
  `[!IMPORTANT]`, `[!WARNING]` or `[!CAUTION]` (GitHub's alert syntax)
  becomes a titled callout; blank `>` lines split a quote into paragraphs.

Headings from h2 down also carry an id (a slug of their text) so a chapter
can be linked into by section. The renderer stays small on purpose: it is
a deliberately small renderer of the corpus's actual dialect, not a general
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
_FOOTNOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]: ?(.*)$")
_FOOTNOTE_REF = re.compile(r"\[\^([^\]\s]+)\]")
_CALLOUT = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$")
_DETAILS_OPEN = re.compile(r"^<details(?: open)?>\s*$")
_SUMMARY = re.compile(r"^<summary>(.*)</summary>\s*$")
_DETAILS_CLOSE = re.compile(r"^</details>\s*$")
_CODE_SPAN = re.compile(r"(<code>.*?</code>)")
_SLUG_STRIP = re.compile(r"<[^>]+>")
_SLUG_JUNK = re.compile(r"[^a-z0-9]+")


def _close(out: list[str], stack: list[str]) -> None:
    while stack:
        out.append(f"</{stack.pop()}>")


def slug(text: str) -> str:
    """A heading's id: its rendered text, lowercased, punctuation folded to
    hyphens. Empty headings get no slug (the caller then omits the id)."""
    plain = html.unescape(_SLUG_STRIP.sub("", text))
    return _SLUG_JUNK.sub("-", plain.lower()).strip("-")


def block_html(text: str, resolver: RefResolver | None = None) -> str:
    footnote_order: list[str] = []       # ids in order of first reference
    footnote_defs: dict[str, str] = {}   # id -> definition markdown

    def fn_number(fid: str) -> int:
        if fid not in footnote_order:
            footnote_order.append(fid)
        return footnote_order.index(fid) + 1

    def apply_footnotes(rendered: str) -> str:
        # Refs are substituted after inline rendering, and never inside a
        # code span — `[^1]` in code is code.
        parts = _CODE_SPAN.split(rendered)
        for i, part in enumerate(parts):
            if part.startswith("<code>"):
                continue
            parts[i] = _FOOTNOTE_REF.sub(
                lambda m: (f'<sup class="fn" id="fnref-{html.escape(m.group(1))}">'
                           f'<a href="#fn-{html.escape(m.group(1))}">'
                           f"{fn_number(m.group(1))}</a></sup>"),
                part)
        return "".join(parts)

    # Every inline span in this document resolves refs against the same page.
    def inline_html(t: str) -> str:
        return apply_footnotes(_inline_html(t, resolver))

    lines = text.splitlines()
    out: list[str] = []
    lists: list[str] = []          # open list tags, outermost first
    para: list[str] = []
    quote: list[str] = []          # "" entries are paragraph breaks
    code: list[str] | None = None  # inside a fenced block when not None
    details_depth = 0
    seen_slugs: dict[str, int] = {}

    def flush_para() -> None:
        if para:
            out.append(f"<p>{inline_html(' '.join(para))}</p>")
            para.clear()

    def flush_quote() -> None:
        if not quote:
            return
        paragraphs: list[list[str]] = [[]]
        for q in quote:
            if q == "":
                if paragraphs[-1]:
                    paragraphs.append([])
            else:
                paragraphs[-1].append(q)
        paragraphs = [p for p in paragraphs if p]
        quote.clear()
        if not paragraphs:
            return
        first = paragraphs[0][0]
        if m := _CALLOUT.match(first):
            kind = m.group(1).lower()
            title = m.group(2).strip() or m.group(1).capitalize()
            paragraphs[0] = paragraphs[0][1:]
            body = "".join(f"<p>{inline_html(' '.join(p))}</p>"
                           for p in paragraphs if p)
            out.append(f'<div class="callout {kind}">'
                       f'<p class="callout-title">{inline_html(title)}</p>'
                       f"{body}</div>")
            return
        out.append("<blockquote>"
                   + "".join(f"<p>{inline_html(' '.join(p))}</p>"
                             for p in paragraphs)
                   + "</blockquote>")

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

        if m := _FOOTNOTE_DEF.match(line):
            # A definition owns the indented lines that follow it.
            flush_all()
            fid, body = m.group(1), [m.group(2)]
            i += 1
            while i < len(lines) and lines[i].startswith(("  ", "\t")):
                body.append(lines[i].strip())
                i += 1
            footnote_defs[fid] = " ".join(b for b in body if b)
            continue

        if _DETAILS_OPEN.match(line):
            flush_all()
            out.append("<details open>" if " open" in line else "<details>")
            details_depth += 1
            i += 1
            continue

        if (m := _SUMMARY.match(line)) and details_depth:
            flush_all()
            out.append(f"<summary>{inline_html(m.group(1))}</summary>")
            i += 1
            continue

        if _DETAILS_CLOSE.match(line) and details_depth:
            flush_all()
            out.append("</details>")
            details_depth -= 1
            i += 1
            continue

        if m := _HEADING.match(line):
            flush_all()
            level = len(m.group(1))
            inner = inline_html(m.group(2))
            attr = ""
            if level >= 2 and (s := slug(inner)):
                n = seen_slugs.get(s, 0)
                seen_slugs[s] = n + 1
                attr = f' id="{s}"' if n == 0 else f' id="{s}-{n + 1}"'
            out.append(f"<h{level}{attr}>{inner}</h{level}>")
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
            quote.append(line.lstrip()[1:].strip())
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
    while details_depth:                          # unterminated collapsible
        out.append("</details>")
        details_depth -= 1

    if footnote_order or footnote_defs:
        # Referenced notes first, in reference order; then any defined but
        # never referenced, so a stray definition is visible rather than lost.
        ids = footnote_order + [f for f in footnote_defs if f not in footnote_order]
        items = []
        for fid in ids:
            body = footnote_defs.get(fid, "")
            rendered = inline_html(body) if body else "<i>(no definition)</i>"
            back = (f' <a class="fnback" href="#fnref-{html.escape(fid)}" '
                    'aria-label="back to text">↩</a>'
                    if fid in footnote_order else "")
            items.append(f'<li id="fn-{html.escape(fid)}">{rendered}{back}</li>')
        out.append('<section class="footnotes"><ol>'
                   + "".join(items) + "</ol></section>")
    return "\n".join(out)
