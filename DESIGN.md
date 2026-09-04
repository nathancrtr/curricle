# DESIGN.md — curricle

The design contract. Later work reads this rather than re-deciding. A value
that is not here was not decided; a value here without provenance was chosen,
which is the one forbidden move.

Produced with `~/.claude/skills/seeded-design`. `DIRECTION.md` holds the
rationale and the rejected forks; this file holds the provenance.

## The subject

A learning platform for one adult working through a hard technical subject
over months, by building the thing being studied. A course is an authored
manifest — phases, units, steps, sources, checkpoints — that does not change,
and an append-only ledger of what the learner did, which does. Every screen is
some view of a fixed survey with a person's own marks on top of it.

## The seed

| | |
|---|---|
| Artifact | Thomas Bros. *New Block Book of Palo Alto and Vicinity*, title page and colour key, 1925 |
| Source | David Rumsey Map Collection, List No. 13231.002 |
| Licence | CC BY-NC-SA. Sampling is unencumbered; the plate is **not** reproduced in this repository |
| Chosen because | It is a reference work's own key to reading itself — a single page whose job is to teach a reader how to navigate the 152 maps behind it. That is this product's job with a course manifest. |

One hue is corroborated by a second artifact: the **Sanborn Map Company**
endpaper, 1949 (Rumsey 16227.002), whose printed green measures hue 68 against
the Thomas Bros. wash at hue 75. Two unrelated American map publishers,
twenty-four years apart, in the same family.

**The dark theme is derived, not seeded.** No dark-ground artifact was
sampled. Hues are held from the light theme and lightness is inverted with the
same floors asserted. That is a set of decisions nobody sourced, and it is
recorded here so the next reader does not mistake it for provenance.

## What the plate does, beyond colour

It runs **two colour systems that never mix.** Blue-line print carries every
piece of structure — streets, block numbers, border rules, the index table.
Hand-applied wash carries every piece of meaning — the land-use class. A
reader can tell at a glance which marks are the map and which are the claim.

It also gets five states out of three washes: green, ochre, red, *red diagonal
hatch*, and *unfilled*. The fourth state is a texture, not a fourth hue.

Both ideas are load-bearing here. The structure/semantics split is the
chrome-versus-state distinction the waypath, the evidence tiers and the
checkpoint results all need. The hatch is the print-native way to keep this
project's existing promise that colour is never the message.

## Tokens

Every row names where the value came from. **`sampled`** means a pixel on the
plate. **`derived`** means a sampled hue with lightness or chroma moved to
clear a floor. Hue is never invented.

| token | light | dark | provenance |
|---|---|---|---|
| `--bg` | `#F4F2F1` | `#1C1917` | hue 24 sampled (paper); **lightness and chroma derived** — see below |
| `--panel` | `#EAE6E3` | `#272320` | derived from `--bg`; steps *down* in light, up in dark |
| `--ink` | `#241C1C` | `#E6E2E0` | sampled, the plate's type |
| `--muted` | `#6E645E` | `#A89F99` | derived from `--ink`, lifted to clear 4.5 |
| `--faint` | `#958A83` | `#6E645E` | derived, 3.0 — decorative marks only, never copy |
| `--line` | `#D8D0CB` | `#3D3733` | derived from `--bg` |
| `--line-soft` | `#E7E2DF` | `#2F2B27` | derived from `--bg` |
| `--edge` | `#8F7C70` | `#7B6E65` | derived, computed against the 3.0 non-text floor |
| `--accent` | `#2D455D` | `#5587B9` | **sampled** — the blue-line print, 1.5% of the plate |
| `--accent-text` | `#2D455D` | `#7DA8D4` | as sampled in light; lifted in dark |
| `--accent-strong` | `#213345` | `#A3C2E0` | derived, same hue |
| `--accent-soft` | `#E4EBF1` | `#243342` | derived, the blue at wash weight |
| `--on-accent` | `#EAE6E3` | `#1C1917` | the paper — reversed type is paper showing through, not white |
| `--good` | `#7A894D` | `#6A7740` | **sampled** hue 75, the green land-use wash, 2.9% of the plate |
| `--good-text` | `#606C3D` | `#9AAE61` | same hue, darkened to clear 4.5 |
| `--good-soft` | `#E5EAD7` | `#303522` | same hue at wash weight |
| `--warn-text` | `#8A5F15` | `#CD9637` | **sampled** hue 38, the ochre wash, 8.3% of the plate |
| `--warn-soft` | `#F6E6CB` | `#3B2E16` | same hue at wash weight |
| `--chip` | `#EBE7E5` | `#34302D` | derived from `--bg` |
| `--stone` | `#6D8FB0` | `#4D6984` | derived from `--accent`, the unlit waypath tick |
| `--r-card` / `--r-ctl` / `--r-chip` | `0px` | `0px` | the plate has ruled fields, not rounded cards |
| `--shadow` / `--shadow-lift` | `none` | `none` | nothing on a printed sheet floats |

