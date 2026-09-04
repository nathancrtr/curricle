# Direction: block book — a survey with your own marks on it

This is the design rationale for curricle's design system: the signature
gesture, the judgment calls, the contrast provenance, and what was rejected
and why. It records three rounds. The first two — *companion*, on a warm
cream, and *verdigris*, on a mineral near-white — are retired, and the
sections below that describe them are kept deliberately: both were produced
by picking the most plausible-looking palette, both landed on a default, and
the second landed six channel-units from a sibling project's shipped accent
while claiming to escape the first. The current round is **block book**,
seeded from an artifact outside the model; `DESIGN.md` at the repo root holds
its provenance, token by token, and this file holds the reasoning.

`curricle/theme.py` is the single source of
tokens: `hubrender`, `currender`, `resrender`, `profilerender` and the front
door all compose `theme.style(own_css)` and none defines a palette, so a
palette edit really is one edit. `tests/test_theme.py` recomputes the contrast
table below from the hex values in `theme.py` and asserts each pair against its
floor, and guards every stylesheet for undefined tokens and for `--faint` on
copy — the numbers here cannot drift from the code without the suite saying
so.

## Thesis

curricle should read as a **survey with your own marks on it**. A course is an
authored manifest that does not change and an append-only ledger that does,
and the interface should keep those two things visibly separate — the way the
1925 Thomas Bros. block book that seeds this design keeps them separate, with
blue-line print carrying every rule, frame and block number and hand-applied
wash carrying every claim about what a block *is*.

That gives the palette a job rather than a mood. `--accent` is the structural
ink: rules, numbers, the waypath, and the primary action, because on the plate
the ink that draws the map is also the ink that points. The wash family is
state and nothing else. Nothing floats, nothing is rounded, and colour never
appears as decoration — if it is there, it is either structure or a claim.

The register this aims at is a working document, not a friendly app and not a
bookish one. The two retired rounds each missed in one of those directions.

## The signature gesture: **the waypath**

A ruled, segmented progress path — one square "stone" per tracked item, drawn
as a block-book tick: outlined for ahead, filled for done, ringed for here —
rendered identically wherever anything is tracked: the front door (a mini path per
course card), the hub's welcome panel, the curriculum meter, the resources
core-path meter. Three rules give it its meaning:

1. **Zero is a path, not a void.** At 0/26 the entire path renders as visible
   unlit stones with the copy "**The path is laid.** 26 steps from here to
   done — begin with …". The old design's invisible `0/26` bar is replaced by
   the strongest moment on the page.
2. **You are here.** The next undone stone is a hollow accent ring — the only
   outlined stone — so resuming ("where was I?") is answered before a word is
   read.
3. **Completion is felt once.** A stone fills with `--accent-strong` *only
   when its state changes in-session* (`theme.WAYPATH_JS` tracks prior
   state); a page load never animates. Guarded by `prefers-reduced-motion`.
   The mark no longer *pops*: a scale-and-spring was the friendly-app reflex
   and the last piece of the retired direction still moving. It now flashes
   a held outline twice, in the register of a form being stamped.

The wordmark is the gesture in miniature: three square ticks — lit, ring,
unlit — before the word "curricle". The mark and the product promise are the same
drawing, which is why there is no second illustration idea anywhere (the one
exception: a small drawn flag for milestones, see below). It is drawn once,
as `theme.WORDMARK` beside the tokens; the front door and the onboarding
wizard both spend that one string, because two surfaces drawing the same mark
from two copies is how a mark drifts.

Where the gesture does **not** go: the profile page tracks nothing, so it gets
no waypath. A gesture applied where it isn't true is decoration. Where it
*does* go, and did not until the design review: the onboarding wizard (see
"Onboarding" below) — a ledger, a fold and a derived "you are here" is the
most literally tracked thing in the product.

## Where the line is drawn (the infantilization test)

The learner has a linguistics degree and a two-year plan. Everything below was
chosen to read as *hospitality to that person*:

- **Copy is plain second person, no exclamation points, no praise-babble.**
  "Welcome back. 3 of 26 done · next up: …" / "Every step walked." / "Good
  evening, sam." The greeting is computed from the actual clock — a real
  courtesy, not a sticker.
