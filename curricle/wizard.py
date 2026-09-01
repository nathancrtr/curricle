"""The onboarding wizard: one URL, and whatever screen the fold says.

Invariant O1 in code: `/onboarding/` renders `onboarding.load_state(...)
.current_stop()`, and nothing else decides. There is no cursor in a cookie,
no step in the session, no "next" the server remembers — a reload can never
put the wizard behind work already done, because there is nothing to put
behind. Within the profile stop the sub-screens (welcome, the four forms,
the review) are chosen by `?screen=`, and that is navigation over screens
the fold has already opened: a value the vocabulary does not know sends the
learner back to `/onboarding/`, and `?screen=` is ignored outright once the
stop is past the profile.

The scope stop has the wizard's one other pair of screens, for the same
reason and under the same rule: a tenant who has finished a course lands on
its card, and starts their next course from that same stop (design §4, Stop
10), so `?course=` chooses between the two. Like `?screen=` it can only
reach a screen the fold has already opened — it names a *finished* flow, or
it names nothing, and the scope form is what nothing means.

Screens say two different things about two different waits (design §5).
`pending` is a machine's turn, so the screen shows the word, the mark, and
elapsed time since the last ledger row — elapsed, never a forecast, because
a forecast over a model call is a number this system would be inventing.
`waiting` is your turn, so the screen shows the ask. `failed` prints
`onboarding.WORDING[(stage, reason)]` and never exception text (O2); the
exception lives in the ledger row's detail, for an operator.

The reasons this module words are *ledger* reasons and only those. The run
queue keeps reasons of its own for rows nobody is being shown — a run that
was superseded, a run whose worker was shut down — and those are queue
bookkeeping, not screens. `WORDING` is keyed by what the ledger says
happened, so every screen here is rendered from the fold and from nothing
else.

Waiting screens watch by polling `/onboarding/status` — the fold's stop,
its status and its elapsed words, as JSON — and swapping the elapsed line
in place; they navigate only when the ledger says there is a different
screen to be on. The `<meta http-equiv="refresh">` tag they used to carry
stays as the `<noscript>` fallback at thirty seconds. It was five, over an
eleven-minute build: a hundred and thirty full reloads, each resetting
scroll, selection and focus and re-announcing the page to a screen reader,
on the one screen whose entire job is waiting without anxiety. The polling
still stops by construction, script or no script: a screen that is not
pending carries neither the tag nor the script.

The forms remain the surface with no script on them at all. That posture
is about the page a learner types into — a form whose behaviour depends on
JavaScript is a form that can lose what somebody wrote — and a screen with
no inputs on it is not that page. Nothing here is progressive enhancement
of a control; it is a clock that stops yanking the page out from under a
reader.

Two screens read something other than the ledger. The outline gate
compiles the drafted course out of the draft tree every time it is drawn,
because derived data is never stored and a copy of an outline kept beside
the real one is a second answer to what was drafted; only the build plan
and the two numbers come out of the `outline_ready` payload, and they do
because they are the artifact being approved — O3 says the numbers in the
approval row are the numbers that were on the screen, and echoing the
stored payload into it is how that stops being a thing anyone has to check.
And the gate and the landing both total the `token_ledger` for what this
course has actually cost. Neither is the metered stage runner: one reads
files, the other reads rows, both spend nothing, and L1 holds on every
route here.
"""

from __future__ import annotations

import html as html_mod
import math
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               Response)

from . import coursehome, db, onboarding, profile, profilerender, theme
from .compiler import compile_course
from .schema import Manifest, Phase
from .sidecar import load_sidecar

# The two waits, in words. Design §5: always mark *and* word — the mark is
# reinforcement, the word is the message, and a screen read with no color at
# all still says which of the two waits this is.
PENDING_WORD = "Working"
WAITING_WORD = "Your turn"
FAILED_WORD = "Stopped"
# The welcome screen's fourth word, which is not a wait at all: a stage that
# never started because the process that runs it is not there (design §6).
WORKER_WORD = "Not running"

# Stop 0's three never-promises, stated above the ask rather than in a
# footer (design §4). Constants because the wizard says them and the tests
# hold the wizard to them; copy nobody can grep for is copy that drifts.
NEVER_PROMISES = (
    "The profile page is the only authority on what this system believes "
    "about you. Everything it knows is on that one page, and you can change "
    "or delete any of it at any time.",
    "Nothing you type here is sent anywhere but your own database and, "
    "later, the model calls that build your course.",
    # The old sentence was "Every dollar of model spend is approved by you
    # on a screen that shows the number first", and it was not true: the
    # outline stage spends before any number has been shown, on the strength
    # of the scope form's "it is the cheap one". What is true is the shape
    # below — one stage approved against a number, the other running under a
    # budget it stops at, and both of them itemised afterwards, which is the
    # clause that makes the promise checkable rather than merely made. It is
    # said here because the landing really does print that receipt.
    "The expensive stage — building your materials — is approved by you on "
    "a screen that shows the number first. Drafting the outline runs under "
    "a budget of its own and never asks you for money. What each of them "
    "actually cost is itemised for you when you land.",
)

# The profile stop's sub-screens, in order: the whole vocabulary `?screen=`
# is allowed to name, and the order the previous/next links walk.
SCREEN_ORDER = ("welcome", "1", "2", "3", "4", "review")

# (screen number, heading, fields on it) — design §4's grouping, verbatim.
# Screen 1 additionally carries the `meta` description, which is one line
# rather than a list of claims and so is not one of the screen's fields.
# `demonstrated` is on no screen at all: it is written by course activity
# through the checkpoint→propose pipe, and a form that offered to type it
# would be the learner asserting what only their work can demonstrate.
PROFILE_SCREENS = (
    ("1", "Who you are", ("background", "education", "tracks")),
    ("2", "How you learn", ("style", "domain_bias", "pacing")),
    ("3", "Calibration", ("calibration", "skip", "scaffold")),
    ("4", "Subjects", ("subject_adapters",)),
)
_FORM_FIELDS = {number: fields for number, _, fields in PROFILE_SCREENS}

# The one key the wizard does not mint. `meta` holds a single claim — the
# skill file's own frontmatter description — under the key the seed and
# `profilerender.render_skill_md` already read, so the form writes that key
# rather than starting a numbered series of one.
META_KEY = "description"

# What each screen is called on a navigation link.
SCREEN_NAMES = {"welcome": "What this does",
                **{number: heading for number, heading, _ in PROFILE_SCREENS},
                "review": "Review and publish"}

# The lede on each form screen. Screen 3's says plainly why those three
# fields are the product (design §4): a profile that only says who you are
# calibrates nothing.
#
# The ledes carry more than they did, because the field explanations carry
# less: a field is one line now (F13 — four fields at three tiers of muted
# text apiece made screen 1 two thousand pixels of reading before the first
# box), and the rationale sentences that earned their place moved up here,
# where they are said once for the screen instead of once per field.
SCREEN_INTROS = {
    "1": "Where you are coming from — the work and study a course can build "
         "on instead of repeating. Short claims, in your own words.",
    "2": "How an explanation has to arrive for it to land, and how much of "
         "your week a course is allowed to ask for. One habit per claim, "
         "stated as an instruction a teacher could follow — and what you "
         "say here about domains is a preference, never a requirement.",
    "3": "These three are the difference between a course that re-explains "
         "your degree and one that builds only what you lack: together they "
         "are the procedure a tutor follows before it says anything new, "
         "and every line of them is a week spent on something you do not "
         "already know.",
    "4": "One course is being written now, but this profile outlives it. "
         "What here holds whatever the subject turns out to be?",
}

# The form's name for each field. Deliberately this surface's own words
# rather than `/profile`'s section titles: that page titles a section of a
# document, and this one asks a person a question.
FIELD_LABELS = {
    "meta": "Skill description",
    "background": "Professional background",
    "education": "Formal education",
    "tracks": "Prior courses and tracks",
    "style": "Learning style",
    "domain_bias": "Domain preferences",
    "pacing": "Pacing",
    "calibration": "Calibrating an explanation",
    "skip": "What to skip",
    "scaffold": "What to scaffold",
    "subject_adapters": "Adapting to other subjects",
}

# field -> (one-line explanation, (example claim, example claim)).
#
# The examples are real claims: the ones the corpus already ships in
# `examples/example-profile-seed.yaml`, abbreviated to the sentence that
# carries them, with a second one written here for the fields the seed only
# has one of. They are examples of a *claim*, not a template — the whole
# point of the form is that the sentences are the learner's, so what these
# demonstrate is the register and the length, and nothing about the shape.
FIELD_COPY: dict[str, tuple[str, tuple[str, str]]] = {
    "meta": (
        "One sentence naming who this profile is for and when Claude should "
        "reach for it.",
        ("Learning profile for a backend engineer with a CS degree studying "
         "distributed systems and formal methods through hands-on "
         "implementation.",
         "Use this whenever the learner asks Claude to teach, explain, tutor, "
         "design exercises, or review learning progress.")),
    "background": (
        "The work you have actually done, read as bridging assets: the "
        "intuitions a course can name rather than teach from scratch.",
        ("Eight years building backend services — mostly Go and Python over "
         "Postgres and Kafka, with real production on-call experience.",
         "Six years of newsroom data work: scraping, cleaning, and arguing "
         "with spreadsheets under a deadline.")),
    "education": (
        "Formal study in both directions — what it covered and, just as "
        "usefully, where it stopped.",
        ("BS in computer science: data structures, algorithms, and complexity "
         "are solid and need no scaffolding, but the theory sequence stopped "
         "at automata.",
         "No degree past secondary school; everything since has come from the "
         "job, from books, and from reading other people's code.")),
    "tracks": (
        "Courses and self-directed tracks you have already worked through — "
        "including the ones that stalled, which are worth as much.",
        ("Worked through a Raft implementation from the paper, and about half "
         "of a database-internals course before it stalled at query planning.",
         "Finished a lecture series on linear algebra two years ago: the "
         "notation stuck, the proofs did not.")),
    "style": (
        "How understanding actually arrives for you.",
        ("Learns by implementing — pair every abstract idea with something "
         "runnable, and treat “show me the code” as always fair.",
         "Reaches understanding through failure modes: what breaks, and what "
         "the system does when it breaks, lands harder than the happy path.")),
    "domain_bias": (
        "Where examples and exercises should be drawn from when the choice "
        "is free.",
        ("Prefers exercise domains drawn from storage engines, consensus, and "
         "stream processing.",
         "Examples from music, language, or games land; examples from finance "
         "slide straight off.")),
    "pacing": (
        "The sizing constant: how much time a week really has in it, so that "
        "one unit is one honest week of work.",
        ("Targets roughly 4 hours per week, usually as two evening sessions.",
         "One long Sunday session rather than daily study — scope units to "
         "survive a week-long gap.")),
    "calibration": (
        "The order an explanation has to arrive in for you.",
        ("When explaining a new concept: open with the failure it exists to "
         "prevent, show it concretely, then give the formal statement and "
         "name it properly.",
         "Give me the shape of the whole thing before any detail; a lesson "
         "built strictly bottom-up loses me by the third step.")),
    "skip": (
        "What never needs explaining to you again.",
        ("Don't explain what an index is, what a transaction is, how HTTP "
         "works, or any language-level feature of Go or Python.",
         "Don't explain big-O, common data structures, or basic algorithm "
         "analysis — the degree covered these and they held.")),
    "scaffold": (
        "What to rebuild from the ground up, assuming nothing stuck.",
        ("Probability and statistics: rebuild from zero whenever a "
         "tail-latency or failure-rate argument needs them.",
         "Proof technique and formal notation — introduce each notation on "
         "first use, then use it freely rather than re-explaining it.")),
    "subject_adapters": (
        "How the rest of this profile translates when the subject is not the "
        "one you are starting with today.",
        ("Subject-agnostic: whatever the material, lead with the failure the "
         "idea prevents and bridge from hands-on intuition to the formal "
         "concept.",
         "For anything mathematical, assume strong engineering judgment and "
         "weak formal machinery, and keep the tone peer-level.")),
}

# The gate in words, on every form screen (design §4). Color says nothing
# here that the sentence does not say first, and the four fields are named
# because "incomplete" is not an instruction.
GATE_LEAD = ("Before you can publish your profile, these still need at least "
             "one claim in your own words:")

# Stop 6's three course shapes, each explained in a sentence (design §4).
# (value, name, what choosing it means) — the values are the manifest's
# `COURSE_MODES` and a test pins them to it, because this radio group is
# where a learner picks the string a sidecar will later declare.
MODE_COPY = (
    ("subject", "A subject",
     "A field you want to understand. The course is organized around the "
     "ideas, and the work exists to make them stick."),
    ("project", "A project",
     "Something you want to have built. The course is organized around "
     "shipping it, and each idea arrives when the build needs it."),
    ("research", "A question",
     "Something you want to be able to investigate. The course is organized "
     "around the literature and the methods that let you read it."),
)

# The scope form's fields, in the words this surface asks them in: the input
# name a POST reads, mapped to (what the box is called, the one line under
# it). The form is assembled from these and the refusals are worded from them
# too, so a box and the sentence refusing it can never drift apart.
SCOPE_LABELS = {
    "mode": ("What kind of course this is",
             "The three shapes ask different things of the same subject. "
             "Pick the one that matches why you want it."),
    "title": ("Working title",
              "What you would call this course today. The course's id and "
              "the folder it lives in are minted from this, once, and never "
              "change afterwards — the words themselves you can change."),
    "subject": ("Subject",
                "The territory, in a phrase or two. Narrower is better: a "
                "course that covers everything covers it in one paragraph "
                "each."),
    "done_looks_like": ("What done looks like",
                        "The thing you want to be able to do at the end, "
                        "concretely enough that you would know it had "
                        "happened."),
    "out_of_scope": ("What this is not",
                     "One line per thing you do not want this course to "
                     "spend your weeks on. The most useful box on this "
                     "page — it is what stops a course growing sideways."),
    "prior_exposure": ("Where you are with this subject already",
                       "Your profile says how you learn; this says what you "
                       "have already met of this subject in particular."),
}

# The lede over the whole form (design §4, Stop 6): no model is called here.
SCOPE_LEDE = ("Nothing on this page calls a model — it is a form, and what "
              "you write in it is what the next stage is briefed with.")

# The hours question, which is the sizing constant for the whole course: one
# unit is meant to be one honest week of your work.
SCOPE_HOURS_LEAD = "Hours a week you can really give this"
SCOPE_HOURS_HINT = ("A range, low to high. Units are sized against the low "
                    "end, so answer for a bad week rather than a good one.")
SCOPE_CADENCE_HINT = ("When those hours happen, if it matters — "
                      "\"two weekday evenings\", \"one long Sunday\". "
                      "Optional.")

# Where the outline stage leaves the course it drafted, under the course's
# own directory in the managed home. Spelled here as it is spelled in the
# worker — the wizard cannot import the module that writes it (L1's grep
# guard), and a name that appears twice is better than a route that reaches
# across the process boundary to ask.
DRAFT_DIR = ".draft-onboarding"

# The gate's lede, and the sentences around the two numbers. Both figures
# come out of the `outline_ready` payload the worker wrote: this module
# still never reads the model configuration, and the words under the
# numbers say which one is the expectation and which one is the stopping
# line — an estimate at display size with cents on it reads as a price, and
# what keeps that honest is the other number standing beside it.
#
# The second number is *headroom*, not a ceiling: budgets are per tenant
# per role for the life of an account, so what bounds this build is what is
# left of them, and it is smaller on a second course than on a first. The
# word under it says "left" for that reason, and the sentence says what the
# mechanism actually is — a pre-call check, which a call already under way
# can carry its role a little past.
GATE_LEDE = ("This is the course that was drafted for you. Read it, then "
             "decide: approve it and the first phase of materials gets "
             "built, or send it back with a note saying what to change.")
GATE_ESTIMATE_WORD = "expected, at today's prices"
GATE_HEADROOM_WORD = "left before it refuses"
# Two sentences, one per figure. The four it used to be were the runner's
# internals recited on the screen where a decision is taken — read a role's
# spend, refuse at or past the budget, a call already under way finishes —
# and that paragraph belongs in `docs/onboarding-design.md`, where it is.
# What this has to say is what each number means and that the second one is
# a stopping line rather than a cap.
GATE_HEADROOM = ("The estimate is an expectation, not a cap: it prices the "
                 "plan at today's rates, and the real bill comes in over or "
                 "under it. The second figure is what these roles have left "
                 "on their budgets — the build refuses at that line, and a "
                 "call already under way finishes, so it stops there rather "
                 "than never crossing it.")
