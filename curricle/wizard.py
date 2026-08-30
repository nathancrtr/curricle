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

Self-refresh is a `<meta http-equiv="refresh">` tag on pending screens and
no JavaScript at all. The polling stops by construction: a screen that is
not pending does not carry the tag, so the browser stops asking the moment
the wait is over.
"""

from __future__ import annotations

import html as html_mod
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import db, onboarding, profile, theme

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
    "Every dollar of model spend is approved by you on a screen that shows "
    "the number first.",
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
SCREEN_INTROS = {
    "1": "Where you are coming from — the work and study a course can build "
         "on instead of repeating. Short claims, in your own words.",
    "2": "How an explanation has to arrive for it to land, and how much of "
         "your week a course is allowed to ask for.",
    "3": "These three are the difference between a course that re-explains "
         "your degree and one that builds only what you lack.",
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
        "reach for it. This is the only field that holds a single line.",
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
        "How understanding actually arrives for you. One habit per claim, "
        "stated as an instruction a teacher could follow.",
        ("Learns by implementing — pair every abstract idea with something "
         "runnable, and treat “show me the code” as always fair.",
         "Reaches understanding through failure modes: what breaks, and what "
         "the system does when it breaks, lands harder than the happy path.")),
    "domain_bias": (
        "Where examples and exercises should be drawn from when the choice "
        "is free. A preference, never a requirement.",
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
        "The order an explanation has to arrive in for you. This is the "
        "procedure a tutor follows before it says anything new.",
        ("When explaining a new concept: open with the failure it exists to "
         "prevent, show it concretely, then give the formal statement and "
         "name it properly.",
         "Give me the shape of the whole thing before any detail; a lesson "
         "built strictly bottom-up loses me by the third step.")),
    "skip": (
        "What never needs explaining to you again. Every line here is time a "
        "course spends on something you do not already know.",
        ("Don't explain what an index is, what a transaction is, how HTTP "
         "works, or any language-level feature of Go or Python.",
         "Don't explain big-O, common data structures, or basic algorithm "
         "analysis — the degree covered these and they held.")),
    "scaffold": (
        "What to rebuild from the ground up, assuming nothing stuck. The "
        "opposite list, and the one people under-report.",
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

# Five seconds is short enough that a finished stage is seen almost at once
# and long enough that a browser left open overnight is not a load.
META_REFRESH = '<meta http-equiv="refresh" content="5">'

# What each stop is called on screen, and in the step strip.
STOP_TITLES = {
    "profile": "Your learner profile",
    "scope": "What you want to learn",
    "outline": "Drafting your course outline",
    "outline_gate": "Your outline, and what the build will cost",
    "build": "Building the first phase",
    "promote": "Publishing your course",
}
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
  h1 { font-weight:700; font-size:clamp(26px,5vw,34px); letter-spacing:-.01em;
       margin:14px 0 0; }
  .lede { margin:12px 0 0; color:var(--muted); font-size:16px; max-width:60ch; }
  .steps { display:flex; flex-wrap:wrap; gap:8px; margin:26px 0 0; padding:0;
           list-style:none; }
  .steps li { display:inline-flex; align-items:center; gap:6px; font-size:12.5px;
              font-weight:600; letter-spacing:.02em; border-radius:999px;
              padding:4px 12px; background:var(--chip); color:var(--muted); }
  .steps li.done { background:var(--good-soft); color:var(--good-text); }
  .steps li.now { background:var(--accent-soft); color:var(--accent-text);
                  box-shadow:inset 0 0 0 1.5px var(--accent); }
  .steps svg { display:block; }
  .stepline { font-size:13.5px; font-weight:600; color:var(--muted);
              margin:10px 0 0; }
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
  .never { margin:22px 0 0; padding:0 0 0 22px; }
  .never li { font-size:14.5px; line-height:1.6; color:var(--muted);
              margin:9px 0; max-width:62ch; }
  .ask { display:flex; flex-wrap:wrap; align-items:center; gap:14px;
         margin:28px 0 0; }
  .ask .aside { font-size:13.5px; color:var(--muted); }
  .screenline { font-size:13.5px; font-weight:600; color:var(--muted);
                margin:22px 0 0; }
  .field { padding:20px 24px; margin:22px 0; }
  .field h3 { font-size:17px; font-weight:700; margin:0 0 5px; }
  .field .explain { font-size:14.5px; line-height:1.6; color:var(--muted);
                    margin:0 0 13px; max-width:62ch; }
  .eg { border-left:2px solid var(--line); padding:1px 0 1px 14px;
        margin:0 0 16px; }
  .eg b { display:block; font-size:11.5px; font-weight:700; letter-spacing:.06em;
          text-transform:uppercase; color:var(--muted); margin:0 0 5px; }
  .eg p { font-size:13.5px; line-height:1.55; color:var(--muted);
          margin:0 0 7px; max-width:62ch; }
  .eg p:last-child { margin-bottom:0; }
  label.claim { display:block; margin:0 0 13px; }
  .claimkey { display:block; font-size:11.5px; font-weight:700;
              letter-spacing:.06em; text-transform:uppercase; color:var(--muted);
              margin:0 0 5px; }
  textarea { width:100%; min-height:64px; resize:vertical;
             font:14px/1.55 """ + theme.FONT_BODY + """;
             color:var(--ink); background:var(--panel);
             border:1.5px solid var(--line); border-radius:12px;
             padding:10px 13px; }
  /* Placeholder copy is read to be acted on, so it is body text and takes
     --muted, never the decorative --faint. */
  textarea::placeholder { color:var(--muted); }
  textarea:focus { outline:none; border-color:var(--accent); }
  .hint { font-size:13px; line-height:1.6; color:var(--muted); margin:0 0 13px; }
  .hint:last-child { margin-bottom:0; }
  .nav { display:flex; flex-wrap:wrap; gap:12px; margin:30px 0 0; }
  .gateline { font-size:14.5px; line-height:1.6; color:var(--muted);
              margin:16px 0 0; max-width:62ch; }
  .gateline b { color:var(--ink); }
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
_CHECK = ('<svg width="11" height="11" viewBox="0 0 11 11" aria-hidden="true">'
          '<path d="M1.6 5.7 4.3 8.4 9.4 2.7" fill="none" '
          'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
          'stroke-linejoin="round"/></svg>')

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
    """
    if since is None:
        return "just started"
    seconds = int((datetime.now(timezone.utc) - since).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)} seconds elapsed"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} elapsed"
    hours, minutes = divmod(minutes, 60)
    return (f"{hours} hour{'s' if hours != 1 else ''} "
            f"{minutes} minute{'s' if minutes != 1 else ''} elapsed")