- **No guilt surface exists.** Nothing counts days away, nothing decays,
  the zero state is framed as a beginning, and the "empty" filter state says
  "everything here is done", not "nothing left!".
- **One micro-animation** (the stone fill), under half a second, only on an
  earned event. No confetti, no bouncing — see the note under the gesture.
- **Square ≠ severe.** Radii are zero and elevation is gone, because the seed
  has ruled fields rather than floating cards. The discipline is carried by
  rule weight and generous spacing, not by softened corners; the voice stays
  level and the colour stays a claim rather than a mood.

## The token system (`curricle/theme.py`)

The four independent `STYLE` blobs are gone. `theme.py` is the single source:
`TOKENS_CSS` (light + dark variables), `BASE_CSS` (shell, panel, chip, pill,
wordmark, waypath, toast), `WAYPATH_JS`, the `WORDMARK` drawing, the
milestone `FLAG_SVG`, and `strip_leading_pictograph`. Every renderer composes `theme.style(own_css)`;
`webapp.py`'s front door draws from the same module. A palette change is now
one edit.

### Type

- Body: a grotesque stack — `"Helvetica Neue", Helvetica, "Segoe UI", Roboto,
  Arial, system-ui` — at 16px/1.6. No font pipeline (constraint honored).
  A grotesque rather than a humanist face because the seed's own lettering is
  drawn sans capitals doing structural work.
- Display (`h1–h3`): **the same stack**. `FONT_DISPLAY` has now shed two
  faces for the same reason. It led with `ui-rounded` under the warm round —
  the friendly-app reflex in the open — and with Avenir Next under the
  verdigris round, which was the same reflex wearing a quieter coat. One
  family separated by size, weight and tracking is the disciplined answer
  where there is no pipeline to spend. The constant survives because it names
  the *role*: the day a display face earns a pipeline, it changes in one
  place.
- **The open decision.** The honest answer is Archivo, with Archivo Narrow
  for structural labels: one family at two widths, which is the plate's own
  logic, and an American grotesque from the same commercial-lettering line.
  That needs vendored woff2 in the package — a self-hosted app should not
  phone out to a font CDN — and the pipeline is a separate decision from the
  palette. `DESIGN.md` records it as open.
- Mono only for things that are literally typed (trigger phrases, code).
- **No letterspaced uppercase anywhere.** The eyebrow vocabulary
  (`BUILD`, `READ`, `MILESTONE`, `PHASE 1 CHECKPOINT`, `HOW THIS CURRICULUM
  WORKS`) was declared removed in the first round and was still in four
  renderers; it is gone now, replaced by sentence-case bold at a size a
  person reads rather than squints at. Tracked small caps is the single most
  legible signature of a template, and it was labelling content the author
  had already capitalised correctly.

### Color

The palette is **two systems wide**, and that is the whole idea — it is the
seed's idea, not a preference. **The blue-line print is structure and action**
(rules, frames, unit numbers, the waypath, primary buttons, links).
**The wash family is state** and appears nowhere else: green for done, ochre
for costs and caution. A reader can tell at a glance which marks are the map
and which are the claim, which is precisely what the 1925 plate is built to
let a surveyor do.

Every hue below traces to a pixel; `DESIGN.md` names which. Only lightness and
chroma were moved, and only to clear a floor. The dark theme is **derived, not
seeded**: no dark-ground artifact was sampled, hues are held and lightness is
inverted, and that is recorded rather than presented as provenance.

This is the third round, and the first two are worth keeping on the record
because both were competently built and every contrast pair in both passed.

The **warm round** — peach ground, brown ink, coral accent — was the model's
default. Cream-and-terracotta with a warm brown ink is what an LLM reaches for
unprompted, to the point that two unrelated products built the same month
landed on near-identical values; the owner recognised it across his own tools
before anyone else did.

The **verdigris round** is the more instructive failure. It was produced
specifically to escape the warm round, by a process that included a contrast
solver and a written rationale, and it shipped an accent six channel-units
from a sibling project's live accent and an ink identical to that project's.
Rejecting a default does not leave the ranked list; it advances down it.
Cobalt, the candidate rejected in that round, used *exactly* the sibling's
ink — the rationale even called it "the other default" and shipped anyway.

