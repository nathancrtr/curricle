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
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI
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

# The profile stop's sub-screens, in order. Issues later in this flow
# replace the placeholder each one renders; the vocabulary is the contract.
PROFILE_SCREENS = ("welcome", "1", "2", "3", "4", "review")

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


def form_screen(number: str) -> Screen:
    """Stops 1–4: the profile forms. Placeholder until they land."""
    return Screen(f"""
  <h1>Profile, screen {html_mod.escape(number)} of 4</h1>
  <div class="gatebox">
    <p class="stateline">{_chip("waiting")}</p>
    <h2>This form is still being built</h2>
    <p>It will ask for a handful of short claims in your own words, and save
    each one as your own assertion — the tier that needs no review.</p>
    <p>In the meantime the same claims can be written from the command line:
    <code>python -m curricle profile assert</code>.</p>
  </div>
  <p class="ask"><a class="pill" href="/onboarding/">← back to the start</a></p>
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
        if screen not in PROFILE_SCREENS:
            # A screen the vocabulary does not know is navigation past the
            # frontier: back to the fold's screen, and to a URL that agrees
            # with what is on it.
            return RedirectResponse("/onboarding/")
        if screen == "welcome":
            rendered = welcome_screen(worker_running=worker_running)
        elif screen == "review":
            rendered = review_screen(profile_state)
        else:
            rendered = form_screen(screen)
        return HTMLResponse(_page(stop, rendered, tenant_slug))
