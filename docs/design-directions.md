# Directions — curricle

Step 4 of `~/.claude/skills/seeded-design`. Prose and hex only; no code is
written until one of these is chosen. Every value below was sampled from the
seed with `scripts/sample.py`; nothing here was picked.

## The seed

| | |
|---|---|
| Artifact | *Thomas Bros. New Block Book of Palo Alto and Vicinity*, title page and colour key, 1925 |
| Source | David Rumsey Map Collection, List No. 13231.002 |
| Licence | Rumsey scans are CC BY-NC-SA — sampling is unencumbered; reproducing the plate in the repo needs attribution and a look at the NC term |
| Chosen because | It is a reference work's own key to reading itself: a page whose whole job is to teach a reader how to navigate the 152 maps behind it. That is curricle's job with a course manifest. |

A second artifact corroborates one hue: the **Sanborn Map Company** endpaper,
1949 (Rumsey 16227.002), whose printed green measures hue 68. The Thomas Bros
wash measures hue 75. Two unrelated American map publishers, twenty-four years
apart, on the same yellow-green — that is independent corroboration, not one
sample.

## What was measured

| role on the plate | seen | ink | share |
|---|---|---|---|
| paper, least oxidised | `#EEE2DA` | | — |
| paper, median (a century of oxidation) | `#E6D2C2` | | — |
| type and rules | `#7C7C7C` | `#241C1C` | 19.1% |
| blue-line print — all structure | `#2C445C` | `#243C54` | 1.5% |
| wash: ochre | `#E4AC4C` | | 8.3% |
| wash: red | `#D41C2C` | `#CC141C` | 3.7% |
| wash: green | `#9CAC6C` | `#8C9C5C` | 2.9% |

Ground is `#EEE2DA`, 89% lightness — the paper as printed, not as it survives.
Separating the stock from the oxidation is a sampling decision, not a taste
one, and it is what makes the ground both lighter than the scan and still
outside the 94–98% band that all three of these products have shared.

Every hue above clears its contrast floor on that ground with **lightness
moves only**; hue and saturation hold at the sampled values.

| hue | sampled | ≥4.5 (text) | ≥3.0 (large / non-text) |
|---|---|---|---|
| 75 green | `#9CAC6C` | `#5D683B` (4.71) | `#77864B` (3.12) |
| 68 green | `#C4CC8C` | `#626A2F` (4.56) | `#7D873B` (3.06) |
| 210 blue | `#2C445C` | `#2D455D` (7.79) | as sampled |
| 38 ochre | `#E4AC4C` | `#855C14` (4.67) | `#AD771A` (3.04) |
| 355 red | `#D41C2C` | `#C71A28` (4.58) | `#D41C2B` (4.13) |

## What the plate does that the colours are not

The plate runs **two colour systems that never mix**. Blue-line print carries
every piece of structure: streets, block numbers, border rules, the index
table. Hand-applied wash carries every piece of meaning: land-use class. A
reader can tell instantly which marks are the map and which are the claim.

And it gets five states out of three washes — green, ochre, red, *red diagonal
hatch*, and *unfilled*. The fourth state is a texture, not a fourth hue.

That is the more valuable half of this seed. curricle already commits, in
CLAUDE.md, to "colour is reinforcement, never the message"; the hatch is the
print-native way to keep that promise, and the structure/semantics split is
the distinction the waypath, the evidence tiers and the checkpoint results all
need and none of them currently draw.

---

## Direction A — Block book

**Seed.** The whole two-system page: blue-line structure over washed
semantics.

**Why this, for this product.** A course manifest is a fixed survey with a
learner's own claims recorded on top of it; the block book is that exact
document, and it keeps the two legible by giving them different inks.

**Palette.**

| role | hex | provenance |
|---|---|---|
| ground | `#EEE2DA` | sampled, least-oxidised paper, 89% |
| ink | `#241C1C` | sampled, type |
| structure | `#2D455D` | sampled, blue-line print, 1.5% |
| state: done | `#5D683B` | sampled hue 75, darkened to clear 4.5 |
| state: attention | `#855C14` | sampled hue 38, darkened to clear 4.5 |
| state: failed | `#C71A28` | sampled hue 355, darkened to clear 4.5 |

**Type.** One reading face, one mono. The plate's own lettering is drawn
sans-serif capitals for structure and nothing else — a specimen to study for
the labels, not to imitate for body text.

**Layout concept.** The page is a survey with an index: content in a ruled
field, navigation as a numbered key beside it rather than a nav bar above it.

**What it would feel like to use.** Unit pages read as sheets in an atlas —
bordered, numbered, with the same rule weight everywhere. The waypath stops
being a progress bar and becomes a block index you can point at.

