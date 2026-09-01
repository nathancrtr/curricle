"""The design system — one source of truth for every rendered surface.

Direction: *companion* — learning as a relationship you keep. Warmth read as
respect and hospitality for an adult doing hard work over a long time, never
as a children's app. Concretely: a warm neutral scale on a sunlit ground, one
coral accent that always means "your progress / your next step", rounded
geometry, soft elevation, humanist type, and plain second-person copy.

The signature gesture is **the waypath**: a rounded, segmented progress path —
one stone per tracked item — rendered identically on every surface that
tracks anything. At zero it is not an empty bar; it is the whole path laid
out ahead of you, visibly, with a hollow "you are here" ring on the next
stone. Completion lights a stone with a small pop. Everything else on the
page practices restraint so this one move can carry the personality.

Both themes come from the same tokens, each tuned by hand (the dark values
are not an inversion — they are a warm lamplit room). Every color pair below
was validated against WCAG AA by computation; the table lives in
DIRECTION.md at the repo root of this branch.

House rules encoded here:
- Color is semantic or absent. Coral = your progress and primary action;
  green = done/checkpoint/free; warm brown-orange = costs/caution. Chips
  always carry their text label; tint is reinforcement, never the message.
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
  --bg:#FDF6EF; --panel:#FFFFFF; --ink:#3B2A1E; --muted:#6D5B4E; --faint:#8A7767;
  --line:#EFDFD2; --line-soft:#F5EAE0; --edge:#A68A73;
  --accent:#E06A4E; --accent-text:#B8432A; --accent-strong:#C6492E;
  --accent-soft:#FBE9E2; --on-accent:#FFFFFF;
  --good:#3D7A4A; --good-text:#2F6B3C; --good-soft:#E4F0E5;
  --warn-text:#9C4A21; --warn-soft:#F9E9DC;
  --chip:#F7EADF; --stone:#EBD9C8;
  --shadow:0 1px 2px rgba(80,48,28,.05), 0 6px 18px rgba(80,48,28,.07);
  --shadow-lift:0 2px 4px rgba(80,48,28,.06), 0 10px 28px rgba(80,48,28,.10);
  color-scheme:light;"""

DARK_VARS = """\
  --bg:#221A14; --panel:#2C221B; --ink:#F5EAE0; --muted:#C4AE9D; --faint:#A78F7C;
  --line:#42352A; --line-soft:#382C22; --edge:#836D5A;
  --accent:#F0754F; --accent-text:#FFA184; --accent-strong:#F0754F;
  --accent-soft:#43291F; --on-accent:#221A14;
  --good:#7FBF8B; --good-text:#8FCF9B; --good-soft:#28382B;
  --warn-text:#EFA275; --warn-soft:#3E2C1E;
  --chip:#3A2D23; --stone:#4A3A2C;
  --shadow:0 1px 2px rgba(0,0,0,.25), 0 6px 18px rgba(0,0,0,.30);
  --shadow-lift:0 2px 4px rgba(0,0,0,.30), 0 10px 28px rgba(0,0,0,.38);
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
FONT_DISPLAY = ('ui-rounded, "Avenir Next", Avenir, Seravek, "Segoe UI", '
                'system-ui, -apple-system, sans-serif')
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
                   border-radius:6px; }}
  button {{ font:inherit; color:inherit; background:none; border:none; padding:0;
           cursor:pointer; }}
  code {{ font-family:{FONT_MONO}; font-size:.88em; background:var(--chip);
         padding:1px 5px; border-radius:6px; }}
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
               border-radius:999px; }}
  .eyebrow a:hover {{ background:var(--accent-soft); }}
  .eyebrow .sep {{ color:var(--faint); }}

  /* ---- cards & chips ---- */
  .panel {{ background:var(--panel); border:1px solid var(--line);
           border-radius:18px; box-shadow:var(--shadow); }}
  .chip {{ display:inline-block; font-size:11.5px; font-weight:600;
          letter-spacing:.02em; border-radius:999px; padding:2px 9px;
          background:var(--chip); color:var(--muted); white-space:nowrap; }}
  .chip.acc {{ background:var(--accent-soft); color:var(--accent-text); }}
  .chip.good {{ background:var(--good-soft); color:var(--good-text); }}
  .chip.warn {{ background:var(--warn-soft); color:var(--warn-text); }}

  /* ---- pill controls (generous touch targets) ---- */
  .pill {{ display:inline-flex; align-items:center; gap:7px; min-height:38px;
          font-size:14px; font-weight:600; color:var(--muted);
          border:1.5px solid var(--line); border-radius:999px; padding:6px 16px;
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
            color:var(--bg); padding:8px 18px; border-radius:999px;
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