# When the headroom will not cover the estimate, said before the button
# rather than discovered as a stopped build. The approve form still
# renders — this is the learner's money and their call — but nothing here
# lets them press it thinking the build can finish.
GATE_SHORT = ("Less is left than the estimate needs; the build will stop "
              "partway. Raise the budgets in models.yaml first.")
GATE_NONE = ("Nothing is left on these roles' budgets, so the build will "
             "stop at its first call and buy nothing. Raise the budgets in "
             "models.yaml first.")

# The two sentences that print what was actually spent, from the ledger the
# runner writes as it spends. Drafting is money that has already gone, and
# the gate said nothing about it before this — the welcome screen's promise
# is about the stage that costs, and the stage that drafts is a stage that
# costs too. The landing's receipt is the same fact after the fact, which is
# what makes the promise checkable rather than merely made: two decimals
# belong here, where they are the bill, and not on an estimate.
# "So far", and the number of drafts when there has been more than one: a
# rejected outline was drafted again and the ledger holds both, so a
# sentence naming "this outline" would be pricing one draft at the cost of
# all of them.
# The one line between the figures and the list: without it the plan reads
# as five more facts about money rather than as what the money is for.
GATE_PLAN_LEAD = "What that buys:"

GATE_SPENT = ("Drafting cost so far: {spent}{across}. That is already "
              "spent, and it is not part of the numbers above.")
GATE_SPENT_ACROSS = ", across {n} drafts"
RECEIPT = ("Model spend for this course: {total} — {draft} to draft, "
           "{build} to build")
RECEIPT_APPROVED = " (approved at about {estimate})"
RECEIPT_NONE = "No model spend is recorded against this course."

# The same number, said where a learner scanning for "how much?" looks:
# under the lede, before three thousand pixels of outline (F19). Stop 0
# promises a screen that shows the number first, and "first" had come to
# mean "above the button" — which it is, and which is not what anybody was
# told. The card itself stays where it is, after the evidence, because that
# is where the decision is taken; this only says the number and points at
# it. The figure and the word under it are the card's own — `estimate_cost`
# draws both places — so the two can never come to say different things
# about the same payload.
GATE_COST_LEAD = ("Building the first phase of materials is the stage that "
                  "costs money, and nothing is spent until you say so —")

# What the reject box asks for, and why an empty one is refused: the note is
# the whole content of a rejection, and a redraft briefed with nothing is the
# same stage run twice at the same cost.
REJECT_LEAD = "What should change"
REJECT_HINT = ("The outline is drafted again with this note in the brief, so "
               "say what was wrong rather than that something was.")
REJECT_EMPTY = ("Sending an outline back needs a note saying what to change — "
                "a redraft briefed with nothing is the same outline again")

# What the build's retry button says under it, and the one thing about this
# stop that differs from every other retry in the wizard: a stopped build
# kept what it had finished, and the approval it ran under is a row upstream
# in the ledger that a stopped run did not spend. So this button asks for
# neither the money already spent nor the decision already taken.
BUILD_RETRY_ASIDE = ("What was already finished was kept, so this carries on "
                     "from where it stopped rather than starting over — and "
                     "it does not ask you to approve anything again.")

# And what the publication's retry says under it. Publishing calls no model
# at all — it moves finished files and compiles them — so the one thing this
# button has to promise is that pressing it costs nothing.
PROMOTE_RETRY_ASIDE = ("Publishing moves files and compiles them; it calls no "
                       "model and spends nothing, so this costs you nothing "
                       "and your built materials are exactly where the build "
                       "left them.")

# The committed page the landing card points at, and the tutor's config
# block with this course and this tenant filled in. The repo has never
# committed the snippet anywhere (design §9), so the doc is where a learner
# who closed the tab finds it again — and the card prints a filled-in copy
# so that nobody has to work out their own paths from a template.
MCP_DOC = "docs/mcp-config.md"
MCP_LEDE = ("The same course, read by your own assistant. This runs on your "
            "machine against this database, and the conversation happens "
            "wherever you already work — on your inference bill, not this "
            "system's.")
# Where the block goes, said before the block. Deliberately unspecific about
# the file: `docs/mcp-config.md` names no path for any host either ("most
# MCP clients read a JSON file of servers"), and a wizard that invented one
# would be sending a stranger to edit a file this repository has never seen.
MCP_DEST = ("Paste this into your assistant's MCP configuration — most "
            "clients keep one JSON file of servers, and this is one entry "
            "in it.")

# The review screen's caption, design §4's own sentence. What is under it is
# the SKILL.md source itself rather than a styled rendering of it: the
# projection *is* a markdown document, and the honest review of a document
# that gets sent somewhere is the document that gets sent. The styled view
# of the same claims already exists at `/profile`, linked from here.
REVIEW_CAPTION = ("This exact document rides along on every model call that "
                  "builds your course.")

# And the line that says which half of it is whose. The document is one
# document — that is settled — but it opens with two paragraphs curricle
# wrote and closes with a footer holding a terminal command, and the lede
# used to claim it was generated "from your claims, and from nothing else",
# which anybody who read the next four lines could see was false. The split
# rendering shows the difference; this sentence says it, because a
# distinction carried by type alone is a distinction some readers do not get.
#
# Structurally, and never by colour: "the grey paragraphs" is a sentence
# that is wrong in the dark theme and wrong again for anyone reading this
# through a screen reader. It names the parts instead — and it does not
# hand curricle the whole frontmatter, because the description line in it
# is the learner's own sentence when they wrote one.
READBACK_LEGEND = ("Curricle wrote the opening paragraphs, the section "
                   "headings and the footer; everything between them is a "
                   "claim of yours, as is the description line at the top.")

# The fallback for a browser with no JavaScript, and only for that browser.
# A full-page refresh resets scroll, selection and focus and re-announces
# the page to a screen reader; over an eleven-minute build at five seconds
# that is a hundred and thirty yanks, and `prefers-reduced-motion` cannot
# govern a meta refresh. So the poll below is the mechanism, this is the
# floor under it, and thirty seconds is chosen for the browser that has no
# choice: long enough not to be a twitch, short enough that nobody sits in
# front of a finished stage.
META_REFRESH = '<meta http-equiv="refresh" content="30">'
NOSCRIPT_REFRESH = f"<noscript>{META_REFRESH}</noscript>"

# The status route, and the one script in the wizard. It exists because the
# two long waits are minutes long and the page under them holds still: the
# elapsed line is swapped in place, and the page is navigated only when the
# ledger says the stage or its status has actually moved — because that is
# the only time there is a different screen to be on. The chip is not
# text-swapped: design §5 says the mark and the word always travel
# together, and a word changed under a mark that still says the other thing
# would be the one lie this screen cannot afford. A status change is a
# reload, which redraws both.
#
# Written as its own constant rather than inside a template: it is
# concatenated, never `%`-formatted and never f-string interpolated with
# braces of its own, and the wizard's own state rides in on data attributes
# rather than being spliced into the source. The route's path is spelled
# twice for that reason — once here as a literal the script can carry and
# once as the route — and a test holds the two spellings together.
STATUS_PATH = "/onboarding/status"
POLL_JS = """
(function () {
  var line = document.getElementById("wait");
  if (!line || !window.fetch) return;
  var elapsed = document.getElementById("wait-elapsed");
  var stop = line.getAttribute("data-stop");
  var status = line.getAttribute("data-status");
  function ask() {
    fetch("/onboarding/status", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s) return;
        if (s.stop !== stop || s.status !== status) { location.reload(); return; }
        if (elapsed) elapsed.textContent = s.elapsed;
      })
      .catch(function () {});
  }
  setInterval(ask, 5000);
})();
"""

# What each stop is called on screen: the h1 on every stop past the
# profile, and the stage name on the masthead's words line at the profile
# stop, which is the one stop whose screens have h1s of their own.
STOP_TITLES = {
    "profile": "Your learner profile",
    "scope": "What you want to learn",
    "outline": "Drafting your course outline",
    "outline_gate": "Your outline, and what the build will cost",
    "build": "Building the first phase",
    "promote": "Publishing your course",
    # Not a stop — the fold's terminal stage, and the only one the waypath
    # is drawn for with every stone behind the learner and none under them.
    "done": "Your course is ready",
}
# And what each stop is called on its stone. Never printed: a stone carries
# no words, so these are what its visually-hidden phrase says instead
# ("Approval: to come"), which is the whole of what a reader who gets no
# drawing is given.
STEP_LABELS = {
    "profile": "Profile", "scope": "Scope", "outline": "Outline",
    "outline_gate": "Approval", "build": "Build", "promote": "Publish",
}


# --------------------------------------------------------------------------
# The wizard's slice of the design system
# --------------------------------------------------------------------------

WIZARD_CSS = theme.style("""\
  .wizard { max-width:720px; margin:0 auto; padding:0 24px 90px; }
  .masthead { padding:40px 0 6px; }
  .masthead .wordmark { margin:0; }
  .masthead .eyebrow { margin:12px 0 0; }
  h1 { font-weight:700; font-size:clamp(26px,5vw,34px); letter-spacing:-.01em;
       margin:14px 0 0; }
  .lede { margin:12px 0 0; color:var(--muted); font-size:16px; max-width:60ch; }
  /* The waypath, at the size the hub draws it: the setup is six stones and
     the same gesture the finished course will use. A list rather than a row
     of bare spans, because each stop is an item with a position — the stone
     is the drawing (aria-hidden) and the word inside it is what that
     position is, for a reader who gets no drawing at all. `display:flex` on
     the item is what blockifies the stone span so the component's width and
     height still apply. */
  ol.waypath { margin:22px 0 0; padding:0; list-style:none; }
  ol.waypath li { display:flex; }
  .vh { position:absolute; width:1px; height:1px; margin:-1px; padding:0;
        overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0; }
  .stepline { font-size:13.5px; font-weight:600; color:var(--muted);
              margin:12px 0 0; }
  .gatebox { background:var(--panel); border:1px solid var(--line);
             border-radius:18px; box-shadow:var(--shadow); padding:20px 24px;
             margin:26px 0; }
  .gatebox.attention { border-color:var(--accent); border-width:1.5px; }
  .gatebox h2 { font-size:19px; font-weight:700; margin:0 0 6px; }
  .gatebox p { font-size:14.5px; line-height:1.6; color:var(--muted);
               margin:0 0 10px; }
  .gatebox p:last-child { margin-bottom:0; }
  .gatebox b { color:var(--ink); }
  .state { display:inline-flex; align-items:center; gap:6px; }
  .state svg { display:block; }
  .stateline { display:flex; flex-wrap:wrap; align-items:center; gap:10px;
               margin:0 0 12px; }
  .stateline .note { font-size:13.5px; font-weight:600; color:var(--muted); }
  .elapsed { font-size:13.5px; font-weight:600; color:var(--muted); }
  .wording { color:var(--ink); }
  /* Three sibling sections, three panels (the operator's Fork D, over the
     art director's recommendation that the promises be the only panel).
     The list sits on the panel's own inset, so it takes no top margin. */
  .never { margin:0; padding:0 0 0 22px; }
  .never li { font-size:14.5px; line-height:1.6; color:var(--muted);
              margin:9px 0; max-width:62ch; }
  .ask { display:flex; flex-wrap:wrap; align-items:center; gap:14px;
         margin:28px 0 0; }
  .ask .aside { font-size:13.5px; color:var(--muted); }
  .field { padding:20px 24px; margin:22px 0; }
  .field h3 { font-size:17px; font-weight:700; margin:0 0 5px; }
  .field .explain { font-size:14.5px; line-height:1.6; color:var(--muted);
                    margin:0 0 13px; max-width:62ch; }
  /* The examples are a <details>, open only while the field is empty (the
     operator's Fork C): they teach the register, and once a learner has
     written in it they have done their job. No script — the `open`
     attribute is written from the fold, like everything else here. */
  .eg { border-left:2px solid var(--line); padding:1px 0 1px 14px;
        margin:0 0 16px; }
  .eg summary { cursor:pointer; }
  .eg[open] summary { margin:0 0 5px; }
  /* Captions over a learner's own words, in the .stepline register:
     sentence case, no tracking, no small caps. The letterspaced uppercase
     eyebrow is the bookish vocabulary DIRECTION.md retired, and this was the
     one surface that had brought it back — over the learner's own sentences,
     which is the worst place in the product for it. */
  .eg summary, .claimkey { font-size:13.5px; font-weight:600;
          color:var(--muted); margin:0; }
  .claimkey { display:block; margin:0 0 5px; }
  .eg p { font-size:13.5px; line-height:1.55; color:var(--muted);
          margin:0 0 7px; max-width:62ch; }
  .eg p:last-child { margin-bottom:0; }
  label.claim { display:block; margin:0 0 13px; }
  /* --edge, not --line: a hairline is decoration and computes 1.30 against
     the panel a box sits on, which is a control boundary nobody can see. And
     `field-sizing` grows the box to the text it holds — the read-back screen
     that slices a learner's own last line in half is not a read-back — with
     `min-height` still the floor and `rows` (set from the saved length) the
     fallback where the property is not supported. */
  textarea { width:100%; min-height:64px; field-sizing:content;
             resize:vertical;
             font:14px/1.55 """ + theme.FONT_BODY + """;
             color:var(--ink); background:var(--panel);
             border:1.5px solid var(--edge); border-radius:12px;
             padding:10px 13px; }
  /* Placeholder copy is read to be acted on, so it is body text and takes
     --muted, never the decorative --faint. */
  textarea::placeholder { color:var(--muted); }
  /* No `outline:none` here: the base sheet's :focus-visible ring is the
     system's focus, and a 1.5px border swap in its place is thinner than the
     ring it replaced. The border colour stays as reinforcement. */
  textarea:focus { border-color:var(--accent); }
  /* The scope form's one-line answers, in the same box as the many-line
     ones: a title and a number are typed into the same kind of field a
     claim is, because they are the same kind of answer. */
  input[type=text], input[type=number] { font:14px/1.55 """
             + theme.FONT_BODY + """; color:var(--ink);
             background:var(--panel); border:1.5px solid var(--edge);
             border-radius:12px; padding:9px 13px; }
  input[type=text] { width:100%; }
  input[type=number] { width:88px; }
  input:focus { border-color:var(--accent); }
  /* The one accent, on the one control that picks the course's shape: with
     no accent-color a checked radio comes out in the browser's blue, which
     would be the only cool colour in the product. Sized like the hub's
     checkboxes, because they are the same control at the same size. */
  input[type=radio] { accent-color:var(--accent-strong); width:17px;
             height:17px; }
  .hours { display:flex; flex-wrap:wrap; align-items:center; gap:10px;
           margin:0 0 13px; }
  .hours span { font-size:14px; color:var(--muted); }
  .choice { display:block; border:1.5px solid var(--edge); border-radius:12px;
            padding:11px 14px; margin:0 0 10px; }
  .choice b { font-size:14.5px; }
  /* 25px is the radio (17px, above) plus its own right margin: the sentence
     hangs under the mode's name, not under the control. Resizing the radio
     means moving this. */
  .choice span { display:block; font-size:13.5px; line-height:1.55;
                 color:var(--muted); margin:4px 0 0 25px; max-width:58ch; }
  .choice input { margin:0 8px 0 0; }
  .hint { font-size:13px; line-height:1.6; color:var(--muted); margin:0 0 13px; }
  .hint:last-child { margin-bottom:0; }
  /* The drafted outline, read back. Phases and the shelf are the same
     panels the forms use, so the review of a course reads in the same
     rhythm as the questions that produced it. */
  ol.units, ul.shelf { margin:0; padding:0; list-style:none; }
  .units li, .shelf li { margin:0 0 15px; max-width:62ch; }
  .units li:last-child, .shelf li:last-child { margin-bottom:0; }
  .units b, .shelf b { font-size:14.5px; }
  .units span, .shelf p { display:block; font-size:13.5px; line-height:1.6;
                          color:var(--muted); margin:3px 0 0; }
  /* A milestone in the read-back, in the hub's own treatment: the green
     tint, the product's one drawn glyph, and the word "milestone" printed
     beside its kind so the row says what it is with every colour stripped
     out. What the hub will track is what the gate reads back. */
  .units li.ms { display:flex; gap:8px; background:var(--good-soft);
                 border-radius:10px; padding:8px 11px; margin:0 0 15px; }
  .units li.ms .flag { flex:none; margin:3px 0 0; color:var(--good-text); }
  /* The steps of a stepped unit, under the unit that owns them: the hub
     checks these off one by one, so an outline that showed only the unit
     would be an approval of fewer things than the course will ask for. */
  ol.substeps { margin:6px 0 0; padding:0 0 0 18px; }
  .substeps li { font-size:13.5px; line-height:1.55; color:var(--muted);
                 margin:2px 0 0; }
  /* What the course adds up to, in the hub's own arithmetic. Derived from
     the compiled draft on every draw, like everything else above it. */
  .counts { font-size:13.5px; font-weight:600; color:var(--muted);
            margin:12px 0 0; }
  /* The gate says the estimate twice — once under the lede, where a
     learner scanning for "how much?" looks (F19), and once inside the card,
     where the decision is taken — so the rule reaches a number on the
     ground as well as one in a panel. The second selector carries .gatebox
     because the panel's own `p` rule is one element more specific than a
     bare class would be, and the number would quietly come out at body size
     and body color. */
  p.cost, .gatebox p.cost { font-family:""" + theme.FONT_DISPLAY + """;
          font-weight:700; font-size:clamp(24px,4.5vw,30px);
          letter-spacing:-.01em; color:var(--ink); margin:0 0 8px; }
  /* The two numbers side by side, and not at the same size. They were, and
     at equal weight the headroom landed first: the eye takes the largest
     number on a card as the price, and the headroom is the one figure on
     this screen that is not the cost. So the estimate keeps display size
     and the headroom steps down one — still a figure, still beside it, no
     longer the headline. The word under each carries which is which,
     because the word is the message and the size is only the order to read
     them in. (No example figure in this comment: a stylesheet is served,
     and a number in a comment is a number on the page.) */
  .costs { display:flex; flex-wrap:wrap; align-items:baseline;
           gap:6px 40px; margin:0 0 12px; }
  .gatebox .costs p.cost { margin:0; }
  .gatebox .costs p.cost.second { font-size:clamp(18px,3vw,21px); }
  .cost .costword { display:block; font:600 13.5px/1.5 """
             + theme.FONT_BODY + """; letter-spacing:0;
             color:var(--muted); margin:2px 0 0; }
  .gatebox p.spent { font-size:14.5px; line-height:1.6; color:var(--muted);
          margin:0 0 10px; max-width:62ch; }
  /* The plan as a list, because it is the thing the money is approved
     against and a run-on sentence is not a thing anybody checks. At body
     weight, though: five bold lines in a row read as five headings over
     nothing, and what these are is five things being bought. The lead line
     is the hinge between the figures and the list — without it the plan
     reads as more facts about money. */
  .gatebox p.buys { font-size:14.5px; font-weight:600; color:var(--ink);
          margin:16px 0 0; }
  ul.plan { margin:8px 0 0; padding:0; list-style:none; }
  .plan li { margin:0 0 11px; max-width:62ch; }
  .plan li:last-child { margin-bottom:0; }
  .plan .what { display:block; font-size:14.5px; color:var(--ink); }
  .plan span.detail { display:block; font-size:13.5px; line-height:1.55;
               color:var(--muted); margin:2px 0 0; }
  .receipt { font-size:14.5px; line-height:1.6; color:var(--muted);
             margin:14px 0 0; max-width:62ch; }
  .receipt b { color:var(--ink); }
  /* The lede's copy of the number: the same drawing as the card's, with a
     little more air over it because it sits on the ground, and one sentence
     under it saying where the decision itself is. */
  p.cost.upfront { margin:22px 0 4px; }
  .costline { font-size:14.5px; line-height:1.6; color:var(--muted);
              margin:8px 0 0; max-width:62ch; }
  /* The course's own name, on the ground rather than in a card: it is the
     one moment of arrival on the gate, and an h3 inside a panel identical to
     the phase panels under it made it a list item (F23). The phases read as
     its contents, and the count line sits under the title it counts. */
  h2.coursetitle { font-family:""" + theme.FONT_DISPLAY + """;
          font-weight:700; font-size:clamp(24px,4.5vw,26px);
          letter-spacing:-.01em; color:var(--ink); margin:34px 0 0; }
  .nav { display:flex; flex-wrap:wrap; gap:12px; margin:30px 0 0; }
  /* The way back is not the action the screen is for, so it is a text link
     and not a pill: one forward action per screen, and it is Save. */
  .nav .back { font-size:14px; font-weight:600; }
  .gateline { font-size:14.5px; line-height:1.6; color:var(--muted);
              margin:16px 0 0; max-width:62ch; }
  .gateline b { color:var(--ink); }
  .caption { font-size:14.5px; line-height:1.6; color:var(--ink);
             margin:26px 0 0; max-width:62ch; }
  /* The projection, shown as what it is: a text file, in a text file's
     typeface, wrapping rather than scrolling sideways so every line of it
     can be read without a horizontal gesture.
     Split, though (the operator's Fork B): curricle's own words — the
     frontmatter, the headings, the two framing paragraphs, the footer — are
     the mono the whole document used to be, and the learner's own sentences
     are set in body type in --ink. One panel, one document, whole; what the
     split does is show, rather than claim, which half of it is theirs. */
  pre.projection { font:13px/1.62 """ + theme.FONT_MONO + """;
                   white-space:pre-wrap; overflow-wrap:anywhere;
                   background:var(--panel); border:1px solid var(--line);
                   border-radius:18px; box-shadow:var(--shadow);
                   color:var(--muted); padding:20px 24px; margin:14px 0 0; }
  pre.projection .mine { font:15px/1.6 """ + theme.FONT_BODY + """;
                   color:var(--ink); }
  /* The tutor's config, inside a panel rather than as one: it is a block
     within the closing card, so it takes the card's own inset rather than
     the projection's full-page shadow. Wrapping for the same reason — a
     path long enough to scroll sideways is a path nobody can copy. */
  pre.snippet { font:12.5px/1.6 """ + theme.FONT_MONO + """;
                white-space:pre-wrap; overflow-wrap:anywhere;
                background:var(--chip); border:1px solid var(--line);
                border-radius:12px; color:var(--ink);
                padding:14px 16px; margin:0 0 12px; }
""")

