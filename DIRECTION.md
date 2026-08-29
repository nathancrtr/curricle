# Direction: companion — learning as a relationship you keep

> **Status — this describes the target, not `main`.** The direction is
> landing as an eight-PR stack, and the prose below is written in the present
> tense of the finished system. PR 1 adds `curricle/theme.py` and this
> document and nothing else: no renderer imports the module, the four
> independent style blobs (`hubrender`, `currender`, `resrender`,
> `profilerender`) are all still in place, and `build/` is byte-for-byte
> unchanged. So every claim here about renderers, layout, screenshots, or
> "a palette change is now one edit" — the token-system section, the judgment
> calls, the composed round — reads as the specification the later PRs are
> held to, not as a description of the tree you are standing in. Editing a
> token in `theme.py` today changes nothing visible; it will once the
> renderer PRs land. The one section that is true of `main` now is the
> contrast table: those numbers are computed from the values in `theme.py`
> and are asserted by `tests/test_theme.py`.

## Thesis

curricle should feel like something that is glad you came back: a course
written for one adult, met with warmth that reads as respect and hospitality —
never as a children's app. Personality comes from one signature move plus
discipline everywhere else; the warmth is carried by geometry, color, and
voice, not by mascots, confetti, or exclamation points.

## The signature gesture: **the waypath**

A rounded, segmented progress path — one "stone" per tracked item — rendered
identically wherever anything is tracked: the front door (a mini path per
course card), the hub's welcome panel, the curriculum meter, the resources
core-path meter. Three rules give it its meaning:

1. **Zero is a path, not a void.** At 0/26 the entire path renders as visible
   unlit stones with the copy "**The path is laid.** 26 steps from here to
   done — begin with …". The old design's invisible `0/26` bar (brief defect
   #4) is replaced by the strongest moment on the page.
2. **You are here.** The next undone stone is a hollow coral ring — the only
   outlined stone — so resuming ("where was I?") is answered before a word is
   read.
3. **Completion is felt once.** A stone lights coral with a one-shot scale
   pop *only when its state changes in-session* (`theme.WAYPATH_JS` tracks
   prior state); a page load never animates. Guarded by
   `prefers-reduced-motion`.

The wordmark is the gesture in miniature: three stones — lit, ring, unlit —
before the word "curricle". The mark and the product promise are the same
drawing, which is why there is no second illustration idea anywhere (the one
exception: a small drawn flag for milestones, see below).

Where the gesture does **not** go: the profile page tracks nothing, so it gets
no waypath. A gesture applied where it isn't true is decoration.

## Where the line is drawn (the infantilization test)

The learner has a linguistics degree and a two-year plan. Everything below was
chosen to read as *hospitality to that person*:

- **Copy is plain second person, no exclamation points, no praise-babble.**
  "Welcome back. 3 of 26 done · next up: …" / "Every step walked." / "Good
  evening, nathan." The greeting is computed from the actual clock — a real
  courtesy, not a sticker.
- **No guilt surface exists.** Nothing counts days away, nothing decays,
  the zero state is framed as a beginning, and the "empty" filter state says
  "everything here is done", not "nothing left!".
- **One micro-animation** (the stone pop), under half a second, only on an
  earned event. No confetti, no bouncing.
- **Rounded ≠ cartoon.** Radii are generous (cards 18px, pills 999) but
  borders are hairline, shadows are quiet, and the type is a humanist sans at
  adult sizes — the geometry is warm, the voice is level.

## The token system (`curricle/theme.py`)

The four independent `STYLE` blobs are gone. `theme.py` is the single source:
`TOKENS_CSS` (light + dark variables), `BASE_CSS` (shell, panel, chip, pill,
waypath, toast), `WAYPATH_JS`, the milestone `FLAG_SVG`, and
`strip_leading_pictograph`. Every renderer composes `theme.style(own_css)`;
`webapp.py`'s front door draws from the same module. A palette change is now
one edit.

### Type

- Body: `"Avenir Next", Avenir, Seravek, "Segoe UI", system-ui` at 16px/1.6 —
  humanist, warm, everywhere available, no font pipeline (constraint honored).
- Display (`h1–h3`): `ui-rounded` first — SF Rounded where the platform has
  it (the one honest "rounded" move), falling back to the body stack. Chrome
  falls back to Avenir Next; the design must and does work on both.
- Mono only for things that are literally typed (trigger phrases, code).
  The letterspaced-mono-small-caps eyebrow vocabulary of the bookish status
  quo is entirely removed.

### Color

