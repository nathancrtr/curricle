"""The design system — one source of truth for every rendered surface.

Direction: *block book*, seeded from the title page and colour key of the
Thomas Bros. **New Block Book of Palo Alto and Vicinity**, 1925 (David Rumsey
Map Collection, 13231.002), with one hue corroborated by the Sanborn Map
Company endpaper of 1949 (16227.002). Full provenance, including what is
sampled and what is derived, lives in DESIGN.md at the repo root. Nothing in
the palette below was chosen; every value traces to a pixel or to a contrast
floor.

The plate's structural idea is the one worth stealing: **two colour systems
that never mix.** Blue-line print carries every piece of structure — the
rules, the frames, the block numbers, the index. Hand-applied wash carries
every piece of meaning — the land-use class. A reader can tell at a glance
which marks are the map and which are the claim, and this system draws the
same distinction between chrome and state.

The signature gesture is **the waypath**: one tick per tracked item, drawn as
a ruled box in blue-line — filled for done, taller and ringed for here,
outlined for ahead. At zero it is not an empty bar; it is the whole path laid
out in front of you. It appears only where something is genuinely tracked.

Both themes come from the same tokens. The light theme is the seed; **the
dark theme is derived**, because no dark-ground artifact seeded this work —
the hues are held and the lightness is inverted, which DESIGN.md records as a
set of decisions nobody sourced. Every pair below was validated against WCAG
AA by computation; the table lives in DIRECTION.md at the repo root.

House rules encoded here:
- Colour is semantic or absent, and the palette is two systems wide.
  `--accent` is the blue-line print: structure, rules, and the primary
  action, because on the plate the structural ink is also what points. The
  wash family is state — `--good` is the green land-use wash, `--warn` the
  ochre. Within the wash family the split is by job, not shade: `--good-text`
  is text weight and clears 4.5; `--good` is the non-text member — dots,
  fills, the border of a checkpoint box — and sits at the 3:1 floor, because
  a passive box drawn at ink weight outdraws the live row beside it. Chips
  always carry their text label; tint is reinforcement, never the message.
- `--panel` is **darker** than `--bg`, which is the one token that surprises
  people. On a near-white ground a lifted panel computes 1.06 and the field
  stops existing. On a printed sheet a field is a tinted block *on* the
  paper, never a lighter one — so the panel steps down, as the plate does.
  The dark theme inverts this, because there the paper analogy does not hold.
- The ground is `#F4F2F1`: hue sampled, lightness and chroma derived. It sits
  inside the 94–98% band that this author's other products also occupy, and
  that is a decision on the record rather than an oversight — see DESIGN.md.
  What carries this direction's identity is the blue-line/wash split, the
  square geometry and state-as-fill, none of which depend on the ground.
- `--measure` is the reading measure, and prose that stacks in one column
  spends it rather than picking its own `ch` value. Six different measures
  (58ch, 60ch, 62ch, 64ch, 66ch, 68ch, across five renderers and sometimes
  twice on one page) rendered as 514/548/552px, so consecutive paragraphs
  ended at three different places and nothing shared a right edge. `ch`
  cannot align across two font sizes; a length can.
- Radii are zero and elevation is `none`. A block book has ruled fields, not
  floating cards; hierarchy is carried by rule weight and fill. The three
  radius tokens stay, spelled everywhere they were, so the decision is
  revisitable in three lines rather than forty.
- `--chip` clears **both** surfaces, not just the ground. With `--panel`
  below `--bg`, a chip tuned against the ground alone computed 1.01 on a
  panel and every chip inside one vanished — trigger phrases, tier labels,
  inline code. The chip now sits below the panel, which is also the right
  drawing: a chip is a smaller field on the same sheet.
- A decorative hairline is `--line`; the edge of a control a learner types
  into is `--edge`, computed against the 3:1 non-text floor, because a box
  whose boundary cannot be seen is a box that is not there.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

LIGHT_VARS = """\
  --bg:#F4F2F1; --panel:#EAE6E3; --ink:#241C1C; --muted:#665D57; --faint:#958A83;
  --line:#D8D0CB; --line-soft:#E7E2DF; --edge:#8F7C70;
  --accent:#2D455D; --accent-text:#2D455D; --accent-strong:#213345;
  --accent-soft:#E4EBF1; --on-accent:#EAE6E3;
  --good:#7A894D; --good-text:#606C3D; --good-soft:#E5EAD7;
  --warn-text:#8A5F15; --warn-soft:#F6E6CB;
  --chip:#E1DAD6; --stone:#6D8FB0;
  --measure:552px;
  --r-card:0px; --r-ctl:0px; --r-chip:0px;
  --shadow:none;
  --shadow-lift:none;
  color-scheme:light;"""

DARK_VARS = """\
  --bg:#1C1917; --panel:#272320; --ink:#E6E2E0; --muted:#AFA7A1; --faint:#6E645E;
  --line:#3D3733; --line-soft:#2F2B27; --edge:#7B6E65;
  --accent:#5587B9; --accent-text:#7DA8D4; --accent-strong:#A3C2E0;
  --accent-soft:#243342; --on-accent:#1C1917;
  --good:#6A7740; --good-text:#9AAE61; --good-soft:#303522;
  --warn-text:#CD9637; --warn-soft:#3B2E16;
  --chip:#423C38; --stone:#4D6984;
  --measure:552px;
  --r-card:0px; --r-ctl:0px; --r-chip:0px;
  --shadow:none;
  --shadow-lift:none;
  color-scheme:dark;"""

# The dark block is emitted twice: once behind the media query (system
# preference) and once behind [data-theme=dark] (explicit toggle / testing),
# with [data-theme=light] able to pin light. Same tokens either way.
TOKENS_CSS = f"""\
  :root {{
{LIGHT_VARS}
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme=light]) {{
{DARK_VARS}
    }}
  }}
  :root[data-theme=dark] {{
{DARK_VARS}
  }}
