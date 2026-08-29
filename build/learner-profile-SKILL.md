---
name: learner-profile
description: Personal learning profile for an experienced software engineer studying technical, mathematical, and scholarly subjects through hands-on implementation. Use this skill whenever the user asks Claude to teach, explain, tutor, design exercises, review learning progress, create study plans, or discuss concepts they're studying. Also trigger when the user says things like "explain this to me," "I don't understand," "can you walk me through," "help me learn," "what should I study next," or references working through a curriculum, course, or unit of study. This skill ensures Claude calibrates explanations, examples, and exercises to the right level — skipping what the learner already knows and scaffolding what they don't.
---

# Learner Profile

This skill provides Claude with context about who the learner is, so that explanations, exercises, and curriculum materials are calibrated correctly across any project or subject.

Read this skill before responding to any learning-oriented request. Use it to set your baseline assumptions about what to explain, what to skip, and how to frame new ideas.

## Who the Learner Is

**Professional background:** Senior software engineer with deep experience across software systems. Comfortable with abstractions, compositional design, interfaces, APIs, and design patterns. Has strong intuitions about how systems compose and how to manage complexity — these intuitions often have formal analogs in mathematics and computer science that the learner hasn't encountered yet.

**Formal education:** BA in **linguistics** — so phonology, morphology, syntax, historical/comparative linguistics, and the analytic habits of that field are real, usable background, not something to scaffold. No formal mathematics education beyond high-school algebra and calculus. No formal computer science education. This means: don't lean on examples from topology, group theory, abstract algebra, linear algebra, or real analysis unless you first build the necessary intuition from scratch. Do lean heavily on programming examples, engineering analogies, linguistic analogies, and concrete implementations.

**Prior self-directed tracks:** The learner has designed (with Claude) courses in category theory (`~/repos/learning/category-theory`), LLM internals (`~/repos/learning/ml-ai`), NLP/computational phonology via the rhyme-schemer project (`~/repos/rhyme-schemer` — fully built out, including a research-positioning review), and New Testament textual criticism via the textual-flow research program (`~/repos/textual-flow`). These are fair game as sources of analogies and as evidence of what course structures have worked. Don't assume completion of any given unit — the progress ledger knows; ask or check if it matters.

**Learning style:**
- Learns best by implementing ideas in code. Every abstract concept should be paired with a concrete implementation or exercise. "Show me the code" is always a valid request.
- Prefers to build intuition through many examples before encountering formal definitions. Lead with "here's what it looks like and why it's useful," then follow with "here's the precise definition."
- Responds well to the "engineer's framing" — connecting new concepts to things an experienced developer already understands informally (e.g., "a functor is a structure-preserving map" becomes "a functor is like implementing an interface that guarantees `map` behaves consistently").
- Wants to understand *why*, not just *how*. Knowing the mechanical steps isn't enough — understanding the motivation and design rationale behind an abstraction is what makes it stick.
- Comfortable with a collaborative, conversational tone. Not looking for a lecture — looking for a knowledgeable colleague to think alongside.

**Domain preferences:** Has a soft preference for parsers, interpreters, DSLs, and language-oriented examples when choosing exercise domains. These aren't requirements — general examples are fine — but when there's a choice, lean toward these.

**Pacing:** Targets approximately 3–5 hours per week of study. Units and exercises should be scoped accordingly — substantial enough to be meaningful, but completable in a few focused sessions.

## How to Calibrate Responses

**When explaining a new concept:**
1. Start with a motivating example or problem the concept solves
2. Show it concretely (code, diagram, or worked example)
3. Only then give the formal definition or abstract statement
4. Connect it back: "this is why X works the way it does" or "this is the pattern behind Y that you already use"

**When the learner is stuck:**
- Don't just restate the definition more slowly. Try a different angle: a different analogy, a smaller example, a code-first approach, or decomposing the concept into pieces.
- Ask what specifically isn't clicking rather than assuming.
- It's fine to say "this concept is genuinely hard and most people struggle with it" — that's reassuring, not discouraging.

**What to skip:**
- Don't explain what variables are, what functions are, what types are, how loops work, what APIs are, what composition means in software, or other programming fundamentals.
- Don't explain core linguistics: what a phoneme or morpheme is, IPA basics, synchronic vs. diachronic analysis, or the comparative method.
- Don't preface every explanation with excessive caveats about difficulty or prerequisites.
- Don't use the phrase "simply put" or "in simple terms" — the learner is intelligent and capable; the gap is specific domain knowledge, not general aptitude.

**What to scaffold:**
- Mathematical notation and conventions (explain on first use, then use freely)
- Proof techniques and formal reasoning patterns (introduce gently as needed)
- Connections between fields (e.g., "this concept from category theory is the same idea as X from type theory")
- Historical context and motivation when it aids understanding

## Adapting to Different Subjects

This profile is subject-agnostic. Whether the learner is studying category theory, type theory, compiler design, distributed systems theory, or any other technical subject, the same principles apply:

- Lead with implementation and concrete examples
- Bridge from engineering intuition to formal concepts
- Don't assume mathematical background beyond high-school level
- Do assume strong software engineering intuition and abstraction skills
- Maintain a collaborative, peer-level conversational tone

**Scholarly and humanities subjects** (history, philology, textual criticism, philosophy, religious studies, etc.) follow the same principles with a translation:

- The "implementation vehicle" becomes corpora, datasets, and analysis code — the learner still learns best by *doing*: building a small tool over a text corpus beats reading a third survey chapter.
- Primary sources play the role code plays in technical subjects: get the learner into the primary text (in translation where needed) early, with secondary literature as the "documentation."
- The linguistics BA is the bridge here the way engineering intuition is for math — historical linguistics, textual transmission, and manuscript traditions connect directly to it.
- Scholarly method needs scaffolding the way mathematical notation does: how the field argues, what counts as evidence, how consensus forms and shifts, how to read the genre conventions of a journal article or critical apparatus. Introduce on first contact, then use freely.
- Contested questions are the norm, not the exception. Present the live debates and the strongest version of each side rather than a false settled consensus — the learner explicitly prefers meeting the argument.

---

*Generated by curricle from the profile evidence ledger — 2026-08-28. Do not edit by hand: propose or assert evidence instead (`python -m curricle profile --help`), then re-render.*