What changed this round is not taste but method: the palette is sampled from
an artifact outside the model, and the values are audited against a register
of everything this author has already shipped. See `DESIGN.md` and
`~/.claude/skills/seeded-design`.

| token | light | dark | role |
|---|---|---|---|
| `--bg` | `#F4F2F1` | `#1C1917` | page ground — near-white by decision, see `DESIGN.md` |
| `--panel` | `#EAE6E3` | `#272320` | fields — **darker** than the ground in light |
| `--ink` | `#241C1C` | `#E6E2E0` | body text |
| `--muted` | `#6E645E` | `#A89F99` | secondary text (AA at any size) |
| `--faint` | `#958A83` | `#6E645E` | decorative marks only (see contrast note) |
| `--line` / `--line-soft` | `#D8D0CB` / `#E7E2DF` | `#3D3733` / `#2F2B27` | decorative hairlines |
| `--edge` | `#8F7C70` | `#7B6E65` | edges of controls you type into |
| `--accent` | `#2D455D` | `#5587B9` | the blue-line print: rules, borders, hovers |
| `--accent-text` | `#2D455D` | `#7DA8D4` | links & small accent text |
| `--accent-strong` | `#213345` | `#A3C2E0` | button fills carrying `--on-accent`; lit waypath ticks |
| `--accent-soft` | `#E4EBF1` | `#243342` | the blue at wash weight |
| `--good` / `--good-text` / `--good-soft` | `#7A894D` / `#606C3D` / `#E5EAD7` | `#6A7740` / `#9AAE61` / `#303522` | the green land-use wash: done, checkpoints, free |
| `--warn-text` / `--warn-soft` | `#8A5F15` / `#F6E6CB` | `#CD9637` / `#3B2E16` | the ochre wash: paid, thin evidence |
| `--chip` | `#EBE7E5` | `#34302D` | neutral chip fill |
| `--stone` | `#6D8FB0` | `#4D6984` | the unlit waypath tick — an outline, not a fill |

**Red is reserved and unspent.** The plate's vermilion (hue 355) is sampled
and recorded but is not a token, because nothing in the product currently
surfaces a failure state. It is what to reach for when one appears, rather
than a new hue chosen at that moment.

### Shape

Radii are **zero**, spelled as three tokens and asserted by
`tests/test_theme.py`: `--r-card`, `--r-ctl`, `--r-chip`, all `0px`. The seed
is a block book, and a block book has ruled fields — a bordered, numbered
box on paper — not rounded cards.

The scale has now been walked all the way down. The first round had eleven
distinct hard-coded radii across the renderers, an 18px card and a 999px pill
on more or less anything holding text, which is the point at which "rounded"
has stopped being a decision and become a habit. The second round replaced
that with a disciplined three-step scale, which was a real improvement and
still a rounded-card system. This round removes the axis: hierarchy is carried
by rule weight and fill, as it is on the plate, where a heavier rule means a
larger division and a wash means a classification.

The three tokens stay, spelled everywhere they were, so the decision is
revisitable in three lines rather than forty.

Elevation is **none**. `--shadow` and `--shadow-lift` resolve to `none` in
both themes. A card on a tinted ground with a hairline does not need a shadow
to be read as a card; nothing on a printed sheet floats, and the two-layer
soft shadow under every panel was the same "floating card" move the radii
were making. The waypath tick is a square because the seed's ticks are ruled
boxes, and it is the one shape in the system that carries meaning rather than
tone.

Spacing/elevation: controls keep ≥34–38px hit height; checkboxes and radios 17–18px
with `accent-color`. **Control edges are `--edge`, never `--line`** — a
text box, a number box and the wizard's radio cards draw their boundary with
a token computed against the 3:1 non-text floor, while `--line` stays the
decorative hairline it was validated as (it computes 1.30 light / 1.31 dark
on `--panel`, which is a box you cannot see). Dark theme ships under both
`prefers-color-scheme` and an explicit `data-theme` attribute (same tokens;
the attribute exists so a toggle or a test can pin either theme).