### The ground, stated plainly

`#F4F2F1` sits at 95% lightness, inside the 94–98% near-white band that
`~/.claude/skills/seeded-design/references/register.md` flags as this author's
strongest cross-project tell — the one value Gatehouse, Job Radar and the
retired verdigris round all shared while everything else differed.

It is here **on purpose, and it is a derivation rather than a sample.** The
plate's paper measures 89% and neither seed contains a lighter ground: the
unfilled blocks on the Thomas Bros. sheet measure `#EAE2D6`, the same paper,
and the Sanborn stock runs 93–97%, which is the band itself. So hue 24 was
held and lightness and chroma were moved.

The reason it is defensible anyway is that in this direction the ground is not
what carries identity. The blue-line/wash split, the square geometry, the
absent elevation and state-as-fill all do that work, and none of them depend
on the ground being dark. The audit will flag it on every run; this paragraph
is the answer.

### Why `--panel` is darker than `--bg`

The one token that surprises people. Lifting a panel above a 95% ground
computes 1.06 and the field stops existing. On a printed sheet a field is a
tinted block *on* the paper, never a lighter one — so the panel steps down, as
the plate's own washed blocks do. The dark theme inverts this, because there
the paper analogy does not hold.

## Type

| | family | source |
|---|---|---|
| Reading | grotesque stack — Helvetica Neue, Helvetica, Segoe UI, Roboto, Arial | the platform's own |
| Display | the same stack, separated by size and weight | — |
| Mono | ui-monospace, Menlo, Consolas | the platform's own |

A grotesque, not a humanist face, and deliberately not a rounded one: the
plate's own lettering is drawn sans capitals doing structural work, and that
is the register. `ui-rounded` led this stack two rounds ago and Avenir Next
one round ago; both were the friendly-app reflex in different clothes.

**Open decision.** The honest answer is Archivo — an American grotesque in the
same commercial-lettering line as the plate — with Archivo Narrow for
structural labels: one family at two widths, which is the plate's own logic.
That needs a font pipeline (vendored woff2 in the package; a self-hosted app
should not phone out to a font CDN), and the pipeline is a separate decision.
Until it exists the stack above is the nearest thing the platform already has,
and it changes in `theme.py` alone.

## Layout grammar

A survey with an index: content in a ruled field, navigation as a key beside
it. Borrowed from the block book, where a title page carries the colour key
for everything behind it and each sheet is a bordered, numbered field.

## Shape and weight

Radius scale: `--r-card` 0, `--r-ctl` 0, `--r-chip` 0.

Elevation: none. Hierarchy is carried by rule weight and fill, which is what
the plate does — a heavier rule means a larger division, and a wash means a
classification. The three radius tokens stay, spelled everywhere they were, so
the decision is revisitable in three lines rather than forty.

## Density