**Honesty flag.** *Would I have produced any part of this for any brief?*
> The card grid, yes — that survives from the current build and should be
> re-derived or dropped. The blue structure ink and the wash/rule separation,
> no; I would never have proposed a second structural hue unprompted.

**What it costs.** Two strong hues is more than most products can carry. Blue
at hue 210 sits just outside the cobalt band (215–250) and will read as
"blueprint" to some viewers, which is a borrowed identity rather than this
one. It is also the most work.

---

## Direction B — Wash only

**Seed.** The same plate with the blue-line system deleted: neutral ink for
all structure, colour reserved entirely for meaning.

**Why this, for this product.** curricle's stated rule is that colour never
carries the message. This is that rule drawn rather than asserted — if colour
appears at all, it is a claim about state, and nothing else on the page is
allowed to use it.

**Palette.**

| role | hex | provenance |
|---|---|---|
| ground | `#EEE2DA` | sampled, 89% |
| ink | `#241C1C` | sampled |
| muted | `#5E554E` | derived from ink, lifted to clear 4.5 (5.73) |
| rules | derived from ground | — |
| state: done | `#5D683B` | sampled hue 75 |
| state: attention | `#855C14` | sampled hue 38 |
| state: failed | `#C71A28` | sampled hue 355 |
| state: not yet | diagonal hatch, no hue | sampled *device*, 1925 |

**Type.** As A.

**Layout concept.** Rules and fills carry every hierarchy; no elevation
anywhere. Nothing on the page floats, because none of this information floats.

**What it would feel like to use.** Quiet and dense. The only colour on a
typical screen is three or four small state marks, so they actually mean
something. A locked unit is hatched rather than greyed, so its state survives
being printed, screenshotted, or read by someone who cannot distinguish the
hues.

**Honesty flag.**
> The neutral-ink-plus-one-accent shape is close to something I would produce
> unprompted, and that is the risk in this direction. What is not default is
> the hatch as a first-class state and the refusal to spend colour on chrome.
> If those two are cut in implementation, this collapses into a default and
> should be abandoned rather than shipped.

**What it costs.** No brand colour. There is no single hue a person would name
if asked what colour curricle is. That is a real loss for a public
open-source project that people encounter as a README screenshot.

---

## Direction C — Trellis

**Seed.** The corroborated green alone — Thomas Bros wash at hue 75, Sanborn
printed endpaper at hue 68 — taken up to primary, with the plate's structural
logic (rules, not shadows) retained.

**Why this, for this product.** A trellis is a rigid lattice supporting
unplanned growth: the manifest is authored and fixed, the event ledger
accumulates over it. The structure is the product's promise, and the green is
the one hue two independent sources put outside every burned band.

**Palette.**

| role | hex | provenance |
|---|---|---|
| ground | `#EEE2DA` | sampled, 89% |
| ink | `#241C1C` | sampled |
| accent | `#626A2F` | sampled hue 68, Sanborn ink, darkened to clear 4.5 |
| accent, at mark weight | `#7D873B` | same hue, 3.06 on ground |
| state: attention | `#855C14` | sampled hue 38 |
| state: failed | `#C71A28` | sampled hue 355, rare by construction |

**Type.** As A.

**Layout concept.** A lattice: fixed vertical structure, content attached at
the crossings.

**What it would feel like to use.** One colour does the work, and it is a
yellow-green nobody else is using. Red appears only on a genuine failure, so
seeing it means something.

**Honesty flag.**
> A single accent on a light ground is the default shape, and I would have
> produced it for any brief. What rescues it here is the specific hue and its
> provenance, not the structure. If the name does not land, this direction
> loses most of its reason and should be folded into B.

**What it costs.** It leans on the rename. It also inverts the plate's own
hierarchy — on the map, green is one ordinary category among three, not the
protagonist — so the seed licenses the hue but not the emphasis.

---

## For the human

- **The accent-role fork is real and is yours.** On the plate, red is the loud
  colour and green and ochre are ordinary. In curricle the ordinary state is
  the common one, so whichever direction wins, something has to invert the
  plate's proportions. A says structure is blue and states are equal; B says
  nothing is loud; C promotes green and demotes red to alarm. Pick the
  inversion deliberately rather than discovering it in CSS.
- Killing all three is a valid outcome and means the seed was wrong.
- Mixing structure from one and colour from another is allowed. Mixing
  palettes is not — it produces the median, which is what we are leaving.
- The question worth asking of each: *could a competitor ship this?*

## Audit

```
python ~/.claude/skills/seeded-design/scripts/audit.py \
  --hex bg=#EEE2DA line=#2D455D ochre=#E7B151 red=#CF1B27 green=#99AB69
```

One FLAG, accepted with reason: the ochre wash at hue 38 falls inside the
10–45° burned band. It is sampled, it is the third colour in a five-state
system, and it is never the accent in any direction above. Recorded here so
the next reader sees the reasoning rather than the value.