# The illustration vocabulary this surface owns: three small marks drawn in
# currentColor, one per wait. Drawn rather than emoji, like theme.FLAG_SVG —
# an emoji is somebody else's typeface and a different size in every one.
_CLOCK = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
          '<circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" '
          'stroke-width="1.6"/><path d="M6 3.1V6l2 1.4" fill="none" '
          'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
          'stroke-linejoin="round"/></svg>')
_ARROW = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
          '<path d="M1.6 6h8M6.4 2.8 9.6 6l-3.2 3.2" fill="none" '
          'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
          'stroke-linejoin="round"/></svg>')
_ALERT = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
          '<circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" '
          'stroke-width="1.6"/><path d="M6 3.2v3.3M6 8.4v.5" fill="none" '
          'stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
          '</svg>')
# (There was a fourth, a check mark, drawn for the done chips of the step
# strip the waypath replaced. A stone that is lit is what "done" looks like
# in this product, and a second drawing for the same word is the kind of
# vocabulary the direction spends its restraint on not having.)

# (mark, word, chip tint) per status. The tint reinforces; the word carries.
_STATUS_CHIPS = {
    "pending": (_CLOCK, PENDING_WORD, ""),
    "waiting": (_ARROW, WAITING_WORD, " acc"),
    "failed": (_ALERT, FAILED_WORD, " warn"),
}


# --------------------------------------------------------------------------
# Small pieces every screen shares
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Screen:
    """One rendered screen: its body, and whether it is still watching.

    `refresh` is not a property of the URL but of the state the body was
    drawn from — a pending stage asks the browser to come back, everything
    else does not — so the two travel together out of every screen function.
    """

    body: str
    refresh: bool = False


def _chip(status: str) -> str:
    """The state chip: mark and word, always both (design §5)."""
    mark, word, tint = _STATUS_CHIPS[status]
    return f'<span class="chip{tint} state">{mark}{word}</span>'


def elapsed_words(since: datetime | None) -> str:
    """How long the wait has run, in words. Elapsed, never a forecast.

    `None` means the flow has no ledger row carrying a time yet, which reads
    honestly as "just started" — the alternative, printing a duration
    measured from nothing, is the invented number this rule exists to refuse.

    Under a minute reads "less than a minute" rather than a figure in
    seconds. Second-precision is precision this screen cannot keep: the
    number moved in five-second jumps under the old refresh and reads as a
    stuck clock, and a stage measured in minutes has nothing to say about
    its first forty seconds that "less than a minute" does not say better.
    """
    if since is None:
        return "just started"
    seconds = int((datetime.now(timezone.utc) - since).total_seconds())
    if seconds < 60:
        return "less than a minute elapsed"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} elapsed"
    hours, minutes = divmod(minutes, 60)
    return (f"{hours} hour{'s' if hours != 1 else ''} "
            f"{minutes} minute{'s' if minutes != 1 else ''} elapsed")


def _waitline(stop: str, status: str,
              flow: onboarding.CourseFlow | None) -> str:
    """The state chip and the elapsed line, on a row the poll can find.

    The two facts the script compares against ride here as data attributes
    rather than being spliced into the script's source: what the ledger said
    when this page was drawn, so the poll can tell "still going" from "there
    is a different screen to be on now" without the server telling it twice.
    The elapsed span carries the only id the script writes to, which is the
    only text on a waiting screen that changes while nothing has happened.
    """
    since = (f'<span class="elapsed" id="wait-elapsed">'
             f"{elapsed_words(flow.updated_at)}</span>"
             if flow is not None else "")
    return (f'<p class="stateline" id="wait" data-stop="{stop}" '
            f'data-status="{status}">{_chip(status)}{since}</p>')


def _stone(stage: str, state: str) -> str:
    """One stone: the drawing for everyone who can see it, the word for the rest.

    The stone itself carries no text, so it is `aria-hidden` and the item
    around it holds the position in a phrase nobody sees — "Outline:
    current". A ring a screen reader cannot read is a position only some
    readers are given.
    """
    tint = {"done": " lit", "current": " here", "to come": ""}[state]
    current = ' aria-current="step"' if state == "current" else ""
    return (f'<li{current}><span class="wp-stone{tint}" aria-hidden="true">'
            f'</span><span class="vh">{STEP_LABELS[stage]}: {state}</span></li>')


def _waypath(stop: str, sub: str | None = None) -> str:
    """Where you are, drawn in the product's own gesture: six stones, one line.

    This function used to draw a strip of chips, and its docstring used to
    argue for it: that the waypath means "where you are on a path you will
    walk", that six setup stops are not that path, and that spending the
    gesture here would spend it on the one part of the product a learner
    sees exactly once. The operator decided the other way (design review,
    fork A), and the decision is the design now. The reasons it turns on:
    onboarding is the most literally tracked thing in the product — a
    ledger, a fold, a derived "you are here" — which is exactly where the
    house rule says the waypath goes; the strip was a second progress idiom
    standing beside the first, in a product whose personality is one move
    plus discipline everywhere else; and the stones a learner watches fill
    across six stops are the stones the hub lays out at full size on the far
    side of the setup, so the hand-off *is* the gesture rather than one
    product handing over to another.

    Server-rendered, like the front door's mini paths: lit behind you, the
    hollow ring on the stop you are at, unlit ahead. `theme.WAYPATH_JS` is
    untouched and unused here — it exists to light a stone while you watch,
    and nothing on these pages changes without a page load.

    Under the stones, one line of words carrying what the strip and the
    `.screenline` used to say between them, each thing said once (F9, F29):
    "Step 3 of 6", the stage's name only where the h1 is not already it, and
    the sub-screen only while the profile stop's four forms are being filled
    in. `done` is the fold's terminal stage rather than a seventh stop, so it
    lights every stone and rings none — a ring over a finished setup would be
    the one screen in the wizard saying there is more to do when there is not.
    """
    total = len(onboarding.STAGE_SEQUENCE)
    if stop == "done":
        stones = "".join(_stone(stage, "done")
                         for stage in onboarding.STAGE_SEQUENCE)
        return (f'<ol class="waypath" role="list">{stones}</ol>'
                f'<p class="stepline">All {total} steps done</p>')
    at = onboarding.STAGE_SEQUENCE.index(stop)
    stones = "".join(
        _stone(stage, "done" if i < at else "current" if i == at else "to come")
        for i, stage in enumerate(onboarding.STAGE_SEQUENCE))
    words = f"Step {at + 1} of {total}"
    if stop == "profile":
        # The one stop with screens of its own, and the only one whose h1 is
        # never the stage name — so this is where the stage name is said.
        words += f" · {STOP_TITLES['profile']}"
        if sub in _FORM_FIELDS:
            words += f" — screen {sub} of {len(PROFILE_SCREENS)}"
    # `role="list"` against `list-style:none`: VoiceOver stops announcing a
    # list whose markers CSS has removed, and the list is how the six stops
    # are counted for a reader who gets none of the drawing.
    return (f'<ol class="waypath" role="list">{stones}</ol>'
            f'<p class="stepline">{words}</p>')


def page_title(stop: str, sub: str | None = None) -> str:
    """What this screen is called in a tab, in history, and in a bookmark.

    Thirteen screens shared one title ("curricle — setting up"), which is a
    history nobody can read back and two tabs nobody can tell apart (F11).
    The screen's own name comes first because that is what a narrow tab shows.
    """
    if stop == "profile" and sub in SCREEN_NAMES:
        return SCREEN_NAMES[sub]
    return STOP_TITLES[stop]


def _page(stop: str, screen: Screen, tenant_slug: str,
          sub: str | None = None) -> str:
    """The wizard's one page shell: the mark, the path, and the screen.

    The masthead leads with the wordmark, and it is `theme.WORDMARK` itself
    rather than a second drawing of it — the mark and the product's promise
    are the same three stones, and the six under it are that gesture at full
    size. Static, with no link on it: a tenant who has not finished setting
    up has no front door to go home to (the gate sends them straight back
    here), and a dead link is worse than no link.

    The crumb reads forward from the mark rather than out of the page:
    `/profile` is a destination this setup is producing, worded as one, and
    it comes second. The tenant slug left the masthead entirely — "tenant
    stranger" is infrastructure printed on the most hospitable screen in the
    product — and says its one true thing in the footer instead.
    """
    e = html_mod.escape
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{NOSCRIPT_REFRESH if screen.refresh else ""}
<title>{e(page_title(stop, sub))} — setting up curricle</title>
<style>
{WIZARD_CSS}</style>
</head>
<body>
<div class="wizard">
  <header class="masthead">
    <p class="wordmark">{theme.WORDMARK} curricle</p>
    <p class="eyebrow">setting up curricle
    <span class="sep">·</span> <a href="/profile">your profile page</a></p>
    {_waypath(stop, sub)}
  </header>
  {screen.body}
  <footer>
    Your saved screens are kept; you can close this tab and pick up where you
    left off. Signed in as {e(tenant_slug)}.
  </footer>