"""

FONT_BODY = ('"Helvetica Neue", Helvetica, "Segoe UI", Roboto, Arial, '
             'system-ui, sans-serif')
# A grotesque, not a humanist face, and deliberately not a rounded one. The
# seed's own lettering is drawn sans capitals doing structural work — block
# numbers, street names, the border rules — and that is the register this
# stack aims at. `ui-rounded` led this list two rounds ago and Avenir Next
# one round ago; both were the friendly-app reflex wearing different clothes.
#
# The honest version of this decision is Archivo, an American grotesque in
# the same commercial-lettering line as the plate, with Archivo Narrow for
# the structural labels — one family at two widths, which is the plate's own
# logic. That needs a font pipeline (vendored woff2 in the package, since a
# self-hosted app should not phone out to a font CDN), and the pipeline is a
# separate decision. Until it exists this stack is the nearest thing the
# platform already has, and it changes here alone when the pipeline lands.
FONT_DISPLAY = FONT_BODY
FONT_MONO = 'ui-monospace, Menlo, Consolas, monospace'

# A formatting hazard, because the renderers reach for two different tools:
# their `SCRIPT` templates are filled with `SCRIPT % {...}`, while their CSS
# and HTML go through f-strings. So the strings below have opposite rules.
# BASE_CSS is full of literal percents — `100%` widths, `-50%` translates,
# `@keyframes` stops — and must therefore *never* be run through `%`
# formatting; it is concatenated into a <style> block as-is. WAYPATH_JS goes
# the other way: it is pasted into a `%`-formatted template, so it must stay
# free of `%` (no modulo, no `width: 50%`) or every call site breaks at once.
BASE_CSS = f"""\
  * {{ box-sizing:border-box; }}
  html {{ -webkit-text-size-adjust:100%; }}
  [hidden] {{ display:none !important; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.6 {FONT_BODY}; }}
  a {{ color:var(--accent-text); }}
  :focus-visible {{ outline:2px solid var(--accent-strong); outline-offset:3px;
                   border-radius:var(--r-ctl); }}
  button {{ font:inherit; color:inherit; background:none; border:none; padding:0;
           cursor:pointer; }}
  /* A command that wraps mid-token is a command nobody can read or copy:
     `python -m curricle profile assert` broke after the hyphen and the next
     line opened with a bare "m". Inline code is an atom. */
  code {{ font-family:{FONT_MONO}; font-size:.88em; background:var(--chip);
         padding:1px 5px; border-radius:var(--r-chip);
         white-space:nowrap; }}
  h1, h2, h3, .display {{ font-family:{FONT_DISPLAY}; }}

  /* ---- the shared shell ---- */
  .eyebrow {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px;
             font-size:13.5px; font-weight:500; color:var(--muted); }}
  /* The crumb link is padded so its hover pill has a hit area, and the
     padding is cancelled by negative margins on *both* sides so the padding
     never enters the rhythm: the text edge aligns with the page on the left,
     and on the right the crumb keeps the same 8px gap the separators do
     (compensating only the left stacked 12px of padding onto the flex gap,
     giving 20px there against 8px everywhere else). Horizontal padding is
     the gap, 8px, and no more: at exactly that size the hover pill fills the
     gap and stops where the next crumb begins, so hovering never reaches
     under the separator dot. Changing the gap means changing both. */
  .eyebrow a {{ text-decoration:none; color:var(--accent-text);
               padding:6px 8px; margin-left:-8px; margin-right:-8px;
               border-radius:var(--r-ctl); }}
  .eyebrow a:hover {{ background:var(--accent-soft); }}
  /* A breadcrumb separator, and only that. The eyebrow used to chain page
     facts onto the end of the navigation with middots — "the curriculum ·
     7 phases · 23 units", "unit 02 · phase 1" — which reads as one list but
     is two things: where you can go back to, and what you are looking at.
     The facts moved under the title where they belong, the separator became
     the slash a breadcrumb has always used, and what is left in the eyebrow
     is a path of places. */
  .eyebrow .sep {{ color:var(--faint); }}
  /* The facts the eyebrow used to carry, in the one place a fact about
     this page belongs: under this page's title. */
  .pagefacts {{ margin:8px 0 0; font-size:13.5px; color:var(--muted); }}

  /* ---- cards & chips ---- */
  .panel {{ background:var(--panel); border:1px solid var(--line);
           border-radius:var(--r-card); box-shadow:var(--shadow); }}
  /* Chips are labels, not lozenges. A pastel pill on every tag is the other
     half of the pill-everything look; at 4px with the tint kept, the
     semantic families still reinforce (the house rule stands — the word is
     always printed and the tint only agrees with it) without six of them
     turning a unit row into a row of buttons. */
  .chip {{ display:inline-block; font-size:12px; font-weight:600;
          border-radius:var(--r-chip); padding:2px 7px;
          background:var(--chip); color:var(--muted); white-space:nowrap; }}
  .chip.acc {{ background:var(--accent-soft); color:var(--accent-text); }}
  .chip.good {{ background:var(--good-soft); color:var(--good-text); }}
  .chip.warn {{ background:var(--warn-soft); color:var(--warn-text); }}

  /* ---- pill controls (generous touch targets) ---- */
  .pill {{ display:inline-flex; align-items:center; gap:7px; min-height:38px;
          font-size:14px; font-weight:600; color:var(--muted);
          border:1px solid var(--edge); border-radius:var(--r-ctl); padding:6px 14px;
          background:var(--panel); cursor:pointer;
          transition:border-color .2s, color .2s, background .2s; }}
  /* A pill is a button whether the element under it is one or is an anchor,
     so the anchor half gives up its underline here rather than in whichever
     surface happens to notice: an underlined label inside a button is a link
     wearing a button's clothes. The front door had this rule locally and the
     wizard did not, which is exactly the drift a shared sheet exists to
     stop. */
  a.pill {{ text-decoration:none; }}
  .pill:hover {{ border-color:var(--accent); color:var(--ink); }}
  .pill[aria-pressed="true"] {{ background:var(--accent-strong);
          border-color:var(--accent-strong); color:var(--on-accent); }}
  .pill.primary {{ background:var(--accent-strong); border-color:var(--accent-strong);
          color:var(--on-accent); text-decoration:none; }}
  .pill.primary:hover {{ filter:brightness(1.06); }}

  /* ---- the mark ---- */
  /* Shared, because two surfaces draw it now: the front door leads with it
     as a link home, and the wizard leads with it as a static mark (there is
     no home for a tenant who has not finished setting up, and a dead link
     is worse than none). A second copy of these four declarations beside a
     second copy of the drawing is how a mark drifts. */
  .wordmark {{ display:inline-flex; align-items:center; gap:10px;
              font:700 22px {FONT_DISPLAY}; color:var(--ink);
              text-decoration:none; letter-spacing:-.01em; }}
  .wordmark svg {{ display:block; }}

  /* ---- the waypath (the signature gesture) ---- */
  .waypath {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .wp-stone {{ width:14px; height:14px; border:1px solid var(--stone);
              background:transparent;
              transition:background .3s ease, border-color .3s ease; }}
  .wp-stone.lit {{ background:var(--accent-strong);
                  border-color:var(--accent-strong); }}
  .wp-stone.here {{ background:transparent; border-color:var(--accent-strong);
                   box-shadow:inset 0 0 0 1px var(--accent-strong); }}
  /* Completion fills a block; it does not bounce. A stone that grows and
     springs back is the friendly-app reflex, and it was the last piece of
     the old direction still moving. The mark still announces itself — the
     fill arrives through a held outline — but in the register of a form
     being stamped rather than a toy responding. */
  .wp-stone.pop {{ animation:wp-pop .5s steps(1, end) 2; }}
  @keyframes wp-pop {{
    0%, 49% {{ box-shadow:inset 0 0 0 3px var(--bg); }}
    50%, 100% {{ box-shadow:none; }}
  }}
  .wp-count {{ font-size:14px; font-weight:600; color:var(--muted);
              white-space:nowrap; }}

  /* ---- toast ---- */
  .saving {{ position:fixed; bottom:18px; left:50%;
            transform:translateX(-50%) translateY(12px);
            font-size:13px; font-weight:600; background:var(--ink);
            color:var(--bg); padding:8px 18px; border-radius:var(--r-ctl);
            opacity:0; pointer-events:none; transition:.25s; }}
  .saving.show {{ opacity:1; transform:translateX(-50%) translateY(0); }}

  footer {{ margin-top:64px; padding-top:22px; border-top:1px solid var(--line);
           font-size:13.5px; color:var(--muted); }}
  @media (prefers-reduced-motion:reduce) {{
    * {{ transition-duration:.01ms !important; animation-duration:.01ms !important; }}
  }}
"""


def style(extra: str = "") -> str:
    """Tokens + base + a surface's own styles, ready for a <style> block."""
    return TOKENS_CSS + BASE_CSS + extra


# --------------------------------------------------------------------------
# The mark
# --------------------------------------------------------------------------

# The wordmark is the waypath itself, in miniature: three stones — lit, ring,
# unlit — because the mark and the product's promise are the same drawing.
# Which is why both of its v1 departures from the path are gone. The lit
# stone fills --accent-strong, the token the path's lit stones moved to when
# the contrast exception was retired; drawing the mark in --accent left the
# one place the gesture is stated on its own out of the decision that reached
# every other waypath. And the stones are the 2:1 lozenge, not circles: the
# lozenge is the chosen stone shape, and a mark whose stones are a different
# shape from the path's stones is a different drawing, whatever it is
# miniaturizing. Scaling is the honest miniaturization — the front door's
# course cards already shrink the stone to 15x8 — so these are 16x8 with a
# 4px gap, and the ring is a hollow lit stone inset 1 with a 2 stroke,
# exactly as `.wp-stone.here` draws it.
#
# It lives here rather than in `webapp.py` because the wizard leads with it
# too, and `webapp` imports the wizard: one drawing, in the module that owns
# the drawing, is the only arrangement in which "reuse, never redraw" is
# something the code enforces rather than something a reviewer remembers.
WORDMARK = ('<svg width="32" height="10" viewBox="0 0 32 10" aria-hidden="true">'
            '<rect x="0" y="0" width="10" height="10" fill="var(--accent-strong)"/>'
            '<rect x="12" y="1" width="8" height="8" fill="none" '
            'stroke="var(--accent-strong)" stroke-width="2"/>'
            '<rect x="22.5" y="0.5" width="9" height="9" fill="none" '
            'stroke="var(--stone)" stroke-width="1"/></svg>')


# --------------------------------------------------------------------------
# The waypath, client side
# --------------------------------------------------------------------------

# Renders the waypath into `el` for `ids` in order. `done` is a predicate,
# `nextId` gets the "you are here" ring. On update, stones whose state
# changed get the pop animation; a full re-render never pops (loading a page
# should feel settled, not showy).
#
# Keep this string `%`-free: it lands inside a `SCRIPT % {...}` template.
# `hrefFor` is optional and turns the here-stone into a link. The ring is
# the drawing of "you are here", and on a surface that can say where here
# *is* — the curriculum, whose entries are on the same page — the mark a
# reader's eye already goes to should be the thing that takes them there.
# Everywhere else it stays a span and nothing changes.
#
# The stones carry their own `aria-hidden` rather than relying on the
# container's, because a focusable link inside an `aria-hidden` subtree is
# an element keyboard users can reach and screen-reader users cannot: the
# path is a picture of what the count beside it says in words, so the stones
# are hidden one by one and the one that navigates is left exposed. Callers
# with no `hrefFor` may keep hiding the whole container; the per-stone
# attribute is harmless underneath it.
#
# Returns the here-stone, so a caller that made it a link can name it.
WAYPATH_JS = """\
function waypath(el, ids, done, nextId, hrefFor) {
  const had = el._wp || null;
  el._wp = {};
  let here = null;
  ids.forEach((id, i) => {
    const href = id === nextId && hrefFor ? hrefFor(id) : null;
    const tag = href ? "a" : "span";
    let s = el.children[i];
    // Replaced rather than reused when the tag has to change: the here-stone
    // moves every time something is marked done, so the anchor and the span
    // trade places over the life of the page.
    if (!s || s.tagName.toLowerCase() !== tag) {
      const fresh = document.createElement(tag);
      if (s) el.replaceChild(fresh, s); else el.appendChild(fresh);
      s = fresh;
    }
    const lit = !!done(id);
    s.className = "wp-stone" + (lit ? " lit" : "") + (id === nextId ? " here" : "");
    if (href) { s.href = href; s.removeAttribute("aria-hidden"); }
    else s.setAttribute("aria-hidden", "true");
    if (id === nextId) here = s;
    if (had && had[id] === false && lit) {
      s.classList.add("pop");
      s.addEventListener("animationend", () => s.classList.remove("pop"), { once: true });
    }
    el._wp[id] = lit;
  });
  while (el.children.length > ids.length) el.lastChild.remove();
  return here;
}
"""


# --------------------------------------------------------------------------
# Copy helpers
# --------------------------------------------------------------------------

# A raw pictograph pasted at the start of a label (the corpus has exactly
# one: textual-flow's "\U0001F4EE Contact milestone: INTF + McCollum emails
# sent") is decoration living in content — this UI has its own illustration
# vocabulary for milestones (the flag mark), so a leading emoji is
# normalized away at render time, along with the space it usually trails.
# Only *leading* pictographs; emoji inside prose are the author's business.
_LEADING_PICTO = re.compile(
    "^[\U0001F000-\U0001FAFF☀-➿︎️‍]+\\s*")


def strip_leading_pictograph(label: str) -> str:
    return _LEADING_PICTO.sub("", label)


# A small inline flag mark for milestones — the one bit of illustration
# vocabulary the UI owns. Drawn, not an emoji: currentColor, aligns to text.
FLAG_SVG = ('<svg class="flag" width="11" height="13" viewBox="0 0 11 13" '
            'aria-hidden="true"><path d="M1.5 1v11M1.5 1.6c2-.9 3.6-.9 5 0 '
            '1.2.8 2.4.9 3.5.4v5c-1.1.5-2.3.4-3.5-.4-1.4-.9-3-.9-5 0z" '
            'fill="none" stroke="currentColor" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"