def _steps(stop: str) -> str:
    """The step strip: where this stop sits in the six, in words.

    Not the waypath. The waypath is the course's gesture and means "where
    you are on a path you will walk"; six setup stops are not that path, and
    borrowing the gesture here would spend it on the one part of the product
    a learner sees exactly once. Done steps carry the check mark beside
    their name and the line beneath says the position in words, so the strip
    is legible with every color stripped out of it.
    """
    at = onboarding.STAGE_SEQUENCE.index(stop)
    items = []
    for i, stage in enumerate(onboarding.STAGE_SEQUENCE):
        label = STEP_LABELS[stage]
        if i < at:
            items.append(f'<li class="done">{_CHECK}{label}</li>')
        elif i == at:
            items.append(f'<li class="now" aria-current="step">{label}</li>')
        else:
            items.append(f"<li>{label}</li>")
    return (f'<ol class="steps">{"".join(items)}</ol>'
            f'<p class="stepline">Step {at + 1} of '
            f'{len(onboarding.STAGE_SEQUENCE)} · {STOP_TITLES[stop]}</p>')


def _page(stop: str, screen: Screen, tenant_slug: str) -> str:
    """The wizard's one page shell.

    The eyebrow leads to `/profile` rather than to the front door on
    purpose: the gate sends an unstarted tenant straight back here, so a
    link home would be a link to this page with extra steps. `/profile` is
    reachable from every state of the account, which is the promise the gate
    is written around.
    """
    e = html_mod.escape
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{META_REFRESH if screen.refresh else ""}
<title>curricle — setting up</title>
<style>
{WIZARD_CSS}</style>
</head>
<body>
<div class="wizard">
  <header class="masthead">
    <p class="eyebrow"><a href="/profile">your profile</a>
    <span class="sep">·</span> setting up curricle
    <span class="sep">·</span> tenant {e(tenant_slug)}</p>
    {_steps(stop)}
  </header>
  {screen.body}
  <footer>
    Your place is kept in the onboarding ledger, not in this page — close the
    tab whenever you like and come back to exactly this screen.
  </footer>