</div>
{f"<script>{POLL_JS}</script>" if screen.refresh else ""}
</body>
</html>
"""


def default_screen(profile_state: profile.ProfileState) -> str:
    """Which sub-screen a bare `/onboarding/` opens at during the profile stop.

    Every redirect in this module lands on `/onboarding/` with nothing after
    it, and the footer promises you can close the tab and pick up where you
    left off, so this function is the whole of whether that sentence is true.
    It used to answer "welcome" always, which made the promise false on every
    screen but the first.

    Derived, like everything else here. A profile with nothing in it has not
    been left off anywhere, so it opens at the welcome. Otherwise the learner
    stopped at the first screen still carrying a gate field with no claim on
    it — `profile_gate_missing` is the same rule the gate sentence and the
    publish refusal already ask. And a profile whose gate is satisfied is one
    screen from being published, so it opens at the review.

    Screen 4 has to be named here rather than falling out of the gate,
    because it carries no gate field: nothing on it can be *missing*, so a
    learner who saved screens 1 to 3 and closed the tab was offered Publish
    without ever being shown "Subjects" — the one screen whose question is
    what the profile is worth once this course is over. So the rule ends
    with it: a profile with no claim under `subject_adapters` opens there,
    and only a profile that has answered every screen opens at the review.

    Answering it is still optional; being *offered* it is not. Emptying the
    box later leaves the claim retracted and this function pointing at
    screen 4 again, which is the honest reading of a field with nothing in
    it — and `?screen=review` still goes straight to the button, because
    `?screen=` opens any screen the fold has opened and this is only the
    answer to a URL that names none.
    """
    if not any(profile_state.field_claims(f) for f in profile.FIELDS):
        return "welcome"
    missing = onboarding.profile_gate_missing(profile_state)
    for number, _, fields in PROFILE_SCREENS:
        if any(f in missing for f in fields):
            return number
    if not profile_state.field_claims("subject_adapters"):
        return "4"
    return "review"


# --------------------------------------------------------------------------
# The screens
# --------------------------------------------------------------------------

def welcome_screen(*, worker_running: bool) -> Screen:
    """Stop 0: what this does, what it costs, what it never does.

    The never-promises sit above the ask because a promise made under the
    button is a promise made after the decision. The worker banner sits
    above them again for the same reason in a different key: a wizard that
    would wait forever on a process nobody started says so before the first
    form, not after it (design §6).
    """
    banner = "" if worker_running else f"""
  <div class="gatebox attention">
    <p class="stateline">
      <span class="chip warn state">{_ALERT}{WORKER_WORD}</span>
      <span class="note">the second process this wizard needs</span></p>
    <h2>Start the worker before you begin</h2>
    <p>Setting up a course takes two processes side by side:
    <code>python -m curricle serve</code>, which is this one, and
    <code>python -m curricle work</code>, which does the building. The second
    one is not running, so anything you start here would wait forever.</p>
    <p>Open a second terminal, start it, and reload this page.</p>
  </div>"""
    promises = "".join(f"<li>{p}</li>" for p in NEVER_PROMISES)
    return Screen(f"""
  <h1>Let us build you a course</h1>
  <p class="lede">Two things happen here, in order: you tell this system how
  you learn, and then it writes a course for you against that profile.</p>
{banner}
  <div class="gatebox">
    <h2>What this will do</h2>
    <p><b>First, your profile.</b> Four short forms — your background, how you
    learn, how to calibrate an explanation for you, and how that translates
    across subjects. Every line is yours, in your own words, and no model is
    called anywhere in that path.</p>
    <p><b>Then, your course.</b> You describe what you want to learn; the
    system drafts an outline and shows it to you; once you approve it, it
    builds the first phase of real materials and publishes the course.</p>
  </div>
  <div class="gatebox">
    <h2>What it costs</h2>
    <p>Two stages call a model and so cost money: <b>drafting the outline</b>,
    which is cheap, and <b>building the first phase of materials</b>, which is
    the expensive one. Each runs under a standing spending ceiling it refuses
    to cross, and the build does not start until you have approved an estimate
    on screen. The profile forms cost nothing.</p>
  </div>
  <div class="gatebox">
    <h2>What this never does</h2>
    <ul class="never">{promises}</ul>
  </div>
  <p class="ask">
    <a class="pill primary" href="/onboarding/?screen=1">Begin →</a>
    <span class="aside">About ten minutes, and you can stop between any two
    screens.</span>
  </p>
