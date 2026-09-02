"""Render the profile: the SKILL.md projection and the web review page.

The skill-file projection is the profile pipeline's founding requirement made
concrete: the document every Claude session reads for calibration is generated
from the evidence fold, never edited by hand. Structural boilerplate (headings,
framing paragraphs) lives here; every substantive sentence is a claim.
"""

from __future__ import annotations

import datetime
import html
import os
import re
import tempfile

from . import theme
from .inlinemd import inline_html
from .profile import ProfileState

# (field, lead-in line or None, render style)
_WHO_SECTIONS = (
    ("background", None, "para"),
    ("education", None, "para"),
    ("tracks", None, "para"),
    ("style", "**Learning style:**", "bullets"),
    ("domain_bias", None, "para"),
    ("pacing", None, "para"),
)
_CALIBRATE_SECTIONS = (
    ("calibration", None, "para"),
    ("skip", "**What to skip:**", "bullets"),
    ("scaffold", "**What to scaffold:**", "bullets"),
)


# Whose words a part of the projection is. The document is one document and
# `render_skill_md` is its one renderer; this is the seam between the frame
# curricle writes — frontmatter keys, headings, the two paragraphs that tell
# a model what it is reading, the footer — and the sentences the learner
# wrote. The onboarding review screen sets the two differently so that "this
# is yours, that is ours" is shown rather than claimed; nothing else needs
# to know, which is why the split lives in the parts and not in a second
# renderer that could disagree with this one.
HOUSE = "house"
LEARNER = "learner"


def _emit(state: ProfileState, sections) -> list[tuple[str, str]]:
    """One group of sections as tagged parts, blank lines and all.

    Sections are separated by an empty part rather than by a join, so that
    joining every part in order with a newline reproduces the document
    exactly — which is what lets the review screen mark the parts up without
    the file that reaches a model changing by a byte.
    """
    out: list[tuple[str, str]] = []
    for field, lead, style in sections:
        claims = state.field_claims(field)
        if not claims:
            continue
        if out:
            out.append((HOUSE, ""))
        if style == "bullets":
            if lead:
                out.append((HOUSE, lead))
            out.append((LEARNER, "\n".join(f"- {c.text}" for c in claims)))
        else:
            out.append((LEARNER, "\n\n".join(c.text for c in claims)))
    return out


def skill_parts(state: ProfileState) -> list[tuple[str, str]]:
    """The projection, in order, each part tagged HOUSE or LEARNER.

    `render_skill_md` is this, joined with newlines; there is no second
    renderer and no marker string threaded through the text.

    A section with no claims prints nothing at all — not even its heading.
    A learner who skips "Subjects" used to get "## Adapting to Different
    Subjects" over a blank, which reads to a model as a section that was
    considered and came back empty, and to the learner reviewing their own
    document as a promise the form failed to keep.

    The frontmatter's `description:` line is tagged by where its text came
    from: it is the learner's own sentence when they wrote one, and the
    house fallback when they did not.
    """
    description = state.claim("meta", "description")
    desc_text = description.text if description else "Personal learning profile."
    today = datetime.date.today().isoformat()

    parts: list[tuple[str, str]] = []

    def house(text: str = "") -> None:
        parts.append((HOUSE, text))

    house("---")
    house("name: learner-profile")
    parts.append((LEARNER if description else HOUSE,
                  f"description: {desc_text}"))
    house("---")
    house("")
    house("# Learner Profile")
    house("")
    house(
        "This skill provides Claude with context about who the learner is, so "
        "that explanations, exercises, and curriculum materials are calibrated "
        "correctly across any project or subject.")
    house("")
    house(
        "Read this skill before responding to any learning-oriented request. "
        "Use it to set your baseline assumptions about what to explain, what "
        "to skip, and how to frame new ideas.")

    for heading, sections in (
            ("## Who the Learner Is", _WHO_SECTIONS),
            ("## How to Calibrate Responses", _CALIBRATE_SECTIONS),
            ("## Adapting to Different Subjects",
             (("subject_adapters", None, "para"),))):
        body = _emit(state, sections)
        if not body:
            continue
        house("")
        house(heading)
        house("")
        parts.extend(body)

    demonstrated = state.field_claims("demonstrated")
    if demonstrated:
        house("")
        house("## Demonstrated in Course Work")
        house("")
        house(
            "Evidence accumulated from actual course activity — checkpoints "
            "and reviewed work, learner-ratified. Recent entries first tell "
            "you what has been *proven*, not merely claimed.")
        house("")
        parts.append((LEARNER,
                      "\n".join(f"- {c.text}" for c in reversed(demonstrated))))

    house("")
    house("---")
    house("")
    house(
        f"*Generated by curricle from the profile evidence ledger — {today}. "
        "Do not edit by hand: propose or assert evidence instead "
        "(`python -m curricle profile --help`), then re-render.*")
    house("")
    return parts