</div>
</body>
</html>
"""


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
  <h1>Let us build you a course.</h1>
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
  <h2>What this never does</h2>
  <ul class="never">{promises}</ul>
  <p class="ask">
    <a class="pill primary" href="/onboarding/?screen=1">Begin →</a>
    <span class="aside">About ten minutes, and you can stop between any two
    screens.</span>
  </p>
""")


def _examples(field: str) -> str:
    """The two example claims, marked as examples rather than as copy.

    House copy, so unescaped, exactly like the never-promises and the wording
    sentences: the only text on a form screen that came from anywhere but
    this module is a claim out of the ledger, and that is escaped where it is
    interpolated.
    """
    _, examples = FIELD_COPY[field]
    return ('<div class="eg"><b>for example</b>'
            + "".join(f"<p>{x}</p>" for x in examples) + "</div>")


def _claim_box(field: str, key: str, text: str, label: str) -> str:
    """One textarea over one claim identity, prefilled from the fold."""
    e = html_mod.escape
    return (f'<label class="claim"><span class="claimkey">{e(label)}</span>'
            f'<textarea name="claim__{e(field)}__{e(key)}" rows="3">'
            f"{e(text)}</textarea></label>")


def _field_block(field: str, claims: list[profile.Claim]) -> str:
    """One field: what it is, what a claim looks like, and what you have said.

    Existing claims come back in fold order, each in its own box under its
    own key, because the key is the claim's identity for the rest of its
    life — editing a box re-asserts that key and emptying it retracts it, and
    both are things the learner should be able to see themselves doing.
    """
    explanation, _ = FIELD_COPY[field]
    boxes = "".join(_claim_box(field, c.key, c.text, c.key) for c in claims)
    hint = ('<p class="hint">Empty a box to delete that claim.</p>'
            if claims else "")
    return f"""
    <div class="panel field">
      <h3>{FIELD_LABELS[field]}</h3>
      <p class="explain">{explanation}</p>
      {_examples(field)}
      {boxes}{hint}
      <label class="claim"><span class="claimkey">Add</span>
      <textarea name="new__{html_mod.escape(field)}" rows="3"
      placeholder="One claim per line"></textarea></label>
    </div>"""


def _meta_block(state: profile.ProfileState) -> str:
    """Screen 1's description line: one box, one key, never a numbered one."""
    claim = state.claim("meta", META_KEY)
    explanation, _ = FIELD_COPY["meta"]
    return f"""
    <div class="panel field">
      <h3>{FIELD_LABELS["meta"]}</h3>
      <p class="explain">{explanation}</p>
      {_examples("meta")}
      {_claim_box("meta", META_KEY, claim.text if claim else "", "Description")}
      <p class="hint">Empty this box to leave the description unset.</p>
    </div>"""