## Contrast — computed, not eyeballed

WCAG relative-luminance ratios, floors: 4.5 text, 3.0 large text/meaningful
non-text. The provenance lives in the repo as `tests/test_theme.py`, which
recomputes the ratios from the hex values in `theme.py` and asserts each pair
below against its floor. A token edit that breaks a floor fails the suite.

| pair | light | dark | floor |
|---|---|---|---|
| ink on bg | **14.96** | **13.59** | 4.5 |
| ink on panel | **13.46** | **12.11** | 4.5 |
| ink on chip | **13.59** | **10.16** | 4.5 |
| muted on bg | **5.16** | **6.73** | 4.5 |
| muted on panel | **4.64** | **6.00** | 4.5 |
| muted on chip | **4.69** | **5.03** | 4.5 |
| accent-text on bg | **8.87** | **7.02** | 4.5 |
| accent-text on panel | **7.98** | **6.25** | 4.5 |
| accent-text on accent-soft | **8.23** | **5.18** | 4.5 |
| good-text on panel | **4.56** | **6.38** | 4.5 |
| done mark (good) vs panel | **3.07** | **3.21** | 3.0 |
| done mark (good) vs bg | **3.41** | **3.60** | 3.0 |
| good-text on good-soft | **4.60** | **5.19** | 4.5 |
| warn-text on panel | **4.54** | **5.95** | 4.5 |
| warn-text on warn-soft | **4.59** | **5.05** | 4.5 |
| on-accent text on accent-strong | **10.42** | **9.45** | 4.5 |
| accent fill vs bg (non-text) | **8.87** | **4.62** | 3.0 |
| accent fill vs panel (non-text) | **7.98** | **4.12** | 3.0 |
| lit tick (accent-strong) vs unlit tick | **3.82** | **3.09** | 3.0 |
| lit tick (accent-strong) vs bg | **11.59** | **9.45** | 3.0 |
| hot ring (accent-strong) vs milestone fill (good-soft) | **10.52** | **6.85** | 3.0 |
| faint on bg (decorative only) | **3.02** | **3.04** | 3.0 |
| unlit tick outline vs bg | **3.03** | **3.06** | 3.0 |
| edge on panel (control boundary) | **3.20** | **3.16** | 3.0 |
| edge on bg (control boundary) | **3.56** | **3.55** | 3.0 |

Two audit-driven fixes: every small-text use of `--faint` (eyebrow labels,
citations, row labels, unit numbers, sources) was promoted to `--muted`
because faint-on-panel does not clear the 4.5 text floor (4.27 under the
retired warm palette, 3.48 under this one); `--faint` now colors only
decorative marks (separators, arrows, the entry dot ring). The floor is the
rule, not the number, so the promotion stands whatever the palette.
And **lit vs unlit ticks**: this has been the tightest pair in every round.
Round one accepted 2.41 (light) as an `aria-hidden` exception; the composed
round retired the exception by filling lit stones with `--accent-strong`. The
block book round keeps that rule and inherits the headroom — **4.65 light /
3.66 dark** — because the unlit tick is now an *outline* in `--stone` rather
than a fill, so the two states differ by drawing as well as by value. The
waypath remains `aria-hidden` decoration always paired with a text count.

**Placeholder text is not decorative.** An earlier draft of this section
listed it with the separators and arrows, and `textarea::placeholder`
accordingly took `--faint` over `--panel` — the same shortfall that
disqualified `--faint` from small text three sentences earlier. Placeholder
copy is instruction, read to be acted on, so it takes `--muted` (5.97 on
panel). Every
renderer inherits that as a requirement, not as a pre-blessed exception.

## Judgment calls (say-it-out-loud reasons)

- **Hub h1 is the course title, not the slug.** "textual-flow" as a page
  title reads as infrastructure; the slug demotes to a small line under it.