Calibrated against the plate, which fits seven maps, a legend, a bar chart and
two index tables on one sheet without being hostile. The curriculum page is
the test: every unit in a course visible with its state, not one idea per
screenful.

## The signature gesture

**The waypath** — one ruled tick per tracked item: filled for done, ringed for
here, outlined for ahead. At zero it is the whole path laid out in front of
you rather than an empty bar.

It appears only where something is genuinely tracked. The profile page has no
waypath because it tracks nothing, and a gesture meaning "where you are on a
path" is a lie on a page with no path.

`theme.WORDMARK` is the same drawing at three stones, and
`tests/test_frontdoor.py::WordmarkTest` reads both out of `theme.py` and
asserts they still match — the mark has been left behind by the path before.

## Banned for this project

Beyond the shared register in the skill:

- The warm round, retired 2026-09-04: `#FDF6EF`, `#E06A4E`, `#C6492E`,
  `#3B2A1E`. The Anthropic cream cluster almost exactly.
- The verdigris round, retired the same day: `#F4F6F4`, `#1B8577`, `#126E62`,
  `#0F6B5F`. Produced specifically to escape the warm palette, by a process
  that included a contrast solver and a written rationale, and it landed six
  channel-units from Job Radar's shipped accent.
- `#0C6E63`, `#17191C`, `#82550A` — Job Radar owns these.
- `#F8F8F8` and the terracotta family in 15–40° — Gatehouse owns these.
- `ui-rounded` anywhere in a font stack.
- Trailing `→` on calls to action; letterspaced uppercase micro-labels;
  middot-chained metadata standing in for a breadcrumb; 999px pills.

## Settled decisions

1. **Near-white ground, accepted with the flag standing.** Argued and decided
   in favour on 2026-09-04. The register's finding was not that near-white is
   unusual but that it was unchosen; this one is chosen. Do not reopen from a
   diff — reopen only with new evidence about what carries identity here.
2. **The dark theme is derived.** Seeding it properly needs a dark-ground
   artifact. Until one is sampled, do not present the dark values as
   provenanced.
3. **Two colour systems, not one accent.** `--accent` is structure *and*
   primary action, because on the plate the structural ink is also what
   points. The wash family is state. A third structural hue is out of scope.
4. **Red is reserved and unspent.** The plate's vermilion (hue 355) is not in
   the token set, because nothing in the product currently surfaces a failure
   state. It is the value to reach for when one appears — not a new hue.
5. **Zero radius and no elevation.** Not a minimalism preference; the seed has
   ruled fields and no shadows, and reintroducing either breaks the drawing.

## Audit

Last run: 2026-09-04

```
python ~/.claude/skills/seeded-design/scripts/audit.py \
  --hex bg=#F4F2F1 ink=#241C1C accent=#2D455D good=#7A894D warn=#8A5F15
```

Expected result: **three flags and one warning, all answered.** The auditor is
working; none of these is a surprise, and none is waved through.

1. `FLAG` — the ground is in the 94–98% near-white band. Settled decision 1.
2. `FLAG` — the ground is 7 channel-units from `#F4F6F4`, the **retired
   verdigris round of this same product**. That is the register's own finding
   restated: near-whites cluster, and the distance metric is a crude L1 in
   RGB that cannot see tint direction. These two differ in the only way
   near-whites can — this one is warm (hue 24), that one was green (hue 120) —
   and the accent, structure, geometry and elevation share nothing. Accepted.
3. `FLAG` — `--warn-text` at hue 38 is in the terracotta band. It is sampled
   from the plate's ochre wash, it is the third colour in a five-state system,
   and it is never the accent in any screen. Accepted.
4. `WARN` — `--ink` is 16 units from Job Radar's `#17191C`. Both are near-
   blacks; this one is warm, that one cool. Near-blacks cluster for the same
   reason near-whites do. Accepted, and worth re-checking if either moves.

Re-run this after any token change. A **new** flag is a real finding; these
four are the standing cost of the direction and are on the record.