def _screen_nav(number: str, missing: tuple[str, ...]) -> str:
    """Previous, next, and the gate — the last of those in plain words.

    When a required field is still empty the link onward to the review is not
    there to be clicked: it is replaced by the sentence naming what is
    missing, so the reason the path stops is on the same line the path stops
    at. Refusing to publish is the review screen's job; this only says so.
    """
    e = html_mod.escape
    at = SCREEN_ORDER.index(number)
    previous, following = SCREEN_ORDER[at - 1], SCREEN_ORDER[at + 1]
    links = [f'<a class="pill" href="/onboarding/?screen={previous}">'
             f"← {SCREEN_NAMES[previous]}</a>"]
    if missing:
        names = ", ".join(FIELD_LABELS[f] for f in missing)
        gate = f'<p class="gateline">{GATE_LEAD} <b>{e(names)}</b>.</p>'
    else:
        gate = ('<p class="gateline">Every field a course is written against '
                'has a claim on the record. '
                '<a href="/onboarding/?screen=review">Review and publish '
                "→</a></p>")
    if following != "review" or not missing:
        links.append(f'<a class="pill" href="/onboarding/?screen={following}">'
                     f"{SCREEN_NAMES[following]} →</a>")
    return f'<div class="nav">{"".join(links)}</div>{gate}'


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
    return Screen(f"""
  <p class="screenline">Profile screen {e(number)} of 4</p>
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


def review_screen(profile_state: profile.ProfileState) -> Screen:
    """Stop 5: the projection, whole, then publish. Placeholder until it lands."""
    missing = onboarding.profile_gate_missing(profile_state)
    gate = (f"<p>Still missing before the profile can be published: "
            f"<b>{html_mod.escape(', '.join(missing))}</b>.</p>"
            if missing else
            "<p>Every field the course builder leans on has at least one "
            "claim on the record.</p>")
    return Screen(f"""
  <h1>Read it back before you publish</h1>
  <div class="gatebox">
    <p class="stateline">{_chip("waiting")}</p>
    <h2>This review screen is still being built</h2>
    <p>It will show the rendered profile whole — the exact document that
    rides along on every model call that builds your course — and publishing
    it is what opens the rest of the setup.</p>
    {gate}
  </div>
  <p class="ask"><a class="pill" href="/onboarding/">← back to the start</a></p>
""")


def stage_screen(stop: str, flow: onboarding.CourseFlow | None) -> Screen:
    """Stops 6–10: one screen per stage, from the flow the fold folded.

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
    since = (f'<span class="elapsed">{elapsed_words(flow.updated_at)}</span>'
             if status == "pending" and flow is not None else "")
    course = (f' for <b>{html_mod.escape(flow.course_id)}</b>'
              if flow is not None and flow.course_id else "")
    return Screen(f"""
  <h1>{STOP_TITLES[stop]}</h1>
  <div class="gatebox">
    <p class="stateline">{_chip(status)}{since}</p>
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


# --------------------------------------------------------------------------
# Mounting
# --------------------------------------------------------------------------

def mount(app: FastAPI, *, engine, scope: db.TenantScope, tenant_slug: str,
          courses: dict, courses_dir: str | None) -> None:
    """Register the wizard's routes on `app`, closure style.

    `courses` is the live course map `create_app` keeps and mutates; the
    wizard reads it and never writes it, so registration stays one process's
    one job. `courses_dir` is the managed home a later stop mints a course id
    against. Both are held here rather than fetched, because the app has
    exactly one of each and passing them is cheaper than a second source of
    truth for either.
    """

    @app.get("/onboarding/")
    def onboarding_page(screen: str = "welcome") -> Response:
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
            # to have about it.
            return HTMLResponse(_page(stop, stage_screen(stop, state.active()),
                                      tenant_slug))
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
        return HTMLResponse(_page(stop, rendered, tenant_slug))

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

        at = SCREEN_ORDER.index(number)
        # 303: the save is done, and what follows is a page to look at — a
        # reload of it must never post the form a second time.
        return RedirectResponse(f"/onboarding/?screen={SCREEN_ORDER[at + 1]}",
                                status_code=303)
