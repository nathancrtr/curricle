"""Inline markdown → HTML, for manifest row content.

Deliberately tiny: the corpus's row prose uses exactly inline code, links,
bold, and italics. Block structure never appears inside a row (that's what
lessons are for), so this stays a four-pattern renderer rather than a
markdown dependency. Code spans are lifted out first so their contents are
never touched by the other patterns.

Images (`![alt](src)`) render to `<img>`; a relative `src` resolves against
the document's directory when a resolver knows it, so a figure sitting
beside its chapter works in the repo and in the app alike.

Links may carry a reference scheme (`res:` / `unit:` / `mat:` / `repo:`,
refs.py) instead of a URL. A `resolver` turns those into hrefs for the page
being rendered; without one, a scheme-link degrades to its label as plain
text — never a dead `href="res:wg"` shipped to a browser.
"""

from __future__ import annotations

import html
import re

from .refs import RefResolver, split_ref

CODE_RE = re.compile(r"`([^`]+)`")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"\*([^*]+)\*")


def inline_html(text: str, resolver: RefResolver | None = None) -> str:
    escaped = html.escape(text, quote=False)

    code_spans: list[str] = []

    def stash(m: re.Match) -> str:
        code_spans.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(code_spans) - 1}\x00"

    out = CODE_RE.sub(stash, escaped)

    def image(m: re.Match) -> str:
        # `![alt](src)`: a relative src is the document's own neighbour on
        # GitHub, so it is resolved against the document's directory here
        # too (refs.RefResolver.asset_href); an absolute URL passes through.
        alt, src = m.group(1), m.group(2)
        href = resolver.asset_href(src) if resolver else src
        # Alt text is an attribute: no markup runs inside it, so the emphasis
        # markers are dropped and the tag is stashed past the later patterns.
        plain = re.sub(r"[*`]", "", alt)
        code_spans.append(f'<img src="{href}" alt="{plain}">')
        return f"\x00{len(code_spans) - 1}\x00"

    out = IMAGE_RE.sub(image, out)

    def link(m: re.Match) -> str:
        label, href = m.group(1), m.group(2)
        if split_ref(href) is not None:
            resolved = resolver.resolve(href) if resolver else None
            if resolved is None:
                return label
            href, external = resolved
        else:
            external = href.startswith(("http://", "https://"))
        attrs = ' target="_blank" rel="noopener"' if external else ""
        return f'<a href="{href}"{attrs}>{label}</a>'

    out = LINK_RE.sub(link, out)
    out = BOLD_RE.sub(r"<b>\1</b>", out)
    out = ITALIC_RE.sub(r"<i>\1</i>", out)

    for i, span in enumerate(code_spans):
        out = out.replace(f"\x00{i}\x00", span)
    return out
