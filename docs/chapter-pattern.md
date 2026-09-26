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
   register and says what may be assumed, so the author reads it before
   writing a word. It never falls back on the sibling chapters or on a
   guess about the learner's background. For textual-flow that means: lead
   with code and data, formalize second; do not scaffold linguistics; do
   scaffold statistics and the conventions of scholarly method. A course
   whose learner meets a field from zero means defining that field's
   vocabulary from zero, however routine it is to the author.
5. **Every term defined where it first appears.** A term of art that the
   profile does not mark as known, and that no earlier chapter defined, is
   defined in the body at its first use. The definition says what the term
   is for as well as what it is: a formula alone is not a definition. The
   first mention of a named benchmark, model, dataset, tool, or paper gets a
   one-line identity. A definition given only in a footnote or inside a
   check-yourself answer doesn't count, because a learner who gets the
   question right never opens it. "Earlier" means earlier in the course's
   reading order,
   the unit order, not the order the chapters were written in. A chapter
   written after the ones that follow it inherits their assumption that it
   has been read, and it must define everything they assume.

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

The standfirst and the objectives are the first things the learner reads, so
they are held to principle 5 like any other line: write them in plain words,
or pair a term with its plain gloss the first time. An objective can promise
"say what a surprisal measures" only if it doesn't lean on the reader already
knowing. Section 1 puts the artifact before the *formal* definition, not before
the words needed to read it. When the artifact's own labels are terms of art
(a column headed `surprisal`, a unit in bits), say in plain words what they
measure beside the artifact.

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
- Length: 3,000–5,000 words. Longer means the unit wants splitting. When
  the ceiling and a definition conflict, the definition wins: cut elsewhere
  or split the unit. An editor trimming for length never trims a
  definition, because to a writer or editor who already knows the term a
  definition looks like redundancy.

## How a chapter is made

Four passes, each by a different agent, because the one who writes is not
the one who judges, and each pass checks something the others cannot see.

1. **Write.** The author gets this document, the learner profile, the
   unit's curriculum entry, and the earlier chapters in reading order. The
   author runs every piece of code the chapter prints, and records in the
   ledger each number the chapter reports.
2. **Prose.** A copy pass removes the habits of machine-written text without
   changing what is said (rolecall's `prose-editor`).
3. **Correctness.** An adversarial review re-runs the printed code as
   printed, checks every quotation against its source, and reads the
   chapter against the curriculum it claims to cover (rolecall's
   `reviewer`).
4. **The learner's read.** The chapter is read front to back as the course's
   learner (rolecall's `audience-reader`). Every term used before it is
   defined is a finding. Every term treated as known must cite the profile
   claim or earlier chapter that makes it known. Where the profile is
   silent, the reader asks the learner a question; the answer becomes a
   profile claim before the chapter is fixed.

The audience reader is generic, and this is its binding for a course:

- **Audience description:** the rendered learner profile,
  `~/.claude/skills/learner-profile/SKILL.md`, which is a projection of the
  profile ledger (`curricle profile show` prints the same claims with their
  tiers). `attested` and `demonstrated` claims count as knowledge; `thin`
  claims do not. Everything under *What to scaffold* is unknown, whatever
  *Who the learner is* suggests.
- **Prior reading:** the course's chapters before this one in reading order,
  meaning unit order and then registry order within a unit, whatever order
  they were written in. The curriculum page is not prior reading; a
  learner skims it.
- **Audience gaps:** the questions go to the learner, and the answers are
  asserted as profile claims (`curricle profile assert`, or `import-seed`
  for a batch) and re-rendered before the author fixes the chapter, so the
  next chapter's read doesn't ask again.

The author applies the findings from 3 and 4. If the fixes from 4 were
substantial, 4 runs again. Passes 2 and 3 were the whole pipeline before
pass 4 existed, and a chapter that passed both still opened with a column
of numbers labelled `surprisal` and no word on what one is. The review had
no reader in it.

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

A unit's text can run to **more than one chapter**, as when a course
needs a primer before a unit's own chapter because the learner meets the
field from zero. Register each with the same `unit:`, in reading order. The
unit page's start panel lists them in that order and opens the first, and
each chapter's banner says which of them it is and links the next. Every
chapter still stands on its own under the pattern. Reach for this rather
than a longer chapter when the extra text is a different subject (the
mechanism the unit's argument runs on), not more of the same one.

A chapter can belong to a **track** instead of a unit (`track: greek` in
place of `unit:`), when a secondary track has its own text: textual-flow's
Greek track is one chapter per cluster of Decker chapters (`c-g01`,
`c-g02`, …). A track has no unit page, so the served hub lists a track's
chapters under its stepper, numbered in registry order and ahead of its
tools; register them in the order they are to be read. A track chapter's
"data" should be the track's own — for Greek, the tagged text of the
letters the course reads, so that every count is re-runnable and the track
converges on the program's corpus rather than on the textbook's examples.

Do **not** also link it from the unit's **Read** row in `curriculum.md`.
The unit page leads with the chapter — it is the "Start here" panel and the
page's one primary action — and the curriculum page's derived Interactive
row and the hub's `chapter` chip both come from the registry, so a Read row
that opens with "[this unit's chapter](mat:c-u01) first" says the same thing
a second time, without hierarchy. The compiler warns on it. The Read row
holds the readings, in the order to take them; the unit page frames them as
"deeper than the chapter".
