"""The design system — one source of truth for every rendered surface.

Direction: *companion* — learning as a relationship you keep. Hospitality for
an adult doing hard work over a long time, never a children's app. The warmth
is carried by the geometry, the copy, and the gesture below; the color is
mineral and quiet, so that the one saturated thing on a page is the thing you
are meant to do next. Concretely: a cool neutral scale on a faintly green-grey
ground, one verdigris accent that always means "your progress / your next
step", generous radii, soft elevation, humanist type, plain second-person copy.

The signature gesture is **the waypath**: a rounded, segmented progress path —
one stone per tracked item — rendered identically on every surface that
tracks anything. At zero it is not an empty bar; it is the whole path laid
out ahead of you, visibly, with a hollow "you are here" ring on the next
stone. Completion lights a stone with a small pop. Everything else on the
page practices restraint so this one move can carry the personality.

Both themes come from the same tokens, each tuned by hand (the dark values
are not an inversion — they are a cool, low-lit room, and the accent lifts
several steps to survive it). Every color pair below was validated against
WCAG AA by computation; the table lives in DIRECTION.md at the repo root.

House rules encoded here:
- Color is semantic or absent, and the palette is deliberately two hues wide.
  Verdigris = your progress and primary action; ochre = costs/caution. Done
  is not a third hue: the whole `--good` family is the neutral ramp, because
  a finished thing has stopped being live and the page should quiet down
  around it, leaving the accent as the only saturated mark on the screen.
  (The tokens stay, spelled everywhere they were, so "done" keeps a name a
  renderer can reason about and the decision can be revisited in three lines
  rather than forty.) Within that family the split is by job, not by shade:
  `--good-text` is `--ink`, because done *text* is still text; `--good` is
  the non-text member — dots, checkbox fills, the border of a milestone or
  checkpoint box — and sits at border weight rather than ink weight, because
  those boxes are passive and a passive box drawn in full ink outweighs the
  live row it shares a page with. That is not a contrast concession: it
  clears the 3:1 non-text floor with room, and the floor is asserted.
  Chips always carry their text label; tint is reinforcement, never the
  message.
- Radii are generous (cards 18px, controls a full pill) — the rounded
  geometry *is* the warmth; borders stay hairline so it never turns toy.
  A decorative hairline is `--line`; the edge of a control a learner types
  into is `--edge`, computed against the 3:1 non-text floor, because a box
  whose boundary cannot be seen is a box that is not there.
- Type: a humanist sans stack (SF Rounded where the platform has it, then
  Avenir Next, then the system face). No serif display, no letterspaced
  mono eyebrows — that was the bookish status quo this direction replaces.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

LIGHT_VARS = """\
  --bg:#F4F6F4; --panel:#FFFFFF; --ink:#1B2124; --muted:#5C6568; --faint:#828B8E;
  --line:#E1E6E3; --line-soft:#ECF0ED; --edge:#849091;
  --accent:#1B8577; --accent-text:#0F6B5F; --accent-strong:#126E62;
  --accent-soft:#DFF0EC; --on-accent:#FFFFFF;
  --good:#55605F; --good-text:#1B2124; --good-soft:#E6EAE8;
  --warn-text:#8A5A00; --warn-soft:#F8EFD8;
  --chip:#E9EDEA; --stone:#D3DAD6;
  --r-card:10px; --r-ctl:7px; --r-chip:4px;
  --shadow:0 1px 2px rgba(20,28,26,.05);
  --shadow-lift:0 2px 6px rgba(20,28,26,.09);
  color-scheme:light;"""

DARK_VARS = """\
  --bg:#111516; --panel:#191E20; --ink:#E7ECEA; --muted:#A6B0AE; --faint:#7C8785;
  --line:#28302F; --line-soft:#20272A; --edge:#606E6C;
  --accent:#4FC3B0; --accent-text:#7ED8C8; --accent-strong:#4FC3B0;
  --accent-soft:#153531; --on-accent:#0B1615;
  --good:#8A9794; --good-text:#E7ECEA; --good-soft:#2A3230;
  --warn-text:#E9BC5E; --warn-soft:#3A2F14;
  --chip:#232A2B; --stone:#343D3D;
  --r-card:10px; --r-ctl:7px; --r-chip:4px;
  --shadow:0 1px 2px rgba(0,0,0,.30);
  --shadow-lift:0 2px 6px rgba(0,0,0,.38);
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

FONT_BODY = ('"Avenir Next", Avenir, Seravek, "Segoe UI", system-ui, '
             '-apple-system, sans-serif')
# Display and body are the same stack. `ui-rounded` used to lead this one —
# SF Rounded where the platform had it — and it was the direction's one
# honest "rounded" move. It went with the warm palette, for the same reason:
# a rounded display face is the other half of the friendly-app default, and
# a system that says "adult doing hard work" should not open every page in
# the face a children's app would pick. With no font pipeline to spend
# (that constraint stands), the professional move is one humanist face
# separated by size, weight and tracking rather than two by shape. The
# constant stays because renderers spell it: it names the *role*, and the
# day a display face is worth a pipeline, it changes here alone.
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
  code {{ font-family:{FONT_MONO}; font-size:.88em; background:var(--chip);
         padding:1px 5px; border-radius:var(--r-chip); }}
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
  .wp-stone {{ width:20px; height:10px; border-radius:5px; background:var(--stone);
              transition:background .35s ease, box-shadow .35s ease; }}
  .wp-stone.lit {{ background:var(--accent-strong); }}
  .wp-stone.here {{ background:transparent;
                   box-shadow:inset 0 0 0 2px var(--accent-strong); }}
  .wp-stone.pop {{ animation:wp-pop .45s ease; }}
  @keyframes wp-pop {{
    0% {{ transform:scale(1); }} 45% {{ transform:scale(1.55); }}
    100% {{ transform:scale(1); }}
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
WORDMARK = ('<svg width="56" height="8" viewBox="0 0 56 8" aria-hidden="true">'
            '<rect x="0" y="0" width="16" height="8" rx="4" fill="var(--accent-strong)"/>'
            '<rect x="21" y="1" width="14" height="6" rx="3" fill="none" '
            'stroke="var(--accent-strong)" stroke-width="2"/>'
            '<rect x="40" y="0" width="16" height="8" rx="4" fill="var(--stone)"/></svg>')


# --------------------------------------------------------------------------
# The waypath, client side
# --------------------------------------------------------------------------

# Renders the waypath into `el` for `ids` in order. `done` is a predicate,
# `nextId` gets the "you are here" ring. On update, stones whose state
# changed get the pop animation; a full re-render never pops (loading a page
# should feel settled, not showy).
#
# Keep this string `%`-free: it lands inside a `SCRIPT % {...}` template.
WAYPATH_JS = """\
function waypath(el, ids, done, nextId) {
  const had = el._wp || null;
  el._wp = {};
  ids.forEach((id, i) => {
    let s = el.children[i];
    if (!s) { s = document.createElement("span"); el.appendChild(s); }
    const lit = !!done(id);
    s.className = "wp-stone" + (lit ? " lit" : "") + (id === nextId ? " here" : "");
    if (had && had[id] === false && lit) {
      s.classList.add("pop");
      s.addEventListener("animationend", () => s.classList.remove("pop"), { once: true });
    }
    el._wp[id] = lit;
  });
  while (el.children.length > ids.length) el.lastChild.remove();
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