One accent with one meaning: **coral = your progress and your next action**
(waypath, primary buttons, links, phase number badges). **Green = done /
checkpoint / free.** **Warm brown-orange = costs and caution** (paid chips,
thin evidence). Neutrals are a warm brown ramp on a faintly peach ground
`#FDF6EF` — deliberately sunnier than the old gray-cream, because panels,
rounded sans, and saturated coral (not serifs and hairlines) now carry the
gestalt. Dark is a tuned "lamplit room", not an inversion: warm near-black
ground, browner panels, coral lifted two steps for contrast.

| token | light | dark | role |
|---|---|---|---|
| `--bg` | `#FDF6EF` | `#221A14` | page ground |
| `--panel` | `#FFFFFF` | `#2C221B` | cards |
| `--ink` | `#3B2A1E` | `#F5EAE0` | body text |
| `--muted` | `#6D5B4E` | `#C4AE9D` | secondary text (AA at any size) |
| `--faint` | `#8A7767` | `#A78F7C` | decorative marks only (see contrast note) |
| `--line` / `--line-soft` | `#EFDFD2` / `#F5EAE0` | `#42352A` / `#382C22` | hairlines |
| `--accent` | `#E06A4E` | `#F0754F` | accent borders & hovers (next-row ring) |
| `--accent-text` | `#B8432A` | `#FFA184` | links & small accent text |
| `--accent-strong` | `#C6492E` | `#F0754F` | button fills carrying `--on-accent` text; lit waypath stones (v2) |
| `--accent-soft` | `#FBE9E2` | `#43291F` | tints (badges, key-insight cards) |
| `--good` / `--good-text` / `--good-soft` | `#3D7A4A` / `#2F6B3C` / `#E4F0E5` | `#7FBF8B` / `#8FCF9B` / `#28382B` | done/checkpoint/free |
| `--warn-text` / `--warn-soft` | `#9C4A21` / `#F9E9DC` | `#EFA275` / `#3E2C1E` | paid/thin |
| `--chip` | `#F7EADF` | `#3A2D23` | neutral chip fill |
| `--stone` | `#EBD9C8` | `#4A3A2C` | unlit waypath stone |

Spacing/radii/elevation: cards 18px radius + `--shadow` (two quiet layers);
controls are pills with ≥34–38px hit height; checkboxes 17–18px with
`accent-color`. Dark theme ships under both `prefers-color-scheme` and an
explicit `data-theme` attribute (same tokens; the attribute exists so a
toggle or a test can pin either theme).

## Contrast — computed, not eyeballed

WCAG relative-luminance ratios, floors: 4.5 text, 3.0 large text/meaningful
non-text. Originally computed by a throwaway script on the design branch; the
provenance now lives in the repo as `tests/test_theme.py`, which recomputes
the ratios from the hex values in `theme.py` and asserts each pair below
against its floor. A token edit that breaks a floor fails the suite.

| pair | light | dark | floor |
|---|---|---|---|
| ink on bg | **12.76** | **14.46** | 4.5 |
| ink on panel | **13.67** | **13.12** | 4.5 |
| muted on bg | **6.02** | **8.07** | 4.5 |
| muted on panel | **6.45** | **7.32** | 4.5 |
| accent-text on bg | **5.06** | **8.71** | 4.5 |
| accent-text on panel | **5.42** | **7.90** | 4.5 |
| accent-text on accent-soft | **4.61** | **6.78** | 4.5 |
| good-text on panel | **6.38** | **8.56** | 4.5 |
| good-text on good-soft | **5.44** | **6.84** | 4.5 |
| warn-text on panel | **6.15** | **7.47** | 4.5 |
| warn-text on warn-soft | **5.19** | **6.37** | 4.5 |
| ink on chip | **11.58** | **11.22** | 4.5 |
| muted on chip | **5.46** | **6.26** | 4.5 |
| on-accent text on accent-strong | **4.78** | **6.01** | 4.5 |
| accent fill vs bg (non-text) | **3.09** | **6.01** | 3.0 |
| accent fill vs panel (non-text) | **3.31** | **5.45** | 3.0 |
| lit stone (accent-strong) vs unlit stone (v2) | **3.48** | **3.81** | 3.0 |
| lit stone (accent-strong) vs bg (v2) | **4.46** | **6.01** | 3.0 |
| faint on bg (decorative only) | 3.99 | 5.60 | — |

Two audit-driven fixes: every small-text use of `--faint` (eyebrow labels,
citations, row labels, unit numbers, sources) was promoted to `--muted`
because light faint-on-panel computes 4.27; `--faint` now colors only
decorative marks (separators, arrows, the entry dot ring).
And **lit vs unlit stones**: round one accepted 2.41 (light) as an
`aria-hidden` exception. The composed round retired the exception — lit
stones now fill with `--accent-strong` (`#C6492E` light / `#F0754F` dark),
which computes **3.48 light / 3.81 dark** against the unlit stone: above the
3:1 floor with the gesture intact. Nothing was traded away: the zero state's
unlit stones are unchanged, the deeper coral still reads unmistakably as
coral, and it is the same token the "you are here" ring and the primary
buttons already used — the ring is now literally a hollow lit stone. The
waypath remains `aria-hidden` decoration always paired with a text count.

