# The chapter pattern

A **chapter** is a unit's own instructional text: the page a learner reads
to learn the unit's content, rather than a pointer to readings that hold it.
It is a material of kind `chapter`, one markdown file under
`learning/interactive/chapters/`, registered once in `course.yaml` and owned
by its unit. The served reader renders it inside the theme; the repo file
renders the same on GitHub, because the dialect extensions were chosen for
that (footnotes, `<details>`, `> [!NOTE]` alerts — see `curricle/blockmd.py`).

This document is the authoring contract. It exists so that chapter two reads
like chapter one and a reader's trust in one carries over to the next. The pattern draws on settled practice from textbook and technical-
writing design — stated objectives, worked examples before formalism,
retrieval practice at the point of learning, and citation with locators — and
adds one thing those genres rarely do: a visible account of how the chapter
was checked.

## What a chapter promises

1. **Self-contained.** A learner who reads only the chapter can do the unit's
   Build and Exercise. The readings go deeper; none is required.
2. **Sourced.** Every substantive claim — a definition, a number, an
   attribution of a position, a convention of a tool or edition — carries a
   footnote naming its source and a locator (page, section, file and element,
   commit). General explanation in the author's own words needs no note.
3. **Checked, and honest about the checking.** The closing section, *How
   this chapter was checked*, is a ledger: what was verified against what,
   and what rests on sources the author could not open. A claim that could
   not be verified is either marked as such or left out. Never launder an
   unverified claim by citing a source you did not read.
4. **Calibrated to the learner.** The course's learner profile sets the
   register. For textual-flow that means: lead with code and data, formalize
   second; do not scaffold linguistics; do scaffold statistics and the
   conventions of scholarly method.

## Structure

Use these sections in this order. Headings are `##`; sub-sections `###`.

```
# Unit N — Title                      (matches the unit's curriculum title)
*One-line standfirst: what this chapter teaches and what you will be able to do.*

> [!NOTE] Before you start
> Prerequisites, reading time, what to have open (a file, a tool).

## What you will be able to do        (3–6 behavioral objectives)
## 1. Start with the data / the thing (a concrete artifact, before any definition)
## 2..k. One concept per section       (definition → example from real data →
                                       engineer's translation → common confusion)
## Where the sources and the data disagree   (only if they do — say so plainly)
## What this sets up                   (how the unit's Build / Exercise use this;
                                       what later units take from it)
## How this chapter was checked        (the verification ledger)
## Sources                             (the footnote definitions live here)
```

Between sections, place **check-yourself** blocks — a `<details>` whose
`<summary>` starts with *Check yourself:* and whose body holds the answer.
Put them where the concept was just taught, not only at the end; three to
six per chapter. Where the chapter can give the learner an oracle for an
exercise (expected counts, a known answer), put that in a `<details>` too,
with a summary that says it is an answer so nobody opens it by accident.

## Sourcing rules

- Cite by footnote: `claim.[^wg-ch1]`, defined once under `## Sources` as
  `[^wg-ch1]: Wasserman & Gurry 2017, ch. 1, pp. 3–15.` Use descriptive ids,
  not numbers, so a reordering never renumbers by hand.
- Link the resource entry with the course's reference scheme —
  `[Wasserman & Gurry](res:wg)` — in the footnote's first use, so the compiler
  validates it and the reader lands on the verified URL. Never paste a bare URL
  in prose; the compiler refuses.
- Reference links inside a chapter are resolved by the reader but **not
  validated by the compiler** (it walks manifest content, not material files).
  So check them by rendering: a `res:` key must exist, and a `repo:` path must
  be one the served app blesses — the `docs:` pointers in `course.yaml` or a
  `repo:` link in manifest content — or it 404s when served. Cite anything
  else by name without a link.
- For data claims, the locator is the file and the element: *open-cbgm
  `examples/3_john_collation.xml`, `<app n="B25K1V15U18">`, at commit `…`*.
  Data files change; the commit or date is part of the citation.
- Quote definitions from an authority verbatim when the wording matters
  (a field's term of art); paraphrase everything else.
- Mark anything taken from a source the author did not open — a paid book
  cited from memory, a page number recalled — in the ledger, in a row of its
  own, as **unverified against the text**.

## The verification ledger

A pipe table, one row per checked claim or claim-family:

| Claim | Checked against | Result |
|---|---|---|
| 137 witnesses × 116 units | the TEI file itself (script) | verified |
| ECM lists a-text support in full only when ≥15 Greek MSS dissent | Head 2010, pp. 136–137 | verified (1st edition; 2nd not checked) |
| W&G define pregenealogical coherence as … | W&G ch. 3 | **unverified against the text** — cited from memory |

Results are one of: *verified*, *verified with caveat* (say which),
*unverified against the text*, *inferred* (say from what). Aim for no
unverified rows, and never hide one.

## Voice and format

- Second person, plain, level. No hype, no exclamation points. Hedge where
  the evidence hedges and nowhere else.
- One idea per sentence. Numbers go in tables or on their own line.
- Code in fenced blocks; a chapter's code should run (it is the learner's
  first draft of the Build).
- Greek is written unaccented where the data is unaccented (the ECM's
  collation is), and glossed on first use.
- Length: 3,000–5,000 words. Longer means the unit wants splitting.

## Figures

A figure is an image on a line of its own: `![caption](figures/name.svg)`.
The reader renders it as a `<figure>` with the alt text as the caption, on a
white plate so a Graphviz SVG survives dark mode; GitHub shows the image with
the alt on hover. Put the files in a `figures/` directory beside the chapter
(`learning/interactive/chapters/figures/`); the compiler treats that
directory as the chapters' assets and does not ask for it to be registered.
Prefer SVG for graphs (crisp, small, greppable). Treat a figure as evidence, like a
number: the ledger says what produced it and when.

## Registering a chapter

```yaml
materials:
- id: c-u01
  kind: chapter
  title: "Witnesses, variants, and the shape of the data"
  path: interactive/chapters/unit-01-collation-data-model.md
  unit: u1
  blurb: The unit's text — read this first; the readings go deeper.
```

Do **not** also link it from the unit's **Read** row in `curriculum.md`.
The unit page leads with the chapter — it is the "Start here" panel and the
page's one primary action — and the curriculum page's derived Interactive
row and the hub's `chapter` chip both come from the registry, so a Read row
that opens with "[this unit's chapter](mat:c-u01) first" says the same thing
a second time, without hierarchy. The compiler warns on it. The Read row
holds the readings, in the order to take them; the unit page frames them as
"deeper than the chapter".