def render_skill_md(state: ProfileState) -> str:
    return "\n".join(text for _, text in skill_parts(state))


def write_skill_md(state: ProfileState, out_path: str) -> None:
    """Install the projection at `out_path`, atomically.

    The one writer every caller of the projection hook goes through, so the
    file on disk is only ever a whole `render_skill_md` or the previous whole
    one. A model reads this document; a half-written one would be a lie told
    in the middle of a sentence, and the render is fast enough that the
    temp-file-and-rename dance costs nothing worth counting.

    The directory is created because the flag names a file this app owns —
    a fresh machine has no `~/.claude/skills/learner-profile/` until
    something puts one there. The mode `mkstemp` gives (0600) rides along on
    purpose: the projection is the learner's profile in plain text.
    """
    text = render_skill_md(state)
    path = os.path.expanduser(out_path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # Same directory as the target, so the rename is a rename and not a copy
    # across filesystems — which is the whole atomicity claim.
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".skill-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        # A failed write leaves the previous projection in place and no
        # debris beside it.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# The web review page
# ---------------------------------------------------------------------------

_FIELD_TITLES = {
    "meta": "Skill description", "background": "Professional background",
    "education": "Formal education", "tracks": "Prior tracks",
    "style": "Learning style", "domain_bias": "Domain preferences",
    "pacing": "Pacing", "calibration": "Calibrating responses",
    "skip": "What to skip", "scaffold": "What to scaffold",
    "subject_adapters": "Adapting to subjects",
    "demonstrated": "Demonstrated in course work",
}

_STYLE = theme.style("""\
  .wrap { max-width:840px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:40px 0 10px; }
  h1 { font-weight:700; font-size:clamp(28px,5vw,38px); letter-spacing:-.01em;
       margin:14px 0 0; }
  .lede { margin:12px 0 0; color:var(--muted); font-size:16px; max-width:60ch; }
  h2 { font-size:20px; font-weight:700; margin:44px 0 4px; }
  .claim { border-bottom:1px solid var(--line-soft); padding:14px 0; font-size:14.5px;
           line-height:1.6; }
  .claim:last-of-type { border-bottom:none; }
  .claim p, .proposal .text p { margin:0 0 9px; }
  .claim p:last-child, .proposal .text p:last-child { margin-bottom:0; }
  .claim ul, .proposal .text ul { margin:0 0 9px; padding-left:19px; }
  .claim li, .proposal .text li { margin:3px 0; }
  .claim .foot, .proposal .text .foot { margin-top:-3px; }
  .claim .foot .tier, .proposal .text .foot .tier { margin-left:0; }
  .tier { display:inline-block; font-size:11px; font-weight:700; letter-spacing:.03em;
          border-radius:999px; padding:2px 9px; background:var(--chip);
          color:var(--muted); margin-left:8px; vertical-align:1px; white-space:nowrap; }
  .tier.demonstrated { background:var(--good-soft); color:var(--good-text); }
  .tier.thin { background:var(--warn-soft); color:var(--warn-text); }
  .src { font-size:12px; font-weight:500; color:var(--muted); margin-top:5px; }
  .pendingbox { background:var(--panel); border:1.5px solid var(--accent);
                border-radius:18px; box-shadow:var(--shadow); padding:18px 22px;
                margin:26px 0; }
  .pendingbox h2 { margin:0 0 4px; font-size:18px; }
  .pendingbox .note { font-size:13.5px; color:var(--muted); margin:0 0 8px; }
  .proposal { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap;
              border-bottom:1px solid var(--line-soft); padding:12px 0; font-size:14.5px; }
  .proposal:last-child { border-bottom:none; }
  .proposal .text { flex:1 1 24rem; line-height:1.6; }
  button { display:inline-flex; align-items:center; min-height:36px;
           font-size:13.5px; font-weight:600; background:var(--panel);
           border:1.5px solid var(--line); border-radius:999px; padding:5px 16px;
           color:var(--muted); cursor:pointer;
           transition:border-color .2s, color .2s, background .2s; }
  button.yes { color:var(--good-text); border-color:var(--good); }
  button.yes:hover { background:var(--good-soft); }
  button.no { color:var(--warn-text); }
  button.no:hover { background:var(--warn-soft); border-color:var(--warn-text); }
""")


_BULLET_RE = re.compile(r"^[-*]\s+")


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """A claim's markdown as ("p" | "ul", lines) blocks, in order.

    Claim text is markdown, and the long claims carry real block structure: a
    lede, a blank line, then a run of "- " bullets. The SKILL.md projection
    emits that verbatim because markdown is what it is; the web page has to
    build the blocks itself. Everything here is deliberately what the corpus
    actually contains — paragraphs and one flat level of bullets. Anything
    else (nesting, headings, fences) is prose to us, which is the same
    refusal-to-guess the compiler makes: a claim is one person's sentences,
    not a document.
    """
    out: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:                          # blank line closes the block
            out.append(("", []))
            continue
        kind, line = (("ul", _BULLET_RE.sub("", line)) if _BULLET_RE.match(line)
                      else ("p", line))
        if out and out[-1][0] == kind:
            out[-1][1].append(line)           # soft-wrapped continuation
        else:
            out.append((kind, [line]))
    return [b for b in out if b[0]]


def _claim_body(text: str, trailer: str) -> str:
    """A claim rendered as blocks, closed by `trailer` (the tier chip).

    The tier word is part of the claim, not of a block inside it, so it rides
    the final paragraph where there is one — which is every short claim, and
    is exactly the single line the page rendered before this function existed.
    A claim that ends in a list gets it on a line of its own instead: hung off
    the last bullet it would read as the tier of that bullet, and the tier is
    provenance for the whole claim.
    """
    blocks = _blocks(text)
    if not blocks:                            # empty text: keep the chip
        return f'<p>{trailer}</p>'
    parts = []
    for i, (kind, lines) in enumerate(blocks):
        last = i == len(blocks) - 1
        if kind == "ul":
            items = "".join(f"<li>{inline_html(x)}</li>" for x in lines)
            parts.append(f"<ul>{items}</ul>")
        else:
            tail = trailer if last else ""
            parts.append(f"<p>{inline_html(' '.join(lines))}{tail}</p>")
    if blocks[-1][0] == "ul":
        parts.append(f'<p class="foot">{trailer}</p>')
    return "".join(parts)

def render_profile_page(state: ProfileState, tenant_slug: str) -> str:
    e = html.escape
    parts: list[str] = []

    if state.pending:
        rows = []
        for p in state.pending:
            note = " <span class=\"tier thin\">supersedes</span>" if p.supersedes else ""
            src = f'<div class="src">{e(p.source)}</div>' if p.source else ""
            trailer = f'<span class="tier {e(p.tier)}">{e(p.tier)}</span>{note}'
            rows.append(
                f'<div class="proposal"><div class="text">'
                f'{_claim_body(p.text, trailer)}{src}</div>'
                f'<button class="yes" onclick="act(\'accept\',\'{e(p.field)}\',\'{e(p.key)}\')">Accept</button>'
                f'<button class="no" onclick="act(\'reject\',\'{e(p.field)}\',\'{e(p.key)}\')">Reject</button>'
                "</div>")
        parts.append('<div class="pendingbox"><h2>Awaiting your review</h2>'
                     '<p class="note">'
                     "The system proposes; you publish. Nothing below renders into "
                     "the profile until accepted.</p>"
                     + "".join(rows) + "</div>")

    for field in _FIELD_TITLES:
        claims = state.field_claims(field)
        if not claims:
            continue
        items = []
        for c in claims:
            src = f'<div class="src">{e(c.source)}</div>' if c.source else ""
            trailer = f'<span class="tier {e(c.tier)}">{e(c.tier)}</span>'
            items.append(f'<div class="claim">{_claim_body(c.text, trailer)}'
                         f'{src}</div>')
        parts.append(f"<h2>{e(_FIELD_TITLES[field])}</h2>" + "".join(items))

    body = "\n".join(parts) or (
        '<p class="lede">Nothing on the record yet. Assert something in your '
        "own voice (<code>python -m curricle profile assert</code>) or let course "
        "activity propose evidence as you work.</p>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>curricle — profile</title>
<style>
{_STYLE}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow"><a href="/">← your courses</a>
    <span class="sep">·</span> the learner profile
    <span class="sep">·</span> tenant {e(tenant_slug)}</p>
    <h1>What the record says about you</h1>
    <p class="lede">Every course is calibrated from this ledger — the better it
    knows you, the less time you spend on things you already know.</p>
  </header>
  {body}
  <footer>
    Every entry is evidence with a provenance tier: <b>attested</b> — you said it;
    <b>demonstrated</b> — course activity proved it; <b>thin</b> — claimed but
    uncorroborated. The skill file Claude reads is a projection of this ledger
    (<code>python -m curricle profile render</code>).
  </footer>
</div>
<script>
function act(kind, field, key) {{
  fetch("/api/profile/events", {{ method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{ kind, field, key }}) }})
    .then(() => location.reload());
}}
</script>
</body>
</html>
"""