- **Nothing is marked by tint alone, and less is marked by tint at all.**
  Three tinted things were retired in the structural round. *Phase and tier
  numeral badges* gave up their `--accent-soft` fill: a phase number is an
  ordinal, not a status, and tinting seven of them spent the accent —
  which means "your next action" — on the one element on the page that is
  never the answer to "what now". They keep their shape, because the hub's
  rail needs a node; the phase holding the hot row still fills, because
  that one *is* a status. *Callout blocks* (key insight, deliverable,
  checkpoint, milestone) gave up their pastel fills for a 2px left rule
  and the label they already carried in words — four different tints down
  one page is a page that looks colour-coded without any colour meaning
  something a reader could name. *The curriculum's highlighter sweep* moved
  from `--accent-soft` to the done family: it fires on completion, so it
  was the one animated gesture in the product spending the accent on the
  opposite of what the accent means.
- **The eyebrow is navigation, and only navigation.** It used to chain page
  facts onto the end of the breadcrumb with middots — "the curriculum · 7
  phases · 23 units", "unit 02 · phase 1", "the learner profile · tenant
  nathan" — which reads as one list but is two things: where you can go
  back to, and what you are looking at. The facts moved to a `.pagefacts`
  line under the title, the separator became the slash a breadcrumb has
  always used, and the crumb that said "phase 1" went entirely, because the
  page says that in a full sentence two lines further down.
- **No trailing arrow on an action.** "Begin →", "Unit page →", "Open the
  widget →", "Save this screen →" — twenty-one of them across the
  renderers and the wizard. The verb already says the direction; the glyph
  is decoration that every generated interface is currently wearing. The
  external-link ↗ on resource links stays, because that one is a
  convention carrying information the label does not.
- **Unit pagination names its destination.** The prev/next pills were a
  glyph plus a title clipped at 46% with an ellipsis, which is to say: the
  arrow said the direction and the ellipsis ate the destination. They are
  now two bordered cards labelled "Previous" and "Next" in words, with the
  title free to wrap — which a screen reader can also read.
- **Chips live under the unit title, never beside it** (hub). Chips beside the
  title crowded it out of its own line; the title owns the full column width
  and chips are a second line of metadata. In the curriculum's single wide column they stay
  inline, where there is room.
- ~~Phase cards flow in CSS columns~~ — **reversed in review and replaced in
  the composed round** (see "Composed round" below). The columns
  packed evenly but made the top row read 0, 2, 4 and put sequential content
  in a card grid; the hub is now a single vertical spine.