**Placeholder text is not decorative.** An earlier draft of this section
listed it with the separators and arrows, and the design branch's
`textarea::placeholder` accordingly took `--faint` over `--panel` — the same
4.27 that disqualified `--faint` from small text three sentences earlier.
Placeholder copy is instruction, read to be acted on, so it takes `--muted`
(6.45 on panel). The renderer PRs inherit that as a requirement, not as a
pre-blessed exception.

## Judgment calls (say-it-out-loud reasons)

- **Hub h1 is the course title, not the slug.** "textual-flow" as a page
  title reads as infrastructure; the slug demotes to a small line under it.
- **Chips live under the unit title, never beside it** (hub). This is the fix
  for brief defect #2 — the title owns the full column width; chips are a
  second line of metadata. In the curriculum's single wide column they stay
  inline, where there is room.
- ~~Phase cards flow in CSS columns~~ — **overruled by the operator and
  replaced in the composed round** (see "Composed round" below). The columns
  packed evenly but made the top row read 0, 2, 4 and put sequential content
  in a card grid; the hub is now a single vertical spine.
- **Milestones get the product's one drawn glyph** — a small flag in
  currentColor — plus a green-tinted row (defect #5). The one such label in
  the corpus — textual-flow's `p2-mail`, "📮 Contact milestone: INTF +
  McCollum emails sent" — has its leading `📮` normalized away at render time
  (`strip_leading_pictograph`, leading pictographs only; emoji inside prose
  are the author's business). This is presentation normalization of
  decoration living in content, not a content edit.
- **Widget/quiz card titles are ink with a coral ↗**, not coral wholesale —
  six saturated titles in a grid would compete with the accent's single
  meaning.
- **Tag chips no longer carry meaning by color alone** (defect #6): every
  chip keeps its text label; tints come from the semantic families (`widget`
  = accent because it is the interactive thing; free/paid = green/warm; the
  rest neutral).
- **The front door** (defect #1) is the direction stated in one screen:
  wordmark, time-of-day greeting, one card per course with title,
  description, mini waypath, honest state copy, and Begin/Continue/Revisit.
  Done-counts and next-up labels are *derived at render time* from the
  manifest + progress fold — nothing new is persisted (constraint honored).
- **Evidence tiers stay provenance-styled**: attested = neutral chip,
  demonstrated = green, thin = warm caution — tint never upgrades a claim
  beyond its tier, and the tier word is always printed.
- **Hub → curriculum/resources pill links render only in server mode**
  (`api` set): in static single-file renders those siblings may not exist,
  and a dead primary button is worse than none.
- **The "here" ring on the front door is server-rendered static HTML** — the
  index needs no JS at all; L1 stays trivially true (no LLM anywhere near a
  request; all pages are pure functions of manifest + fold).

## Taste forks decided unattended (operator may overrule)

1. **Ground tint: faint peach (`#FDF6EF`) vs pure white.** Chose peach — the
   sunny ground is half the warmth; pure white with the same tokens reads
   more "tool", less "companion". Flipping is a one-token edit in `theme.py`.
2. **Stone shape: rounded lozenge vs circle.** Chose the 20×10 lozenge —
   circles at 26-per-course read as dots/dippers and collide with checkbox
   circles; lozenges read as paving. Alternative kept in mind if the mark
   ever needs animation room.
3. **Time-of-day greeting vs static "Welcome back".** Chose the clock: it is
   the single cheapest genuinely-personal gesture the server can make. If it
   feels too chatty, the static lede "Pick up where you left off." already
   carries the page.
4. **Phase columns down-then-across vs preserving the baseline's row order.**
   Chose columns — **the operator overruled this in review** ("a bizarre way
   of displaying this kind of sequential information"); the composed round
   replaced the layout entirely. See below.

## Deliberately rejected (do not relitigate)

- Mascots, streaks, day counters, XP, badges, confetti — nixed by brief and
  by the direction's own test.
- Serif display, cream-parchment gestalt, letterspaced mono eyebrows — the
  bookish status quo being replaced.
- A second gesture (progress rings were sketched for the phase badges) —
  two gestures compete; the badges stay static numerals.
- Embedded webfonts as data-URIs — pages are self-contained files; paying
  ~100KB+ per page per weight for typography the system stacks nearly match
  is a bad trade under the no-pipeline constraint.

## Composed round (v2) — the hub spine

The operator chose this direction as the base with one emphatic correction:
the hub's masonry phase columns were "very bad … a bizarre way of displaying
this kind of sequential information," and the other two candidates' hubs
(atlas's ruled phase spine, momentum's vertical rail with a now-band) were
named as much closer. This round replaces the layout; the visual system,
waypath, zero state, and front door are untouched by instruction.

**What the hub is now.** The program track is a single vertical spine — one
column, phases in walking order, top to bottom, so sequence is carried by the
layout itself and reading order cannot be ambiguous. A 2px hairline rail
threads the phase badges (the badges are unchanged from round one; they
became the rail's nodes) and ends at the last badge — a path should not trail
past its final marker. Structure is borrowed from atlas/momentum as directed;
the rendering is companion's own: warm ground, the same rounded badges,
hairline rail rather than atlas's cool rule and mono grid references, no
grey-and-orange. Specifically:

- **Unit titles own the line; chips trail inline after the title** (atlas's
  pattern, and what our own curriculum already did in its wide column). The
  under-title chip row existed only to survive the narrow masonry column;
  with the full-width spine it lost its reason.
- **Per-phase counts** ("3 of 4", right-aligned in the phase head, tabular
  numerals) — adopted from momentum; live-updated with every check. Plain
  numerals, no praise-babble: companion's voice.
- **One hot element** (momentum's mechanic): the first undone row is raised —
  panel background, 1.5px `--accent` border (3.31:1 vs panel), quiet shadow,
  a small coral "next" chip so the meaning is worded, not color-alone. The
  phase holding it fills its number badge `--accent-strong` (4.78:1 under
  white numerals). Everything else stays flat on the ground; the spine is
  deliberately not seven stacked cards, which would have been the card
  problem again, vertically.
- **The welcome panel keeps the waypath and gains the now-band's behavior**
  (the dispatch's default, accepted): the summary line already named the next
  item; it now carries a primary **Begin → / Continue →** pill. One element,
  not two — the waypath *is* companion's now-band, and splitting them would
  have said "where you are" twice at the top of a page whose whole spine says
  it a third time. The pill hides on course completion.
- **The continue action deep-links** (momentum's other praised mechanic): in
  server mode to `curriculum.html#u-<id>`; the curriculum resolves the hash —
  an entry id or a step id inside one — opens that entry, and scrolls to it
  (verified by DOM dump: `#u-u4` and `#u-p0-para` both open the right
  entry). In a standalone single-file render the curriculum may not exist
  beside the hub, so the pill jumps down the page to the next row's checkbox
  instead — same promise, honest to the medium.
- **The stone-contrast exception is retired**: lit stones moved from
  `--accent` to `--accent-strong`, 3.48/3.81 vs unlit (see the contrast
  section). This propagates to every waypath — wordmark, front door, meters.

**Zero test changes.** The `PHASES`/`TRACKS` payload shape, storage keys,
checkable ids, and progress-id pins are exactly as before; only the DOM built
from the payload changed. The suite was green throughout, corpus parity
included (the skip that appeared in this round's log was the ml-ai corpus,
resolvable from a worktree since PR 0; today the suite runs 74 tests with no
skips).

**Alternatives decided unattended this round:**

1. *All phases as stacked panels* — rejected: seven full-width cards re-create
   the card-grid feel vertically and flatten the hierarchy the resuming
   learner needs.
2. *A separate momentum-style now-band above the waypath* — rejected in favor
   of merging its behavior into the welcome panel (above); the operator may
   overrule by splitting the pill row into its own strip, which the markup
   makes trivial.
3. *Atlas's proportional per-phase traverse strip and mono `P2·U04` grid
   references* — deliberately not imported: they are atlas's identity, not
   structural logic, and companion already carries position via the waypath
   and numbered badges.

## Left undone / notes

- **Narrow screenshots** (design-branch artifacts; they were review evidence
  and are deliberately not committed here): macOS headless Chrome clamps the
  layout viewport at ~500px. The composed round adopted the iframe harness
  the other directions used, so the narrow shots were **true 420px layouts**
  (a 420px iframe inside a 500px window) and the rest true 500px direct
  renders; widths between 420 and 500 are plain single-column CSS.
- The rhyme-schemer exercise cards have no blurbs in the data, so those cards
  render title-only — slightly bare, honest to content.
- Dark-mode screenshots pin the theme via `data-theme="dark"` on a copied
  file — same tokens the media query serves; a live `prefers-color-scheme`
  toggle was verified by the CSS structure, not by a separate shot.
- Progress-id contracts, storage keys, and event payloads are untouched; all
  74 tests pass including the textual-flow parity pins.