""")


def _examples(field: str, *, unanswered: bool) -> str:
    """The two example claims — open while the field is empty, folded after.

    The examples teach a register: the length of a claim, its plainness, the
    fact that it is a sentence rather than a form field. Once a learner has
    written in that register they have done their job, and four fields
    holding two examples each is the difference between a screen you read and
    a screen you scroll (the operator's Fork C). So they are a `<details>`
    whose `open` comes off the fold — the same place the boxes come from —
    and never off a script or a cookie: this page has no state a reload could
    lose, and that is as true of a disclosure triangle as of a claim.

    House copy, so unescaped, exactly like the never-promises and the wording
    sentences: the only text on a form screen that came from anywhere but
    this module is a claim out of the ledger, and that is escaped where it is
    interpolated.
    """
    _, examples = FIELD_COPY[field]
    return (f'<details class="eg"{" open" if unanswered else ""}>'
            "<summary>For example</summary>"
            + "".join(f"<p>{x}</p>" for x in examples) + "</details>")


def box_rows(text: str) -> int:
    """How many rows a box holding `text` opens at.

    `field-sizing:content` is what actually fits a box to what is in it, so
    where a browser has that property this number is only the opening
    guess. Where it does not, this is the whole of the fix: a saved claim
    four lines long came back in a three-row box with its last line sliced
    through the x-height, on the one screen whose promise is that your own
    words are read back to you. Eighty columns is about what the box holds
    at this column width; an empty box opens at two, because a one-sentence
    claim sitting in three rows is two blank lines of nothing.

    Wrapping is counted per *line*, not over the whole text, and that is
    load-bearing rather than fussy: a claim of six short lines is 101
    characters, and a count over the string would open it at two rows and
    clip four of them — the same defect, on the same screen. The box beside
    this one now says in words that line breaks stay inside a claim, so the
    fallback has to be able to hold what that sentence invites. An empty
    line still occupies a row, which is why the length of one floors at 1.
    """
    return max(2, sum(math.ceil(max(len(line), 1) / 80)
                      for line in text.split("\n")))


def _claim_box(field: str, key: str, text: str, label: str,
               aria: str) -> str:
    """One textarea over one claim identity, prefilled from the fold.

    The caption a learner reads is the claim's position in its field — "Claim
    2" — and never the key it is filed under. The key is the claim's identity
    and it is forever, but `SUBJECT_ADAPTERS-02` set over somebody's own
    sentence reads as a database admin screen rather than as hospitality. It
    rides in `title`, for an operator who wants it, and in the `name` the
    POST reads back, which is where it was always doing the work.

    `aria` is what that caption costs and what pays it back. "Claim 1" is the
    right words on screen and the wrong accessible name: screen 1 carries
    three fields, so a form list read aloud would be "Claim 1, Claim 1, Claim
    1" where the old key at least told them apart. The `<h3>` naming the
    field is not associated with the box, so the field's own heading is
    carried into the name here — "Professional background, claim 1" — with
    the visible words inside it, which is the rule about labels and names.
    """
    e = html_mod.escape
    return (f'<label class="claim" title="{e(key)}">'
            f'<span class="claimkey">{e(label)}</span>'
            f'<textarea name="claim__{e(field)}__{e(key)}" '
            f'aria-label="{e(aria)}" '
            f'rows="{box_rows(text)}">{e(text)}</textarea></label>')


def _field_block(field: str, claims: list[profile.Claim]) -> str:
    """One field: what it is, what a claim looks like, and what you have said.

    Existing claims come back in fold order, each in its own box under its
    own key, because the key is the claim's identity for the rest of its
    life — editing a box re-asserts that key and emptying it retracts it, and
    both are things the learner should be able to see themselves doing.

    Two identical-looking boxes keep opposite rules about the Enter key: the
    saved ones hold their newlines inside one claim, and the Add box splits
    on every line. There is no script on this page to make them one control
    and the parsing is not the thing to change, so each box says its own rule
    directly under or over itself — a learner who presses Enter in a saved
    box was otherwise told the opposite by the placeholder below it.

    Two sentences, not four. The first pass at that rule printed one line
    above the saved boxes, a second under them and a third under the Add
    box, which is three instructions around two controls: the two about the
    saved boxes are now one line sitting between them and the Add box, where
    everything it describes is directly above it and the box it is *not*
    about is directly below.
    """
    explanation, _ = FIELD_COPY[field]
    boxes = "".join(
        _claim_box(field, c.key, c.text, f"Claim {n}",
                   f"{FIELD_LABELS[field]}, claim {n}")
        for n, c in enumerate(claims, 1))
    rule = ('<p class="hint">Each box is one claim: edit it to change it, '
            "empty it to delete it, and line breaks stay inside it.</p>"
            if claims else "")
    return f"""
    <div class="panel field">
      <h3>{FIELD_LABELS[field]}</h3>
      <p class="explain">{explanation}</p>
      {_examples(field, unanswered=not claims)}
      {boxes}{rule}
      <label class="claim"><span class="claimkey">Add a claim</span>
      <textarea name="new__{html_mod.escape(field)}"
      aria-label="{html_mod.escape(FIELD_LABELS[field])}, add a claim"
      rows="{box_rows('')}"
      placeholder="One claim per line"></textarea></label>
      <p class="hint">Each line becomes its own claim.</p>
    </div>"""


def _meta_block(state: profile.ProfileState) -> str:
    """Screen 1's description line: one box, one key, never a numbered one."""
    claim = state.claim("meta", META_KEY)
    explanation, _ = FIELD_COPY["meta"]
    # One box, so "has this field been answered" is one claim's existence.
    return f"""
    <div class="panel field">
      <h3>{FIELD_LABELS["meta"]}</h3>
      <p class="explain">{explanation}</p>
      {_examples("meta", unanswered=claim is None)}
      {_claim_box("meta", META_KEY, claim.text if claim else "",
                  "Description", FIELD_LABELS["meta"])}
      <p class="hint">One line, and one line only — empty this box to leave
      the description unset.</p>
    </div>"""


def _screen_nav(number: str, missing: tuple[str, ...]) -> str:
    """The way back, and the gate in plain words. No way forward but Save.

    One forward action per screen, and it is the Save button inside the
    form. The next-screen pill that used to sit here was a second forward
    arrow forty pixels under the first, outside the `<form>`, and pressing
    it discarded whatever had just been typed — on a page whose footer
    invites you to leave. The arrow is the accent's one meaning, "your next
    action", and it cannot mean two of them. Saving a screen you have not
    touched writes nothing and moves you on, so nothing was lost with the
    pill. Back stays, as a quiet text link, because it is not what the
    screen is for.

    When a required field is still empty the gate is the sentence naming
    what is missing, so the reason the path stops is on the line the path
    stops at. Refusing to publish is the review screen's job; this only says
    so — and it says it once, rather than trailing a second link to the
    review behind a Save button that already goes there.
    """
    e = html_mod.escape
    previous = SCREEN_ORDER[SCREEN_ORDER.index(number) - 1]
    back = (f'<a class="back" href="/onboarding/?screen={previous}">'
            f"← {SCREEN_NAMES[previous]}</a>")
    if missing:
        names = ", ".join(FIELD_LABELS[f] for f in missing)
        gate = f'<p class="gateline">{GATE_LEAD} <b>{e(names)}</b>.</p>'
    else:
        gate = ('<p class="gateline">Every field a course is written against '
                "has a claim on the record.</p>")
    return f'<div class="nav">{back}</div>{gate}'


def form_screen(number: str, profile_state: profile.ProfileState) -> Screen:
    """Stops 1–4: the profile forms, one `assert` per line you write.

    Everything on the screen is derived per request — the boxes from the
    profile fold, the gate sentence from the same fold — because the only
    record of what you have said is the evidence ledger, and a form drawn
    from anything else would be a second one.

    Plain urlencoded HTML, no JavaScript: the page a learner types their own
    profile into is the last place to make the typing depend on a script
    loading. The tier is `attested` and it is not a choice on the form —
    provenance decides it, and the provenance of a box you typed is you.
    """
    e = html_mod.escape
    heading, fields = next((h, f) for n, h, f in PROFILE_SCREENS if n == number)
    blocks = [_meta_block(profile_state)] if number == "1" else []
    blocks += [_field_block(f, profile_state.field_claims(f)) for f in fields]
    # No "Profile screen 2 of 4" line here any more: the masthead's words
    # line under the stones says it, once, beside the step it belongs to.
    return Screen(f"""
  <h1>{heading}</h1>
  <p class="lede">{SCREEN_INTROS[number]}</p>
  <form method="post" action="/onboarding/profile/{e(number)}">
    {"".join(blocks)}
    <p class="ask">
      <button class="pill primary" type="submit">Save this screen →</button>
      <span class="aside">Saved in your own voice, and read back to you on
      your profile page. Nothing here is sent to a model.</span>
    </p>
  </form>
{_screen_nav(number, onboarding.profile_gate_missing(profile_state))}
""")


def _projection(profile_state: profile.ProfileState) -> str:
    """The document, whole, with each part set in the voice that wrote it.

    `profilerender.skill_parts` is `render_skill_md` before its own join, so
    what is on the screen is still exactly the file that reaches a model —
    the same bytes, in the same order, with a span around the ones the
    learner typed. Not a second rendering of the same claims: a review of a
    document that gets sent somewhere is the document that gets sent.

    Escaped part by part, because every learner part is a sentence somebody
    typed and the house parts are the only text here that came from this
    repository.
    """
    e = html_mod.escape
    return "\n".join(
        f'<span class="mine">{e(text)}</span>'
        if source == profilerender.LEARNER else e(text)
        for source, text in profilerender.skill_parts(profile_state))


def review_screen(profile_state: profile.ProfileState) -> Screen:
    """Stop 5: the projection, whole, in two voices, with publish at both ends.

    The document is rendered here and nowhere else in this module —
    `profilerender` is the only thing that knows how a profile becomes that
    file, and a second renderer for the review screen would be a second
    answer to what the model is about to read.

    Two changes the review found, both about a screen whose job is
    *re-reading*. The document is set in two voices (the operator's Fork B):
    curricle's frame stays the mono it always was, the learner's own
    sentences are body type in ink, and a caption says which is which in
    words. And the Publish button is drawn above the document as well as
    below it, because below it meant nineteen hundred pixels down at desktop
    and twice that at 400px, with nothing above the fold saying a decision
    was waiting at all. Two buttons, one action: the POST is guarded by the
    fold, so the second press of either is a 409 rather than a second row.

    Publishing is refused here as well as displayed: the confirm form is not
    drawn at all while the gate is unsatisfied, and `POST .../publish` asks
    `profile_gate_missing` again for itself, because a button that is absent
    from a page is not a rule. The refusal panel is drawn once rather than
    twice — it is not the decision this screen offers, it is the reason
    there is none yet, and a page that says so at both ends is a page
    nagging somebody who has already read it.
    """
    e = html_mod.escape
    missing = onboarding.profile_gate_missing(profile_state)
    if missing:
        names = ", ".join(FIELD_LABELS[f] for f in missing)
        top = f"""
  <div class="gatebox attention">
    <p class="stateline">{_chip("waiting")}</p>
    <h2>Not ready to publish yet</h2>
    <p>{GATE_LEAD} <b>{e(names)}</b>.</p>
  </div>"""
        bottom = ""
    else:
        top = bottom = """
  <form method="post" action="/onboarding/profile/publish">
    <p class="ask">
      <button class="pill primary" type="submit">Publish my profile →</button>
      <span class="aside">Publishing opens the rest of the setup. Your claims
      stay editable on your profile page for as long as you have an account.</span>
    </p>
  </form>"""
    return Screen(f"""
  <h1>Read it back before you publish</h1>
  <p class="lede">This is the whole of what a course gets told about you.</p>
  <p class="caption">{REVIEW_CAPTION} {READBACK_LEGEND}</p>
{top}
  <pre class="projection">{_projection(profile_state)}</pre>
  <div class="nav">
    <a class="pill" href="/onboarding/?screen=1">← Edit your claims</a>
    <a class="pill" href="/profile">See it as a page</a>
  </div>
{bottom}
""")


def _scope_panel(name: str, control: str, *, labelled: bool = True) -> str:
    """One question on the scope form: what it asks, why, and the box.

    The heading *is* the label — one question per panel, so a second name
    over the box would be the same words twice. `labelled=False` is for the
    one panel whose control is a group rather than a box: a radio group's
    label is each option's own, and `for` pointing at one of three would name
    the wrong thing.
    """
    label, explain = SCOPE_LABELS[name]
    heading = (f'<label for="f-{name}">{label}</label>' if labelled else label)
    return f"""
    <div class="panel field">
      <h3>{heading}</h3>
      <p class="explain">{explain}</p>
      {control}
    </div>"""


def _scope_line(name: str) -> str:
    return f'<input type="text" id="f-{name}" name="{name}" required>'


def _scope_box(name: str, placeholder: str, required: bool) -> str:
    return (f'<textarea id="f-{name}" name="{name}" rows="{box_rows("")}" '
            f'placeholder="{placeholder}"'
            f'{" required" if required else ""}></textarea>')


def scope_screen() -> Screen:
    """Stop 6: the form that is not a model call.

    Design §4 is explicit that the `scope` stage "turns out not to be an LLM
    stage at all: it is a form" — so nothing here is drafted, guessed or
    completed for the learner, and the eight answers below are the whole of
    what the next stage is briefed with. Blank rather than prefilled: the
    form is only ever drawn at a stop with no scope on the ledger behind it,
    and a box holding a suggestion would be this page answering its own
    question.

    Required fields carry the browser's `required` and are checked again at
    the POST, for the same reason the publish button is: a rule a page draws
    is not a rule a server keeps.
    """
    radios = "".join(
        f'<label class="choice"><input type="radio" name="mode" '
        f'value="{value}" required><b>{name}</b><span>{sentence}</span></label>'
        for value, name, sentence in MODE_COPY)
    hours = f"""
    <div class="panel field">
      <h3>{SCOPE_HOURS_LEAD}</h3>
      <p class="explain">{SCOPE_HOURS_HINT}</p>
      <p class="hours"><span>between</span>
        <input type="number" name="hours_lo" min="1" max="80" required
               aria-label="Fewest hours a week">
        <span>and</span>
        <input type="number" name="hours_hi" min="1" max="80" required
               aria-label="Most hours a week">
        <span>hours</span></p>
      <p class="hint">{SCOPE_CADENCE_HINT}</p>
      <label class="claim"><span class="claimkey">When, roughly</span>
      <input type="text" name="cadence"></label>
    </div>"""
    return Screen(f"""
  <h1>{STOP_TITLES["scope"]}</h1>
  <p class="lede">{SCOPE_LEDE}</p>
  <form method="post" action="/onboarding/scope">
    {_scope_panel("title", _scope_line("title"))}
    {_scope_panel("subject", _scope_line("subject"))}
    {_scope_panel("mode", radios, labelled=False)}
    {hours}
    {_scope_panel("done_looks_like",
                  _scope_box("done_looks_like",
                             "I can read a paper in this field and say what "
                             "it claims.", True))}
    {_scope_panel("out_of_scope",
                  _scope_box("out_of_scope", "One line per thing to leave out",
                             False))}
    {_scope_panel("prior_exposure",
                  _scope_box("prior_exposure",
                             "What you have already read, built or half-"
                             "finished in this subject.", False))}
    <p class="ask">
      <button class="pill primary" type="submit">Draft my outline →</button>
      <span class="aside">This starts the first stage that calls a model. It
      is the cheap one, and it stops at its own spending ceiling; the
      expensive stage waits for your approval of an estimate.</span>
    </p>
  </form>
""")


def outline_screen(flow: onboarding.CourseFlow | None) -> Screen:
    """Stop 7: a machine's turn, or the sentence for why it stopped.

    Pending shows the stage name, the word, and elapsed time since the last
    ledger row — "and nothing else it would have to invent" (design §4). No
    percentage, no estimate of how long is left: this stage is one or two
    model calls whose length nobody here knows, and a progress bar over it
    would be an animation of a guess.

    Failed shows `WORDING[("outline", reason)]` and a button. The reason key
    itself never reaches the page (O2) and neither does the exception; both
    are in the ledger row for an operator. Retrying is offered without a
    caveat because a failed outline kept nothing — the draft's three files
    are deleted on every way out but success.

    (`waiting` is a state this wizard cannot write: the scope save appends
    the request row in the same transaction as the scope. A ledger that
    somehow held one reads as the pending screen without the refresh, which
    is the honest rendering of a stage nobody has asked for yet.)
    """
    status = flow.status if flow is not None else "waiting"
    if status == "failed" and flow is not None:
        worded = onboarding.WORDING.get(
            ("outline", flow.reason or ""),
            "That stage stopped and nothing partial was kept.")
        return Screen(f"""
  <h1>{STOP_TITLES["outline"]}</h1>
  <div class="gatebox attention">
    <p class="stateline">{_chip("failed")}</p>
    <h2>The outline stopped</h2>
    <p class="wording">{worded}</p>
    <form method="post" action="/onboarding/outline/retry">
      <p class="ask">
        <button class="pill primary" type="submit">Try again →</button>
        <span class="aside">Nothing partial was kept, so this starts the
        stage over rather than resuming it.</span>
      </p>
    </form>
  </div>
""")
    return Screen(f"""
  <h1>{STOP_TITLES["outline"]}</h1>
  <div class="gatebox">
    {_waitline("outline", status, flow)}
    <h2>Reading your profile, and writing a curriculum against it</h2>
    <p>Two things are being drafted: the phases and units of the course
    itself, and the shelf of resources it will send you to. Both are checked
    by the same compiler your own courses go through, and a draft that does
    not compile is refused rather than shown to you.</p>
    <p>There is no progress bar here and no estimate of how much longer it
    will be, because this system would have to invent both. Leave the tab
    open or close it — the ledger keeps your place either way.</p>
  </div>
""", refresh=status == "pending")


def draft_manifest(courses_dir: str | None, course_id: str) -> Manifest | None:
    """The drafted outline, compiled fresh off disk. None if it won't compile.

    Derived data is never stored: the structure on the gate screen is a
    compile of the tree the outline stage wrote, never a copy of it carried
    in a ledger row. This is the compiler, which reads files and spends
    nothing — the stage that drafted the tree runs in the other process.

    None is the whole vocabulary of failure here, and deliberately so. A
    home nobody configured, a draft deleted by hand between two screens, a
    sidecar that will not load, a compile that comes back with errors: the
    honest screen is the same one in all four cases, because in all four
    there is no outline to show and none of the findings are a learner's to
    act on. The exception set is the one the outline stage guards its own
    load with — the sidecar loader raises through whatever it cannot turn
    into a finding.
    """
    if not courses_dir:
        return None
    root = os.path.join(os.path.abspath(os.path.expanduser(courses_dir)),
                        course_id, DRAFT_DIR)
    sidecar_path = os.path.join(root, coursehome.SIDECAR_NAMES[0])
    if not os.path.isfile(sidecar_path):
        return None
    try:
        manifest, _ = compile_course(root, load_sidecar(sidecar_path))
    except (ValueError, TypeError, OSError, yaml.YAMLError):
        return None
    return manifest


@dataclass(frozen=True)
class Spend:
    """What one course cost, as the token ledger has it, split at the approval.

    Two figures because the learner made two different decisions about them:
    the drafting happened on the strength of "it is the cheap one" and the
    build happened on the strength of a number they approved. A receipt that
    printed one total would be answering neither.
    """

    draft: Decimal
    build: Decimal
    drafts: int = 0     # how many drafting runs that first figure paid for

    @property
    def total(self) -> Decimal:
        # The rounded parts, added: a total rounded from the raw sum can come
        # out a cent away from the two figures printed beside it, and a
        # receipt whose own arithmetic does not check is worse than no
        # receipt.
        return _cents(self.draft) + _cents(self.build)


def _cents(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(figure) -> Decimal | None:
    """A payload figure as a number, or None when it is not one.

    The two figures on the gate are strings written by the other process,
    and the screen compares them to decide whether to warn. A row from
    before those strings existed, or one an operator has edited by hand,
    is a screen that says less rather than a screen that raises.
    """
    try:
        return Decimal(str(figure))
    except (ArithmeticError, ValueError, TypeError):
        return None


def dollars(amount: Decimal) -> str:
    """Money, at the one precision this system states it in."""
    return f"${_cents(amount):.2f}"


def estimate_cost(estimate: str, *, mark: str = "cost") -> str:
    """The estimate as the gate draws it: "about $X" over the word for it.

    Two places on that screen state this figure — the lede, so the number is
    genuinely first, and the card, where the decision is taken — and they
    are the same drawing of the same payload string by construction rather
    than by two format strings agreeing. "About", because an estimate at
    display size with cents on it otherwise reads as a price; the word
    underneath says which of the card's two numbers this one is.

    An empty figure draws nothing at all. A payload with no estimate in it
    is a row from before the worker wrote one, and "about $" with nothing
    after it is the invented number this module refuses in every other
    place it prints one.
    """
    if not estimate:
        return ""
    return (f'<p class="{mark}">about ${html_mod.escape(estimate)}'
            f'<span class="costword">{GATE_ESTIMATE_WORD}</span></p>')


def course_spend(rows, ledger) -> Spend:
    """What `rows`' course spent, from ledger rows and the clock they share.

    The token ledger has no course column — a row names a stage, a stage is
    a role, and one role is bought by every course a tenant ever builds. So
    what a course cost is the metered rows falling inside that course's own
    window in the onboarding ledger: after its first row, before its
    `promoted` row if it has one, and split at its approval, which is the
    moment the learner's decision changed from "draft me something" to "buy
    this". Both ledgers timestamp server-side against the same clock.

    This is the one reader in the wizard that wants row times rather than
    the fold: the fold carries a flow's *latest* time, deliberately, and
    money is a question about an interval. Ordering still belongs to row
    ids everywhere it decides anything — nothing here decides, it totals.

    `rows` is this course's onboarding rows; `ledger` is the tenant's
    metered calls. A tenant with two courses in flight at once would double
    count the overlap, which the wizard's one-flow-at-a-time shape does not
    produce: the scope form is only reachable when nothing else is live.
    """
    times = [r.created_at for r in rows]
    if not times:
        return Spend(Decimal(0), Decimal(0))
    start = min(times)
    approved = max((r.created_at for r in rows
                    if r.kind == "outline_approved"), default=None)
    finished = max((r.created_at for r in rows if r.kind == "promoted"),
                   default=None)
    # Where each drafting attempt begins, so a cost can be attributed to
    # one. Asking for something is not paying for it: a stage that failed
    # before its first call, or one whose run was superseded, is a request
    # row with no metered row behind it, and counting requests printed
    # "across 2 drafts" over a figure one draft had paid for. Only the
    # windows that hold spend are counted.
    asked = sorted(r.created_at for r in rows
                   if r.kind == "outline_requested")
    spent_in = set()
    draft = build = Decimal(0)
    for row in ledger:
        when = row.created_at
        if when < start or (finished is not None and when > finished):
            continue
        if approved is None or when < approved:
            draft += Decimal(row.cost_usd)
            begun = [t for t in asked if t <= when]
            if begun:
                spent_in.add(max(begun))
        else:
            build += Decimal(row.cost_usd)
    return Spend(draft, build, len(spent_in))


# (plan key, what that key buys, what the build screen calls it) — the
# plan's keys are the build spec's own field names, so the list is assembled
# from the keys rather than from any prose the payload happens to carry.
PLAN_PARTS = (
    ("lesson_unit", "a Socratic lesson", "the lesson"),
    ("widget_unit", "a widget", "the widget"),
    ("exercise_unit", "a scaffolded exercise", "the exercise"),
)

# Why something in the plan is not bought, as a reason rather than a status.
# "Skipped" reads as a thing that went wrong or got dropped; what actually
# happened to the bank is that a bank section is appended to a question bank
# and a brand-new course has none for it to be appended to.
BANK_REASON = "not built for a new course"
UNPLANNED_REASON = "not part of this build"


@dataclass(frozen=True)
class PlanItem:
    """One thing the build will or will not buy.

    Two renderings, one derivation. The gate lists these and the build
    screen names the bought ones in a sentence, so the screen the money is
    approved on and the screen it is spent on cannot describe different
    builds — which they did: the build screen said the question bank was
    among what "you approved" while the gate, two clicks earlier, had said
    it was skipped.
    """

    label: str      # "Unit 2 · a widget" — the gate's line
    name: str       # "the widget" — what the build screen calls it
    detail: str     # the widget's concept, or why this one is not bought
    bought: bool


def plan_items(plan: dict, manifest: Manifest | None) -> tuple[PlanItem, ...]:
    """The build plan as a list. Plain text — escaped where it is rendered.

    The plan is read back out of the ledger rather than recomputed, because
    it is half of what the learner approves and the approval row echoes it:
    a list derived from a second, freshly computed plan could describe a
    build nobody agreed to. The manifest is asked one question only — what a
    unit or a phase is called on this page — and one the compile does not
    know is printed as the id it is, rather than guessed at.

    A null entry keeps its line rather than being dropped: "no widget" is
    part of what the estimate is an estimate of, and a plan that listed only
    what it does buy would read as a shorter course rather than a cheaper
    build.
    """
    units = {u.id: u for u in manifest.units} if manifest is not None else {}
    phases = {p.id: p for p in manifest.phases} if manifest is not None else {}
    phase = phases.get(plan.get("phase_id"))
    phase_words = (f"Phase {phase.num}" if phase is not None
                   else str(plan.get("phase_id") or "The first phase"))

    items = []
    for key, what, name in PLAN_PARTS:
        unit_id = plan.get(key)
        if not unit_id:
            items.append(PlanItem(what[0].upper() + what[1:], name,
                                  UNPLANNED_REASON, False))
            continue
        unit = units.get(unit_id)
        where = f"Unit {unit.num}" if unit is not None else str(unit_id)
        detail = ""
        if key == "widget_unit":
            # The concept, unless it is the unit's own gloss again. The
            # designer role has filled that field with the gloss verbatim,
            # and a parenthetical repeating the sentence three lines above
            # it is text shown that says nothing — the learner reads it
            # twice to find out it was the same thing.
            concept = (plan.get("widget_concept") or "").strip()
            gloss = (unit.gloss or "").strip() if unit is not None else ""
            detail = concept if concept and concept != gloss else ""
        items.append(PlanItem(f"{where} · {what}", name, detail, True))

    quiz = bool(plan.get("quiz"))
    items.append(PlanItem(f"{phase_words} checkpoint quiz",
                          "the checkpoint quiz",
                          "" if quiz else UNPLANNED_REASON, quiz))
    bank = bool(plan.get("bank"))
    items.append(PlanItem(
        "Question bank" + (" · a new section" if bank else ""),
        "the question bank", "" if bank else BANK_REASON, bank))
    return tuple(items)


def _and_list(names: list[str]) -> str:
    """["a", "b", "c"] as "a, b and c". House style: no serial comma."""
    if len(names) < 3:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def build_inventory(plan: dict) -> str:
    """What the build screen says is being written, from the approved plan.

    The manifest is not asked for and not needed: this sentence names the
    artifacts, never the units they belong to, so it is the one rendering of
    the plan that stays true with the draft tree already moved into place.
    """
    bought = [item.name for item in plan_items(plan, None) if item.bought]
    if not bought:
        return ("The materials you approved are being written and checked "
                "one at a time.")
    listed = _and_list(bought)
    return (f"{listed[0].upper()}{listed[1:]} you approved "
            f"{'is' if len(bought) == 1 else 'are'} being written and "
            "checked one at a time.")


def _phase_block(manifest: Manifest, phase: Phase) -> str:
    """One phase: its number, title and goal, then everything it will track.

    `entries` carries milestone ids beside unit ids and both get a line.
    This skipped the milestones once, on the argument that a side-quest is
    not a unit — true, and beside the point: the gate is the approval, the
    hub tracks milestones as checkable stones like everything else, and an
    approval that omits what will be tracked is not a faithful read-back.
    They arrive in the hub's own treatment (the flag, the green tint) with
    the word "milestone" printed, because colour is never the message.

    A stepped unit prints its steps under it for the same reason: the hub
    checks off the steps, not the unit, so the outline that shows only the
    unit shows fewer things than the course will ask for.
    """
    e = html_mod.escape
    units = {u.id: u for u in manifest.units}
    milestones = {m.id: m for m in manifest.milestones}
    items = []
    for entry in phase.entries:
        unit = units.get(entry)
        if unit is None:
            milestone = milestones.get(entry)
            if milestone is None:
                continue
            label = theme.strip_leading_pictograph(milestone.label)
            items.append(f'<li class="ms">{theme.FLAG_SVG}<div><b>{e(label)}'
                         f"</b><span>Milestone · {e(milestone.kind)}</span>"
                         "</div></li>")
            continue
        gloss = (f"<span>{e(unit.gloss)}</span>" if unit.gloss else "")
        steps = ("".join(f"<li>{e(s.label)}</li>" for s in unit.steps)
                 if unit.steps else "")
        walk = f'<ol class="substeps">{steps}</ol>' if steps else ""
        items.append(f"<li><b>Unit {unit.num} — {e(unit.title)}</b>"
                     f"{gloss}{walk}</li>")
    return f"""
    <div class="panel field">
      <h3>Phase {phase.num} — {e(phase.title)}</h3>
      <p class="explain">{e(phase.goal)}</p>
      <ol class="units">{"".join(items)}</ol>
    </div>"""


def count_line(manifest: Manifest) -> str:
    """What the course adds up to, in the arithmetic the hub will use.

    Derived on every draw and stored nowhere. A step is what the hub gives a
    stone to: a stepped unit's steps one by one, an unstepped unit itself,
    and every milestone — which is why the gate used to read back twelve
    units over a course the hub then greeted as sixteen steps. A term with
    nothing under it is left out rather than printed as a zero.
    """
    units = {u.id: u for u in manifest.units}
    seen_units = milestones = steps = 0
    for phase in manifest.phases:
        for entry in phase.entries:
            unit = units.get(entry)
            if unit is None:
                milestones += 1
                steps += 1
            else:
                seen_units += 1
                steps += len(unit.steps) or 1
    parts = [(len(manifest.phases), "phase"), (seen_units, "unit"),
             (milestones, "milestone"), (steps, "step")]
    return " · ".join(f"{n} {word}{'' if n == 1 else 's'}"
                      for n, word in parts if n)


def _ladder_block(manifest: Manifest) -> str:
    """The track ladder, when one was designed. Nothing at all when not.

    A heading over an empty list would tell a learner their course has a
    parallel track and then show them none of it. The eyebrow says what the
    panel is, because a ladder that only carried its own name would read as
    one more phase with strange units in it.
    """
    e = html_mod.escape
    if not manifest.tracks:
        return ""
    blocks = []
    for track in manifest.tracks:
        stages = "".join(
            f"<li><b>{e(s.label)}</b>"
            + (f"<span>{e(s.goal)}</span>" if s.goal else "")
            + "</li>" for s in track.stages)
        cadence = (f'<p class="explain">{e(track.cadence)}</p>'
                   if track.cadence else "")
        blocks.append(f"""
    <div class="panel field">
      <span class="claimkey">A parallel track, on its own clock</span>
      <h3>{e(track.name)}</h3>
      {cadence}
      <ol class="units">{stages}</ol>
    </div>""")
    return "".join(blocks)


def _shelf_block(manifest: Manifest) -> str:
    """The resource shelf: each entry's title, its link, and its essay.

    The essay is the manifest's own `why_this_one`, not the shelf markdown
    read a second time — the compiled field is what the course will show the
    learner later, and reviewing anything else would be reviewing a document
    the finished course does not use.
    """
    e = html_mod.escape
    if not manifest.resources:
        return ""
    items = []
    for res in manifest.resources:
        essay = (f"<p>{e(res.why_this_one)}</p>" if res.why_this_one else "")
        items.append(f'<li><b><a href="{e(res.url)}">{e(res.title)}</a></b>'
                     f"{essay}</li>")
    return f"""
    <div class="panel field">
      <h3>The resource shelf</h3>
      <p class="explain">What this course will send you to read, and why each
      one is on the shelf.</p>
      <ul class="shelf">{"".join(items)}</ul>
    </div>"""


def outline_gate_screen(flow: onboarding.CourseFlow,
                        manifest: Manifest | None,
                        spend: Spend | None = None) -> Screen:
    """Stop 8: the outline, read back, and then the spend decision.

    The two halves have two different sources and that is the design (§4).
    Everything above the line is compiled from the draft on disk, so what is
    reviewed is the course as the compiler sees it rather than a summary
    somebody stored. Everything below it — the plan, the two numbers — comes
    out of the `outline_ready` payload, because those are the artifact being
    approved, and the approval row echoes the same payload back: the numbers
    on this screen and the numbers in the ledger are the same bytes by
    construction (O3).

    Three figures, three sources, and none of them a price this module
    read. The estimate and the headroom are the worker's, carried here in
    the payload — the headroom being what was left of these roles' budgets
    when the outline was drafted, which is smaller on a second course than
    on a first and is why the sum of the budgets is not what gets printed.
    What the outline has already cost is the token ledger's, summed for
    this course — a database read on a request path, which is the same
    thing every other screen here does and not the thing L1 forbids.

    A headroom under the estimate is said out loud, above the button. The
    button still renders: it is the learner's account and their decision,
    and a build that stops partway keeps everything it finished. What this
    screen will not do is let them press it believing otherwise.

    The numbers sit above the button, which is the promise Stop 0 made in
    those words. And when the draft will not compile there is no button at
    all: a spend button over an outline this system cannot read would be a
    promise about a course nobody can see.

    Everything interpolated here came out of a model or out of a learner's
    own typing, so all of it is escaped. This is the first screen in the
    wizard where that is load-bearing rather than a habit.
    """
    e = html_mod.escape
    if manifest is None:
        return Screen(f"""
  <h1>{STOP_TITLES["outline_gate"]}</h1>
  <div class="gatebox attention">
    <p class="stateline">{_chip("failed")}</p>
    <h2>The drafted outline cannot be read back</h2>
    <p class="wording">The draft is missing, or it no longer compiles, so
    there is nothing here it would be honest to show you — and this system
    never asks you to approve spending on a course it cannot read. Nothing
    has been spent on materials.</p>
    <p>Drafting it again is safe: the outline stage keeps nothing on its way
    out, and the next draft is written from your scope exactly as the first
    one was.</p>
    <form method="post" action="/onboarding/outline/retry">
      <p class="ask">
        <button class="pill primary" type="submit">Draft it again →</button>
        <span class="aside">This is the cheap stage, and it stops at its own
        spending ceiling.</span>
      </p>
    </form>
  </div>
""")
    outline = flow.outline or {}
    estimate = str(outline.get("estimate_usd") or "")
    estimate_cost_card = estimate_cost(estimate)
    # The number, said under the lede as well as in the card (F19), in the
    # card's own words and off the card's own string. No estimate on the row
    # is no line here — the same way the card prints no headroom it was
    # never given — because a sentence pointing at a number nobody can see
    # is worse than the scroll it was meant to save.
    lede_cost = (estimate_cost(estimate, mark="cost upfront")
                 + f'<p class="costline">{GATE_COST_LEAD} '
                   f'<a href="#cost">the plan and the approve button are '
                   f"below the outline ↓</a></p>") if estimate else ""
    # The course's own name, on the ground and at display size: this is the
    # first time the learner sees what was drafted for them, and it was an
    # h3 in a card identical to the five phase cards under it (F23). The
    # description is the page's second lede rather than a card's small
    # print, and the count line sits under the title it counts.
    description = (f'<p class="lede">{e(manifest.course.description)}</p>'
                   if manifest.course.description else "")
    phases = "".join(_phase_block(manifest, p) for p in manifest.phases)
    # The headroom, and the warning that belongs with it. A payload written
    # before the worker carried the figure prints no figure rather than an
    # invented one, and the sentence under the pair describes the mechanism
    # either way. When there is a figure it is compared with the estimate,
    # because "the build will stop partway" is a thing to be told before the
    # button rather than to discover as a stopped stage.
    headroom = str(outline.get("headroom_usd") or "")
    # One size down (`second`): the estimate is the number this card is
    # about, and two figures at display size put the one that is not the
    # cost where the eye lands first.
    headroom_cost = (f'<p class="cost second">${e(headroom)}'
                     f'<span class="costword">{GATE_HEADROOM_WORD}</span></p>'
                     if headroom else "")
    left, wanted = _money(headroom), _money(outline.get("estimate_usd"))
    warning = ""
    if left is not None:
        if not left:
            warning = f"<p><b>{GATE_NONE}</b></p>"
        elif wanted is not None and left < wanted:
            warning = f"<p><b>{GATE_SHORT}</b></p>"
    drafting = (GATE_SPENT.format(
        spent=dollars(spend.draft),
        across=(GATE_SPENT_ACROSS.format(n=spend.drafts)
                if spend.drafts > 1 else ""))
        if spend is not None and spend.draft else "")
    spent = f'<p class="spent">{drafting}</p>' if drafting else ""
    plan = "".join(
        f'<li><span class="what">{e(item.label)}</span>'
        + (f'<span class="detail">{e(item.detail)}</span>'
           if item.detail else "")
        + "</li>"
        for item in plan_items(outline.get("plan") or {}, manifest))
    return Screen(f"""
  <h1>{STOP_TITLES["outline_gate"]}</h1>
  <p class="lede">{GATE_LEDE}</p>
  {lede_cost}
  <h2 class="coursetitle">{e(manifest.course.title)}</h2>
  {description}
  <p class="counts">{count_line(manifest)}</p>
{phases}{_ladder_block(manifest)}{_shelf_block(manifest)}
  <div class="gatebox attention" id="cost">
    <p class="stateline">{_chip("waiting")}
      <span class="note">building the first phase is the stage that costs
      money</span></p>
    <h2>What building phase 1 will cost</h2>
    <div class="costs">
      {estimate_cost_card}
      {headroom_cost}
    </div>
    <p>{GATE_HEADROOM}</p>
    {warning}
    {spent}
    <p class="buys">{GATE_PLAN_LEAD}</p>
    <ul class="plan">{plan}</ul>
    <form method="post" action="/onboarding/outline/approve">
      <p class="ask">
        <button class="pill primary" type="submit">Approve and build phase 1
        →</button>
        <span class="aside">Your approval is recorded with the numbers you
        were shown, and nothing spends a token without it.</span>
      </p>
    </form>
  </div>
  <div class="gatebox">
    <h2>Or send it back</h2>
    <p>{REJECT_HINT}</p>
    <form method="post" action="/onboarding/outline/reject">
      <label class="claim"><span class="claimkey">{REJECT_LEAD}</span>
      <textarea name="note" rows="{box_rows('')}" required
      placeholder="Eight weeks on the front end is too many — I have four."
      ></textarea></label>
      <p class="ask">
        <button class="pill" type="submit">Draft it again with this note
        →</button>
        <span class="aside">This re-runs the cheap drafting stage. No
        materials are built and no estimate is approved.</span>
      </p>
    </form>
  </div>
""")


def build_screen(flow: onboarding.CourseFlow | None) -> Screen:
    """Stop 9, in the outline stop's own words and shape.

    Pending makes the same two sentences the drafting screen does: what is
    happening, and that nothing here is forecasting how long it will take.

    Failed prints `WORDING[("build", reason)]` and a button, and the button
    says something the outline's cannot — a stopped build kept whatever it
    had already finished, so this one continues rather than starting over.
    Neither the reason key nor the exception reaches the page (O2); both are
    in the ledger row for an operator. What the screen also never says is
    that anything has to be approved again: the approval is a row upstream
    in the ledger and a stopped run did not spend it.

    `waiting` is a state this stop should never be seen in — the approval
    and the request for the build are one transaction — but a ledger that
    somehow held only the approval reads as this screen without the refresh,
    which is the honest rendering of a stage nobody has asked for yet.
    """
    status = flow.status if flow is not None else "waiting"
    if status == "failed" and flow is not None:
        worded = onboarding.WORDING.get(
            ("build", flow.reason or ""),
            "That stage stopped and what it had already finished was kept.")
        return Screen(f"""
  <h1>{STOP_TITLES["build"]}</h1>
  <div class="gatebox attention">
    <p class="stateline">{_chip("failed")}</p>
    <h2>The build stopped</h2>
    <p class="wording">{worded}</p>
    <form method="post" action="/onboarding/build/retry">
      <p class="ask">
        <button class="pill primary" type="submit">Carry on →</button>
        <span class="aside">{BUILD_RETRY_ASIDE}</span>
      </p>
    </form>
  </div>
""")
    # The inventory is the approved plan's own, not a fixed sentence: this
    # screen used to name the question bank among the things "you approved"
    # while the gate had said, two clicks earlier, that a new course does
    # not get one. Two screens, one derivation, and they cannot disagree.
    approval = (flow.approval or {}) if flow is not None else {}
    return Screen(f"""
  <h1>{STOP_TITLES["build"]}</h1>
  <div class="gatebox">
    {_waitline("build", status, flow)}
    <h2>Building your phase-1 materials</h2>
    <p>{build_inventory(approval.get("plan") or {})}
    Every one of them is refused rather than kept if it fails its checks, and
    what has already been finished survives a stage that stops partway.</p>
    <p>There is no progress bar here and no estimate of how much longer it
    will be, because this system would have to invent both. Leave the tab
    open or close it — the ledger keeps your place either way.</p>
  </div>
""", refresh=status == "pending")


def promote_screen(flow: onboarding.CourseFlow | None) -> Screen:
    """Stop 10's pending and failed faces: the last machine turn, no gate.

    There is no ask on the pending face because design §4 put no human turn
    between the build and the publication — the decision was taken at the
    gate, and this stop is the system keeping to it. So the copy says what
    is being done rather than what is being asked, and it names the one rule
    that could still stop it: a course that does not compile is not served,
    and this is where that is checked for the last time.

    The failed face says the one thing that is true of every way this stage
    can stop, and is the reason the sequence is ordered the way it is: the
    ledger row that publishes a course is appended after the compile at the
    course's own final location, so a stage that stopped published nothing.
    The retry is therefore offered without a caveat about money, because
    unlike the two stages before it this one never spends any.

    `WORDING[("promote", reason)]` and never the exception behind it (O2);
    the reason key itself never reaches the page either.
    """
    status = flow.status if flow is not None else "waiting"
    if status == "failed" and flow is not None:
        worded = onboarding.WORDING.get(
            ("promote", flow.reason or ""),
            "That stage stopped and your course was not published.")
        return Screen(f"""
  <h1>{STOP_TITLES["promote"]}</h1>
  <div class="gatebox attention">
    <p class="stateline">{_chip("failed")}</p>
    <h2>Publishing stopped</h2>
    <p class="wording">{worded}</p>
    <form method="post" action="/onboarding/promote/retry">
      <p class="ask">
        <button class="pill primary" type="submit">Try again →</button>
        <span class="aside">{PROMOTE_RETRY_ASIDE}</span>
      </p>
    </form>
  </div>
""")
    return Screen(f"""
  <h1>{STOP_TITLES["promote"]}</h1>
  <div class="gatebox">
    {_waitline("promote", status, flow)}
    <h2>Installing your course</h2>
    <p>The materials that were built are being moved into the course itself
    and registered, and the whole thing is compiled one last time. A course
    that does not compile is never served, so nothing is put in place until
    that check has passed.</p>
    <p>There is no progress bar here and no estimate of how much longer it
    will be, because this system would have to invent both. Leave the tab
    open or close it — the ledger keeps your place either way.</p>
  </div>
""", refresh=status == "pending")


def promoted_flow(state: onboarding.OnboardingState,
                  course: str | None) -> onboarding.CourseFlow | None:
    """Which finished course the landing card is for, if it is for one.

    The scope stop has two screens behind it now, and this is the whole of
    what chooses between them (design §4, Stop 10). With no hint in the URL
    the card is drawn for the last course to finish, because the request
    that arrives with no hint is the one the publishing screen's own refresh
    made and the learner is looking for the course they just built. A hint
    naming a finished course draws that one's card — the card is a page you
    can come back to, not a moment that passes.

    A hint naming anything else is the way to the scope form, and `?course=`
    is what the card's own "start another" link carries: no course answers
    to the empty string, because minting never produces one, so the sentinel
    cannot collide with a real id. That is deliberate rather than clever —
    the scope form is the screen for a course that does not exist yet, and
    asking for it by naming no course is what it is.
    """
    finished = [f for f in state.flows.values() if f.stage == "done"]
    if course is None:
        return finished[-1] if finished else None
    return next((f for f in finished if f.course_id == course), None)


def mcp_config(course_path: str, tenant_slug: str) -> str:
    """The tutor's config block, filled in for one course and one tenant.

    Plain text, escaped where it is rendered: both values came from outside
    this module — one from the environment, one from the command line.
    Written out here rather than assembled from a serializer, because what
    the learner copies is a *document*, and its line breaks and its
    indentation are as much of it as its keys are.

    One argument per line at two-space indents, rather than continuations
    aligned under the opening bracket. Column alignment put the course path
    at column 15 of a block that wraps at 400px, so the one value nobody can
    eyeball — an absolute path — broke across three lines and read as
    corrupt. Now the only thing that can wrap is the path itself.
    """
    return f"""{{
  "mcpServers": {{
    "curricle-tutor": {{
      "command": "python",
      "args": [
        "-m",
        "curricle",
        "mcp",
        "--course",
        "{course_path}",
        "--tenant",
        "{tenant_slug}"
      ]
    }}
  }}
}}"""


def receipt_line(spend: Spend, estimate: str | None) -> str:
    """The bill for one course, itemised. Markup, not text.

    Stop 0 promises that every dollar of model spend is approved on a screen
    that shows the number first. The receipt is what makes that promise
    checkable rather than merely made — including for the drafting stage,
    which spent real money on the strength of an aside calling it the cheap
    one. Two decimals belong here and only here: this is a bill, not an
    expectation, and it is the one figure on the walk that is a fact.

    Everything in it is house copy or a figure this module formatted, with
    one exception: the approved estimate is a string out of a ledger row, so
    it is escaped here rather than at the point of rendering.
    """
    if not spend.total:
        return RECEIPT_NONE
    line = RECEIPT.format(total=f"<b>{dollars(spend.total)}</b>",
                          draft=dollars(spend.draft),
                          build=dollars(spend.build))
    if estimate:
        line += RECEIPT_APPROVED.format(
            estimate=f"${html_mod.escape(str(estimate))}")
    return line + "."


def landing_screen(flow: onboarding.CourseFlow, courses_dir: str | None,
                   tenant_slug: str, spend: Spend) -> Screen:
    """Stop 10's last face: the course, and the two ways to work on it.

    The hub link comes first and carries no numbers with it. Done marks at
    zero and a next-up pointing at unit 1 are the hub's own derived answer,
    and printing them here would be this page keeping a second copy of a
    count it does not own — which is the one thing this codebase does not do
    with derived data. So the card says the course is ready and links to the
    page that can say the rest.

    The one number this page does print is the receipt, and it is not a copy
    of anything: it is the token ledger totalled for this course, beside the
    estimate the learner approved. Money is the thing the ledger is the only
    authority on, and the walk ends without it having ever been stated.

    Then the two onward paths (design §4). The browser one is a sentence,
    because the link above it is already the whole of it. The tutor one is a
    snippet, because a config block is not a thing to describe: it is filled
    in with this courses home and this tenant so that the learner copies an
    answer rather than a template, and the committed doc is named underneath
    for the day they need it again with the tab closed.

    Everything interpolated is escaped: the course id was minted from a
    title the learner typed, the path came from the environment, and the
    tenant slug came from the command line.
    """
    e = html_mod.escape
    course_id = flow.course_id
    course_path = (os.path.join(
        os.path.abspath(os.path.expanduser(courses_dir)), course_id)
        if courses_dir else course_id)
    approved = (flow.approval or {}).get("estimate_usd")
    return Screen(f"""
  <h1>{STOP_TITLES["done"]}</h1>
  <p class="lede">Everything you approved was built, checked, compiled and
  put in place. This is a course now, and where you are on it is kept for
  you from here on.</p>
  <p class="receipt">{receipt_line(spend, approved)}</p>
  <p class="ask">
    <a class="pill primary" href="/c/{e(course_id)}/index.html">Open your
    course →</a>
    <span class="aside">The hub is the front of it: the path, what comes
    next, and the materials as you reach them.</span>
  </p>
  <div class="gatebox">
    <h2>Work in the browser</h2>
    <p>Read the curriculum, walk the units, and mark what you finish. The
    lessons, the widget, the exercise and the checkpoint quiz are served
    from the same place, and every mark you make is written to your own
    database rather than to this tab.</p>
  </div>
  <div class="gatebox">
    <h2>Or connect the tutor to your assistant</h2>
    <p>{MCP_LEDE}</p>
    <p>{MCP_DEST}</p>
    <pre class="snippet">{e(mcp_config(course_path, tenant_slug))}</pre>
    <p class="hint">The same block, with the paths left blank, is committed
    at <code>{MCP_DOC}</code> — that page explains what the tutor can see
    and what it can write.</p>
  </div>
  <div class="nav">
    <a class="pill" href="/onboarding/?course=">Start another course →</a>
    <a class="pill" href="/profile">Your profile</a>
  </div>
""")


def stage_screen(stop: str, flow: onboarding.CourseFlow | None) -> Screen:
    """The placeholder for a stop with no screen of its own yet.

    Every stop has one now, so what is left for this is the fold that
    reaches a stop with no flow behind it at all — an outline gate with
    nothing to gate, which is a ledger nobody's code can write and a screen
    that should still say something true if one ever appears.

    Everything on it comes from the ledger. A stage that is `failed` prints
    the sentence `WORDING` keeps for its `(stage, reason)` pair and never the
    exception behind it (O2) — the exception is in the row's detail, where an
    operator reading the ledger will find it and a learner will not.
    """
    status = flow.status if flow is not None else "waiting"
    sentence = ""
    if status == "failed" and flow is not None:
        # `.get` rather than `[]`: the completeness test over the full
        # (worker stage, reason) cross product is what guarantees the entry
        # exists, and a screen is the wrong place to raise if it ever doesn't.
        # Unescaped because it is house copy, like every other sentence on
        # this page: escaping it would only turn its apostrophes into
        # entities, and the reason *key* — the one value here that came from
        # a machine — never reaches the page at all.
        worded = onboarding.WORDING.get(
            (stop, flow.reason or ""),
            "That stage stopped and nothing partial was kept.")
        sentence = f'<p class="wording">{worded}</p>'
    course = (f' for <b>{html_mod.escape(flow.course_id)}</b>'
              if flow is not None and flow.course_id else "")
    return Screen(f"""
  <h1>{STOP_TITLES[stop]}</h1>
  <div class="gatebox">
    {_waitline(stop, status, flow if status == "pending" else None)}
    <h2>This screen is still being built</h2>
    {sentence}
    <p>The setup is at the <b>{html_mod.escape(stop)}</b> stage{course}, and
    the ledger is keeping your place until the screen for it lands.</p>
  </div>
""", refresh=status == "pending")


# --------------------------------------------------------------------------
# Saving a screen
# --------------------------------------------------------------------------

_NUMBERED_KEY = re.compile(r"^(.+)-(\d+)$")


def next_key(spent: list[tuple[str, str]], field: str) -> str:
    """The next key for `field`: `{field}-NN`, and NN is never reused.

    The high-water mark is read off the *ledger*, not off the fold, and off
    every row in it whatever its kind. A retracted claim has left the fold
    and its number is still spent; an agent's `propose` on `{field}-NN` —
    which the MCP tools can write against any identity — has spent that
    number too, because the accept that follows creates a claim under it
    with no `assert` row anywhere behind it. Minting over either one would
    hand a live claim's identity to a new sentence and silently supersede
    it, and every consumer that remembers a key (the profile page, the MCP
    tools, an export somebody has already taken) would be wrong about which
    claim it meant. Keys are forever, so a number that has ever named a
    claim, or ever been offered as one, has been spent.
    """
    highest = 0
    for row_field, key in spent:
        match = _NUMBERED_KEY.match(key)
        if row_field == field and match and match.group(1) == field:
            highest = max(highest, int(match.group(2)))
    return f"{field}-{highest + 1:02d}"


def parse_form(body: bytes) -> dict[str, str]:
    """A urlencoded form body as {name: text}, blank values kept.

    Parsed here rather than through `request.form()` because Starlette's
    parser asks for `python-multipart` whatever the encoding, and these
    forms are plain urlencoded text with no file input anywhere in them —
    a dependency to read a body the standard library already reads is a
    dependency this layer does not need.

    Blank values are kept because a box that arrived empty is a deletion.
    A repeated name takes its last value, the way a server-side form parser
    conventionally does; the wizard's own markup emits each name once.
    """
    pairs = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {name: values[-1] for name, values in pairs.items()}


def submitted(form: dict[str, str], name: str) -> str | None:
    """One textarea's text, or None when the form did not carry that box.

    None and "" are different answers and the difference is a claim's life:
    a box that arrived empty is a deletion, a box that did not arrive at all
    is a screen that never asked. Newlines are normalized because a browser
    posts CRLF and the ledger should not record the difference.
    """
    raw = form.get(name)
    if raw is None:
        return None
    return raw.replace("\r\n", "\n").strip()


def claim_lines(form: dict[str, str], field: str) -> list[str]:
    """The `new__{field}` box, one claim per non-empty line."""
    raw = submitted(form, f"new__{field}") or ""
    return [line.strip() for line in raw.split("\n") if line.strip()]


class InvalidScope(ValueError):
    """A scope form this wizard refuses rather than completes for you."""


def scope_payload(form: dict[str, str]) -> dict:
    """The `scope_saved` payload, or a refusal naming the box that is empty.

    Every refusal here names a field in the words the form asks it in, because
    "invalid" is not an instruction. Nothing is defaulted: an unanswered
    "what done looks like" is the single most load-bearing line in the whole
    prompt, and a stage briefed with a system-invented answer to it would be
    building somebody else's course.

    The optional three come back as `""` and `[]` rather than as absences —
    the payload shape is a wire contract with the gate screen and the worker,
    and a key that is sometimes missing is a key every consumer has to guard.
    """
    def required(name: str) -> str:
        text = submitted(form, name) or ""
        if not text:
            raise InvalidScope(f"{SCOPE_LABELS[name][0]} is required")
        return text

    def hours(name: str, label: str) -> int:
        text = submitted(form, name) or ""
        try:
            return int(text)
        except ValueError:
            raise InvalidScope(f"{label} must be a whole number of hours")

    # Asked in the order the form asks them, so a refusal names the first
    # box a learner would have to scroll back to rather than an arbitrary one.
    title, subject = required("title"), required("subject")
    mode = submitted(form, "mode") or ""
    if mode not in {value for value, _, _ in MODE_COPY}:
        raise InvalidScope(f"{SCOPE_LABELS['mode'][0]}: choose one of "
                           + ", ".join(name for _, name, _ in MODE_COPY))
    lo = hours("hours_lo", "The low end of your hours a week")
    hi = hours("hours_hi", "The high end of your hours a week")
    if lo < 1:
        raise InvalidScope("A course that asks for under an hour a week is "
                           "not a course — give it at least one")
    if hi < lo:
        raise InvalidScope("The high end of your hours a week cannot be "
                           "below the low end")
    done_looks_like = required("done_looks_like")
    out_of_scope = submitted(form, "out_of_scope") or ""
    return {
        "title": title,
        "subject": subject,
        "mode": mode,
        "hours_per_week": [lo, hi],
        "cadence": submitted(form, "cadence") or "",
        "done_looks_like": done_looks_like,
        "out_of_scope": [line.strip() for line in out_of_scope.split("\n")
                         if line.strip()],
        "prior_exposure": submitted(form, "prior_exposure") or "",
    }


# --------------------------------------------------------------------------
# Mounting
# --------------------------------------------------------------------------

def mount(app: FastAPI, *, engine, scope: db.TenantScope, tenant_slug: str,
          courses: dict, courses_dir: str | None,
          profile_skill_out: str | None = None) -> None:
    """Register the wizard's routes on `app`, closure style.

    `courses` is the live course map `create_app` keeps and mutates; the
    wizard reads it and never writes it, so registration stays one process's
    one job. `courses_dir` is the managed home, and the two together are what
    Stop 6 mints a course id against: a name is free only if no served course
    and no directory in the home already answers to it. Both are held here
    rather than fetched, because the app has exactly one of each and passing
    them is cheaper than a second source of truth for either.

    `profile_skill_out` is the projection's install path, or None for off —
    the interim home of a setting that wants to be tenant config the day
    tenant config exists (design §11).
    """

    def render_projection() -> None:
        """Re-render the installed SKILL.md, if one is installed anywhere.

        Called after a profile write commits, never inside the transaction:
        a file written beside an uncommitted row would be a projection of a
        ledger that might yet roll back. The fold is re-read rather than
        reused for the same reason — what the writing transaction held is
        the profile as it was *before* its own rows.

        Off by default, and the read only happens when it is on.
        """
        if profile_skill_out is None:
            return
        with engine.begin() as conn:
            state = profile.load_profile(conn, scope)
        profilerender.write_skill_md(state, profile_skill_out)

    def read_spend(course_id: str) -> Spend:
        """What this tenant's ledgers say `course_id` has cost so far.

        One transaction over both ledgers, because a receipt totalled from
        two moments could name a call that the window drawn beside it does
        not contain. Tenant-scoped like every other read here: the scope is
        the app's own, and there is no other way to these rows.
        """
        with engine.begin() as conn:
            rows = [r for r in conn.execute(scope.onboarding_select())
                    if r.course == course_id]
            ledger = list(conn.execute(scope.ledger_costs()))
        return course_spend(rows, ledger)

    @app.get(STATUS_PATH)
    def onboarding_status() -> JSONResponse:
        """Where the fold is, in three fields, for the waiting screens.

        The whole of what a waiting page needs to know whether anything has
        changed: which stop, which of the two waits, and how long it has
        been. It reads the same fold the page was drawn from and nothing
        else — L1 holds here exactly as it does on every other route in this
        module, because a status route that could reach a model would be a
        model on a request path with a poll behind it.

        Scoped to this app's tenant like every other read: there is one
        tenant per process and no argument on this route to name another.
        """
        with engine.begin() as conn:
            state = onboarding.load_state(conn, scope)
        flow = state.active()
        return JSONResponse({
            "stop": state.current_stop(),
            "status": flow.status if flow is not None else "waiting",
            "elapsed": elapsed_words(flow.updated_at
                                     if flow is not None else None),
        })

    @app.get("/onboarding/")
    def onboarding_page(screen: str | None = None,
                        course: str | None = None) -> Response:
        # One transaction for the three questions a screen can ask: where the
        # fold says you are, what your profile holds, and whether the second
        # process is running. Three round trips would let the page describe a
        # moment that never existed.
        with engine.begin() as conn:
            state = onboarding.load_state(conn, scope)
            profile_state = profile.load_profile(conn, scope)
            worker_running = db.worker_alive(conn)

        stop = state.current_stop()
        if stop != "profile":
            # O1: past the profile stop the fold alone decides, and a
            # `?screen=` in the address bar is not an opinion the wizard has
            # to have about it. One screen per stop, and the stops with no
            # screen of their own yet keep the placeholder.
            flow = state.active()
            if stop == "scope":
                # Two screens behind one stop: a course that finished has a
                # card to land on, and the same stop is where a second
                # course is started from (design §4, Stop 10). The card is
                # drawn under the fold's terminal stage rather than under
                # "scope", because the waypath over a finished setup must not
                # ring a stone as though a step were still in progress.
                landed = promoted_flow(state, course)
                if landed is not None:
                    return HTMLResponse(_page(
                        "done",
                        landing_screen(landed, courses_dir, tenant_slug,
                                       read_spend(landed.course_id)),
                        tenant_slug))
                rendered = scope_screen()
            elif stop == "outline":
                rendered = outline_screen(flow)
            elif stop == "outline_gate" and flow is not None:
                # The compile happens out here rather than inside the screen
                # so the screen stays a function of what it was handed, and
                # outside the transaction above because reading a directory
                # is not a thing to hold a database transaction across.
                rendered = outline_gate_screen(
                    flow, draft_manifest(courses_dir, flow.course_id),
                    read_spend(flow.course_id))
            elif stop == "build":
                rendered = build_screen(flow)
            elif stop == "promote":
                rendered = promote_screen(flow)
            else:
                rendered = stage_screen(stop, flow)
            return HTMLResponse(_page(stop, rendered, tenant_slug))
        if screen is None:
            # No `?screen=` at all is a learner arriving or coming back, and
            # the fold says where they left off rather than this page always
            # saying "welcome" — which is the promise the footer makes.
            screen = default_screen(profile_state)
        if screen not in SCREEN_ORDER:
            # A screen the vocabulary does not know is navigation past the
            # frontier: back to the fold's screen, and to a URL that agrees
            # with what is on it.
            return RedirectResponse("/onboarding/")
        if screen == "welcome":
            rendered = welcome_screen(worker_running=worker_running)
        elif screen == "review":
            rendered = review_screen(profile_state)
        else:
            rendered = form_screen(screen, profile_state)
        # The sub-screen travels into the shell as well as into the body: it
        # is what the words line under the stones and the page's own title
        # are drawn from, and both of those live in the masthead.
        return HTMLResponse(_page(stop, rendered, tenant_slug, screen))

    # Registered before `/onboarding/profile/{number}`: routes match in
    # registration order, and the other way round "publish" would arrive as a
    # screen number and leave as a 404.
    @app.post("/onboarding/profile/publish")
    def publish_profile() -> Response:
        """Stop 5's confirm: one ledger row saying publishing happened.

        The row carries no claim and never will (design §5) — the profile
        ledger is the record of what you said, and this one records only
        that you were ready. Two checks, both against the fold and both
        inside the writing transaction, so neither can be answered by a page
        that was drawn a while ago:

        - O1: a tenant past the profile stop is not publishing a profile;
          they published one already, and the second row would be a no-op
          written over a course build in flight.
        - The gate: `onboarding.profile_gate_missing` is the single rule,
          asked here as well as displayed on the way here, because a form a
          learner reached with a stale tab or with curl is a form that never
          saw the button being absent.
        """
        with engine.begin() as conn:
            if onboarding.load_state(conn, scope).current_stop() != "profile":
                raise HTTPException(409, "your profile is already published; "
                                         "edit your claims on /profile")
            missing = onboarding.profile_gate_missing(
                profile.load_profile(conn, scope))
            if missing:
                names = ", ".join(FIELD_LABELS[f] for f in missing)
                raise HTTPException(
                    422, f"these fields still need a claim: {names}")
            onboarding.append_event(conn, scope, "profile_published", "", {})
        render_projection()
        # 303 to the one URL: what the learner sees next is whatever the fold
        # says now, which is the scope stop.
        return RedirectResponse("/onboarding/", status_code=303)

    @app.post("/onboarding/profile/{number}")
    async def save_profile_screen(number: str, request: Request) -> Response:
        """Save one form screen: an `assert` per claim, in the learner's voice.

        One transaction for the whole screen, and the fold is re-read inside
        it — the boxes the browser posted describe claims as they were when
        the page was drawn, and the events written here are computed against
        the ledger as it is now.

        Nothing on this path judges a claim. The tier is `attested` because
        of where the words came from, not because of how much the system
        believes them, and `profile.validate_profile_event` remains the only
        thing that can refuse one: a refusal arrives as a 422 rather than as
        a second opinion written here.

        Accepted limitation: two tabs posting the same screen at the same
        instant both read the ledger under READ COMMITTED, so both can mint
        the same number and the second write supersedes the first. This is a
        single learner filling in their own profile on a local app, where the
        race is a person racing themselves; the fix (a serializable read, or
        a unique index on the minted identity) belongs with multi-tenancy,
        where two writers are two people.
        """
        if number not in _FORM_FIELDS:
            raise HTTPException(404)
        # Refuse rather than guess, twice over: a body in another encoding,
        # and a body that is not text at all, both parse to no boxes — and
        # no boxes is indistinguishable from a screen the learner cleared,
        # which is a retract of everything on it.
        if not request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"):
            raise HTTPException(415, "the profile forms post urlencoded")
        try:
            form = parse_form(await request.body())
        except UnicodeDecodeError:
            raise HTTPException(415, "the profile forms post urlencoded")
        with engine.begin() as conn:
            if onboarding.load_state(conn, scope).current_stop() != "profile":
                # O1 for a write: the fold has closed this screen — a tenant
                # who has published a profile never re-gates (design §4, Stop
                # 10), so a form posted from a stale tab is refused rather
                # than replayed into a ledger that has moved on.
                raise HTTPException(409, "the profile stop is behind you; "
                                         "edit your claims on /profile")
            state = profile.load_profile(conn, scope)
            # Every key this tenant's ledger has ever carried, whatever the
            # row said — the minting rule's high-water mark. The fold cannot
            # answer this: a retracted claim has left it and its number must
            # still never come back, and a proposed one may not have arrived
            # in it yet.
            spent = [(r.field, r.key)
                     for r in conn.execute(scope.profile_select())]

            def save(field: str, key: str, claim: profile.Claim | None) -> None:
                text = submitted(form, f"claim__{field}__{key}")
                current = claim.text.strip() if claim is not None else ""
                if text is None or text == current:
                    return                      # never asked, or untouched
                if not text:
                    if claim is not None:
                        profile.append_profile_event(conn, scope, "retract",
                                                     field, key)
                    return
                profile.append_profile_event(
                    conn, scope, "assert", field, key,
                    {"text": text, "tier": "attested"})

            try:
                if number == "1":
                    save("meta", META_KEY, state.claim("meta", META_KEY))
                for field in _FORM_FIELDS[number]:
                    for claim in state.field_claims(field):
                        save(field, claim.key, claim)
                    for line in claim_lines(form, field):
                        key = next_key(spent, field)
                        # Minted inside the loop and remembered here, so two
                        # new lines in one box get two consecutive numbers.
                        spent.append((field, key))
                        profile.append_profile_event(
                            conn, scope, "assert", field, key,
                            {"text": line, "tier": "attested"})
            except profile.InvalidProfileEvent as exc:
                raise HTTPException(422, str(exc))

        render_projection()
        at = SCREEN_ORDER.index(number)
        # 303: the save is done, and what follows is a page to look at — a
        # reload of it must never post the form a second time.
        return RedirectResponse(f"/onboarding/?screen={SCREEN_ORDER[at + 1]}",
                                status_code=303)

    @app.post("/onboarding/scope")
    async def save_scope(request: Request) -> Response:
        """Stop 6: the scope, the course's name, and the request for Stop 7.

        Three writes in one transaction, because there is no human turn
        between Stops 6 and 7 (design §4): the scope, the request row that
        says a stage was asked for, and the queued run itself. Either a
        learner has a course being drafted or they have nothing at all —
        a scope on the ledger with nothing queued behind it would be a
        wizard sitting on "Working" forever with no worker to answer it.

        Enqueuing here is this surface's one and only queue privilege: the
        web app writes request rows and reads outcome rows (design §6), and
        `scope.runs_insert` is the whole of that. What runs the stage is the
        second process, and this module has no idea how.

        The id is minted inside the transaction, against the courses this
        app serves and the directories in the home. It is not reserved
        anywhere — the `scope_saved` row is the reservation, and the
        directory that will carry the same name is created by the stage that
        first writes into it.
        """
        # The same rule the profile forms keep, for the same reason: a body
        # this parser cannot read arrives as no boxes at all, and no boxes is
        # indistinguishable from a form somebody left blank.
        if not request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"):
            raise HTTPException(415, "the scope form posts urlencoded")
        try:
            form = parse_form(await request.body())
        except UnicodeDecodeError:
            raise HTTPException(415, "the scope form posts urlencoded")

        with engine.begin() as conn:
            if onboarding.load_state(conn, scope).current_stop() != "scope":
                # O1 for a write: the fold is not at this stop, so this form
                # is a stale tab. Saving it would start a second course under
                # a first one, or re-scope a course already being built.
                raise HTTPException(409, "this setup is not at the scope "
                                         "stop — reload /onboarding/")
            try:
                payload = scope_payload(form)
            except InvalidScope as exc:
                # Nothing has been written yet, and the transaction rolls
                # back regardless: a refused form leaves no half-scoped
                # course and no run nobody asked for.
                raise HTTPException(422, str(exc))
            course_id = coursehome.mint_course_id(
                payload["title"], coursehome.taken_ids(courses, courses_dir))
            onboarding.append_event(conn, scope, "scope_saved", course_id,
                                    payload)
            onboarding.append_event(conn, scope, "outline_requested",
                                    course_id, {})
            conn.execute(scope.runs_insert(course_id, "outline", {}))
        # 303 to the one URL: what the fold says now is the outline stop.
        return RedirectResponse("/onboarding/", status_code=303)

    @app.post("/onboarding/outline/retry")
    def retry_outline() -> Response:
        """Ask for the outline again. The retry button *is* the scheduler.

        Nothing reschedules a failed stage on its own (design §6) — an
        automatic retry re-spends a learner's money without being asked — so
        a stopped outline waits here until a person presses the button. Safe
        without qualification: a failed outline kept nothing.

        A note from a rejected outline rides along in the `outline_requested`
        payload, because a retry after a rejection is still that note being
        answered and the ledger should say so. The queued run itself carries
        nothing: the note lives in the fold, which is where the stage reads
        it from, and copying it into two places would be two places to
        disagree.

        Two folds reach this button, and the second one is the gate with a
        draft it cannot read. That state has no outline to review and no
        approval to give, so a redraft is the only move left — but it is
        offered *only* while the draft really is unreadable, checked here as
        well as on the screen. Otherwise this would be a second way out of a
        healthy gate: one that discards a good outline and briefs its
        replacement with nothing, which is exactly what rejecting with a note
        exists to prevent.
        """
        with engine.begin() as conn:
            flow = onboarding.load_state(conn, scope).active()
            stopped = (flow is not None and flow.stage == "outline"
                       and flow.status == "failed")
            unreadable = (flow is not None and flow.stage == "outline_gate"
                          and draft_manifest(courses_dir,
                                             flow.course_id) is None)
            if flow is None or not (stopped or unreadable):
                raise HTTPException(409, "there is no outline waiting to be "
                                         "drafted again — reload /onboarding/")
            onboarding.append_event(conn, scope, "outline_requested",
                                    flow.course_id,
                                    {"note": flow.note} if flow.note else {})
            conn.execute(scope.runs_insert(flow.course_id, "outline", {}))
        return RedirectResponse("/onboarding/", status_code=303)

    @app.post("/onboarding/outline/approve")
    def approve_outline() -> Response:
        """Stop 8's decision: the row that lets money be spent, and the run.

        O3 lives here. The approval carries the numbers the learner was
        shown, and it carries them by echoing `outline_ready`'s own payload
        rather than by reading them off the form — a form could post any
        number at all, and the point of the row is that the screen and the
        ledger agree. The plan travels with it for the same reason: what
        gets built is the plan that was approved, and the build reads it
        from this row rather than recomputing one of its own.

        Both numbers, now that the screen shows both: the estimate is what
        the learner expected to pay and the headroom is what was left to
        spend before the build starts refusing, and an approval echoing only
        half of what was on the screen is only half a record of the
        decision. The headroom is copied only when the payload has one — a
        draft made before the worker carried it is a row this screen still
        renders, and a `None` written into the ledger to fill a gap would be
        a number nobody was shown. It is a reading taken when the outline
        was drafted, so the row records what the learner was told, which is
        what O3 asks of it; the runner still re-reads the ledger before
        every call it makes.

        Three writes in one transaction, because there is no human turn
        between Stops 8 and 9: an approval with no build queued behind it is
        a learner who has spent their decision and got nothing for it.

        Two refusals, both against state rather than against the form. O1:
        the fold has to be at this stop, or the button came from a stale tab.
        And the draft has to still compile: the screen draws no approve
        button over an outline it could not render, and a button that is
        absent from a page is not a rule.
        """
        with engine.begin() as conn:
            flow = onboarding.load_state(conn, scope).active()
            if flow is None or flow.stage != "outline_gate":
                raise HTTPException(409, "there is no outline waiting for "
                                         "your approval — reload /onboarding/")
            if draft_manifest(courses_dir, flow.course_id) is None:
                raise HTTPException(409, "the drafted outline no longer "
                                         "compiles, so there is nothing to "
                                         "approve — draft it again")
            outline = flow.outline or {}
            approval = {"estimate_usd": outline.get("estimate_usd"),
                        "plan": outline.get("plan")}
            if outline.get("headroom_usd") is not None:
                approval["headroom_usd"] = outline["headroom_usd"]
            onboarding.append_event(
                conn, scope, "outline_approved", flow.course_id, approval)
            onboarding.append_event(conn, scope, "build_requested",
                                    flow.course_id, {})
            conn.execute(scope.runs_insert(flow.course_id, "build", {}))
        return RedirectResponse("/onboarding/", status_code=303)

    @app.post("/onboarding/build/retry")
    def retry_build() -> Response:
        """Ask for the build again. The retry button is still the scheduler.

        No new approval is required, and this is the one place in the wizard
        where that is worth saying out loud: the `outline_approved` row is
        upstream in the ledger and a run that stopped did not consume it, so
        O3 is satisfied by the row that is already there. What the retry does
        buy is only what the stopped run had not finished — `build_phase`
        checkpoints into the draft after every artifact and a resumed run
        merges into the same draft rather than paying for it twice, which is
        exactly what the button's own sentence promises.

        One refusal, against the fold rather than the form: there has to be
        a stopped build here, or the button came from a stale tab. Two rows'
        worth of work in one transaction, like every other request in this
        module — the ledger row saying a build was asked for, and the run
        row that makes it happen.
        """
        with engine.begin() as conn:
            flow = onboarding.load_state(conn, scope).active()
            if (flow is None or flow.stage != "build"
                    or flow.status != "failed"):
                raise HTTPException(409, "there is no stopped build to carry "
                                         "on with — reload /onboarding/")
            onboarding.append_event(conn, scope, "build_requested",
                                    flow.course_id, {})
            conn.execute(scope.runs_insert(flow.course_id, "build", {}))
        return RedirectResponse("/onboarding/", status_code=303)

    @app.post("/onboarding/promote/retry")
    def retry_promote() -> Response:
        """Ask for the publication again. The cheapest retry in the wizard.

        Same two rows as the other two retries — the request, and the run —
        and for the same reason: without the request row there is nothing to
        move the flow off `failed`, and the wizard would show a live run as
        a dead one for as long as it took (O1). The stage itself is the one
        that spends nothing, so this button asks for no approval and there
        is no half-bought work for it to be careful about; what it is
        careful about instead is the tree, and that care is the handler's —
        every step of publishing is skipped by the state it already finds.

        One refusal, against the fold rather than the form: there has to be
        a stopped publication here, or the button came from a stale tab.
        """
        with engine.begin() as conn:
            flow = onboarding.load_state(conn, scope).active()
            if (flow is None or flow.stage != "promote"
                    or flow.status != "failed"):
                raise HTTPException(409, "there is no stopped publication to "
                                         "try again — reload /onboarding/")
            onboarding.append_event(conn, scope, "promote_requested",
                                    flow.course_id, {})
            conn.execute(scope.runs_insert(flow.course_id, "promote", {}))
        return RedirectResponse("/onboarding/", status_code=303)

    @app.post("/onboarding/outline/reject")
    async def reject_outline(request: Request) -> Response:
        """Send the outline back with a note, which re-runs Stop 7.

        The note is the whole content of a rejection and an empty one is
        refused: a redraft briefed with nothing is the same stage run again
        at the same cost, and the learner would be paying for the system's
        silence. Two rows, because they say two different things — that this
        outline was rejected, and that another one was asked for — and the
        note is on both, so neither row has to be read through the other.

        The queued run carries the note as well. That is one more copy than
        the retry button writes, and it is deliberate: this run exists *to*
        answer this note, and a stage that reads its own row's payload is
        briefed by the thing that queued it rather than by whatever the fold
        looks like by the time a worker gets there.
        """
        if not request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"):
            raise HTTPException(415, "the reject form posts urlencoded")
        try:
            form = parse_form(await request.body())
        except UnicodeDecodeError:
            raise HTTPException(415, "the reject form posts urlencoded")
        note = submitted(form, "note") or ""
        with engine.begin() as conn:
            flow = onboarding.load_state(conn, scope).active()
            if flow is None or flow.stage != "outline_gate":
                raise HTTPException(409, "there is no outline waiting on your "
                                         "review — reload /onboarding/")
            if not note:
                raise HTTPException(422, REJECT_EMPTY)
            onboarding.append_event(conn, scope, "outline_rejected",
                                    flow.course_id, {"note": note})
            onboarding.append_event(conn, scope, "outline_requested",
                                    flow.course_id, {"note": note})
            conn.execute(scope.runs_insert(flow.course_id, "outline",
                                           {"note": note}))
        return RedirectResponse("/onboarding/", status_code=303)