- **Milestones get the product's one drawn glyph** — a small flag in
  currentColor — plus a green-tinted row. The one such label in the corpus —
  textual-flow's `p2-mail`, "📮 Contact milestone: INTF +
  McCollum emails sent" — has its leading `📮` normalized away at render time
  (`strip_leading_pictograph`, leading pictographs only; emoji inside prose
  are the author's business). This is presentation normalization of
  decoration living in content, not a content edit.
- **Widget/quiz card titles are ink with an accent ↗**, not accent wholesale —
  six saturated titles in a grid would compete with the accent's single
  meaning.
- **Tag chips no longer carry meaning by color alone**: every chip keeps its
  text label; tints come from the semantic families (`widget` = accent because
  it is the interactive thing; free/paid = green/warm; the rest neutral).
- **The front door** — the product had none — is the direction stated in one
  screen: wordmark, time-of-day greeting, one card per course with title,
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

## Taste forks decided unattended (reversible)

1. **Ground tint — settled, no longer a fork.** This was decided unattended
   twice (mineral grey-green over white, then warm cream over both) and both
   times the decision was really "some near-white", which is the value the
   cross-project register flags. It is now a recorded decision with sampled
   provenance and an accepted audit flag: `#F4F2F1`, hue 24, lightness and
   chroma derived. See `DESIGN.md`, settled decision 1. Do not reopen it from
   a diff.
   The consequence worth remembering: on a near-white ground `--panel` cannot
   be lighter — it computes 1.06 and the field stops existing — so it steps
   *down*, which is also what a washed block does on a printed sheet.
2. **Stone shape: square tick vs rounded lozenge vs circle.** Now the square.
   Circles at 26-per-course read as dots and collide with checkbox circles;
   the lozenge read as paving and belonged to the retired direction. The
   block-book tick is a ruled box, and unlit is an *outline* rather than a
   fill, so ahead-versus-done differs by drawing and not only by value —
   which is where the tightest contrast pair in the system got its headroom.
3. **Time-of-day greeting vs static "Welcome back".** Chose the clock: it is
   the single cheapest genuinely-personal gesture the server can make. If it
   feels too chatty, the static lede "Pick up where you left off." already
   carries the page.
4. **Phase columns down-then-across vs preserving the baseline's row order.**
   Chose columns — **reversed in review**: a card grid is a bizarre way of
   displaying this kind of sequential information, and the composed round
   replaced the layout entirely. See below.

## Deliberately rejected (do not relitigate)

- Mascots, streaks, day counters, XP, badges, confetti — excluded by
  requirement and by the direction's own test.
- Serif display, cream-parchment gestalt, letterspaced mono eyebrows — the
  bookish status quo being replaced.
- A second gesture (progress rings were sketched for the phase badges) —
  two gestures compete; the badges stay static numerals.
- Embedded webfonts as data-URIs — pages are self-contained files; paying
  ~100KB+ per page per weight for typography the system stacks nearly match
  is a bad trade under the no-pipeline constraint.

## Composed round (v2) — the hub spine

Decided in review: companion is the base, with one emphatic correction — the
hub's masonry phase columns were "very bad … a bizarre way of displaying this
kind of sequential information," and the other two candidates' hubs (atlas's
ruled phase spine, momentum's vertical rail with a now-band) were much closer.
This round replaces the layout; the visual system, waypath, zero state, and
front door are untouched.

**What the hub is now.** The program track is a single vertical spine — one
column, phases in walking order, top to bottom, so sequence is carried by the
layout itself and reading order cannot be ambiguous. A 2px hairline rail
threads the phase badges (the badges are unchanged from round one; they
became the rail's nodes) and ends at the last badge — a path should not trail
past its final marker. Structure is borrowed from atlas and momentum; the
rendering is companion's own: warm ground, the same rounded badges,
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
  a small accent "next" chip so the meaning is worded, not color-alone. The
  phase holding it fills its number badge `--accent-strong` (4.78:1 under
  white numerals). Everything else stays flat on the ground; the spine is
  deliberately not seven stacked cards, which would have been the card
  problem again, vertically.
- **The welcome panel keeps the waypath and gains the now-band's behavior**:
  the summary line already named the next item; it now carries a primary
  **Begin → / Continue →** pill. One element,
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

**The payload is untouched.** The `PHASES`/`TRACKS` payload shape, storage
keys, checkable ids, and progress-id pins are exactly as before; only the DOM
built from the payload changed. The layout is a rendering decision and owes the
ledger nothing.

**Alternatives decided unattended this round:**

1. *All phases as stacked panels* — rejected: seven full-width cards re-create
   the card-grid feel vertically and flatten the hierarchy the resuming
   learner needs.
2. *A separate momentum-style now-band above the waypath* — rejected in favor
   of merging its behavior into the welcome panel (above); splitting the pill
   row into its own strip stays trivial in the markup if that is reversed.
3. *Atlas's proportional per-phase traverse strip and mono `P2·U04` grid
   references* — deliberately not imported: they are atlas's identity, not
   structural logic, and companion already carries position via the waypath
   and numbered badges.

## The material contract (materials go native)

The factory's material roles inherit this contract for everything they
generate next.

A served material — widget, quiz, trainer — is a curricle surface, not a
guest. The contract is three visible lines, never injected machinery:

1. **`<link rel="stylesheet" href="../../theme.css">`** (path-relative to
   the course root) and **no local chrome palette**: the material's own
   `<style>` holds layout and mechanics only, spelled in theme tokens. Both
   themes arrive free; a material defining its own `--bg` is the same bug as
   a renderer keeping its own `:root`.
2. **The eyebrow crumb** replaces any bespoke nav or toolbar: back to the
   course hub, then the nearest home (its unit page, or the curriculum).
   Course-local theme toggles go too — one platform, one theming rule
   (system preference, `data-theme` to pin); rhyme-schemer's toolbar toggle
   was the case that decided this.
3. **One report, at the one completion moment**, for anything that *has*
   one: `<script src="../../material.js">` and a single
   `curricle.checkpoint("<material id>", {score, total, misses})` when the
   last question locks. The id is written in the file, visibly; the server
   validates it against the manifest, so a typo is a 422, not silent loss.
   **Endless drills do not report** — a streak trainer has no result, only
   a running feedback loop, and a ledger row per drill round would flood
   the profile's proposal queue with noise the learner must then triage.
   (greek-alphabet-trainer is the canonical non-reporter.)

**Data ink stays local.** A material's content colors — reading tints, a
vowel-space's category hues — are what the material is *about*, not chrome.
They live in the material as its own token pairs (light + dark blocks,
same shape as theme.py's), and legacy names the drawing code references
(`--warn`, `--accent-ink`) are aliased onto theme tokens rather than
renamed, keeping migrations stylesheet-sized. The theme deliberately does
not grow tokens for one widget's data.

Materials are **server-required** by decision: they may assume theme.css
and material.js exist beside the course. Opened as bare files they still
function (the shim guard is `window.curricle &&`), they just render
unthemed and tell no one. The static export, when it arrives, bundles both
files rather than reopening this.

## The unit page flows

Clicking a unit lands on one readable document that walks end-to-end, not a
stack of link dumps. Decisions taken:

- **Content links by reference, not URL** (schema-spec rule 4, now real):
  `[W&G](res:wg)`, `[Unit 8](unit:u8)`, `[the trainer](mat:t-alphabet)`,
  `[the readme](repo:README.md)` in any content field. The compiler refuses
  a dangling target; each renderer resolves for its own medium (`refs.py`) —
  served pages route markdown through the reader, standalone files link the
  honest nearest thing. A resource whose only URL is an identifier
  (`urn:isbn:`) resolves to its shelf entry instead of pretending to be a
  link. A ref rendered with no resolver degrades to its label as plain
  text — never a dead `href="res:wg"`.
- **The Interactive row is derived, never authored** (spec rule 2 applied
  at last): the curriculum computes it from material attachments — kind in
  words, title as the link. An authored row still renders (and suppresses
  derivation) so an unmigrated course is honored, but the compiler warns it
  into retirement. The unit page drops the row entirely: the material cards
  *are* that row, richer.
- **Material cards lead with the thing's name.** The verb ("Take the quiz")
  demoted from `<h3>` to the action line; a grid of four headings now reads
  as four materials, not four imperatives.
- **The Milestone row takes the done family** — the neutral fill that means
  "done" everywhere else, because the milestone is what done will mean
  here. `Key insight` keeps the accent tint; every other row stays plain.
- **The page carries what the sidecar always knew**: the phase goal under
  the masthead, a context line in words (builds on →, load-bearing /
  safe-to-skim, skippable-when, gated · pending), and the per-unit note.
  Words first, chips as reinforcement, per the house rule.
- **Checkpoint prose lands on the phase-closing unit** — the unit that ends
  a phase renders the full checkpoint (prose, track goals, quiz); earlier
  units get the one-line "builds toward it" strip. The checkpoint belongs
  to the walk, not to every page equally.
- **The unit page gets no waypath.** It tracks one unit's mark and its steps;
  a path gesture there would claim more than the page tracks, and the mark pill
  plus live step checkboxes are the honest amount of liveness.
- **A lesson guide announces what it is.** The reader banners it as a dialogue
  script written for a tutor to run, because an in-browser tutor would put an
  LLM on a request path and L1 is settled: the reader presents the script, the
  learner's own assistant runs it.
- **The path continues at the bottom**: prev/next pills in walking order
  (next is the primary pill — the accent = your next action), and the reader
  ends with "Back to Unit N", so a lesson is a loop through the unit, not
  a dead end. The reader's dialogue banner retargets the course's trigger
  phrase to the unit at hand ("Teach me Unit 6 interactively", not the
  phrase's hard-coded example unit).
- **`repo/` serves exactly what the manifest names.** Repo-level documents
  (REVIEW.md, a `repo:` target) are served through the themed reader — but
  only paths the compiler blessed. The course repo holds more than the
  course (gitignored seeds, keys, `.git`), so "whatever is on disk" was
  never on the table.

## Onboarding (the design review's second batch)

The wizard is the first ten minutes anybody spends with curricle, and it was
built before this direction had been applied to a form. A live art-direction
review of all fifteen stops produced four taste forks; all four were decided in
review, and they are the design now rather than a recommendation.

- **The masthead is the mark and the waypath** (fork A, over "keep the chip
  strip" and "words only"). Wordmark → six `.wp-stone`s, server-rendered, lit
  behind you, the hollow ring on the stop you are at → one line of words
  ("Step 1 of 6 · Your learner profile — screen 2 of 4"). The chip strip and
  its second position line are gone: two progress idioms in a product whose
  personality is one move plus discipline is one idiom too many, and the
  strip was inert for the first six screens while the line under it did all
  the moving. The counter-argument the code used to carry — that the waypath
  means "a path you will walk" and the setup is walked once — lost to the
  house rule it was arguing against: *the waypath goes wherever something is
  genuinely tracked*, and the stones a learner watches fill across six stops
  are the stones the hub lays out on the far side. The hand-off is the
  gesture. No script: `WAYPATH_JS` lights a stone while you watch, and
  nothing here changes without a page load. The stones are `aria-hidden` and
  each carries its position in a visually-hidden word, because a ring a
  screen reader cannot read is a position only some readers get.
- **The read-back is split, not rendered** (fork B, over "raw mono" and
  "rendered markdown with the source behind a disclosure"). The projection is
  still shown whole and is still the exact file a model reads — one renderer,
  `profilerender.skill_parts`, which is `render_skill_md` before its own join
  — with curricle's frame in the mono it always was and the learner's own
  sentences in body type. A caption says which is which in words, because a
  distinction carried by type alone is one some readers never get. The lede
  used to claim the document was generated "from your claims, and from
  nothing else", four lines above two paragraphs curricle wrote; that clause
  is gone. Publish is drawn above the document as well as below it.
- **Examples collapse once a field is answered** (fork C). The two example
  claims per field teach a register; once a learner has written in it they
  have done their job, and four fields' worth of them is the difference
  between a screen you read and a screen you scroll. A `<details>` whose
  `open` comes off the fold — no script, no cookie, same rule as everything
  else on these pages.
- **Three panels on the welcome screen** (fork D — **decided in review against
  the art director's recommendation**, which was to make the
  never-promises the *only* panel and let the two explanations sit on the
  ground, on the grounds that the promises are what a stranger is there to
  check). Three sibling sections now read as three siblings.

Two hierarchy fixes ride along on the same batch. The outline gate says the
estimate under the lede as well as inside the card — Stop 0 promises "a
screen that shows the number first", and first had come to mean "after three
thousand pixels of outline" — and the course's own title is a display `h2` on
the ground above the phase panels rather than an `h3` in a card identical to
them, with the count line under the title it counts. Both copies of the
number are drawn by `estimate_cost`, so the lede and the card cannot come to
say different things about one payload, and a row carrying no estimate draws
neither rather than "about $" with nothing after it. The welcome screen's
money promise was reworded to what is true: the expensive stage is approved
against a number, the outline runs under a budget of its own, and both are
itemised on the landing, which is the clause that makes the promise
checkable.

The cost card itself came out of the same review with three corrections.
The two figures are not the same size — the estimate keeps display size and
the headroom steps down one, because at equal weight the eye takes the
largest number on a card as the price and the headroom is the one figure
there that is not the cost. The paragraph under them is two sentences, one
per figure; the runner's mechanism (a check before every call, a call under
way finishing) is written down in `docs/onboarding-design.md` and not
recited on the screen where the decision is taken. And the plan is a list of
things being bought rather than five bold lines that read as five headings:
body weight, the detail muted, under one short line — "What that buys:" —
that hinges the money to what it is for. (A stylesheet is served, so the
comment explaining any of this may not carry an example figure: a number in
a CSS comment is a number on the page.)

## Left undone / notes

- The rhyme-schemer exercise cards have no blurbs in the data, so those cards
  render title-only — slightly bare, honest to content.
- Progress-id contracts, storage keys, and event payloads are untouched by the
  design system: nothing here is allowed to become a reason to migrate a
  learner's state.
