"""The worker: claim a queued run, run its stage, append the outcome.

L1 says no LLM on a request path, ever, so the onboarding stages that talk
to a model do not run inside `serve`. They run here, in `python -m curricle
work` — "a separate process beside `serve`, sharing the database and nothing
else" (onboarding-design.md §6). The web app writes request rows and reads
outcome rows; it never imports the model runner, and a grep guard keeps it
honest.

This is deliberately the thin slice of the queue platform-design §6.1
already plans, not a rival to it: one process, one claim at a time, and no
retry scheduling at all — the wizard's retry button *is* the scheduler. A
failed stage is simply requested again, which is a row, which is the fold's
business rather than this module's.

What a *succeeded* stage may do is queue the next one (`CHAINS_TO`), and
that is not the same thing: design §4 rejected a second human gate between
the build and the promotion, so there is no person to wait for between them
and a flow that stopped there would be waiting on nobody. Nothing chains off
a failure, which is the whole distinction — a stage that stopped costs money
to run again, and only a person may ask for that.

A run takes exactly two transactions, and the split is the important part.
The first claims the row and commits it `running` — so the claim is a fact
the moment it is made, visible to anything that looks, and a stage that then
falls over cannot be handed out again by a rollback. The handler runs with
no transaction open at all, because a stage is minutes of model calls and
holding a row lock across them would be a database problem waiting to
happen. The second appends the outcome event and finishes the run row
together: *that* pair is the invariant worth an atom, since an outcome the
ledger records but the queue thinks is still going (or the reverse) is drift
nobody can reconstruct afterwards. What is not covered — and never was — is
whatever a handler wrote while it ran: `token_ledger` rows are committed by
the runner as the money is spent, which is exactly right for a spend record,
and no rollback here un-spends them.

The cost of committing the claim early is a run that can be left `running`
by a worker that dies mid-stage. Nothing sweeps that automatically at
runtime, because a worker cannot tell the difference between a peer's live
run and a dead one's wreckage — but at startup it can: the advisory lock
proves no other worker is alive, so every `running` row is wreckage, and it
is failed with reason `interrupted`. Deliberately *not* re-run: an automatic
retry after a crash re-spends real money on the learner's behalf without
being asked. The human sees an honest failure and a retry button.

T1 runs through all of it: the tenant comes from the claimed row and from
nowhere else. The worker serves every tenant and has no ambient one;
`db.for_tenant(run.tenant_id)` is the only scope a handler ever sees.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from decimal import Decimal
from typing import Callable

import sqlalchemy as sa
import yaml

from . import coursehome, db, factory, llm, onboarding, profile
from .compiler import compile_course
from .sidecar import load_sidecar

# A handler runs one claimed stage. It returns the outcome to append to the
# onboarding ledger, or None (nothing to record — the noop stage).
#   handler(engine, scope, run) -> tuple[event_kind, payload] | None
# `run` is the claimed row (id, tenant_id, course, stage, payload).
# A handler opens its own short transactions to read and holds none across
# the work itself; an outcome that has to queue the stage after it says so
# through `CHAINS_TO` rather than by inserting a row of its own, so that the
# event and the run row it causes land in one transaction the handler never
# has to know about.
Handler = Callable[[sa.Engine, db.TenantScope, sa.Row],
                   "tuple[str, dict] | None"]

# Where the outline stage leaves the course it drafted, under that course's
# directory in the managed home, and where the build stage reads it back
# from. `wizard.DRAFT_DIR` is the same name on the other side of the process
# boundary — the wizard cannot import this module (L1's grep guard).
DRAFT_DIR = ".draft-onboarding"

# The phase the wizard builds and promotes. Onboarding writes phase 1 and
# only phase 1 (design §4, Stop 9), so the checkpoint promotion reads is
# `interactive/.draft-p1/` — and `_unpromoted` below refuses to move a tree
# that still holds any other, rather than publishing a draft nobody promoted.
PHASE_ID = "p1"

# What an outcome queues behind itself, in the same transaction as the
# outcome event. Design §4 rejected a second human gate over the built
# materials, so `build_ready` is not a stop: the decision to publish was
# taken at the outline gate, and a finished build with nothing queued behind
# it would be a flow waiting on a person who has already answered.
CHAINS_TO = {"build_ready": "promote"}

# How a stage builds the thing that spends money. A seam, not a setting:
# tests hand back a Runner whose transport is scripted, and the process that
# serves web requests never reaches this module at all. Production has
# exactly one answer and it is the default.
RUNNER_FACTORY = llm.Runner


class StageFailed(RuntimeError):
    """A stage refusing in the ledger's own vocabulary.

    `reason` is a REASONS key, which is what makes this different from any
    other exception a handler can raise: `_reason_of` takes it at its word
    and the wizard has a sentence ready for it. Everything without one is a
    `worker_error`, honestly recorded as the bug it is.
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def _noop(engine: sa.Engine, scope: db.TenantScope, run: sa.Row) -> None:
    """The stage that proves the machinery without spending a token.

    Slice 1 of the build order runs end to end before any role exists
    (design §10), and a stage the worker can run for free stays useful long
    after as the smoke test for everything around it.
    """
    return None


def _outline(engine: sa.Engine, scope: db.TenantScope,
             run: sa.Row) -> tuple[str, dict]:
    """Stop 7: draft this course's outline, and price building phase 1 of it.

    Everything the stage needs comes from the claimed row's tenant (T1): the
    scope out of that tenant's onboarding fold, the profile out of that
    tenant's evidence fold, and a runner whose spend is metered against that
    tenant's ledger. The worker has no tenant of its own to fall back on.

    One short read, and then no transaction at all. The draft is minutes of
    model calls, and `run_once` has already committed the claim precisely so
    that nothing here has to hold a row lock across them; the outcome this
    returns is what the second transaction records. A worker that dies in
    the middle leaves a `running` row for the next one's startup sweep,
    which fails it honestly as `interrupted` rather than re-spending.

    The plan and the estimate are computed here rather than at the gate
    because they are what the gate is a gate *on*: the learner approves a
    number, and O3 says the row carries the number they were shown.
    """
    with engine.begin() as conn:
        flow = onboarding.load_state(conn, scope).flows.get(run.course)
        prof = profile.load_profile(conn, scope)
    if flow is None or not flow.scope:
        # Not a stage failure in the ledger's sense — it is a run enqueued
        # for a course nobody scoped, which is a bug in whoever enqueued it.
        raise StageFailed("worker_error",
                          f"no saved scope for course {run.course!r}")

    # Asked before the runner is built, so an unconfigured courses home
    # fails the run before it can spend anything. There is no default home
    # and this is not the place to invent one.
    draft_dir = os.path.join(coursehome.courses_dir(), run.course, DRAFT_DIR)
    runner = RUNNER_FACTORY(engine, scope)
    try:
        factory.build_outline(runner, prof, run.course, flow.scope, draft_dir,
                              note=run.payload.get("note") or flow.note)
    except llm.NoApiKey as exc:
        # The first-run failure of a fresh checkout, and the one the generic
        # worker error serves worst: a stranger who retries without putting
        # a key somewhere gets this face forever. The call was refused
        # before it was billed, so nothing was spent and the wizard's
        # sentence can say so — see WORDING[("outline", "no_api_key")].
        raise StageFailed("no_api_key", str(exc)) from exc
    except llm.BadApiKey as exc:
        # A different sentence because it is a different instruction: the
        # credential exists and was refused, so it is replaced rather than
        # provided. Told apart by the transport, on the SDK's own classes.
        raise StageFailed("bad_api_key", str(exc)) from exc
    except llm.BudgetExceeded as exc:
        # The runner refuses in money's vocabulary; the ledger has a key for
        # it and the wizard has a sentence. Wrapped rather than re-raised
        # bare, because `BudgetExceeded` carries no reason of its own.
        raise StageFailed("budget_exceeded", str(exc)) from exc

    # The draft was already compiled clean by the stage that wrote it; this
    # is the same compile again for the manifest itself, which is what the
    # plan is derived from. A refusal here would mean the two disagreed.
    try:
        sidecar = load_sidecar(os.path.join(draft_dir, factory.OUTLINE_FILES[1]))
        manifest, issues = compile_course(draft_dir, sidecar)
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        # The same set the outline stage's own validator guards with: the
        # sidecar loader raises through what it cannot turn into a finding.
        raise StageFailed("compile_failed",
                          f"{type(exc).__name__}: {exc}") from exc
    if manifest is None:
        raise StageFailed("compile_failed",
                          "\n".join(str(i) for i in issues if i.level == "error"))

    try:
        plan = factory.default_build_plan(manifest)
    except ValueError as exc:
        # An outline that compiles and still has no phase 1, or a phase 1
        # with no units in it: a shape this system accepts from the compiler
        # and cannot build from. That is the outline being wrong, not the
        # worker breaking, so it is worded as such and the retry is offered.
        raise StageFailed("validation_failed", str(exc)) from exc
    estimate = factory.estimate_build_cost(runner.config, plan)
    headroom = _build_headroom(runner, plan)
    return "outline_ready", {"plan": plan,
                             "estimate_usd": f"{estimate:.2f}",
                             "headroom_usd": f"{headroom:.2f}"}


def _build_headroom(runner: llm.Runner, plan: dict) -> Decimal:
    """What this build has left to spend before a role starts refusing.

    Not the configured budgets added up. A budget is *per tenant per stage*
    for the life of the account (models.yaml), and `run_role` compares a
    role's whole ledger history against it — so a tenant on their second
    course has already eaten into every one of these, and the sum of the
    budgets would be a number nobody can still spend. Printing that at the
    gate would put a cap on the screen that the very next call could refuse
    to honour, and O3 would record it forever.

    So: budget minus what this tenant has already spent on that role,
    floored at zero, summed over the roles this plan actually runs.
    `runner.spent` is the same read `run_role` performs before every call,
    taken here at the moment the outline becomes ready — which is what
    makes the figure true of the decision the learner is about to make
    rather than of the account in general.

    It is a stopping line and not a hard cap, and the gate says so: the
    check is made *before* a call, so a call already under way can carry
    its role a little past the budget it was checked against.
    """
    return sum((max(runner.config.budget_for_stage(role) - runner.spent(role),
                    Decimal(0))
                for key, role in factory.PLAN_ROLES if plan.get(key)),
               Decimal(0))


def _build(engine: sa.Engine, scope: db.TenantScope,
           run: sa.Row) -> tuple[str, dict]:
    """Stop 9: build phase 1 of the approved outline into the draft tree.

    O3 gets its teeth here — "no token is spent without an upstream ledger
    row recording the learner's approval and the estimate they were shown".
    The check is `_approved_plan`'s and it happens before a runner is built,
    so a build nobody approved cannot reach a model even by accident.

    The plan that runs is the *approval's* plan, never a freshly computed
    one: what the learner read at the gate is what gets bought. Its keys are
    `BuildSpec`'s own field names, so it arrives as `BuildSpec(**plan)` with
    nothing in between to mistranslate it.

    Two short reads and then no transaction at all, the same shape as the
    outline stage: the build is minutes of model calls, and the claim is
    already committed. Whatever the run does manage to buy is checkpointed
    into the draft as it goes, which is what makes the retry a resume rather
    than a second purchase.
    """
    with engine.begin() as conn:
        rows = list(conn.execute(scope.onboarding_select()))
        prof = profile.load_profile(conn, scope)
    plan = _approved_plan(rows, run.course)

    # Asked before the runner is built, like the outline stage's: a home
    # nobody configured fails the run rather than being guessed at.
    draft_root = os.path.join(coursehome.courses_dir(), run.course, DRAFT_DIR)
    try:
        sidecar = load_sidecar(os.path.join(draft_root, factory.OUTLINE_FILES[1]))
        manifest, issues = compile_course(draft_root, sidecar)
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        # The draft compiled clean when the outline stage wrote it and again
        # when the gate drew it, so a refusal here means it has been edited
        # or lost since. Nothing is built against a tree the compiler will
        # not vouch for.
        raise StageFailed("compile_failed",
                          f"{type(exc).__name__}: {exc}") from exc
    if manifest is None:
        raise StageFailed("compile_failed",
                          "\n".join(str(i) for i in issues if i.level == "error"))

    # The draft mirrors a course's own layout, so the content root is its
    # `learning/` and `build_phase` writes `interactive/.draft-p1/` under it
    # by exactly the existing mechanics. Nothing in this stage writes outside
    # the draft tree; only promotion touches a course.
    content_root = os.path.join(draft_root, "learning")
    spec = _remaining(factory.BuildSpec(**plan), content_root)
    try:
        report = factory.build_phase(RUNNER_FACTORY(engine, scope), manifest,
                                     prof, content_root, spec)
    except llm.NoApiKey as exc:
        # The same two classifications as the outline stage's: a credential
        # that is missing, and one that is refused, are both things the
        # learner can fix, and each is worth its own sentence rather than
        # the generic stopped-worker one.
        raise StageFailed("no_api_key", str(exc)) from exc
    except llm.BadApiKey as exc:
        raise StageFailed("bad_api_key", str(exc)) from exc
    except llm.BudgetExceeded as exc:
        raise StageFailed("budget_exceeded", str(exc)) from exc
    except factory.ValidationFailed as exc:
        # Generated material that failed its checks was thrown away rather
        # than half-kept, and everything earlier in the run was checkpointed:
        # the retry buys the refused artifact again and nothing else.
        raise StageFailed("validation_failed", str(exc)) from exc

    # What *this* run bought. The full set of the phase's artifacts lives in
    # the draft's own checkpoint manifest, which is what promotion reads —
    # a resumed run honestly reports only the part it paid for.
    return "build_ready", {
        "artifacts": [a.rel_path or a.note for a in report.artifacts],
        "costs": report.costs,
    }


def _approved_plan(rows: list[sa.Row], course: str) -> dict:
    """The plan the learner approved for `course`, or a refusal (O3).

    Structural, by ledger order, and never by trusting whoever queued the
    run: the approval has to be *later than the latest outline*, so an
    approval of a draft that was since rejected and redrafted does not
    authorise a build of the new one. Row ids are the order — the fold does
    not expose them, which is why this reads rows rather than a flow.

    Both halves of the approval must be on the row. A plan says what would
    be bought and the estimate says what the learner was told it costs; a
    row carrying neither is a decision nobody can show was informed, so it
    buys nothing.
    """
    mine = [r for r in rows if r.course == course]
    latest_outline = max((r.id for r in mine if r.kind == "outline_ready"),
                         default=0)
    approval = next((r for r in reversed(mine)
                     if r.kind == "outline_approved" and r.id > latest_outline),
                    None)
    if approval is None:
        raise StageFailed(
            "unapproved",
            f"no outline_approved after the latest outline for {course!r}")
    payload = approval.payload or {}
    plan, estimate = payload.get("plan"), payload.get("estimate_usd")
    if not isinstance(plan, dict) or not isinstance(estimate, str):
        raise StageFailed(
            "unapproved",
            f"the approval on file for {course!r} carries no plan and estimate")
    return plan


# The spec fields a checkpointed artifact has already paid for, by the kind
# of material it registers. The bank has no material of its own — it is a
# section appended to somebody else's file — so it is recognised below by
# having no path rather than by a kind.
_ALREADY_BOUGHT = {
    "lesson": {"lesson_unit": None},
    "widget": {"widget_unit": None, "widget_concept": None},
    "exercise": {"exercise_unit": None},
    "quiz": {"quiz": False},
}


def _remaining(spec: factory.BuildSpec, content_root: str) -> factory.BuildSpec:
    """The approved plan minus whatever the draft already holds.

    `build_phase` merges a resumed run into the same draft and checkpoints
    after every artifact, but it buys whatever its spec asks for — so
    narrowing the spec is the caller's half of that bargain, and the caller
    is a learner who pressed retry over a build that stopped partway. This
    is what makes the wizard's sentence true: finished materials were kept,
    so a retry carries on rather than paying for them twice.
    """
    path = os.path.join(content_root, "interactive", f".draft-{spec.phase_id}",
                        "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            done = json.load(f).get("artifacts", [])
    except (OSError, ValueError):
        # No checkpoint, or one nothing can read: the honest answer is the
        # whole plan, which is what a first run gets anyway. A draft this
        # stage cannot understand is never a reason to refuse the build.
        return spec
    bought: dict = {}
    for artifact in done:
        if not artifact.get("rel_path"):
            bought["bank"] = False
            continue
        kind = (artifact.get("material") or {}).get("kind")
        bought.update(_ALREADY_BOUGHT.get(kind, {}))
    return dataclasses.replace(spec, **bought)


def _sidecar_at(root: str) -> str | None:
    """Where this course keeps its sidecar, or None if it keeps none yet.

    The same two names, in the same order, that `webapp.load_course` looks
    in — a course the app would refuse to read is not one this stage may
    call published.
    """
    for name in coursehome.SIDECAR_NAMES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None


def _unpromoted(content_root: str) -> list[str]:
    """Checkpoint directories still sitting in the draft's `interactive/`.

    `factory.promote` deletes the checkpoint it promoted, so anything left
    here is a phase whose artifacts were bought and never moved into the
    course. Publishing over that would serve a course quietly missing the
    materials the learner paid for, which is the one outcome worse than a
    refusal — so the tree is refused and the draft is left where it is.
    """
    interactive = os.path.join(content_root, "interactive")
    if not os.path.isdir(interactive):
        return []
    return sorted(name for name in os.listdir(interactive)
                  if name.startswith(".draft-"))


def _bank_would_be_lost(checkpoint_path: str) -> bool:
    """A bank section in the checkpoint with nowhere to append it?

    The bank is the one artifact that is not a file: it is text appended to
    the course's existing question bank, so it carries no `rel_path` and
    `factory.promote` finds its destination in the checkpoint's own
    `bank_target`. When that is None the section is passed over in silence —
    material the learner paid for, gone with no row anywhere saying so.

    `factory.default_build_plan` no longer buys a bank for a course that has
    none, so this cannot happen on the mainline; it is here so that the day
    something regresses, a learner gets a refusal they can see rather than a
    loss nobody can. An unreadable checkpoint is not this function's
    business — the compile gate below has the honest word for that.
    """
    try:
        with open(checkpoint_path, encoding="utf-8") as f:
            build = json.load(f)
    except (OSError, ValueError):
        return False
    if build.get("bank_target"):
        return False
    return any(not a.get("rel_path") for a in build.get("artifacts", []))


def _move_into(src_dir: str, dst_dir: str) -> None:
    """Move every child of `src_dir` into `dst_dir`, merging directories.

    Renames rather than copies, so a course does not exist twice on disk
    even for an instant. The merge is not generality for its own sake: a
    worker that died halfway through this loop left some children already
    in place, and the retry has to finish the move rather than trip over
    its own predecessor's progress.
    """
    for name in sorted(os.listdir(src_dir)):
        src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        if os.path.isdir(src) and os.path.isdir(dst):
            _move_into(src, dst)
            os.rmdir(src)
        else:
            os.replace(src, dst)


def _install(draft_root: str, course_root: str, course_id: str) -> None:
    """Step 2: the draft's contents become the course, under its own name.

    Three refusals before anything moves, because everything after the move
    is harder to undo than to prevent. Nothing may be left unpromoted; the
    tree must still carry a sidecar; and the id in that sidecar must be
    exactly the directory's name. That last one is not fussiness: every
    registration path in the app looks a course up by directory basename and
    serves it under the id its sidecar declares, so a course whose two names
    disagree is one nothing can serve and everything recompiles. Minting
    makes them equal by construction — this refuses rather than guesses on
    the day something has made them differ.
    """
    left = _unpromoted(os.path.join(draft_root, "learning"))
    if left:
        raise StageFailed(
            "validation_failed",
            f"the draft still holds unpromoted materials in {', '.join(left)}")
    sidecar_path = _sidecar_at(draft_root)
    if sidecar_path is None:
        raise StageFailed("compile_failed",
                          f"the draft at {draft_root} carries no sidecar")
    try:
        declared = load_sidecar(sidecar_path).course.id
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        raise StageFailed("compile_failed",
                          f"{type(exc).__name__}: {exc}") from exc
    if declared != course_id:
        raise StageFailed(
            "validation_failed",
            f"the drafted course calls itself {declared!r} but the directory "
            f"it would be published into is {course_id!r} — refusing to "
            "publish a course under a name it never claimed")
    _move_into(draft_root, course_root)
    os.rmdir(draft_root)


def _promote(engine: sa.Engine, scope: db.TenantScope,
             run: sa.Row) -> tuple[str, dict] | None:
    """Stop 10: the built draft becomes the course, or nothing happens.

    Four steps, ordered so that an interruption leaves a state the retry can
    finish rather than one somebody has to reconstruct by hand: the existing
    promotion mechanics *inside the draft tree*, then the move into place,
    then the final compile at the final location, then the row that says the
    course exists. The last two are the point of the order — `promoted` is
    appended only after a compile of the course where it will actually be
    served, because "only promotion touches a course, and it aborts unless
    the compile stays clean" has to gate the ledger row and not merely print
    beside it.

    Every step is skippable by the state it already found, which is what
    makes the retry safe. A flow that already has a `promoted` row returns
    None and appends nothing — the ledger is append-only and a duplicate is
    suppressed at the writer, never deleted afterwards. A draft with no
    checkpoint left in it has been promoted once already, so that step is
    passed over; a draft directory that is gone — or that is still there
    with nothing left in it, which is the crash window between the last
    child moving and the directory being removed — was already moved, so the
    move is too, and the compile and the row run on their own.

    What this handler never reads is the `build_ready` payload. That row
    lists what one run bought, and a resumed build honestly reports only its
    own part — the full inventory is the checkpoint manifest in the draft,
    which is what the promotion mechanics read for themselves.
    """
    with engine.begin() as conn:
        rows = list(conn.execute(scope.onboarding_select()))
    if any(r.kind == "promoted" and r.course == run.course for r in rows):
        # Two runs queued behind one build, or a retry over a promotion that
        # got further than its worker survived to report. The course is
        # published either way, and a second row saying so would be the
        # ledger claiming it happened twice.
        return None

    # Asked before anything else, like the two stages before it: a courses
    # home nobody configured fails the run rather than being guessed at.
    course_root = os.path.join(coursehome.courses_dir(), run.course)
    draft_root = os.path.join(course_root, DRAFT_DIR)
    if os.path.isdir(draft_root) and not os.listdir(draft_root):
        # The one instant `_install` is not atomic across: every child has
        # been renamed into the course and the empty shell has not been
        # removed yet. An empty draft is a finished move, not a draft — and
        # read as a draft it would be one with no sidecar, which is a
        # refusal the retry would hit again forever.
        os.rmdir(draft_root)
    if os.path.isdir(draft_root):
        content_root = os.path.join(draft_root, "learning")
        checkpoint = os.path.join(content_root, "interactive",
                                  f".draft-{PHASE_ID}", "manifest.json")
        if os.path.isfile(checkpoint):
            if _bank_would_be_lost(checkpoint):
                raise StageFailed(
                    "validation_failed",
                    "the built phase holds a question-bank section and this "
                    "course has no question bank to append it to — refusing "
                    "to publish materials that would be dropped in silence")
            try:
                factory.promote(draft_root, content_root,
                                os.path.join(draft_root,
                                             factory.OUTLINE_FILES[1]),
                                PHASE_ID)
            except factory.ValidationFailed as exc:
                # Promotion's own compile gate, refusing inside the draft:
                # the materials broke the course, so they are not moved.
                raise StageFailed("compile_failed", str(exc)) from exc
            except (OSError, ValueError, TypeError, KeyError,
                    yaml.YAMLError) as exc:
                raise StageFailed("worker_error",
                                  f"{type(exc).__name__}: {exc}") from exc
        _install(draft_root, course_root, run.course)
    elif _sidecar_at(course_root) is None:
        # No draft and no course: there is nothing here to publish, which is
        # a run enqueued for a flow that never built anything.
        raise StageFailed("worker_error",
                          f"nothing to publish: no draft at {draft_root} and "
                          f"no course at {course_root}")

    sidecar_path = _sidecar_at(course_root)
    if sidecar_path is None:
        raise StageFailed("compile_failed",
                          f"the promoted course at {course_root} carries no "
                          "sidecar")
    try:
        manifest, issues = compile_course(course_root, load_sidecar(sidecar_path))
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        raise StageFailed("compile_failed",
                          f"{type(exc).__name__}: {exc}") from exc
    if manifest is None:
        raise StageFailed("compile_failed",
                          "\n".join(str(i) for i in issues if i.level == "error"))
    # Registration is nobody's job here. This process and `serve` share a
    # database and a filesystem and nothing else, so nothing can call into
    # the app: the course is picked up by the front door's rescan and the
    # route miss, and this handler's work ends at the row.
    return "promoted", {"course_id": run.course}


HANDLERS: dict[str, Handler] = {"noop": _noop, "outline": _outline,
                                "build": _build, "promote": _promote}

# What a stage says in the ledger when it fails — because its handler
# raised, because the outcome it returned was refused, or because the worker
# running it was interrupted. A stage without an entry here has no failure
# vocabulary yet, so a failure of it is recorded on the run row alone.
FAILURE_KINDS = {
    "outline": "outline_failed",
    "build": "build_failed",
    "promote": "promote_failed",
}


def run_once(engine: sa.Engine,
             handlers: dict[str, Handler] | None = None) -> bool:
    """Claim and run at most one queued run. True if there was one.

    Two transactions, per the module docstring: the claim commits before the
    stage starts, and the outcome event and the finished run row commit
    together afterwards. The handler runs between them with nothing open.
    """
    handlers = HANDLERS if handlers is None else handlers
    with engine.begin() as conn:            # transaction 1: the claim
        run = db.claim_next_run(conn)
        if run is None:
            return False
        # T1: the tenant is this row's, never an ambient one. The worker
        # process has no tenant of its own to fall back to.
        scope = db.for_tenant(run.tenant_id)
        superseded = _superseded(conn, scope, run)

    if superseded:
        # A run with nothing left to buy — see `_superseded`. The fold
        # already declines to act on a late outcome; this is the half that
        # protects the budget rather than the screen, and it is checked in
        # the claim's own transaction so the answer is not a stale read.
        with engine.begin() as conn:
            db.finish_run(conn, run.id, "done", "superseded")
        return True

    handler = handlers.get(run.stage)
    if handler is None:
        # No handler is not a stage failure: the stage never started, so its
        # vocabulary never applied and there is nothing truthful to append.
        # The run row carries the reason for an operator, and the wizard's
        # wording table has a sentence for the day one of these reaches a
        # learner.
        with engine.begin() as conn:
            db.finish_run(conn, run.id, "failed", "unknown_stage")
        return True

    try:
        outcome = handler(engine, scope, run)
    except Exception as exc:
        # Nothing is re-raised: one stage falling over is a row, not the end
        # of the worker.
        _record_failure(engine, scope, run, _reason_of(exc), str(exc))
        return True

    try:
        with engine.begin() as conn:        # transaction 2: outcome + finish
            if outcome is not None:
                kind, payload = outcome
                onboarding.append_event(conn, scope, kind, run.course, payload)
                follow_on = CHAINS_TO.get(kind)
                if follow_on is not None:
                    # In here rather than after, because an outcome the fold
                    # reads as "a machine's turn" with no run queued for that
                    # machine is a flow pending on nothing at all.
                    conn.execute(scope.runs_insert(run.course, follow_on, {}))
            db.finish_run(conn, run.id, "done")
    except (onboarding.InvalidOnboardingEvent, TypeError, ValueError) as exc:
        # A handler that returns an outcome the ledger refuses — a malformed
        # payload, or something that isn't a (kind, payload) pair at all — is
        # a bug in the handler, and it is treated exactly like a handler that
        # raised: the invalid outcome is not recorded, the stage's failure
        # is, and the run ends failed rather than being tried forever. (The
        # first two are the same class; both are named because the shapes a
        # handler can get wrong are the point of catching here.)
        _record_failure(engine, scope, run, "worker_error", str(exc))
    return True


def _record_failure(engine: sa.Engine, scope: db.TenantScope, run: sa.Row,
                    reason: str, detail: str) -> None:
    """One transaction: the stage's failure event, and the finished row.

    A stage with no entry in FAILURE_KINDS has no failure vocabulary yet, so
    its failure is recorded on the run row alone — the ledger says nothing
    rather than something it cannot mean.
    """
    with engine.begin() as conn:
        kind = FAILURE_KINDS.get(run.stage)
        if kind is not None:
            onboarding.append_event(conn, scope, kind, run.course,
                                    {"reason": reason, "detail": detail[:500]})
        db.finish_run(conn, run.id, "failed", reason)


def sweep_interrupted(engine: sa.Engine) -> int:
    """Fail every run still `running`, as the wreckage of a dead worker.

    Only ever safe to call while holding the worker lock: the lock is the
    proof that no other worker is alive, and therefore that a `running` row
    is nobody's live claim. The runs are failed, never re-run — a crash that
    silently re-spends the learner's money is worse than a failure they can
    see and retry.
    """
    with engine.begin() as conn:
        stale = db.stale_runs(conn)
        for run in stale:
            scope = db.for_tenant(run.tenant_id)
            kind = FAILURE_KINDS.get(run.stage)
            if kind is not None:
                onboarding.append_event(
                    conn, scope, kind, run.course,
                    {"reason": "interrupted",
                     "detail": "the worker holding this run did not survive "
                               "to report it"})
            db.finish_run(conn, run.id, "failed", "interrupted")
    return len(stale)


# The stops in order, for the one question this module asks of the order:
# has a flow already gone past the stage a claimed run would run?
_STAGE_INDEX = {name: i for i, name in enumerate(onboarding.STAGE_SEQUENCE)}


def _superseded(conn: sa.Connection, scope: db.TenantScope,
                run: sa.Row) -> bool:
    """Is there nothing left for this run to buy?

    Two ways there can be. The course has been promoted, and a promoted
    course is finished business — the fold treats `promoted` as absorbing,
    so a late outcome could not resurrect it anyway, but the fold protects
    the screen and this protects the budget.

    Or the flow has moved past the stage this run would run. That is the
    approve gate's race made harmless: approving is a read and three writes
    under READ COMMITTED with no unique index behind it, so two tabs
    answering at the same moment both see a flow waiting at the gate and
    both queue a build. O3's letter survives that — each run has an approval
    above it — and its intent does not, because one decision would be billed
    twice. The second run is claimed after the first has moved the flow on
    to `promote`, and it is finished done/superseded with nothing appended,
    because a run that bought nothing has nothing to report.

    A sibling build some worker has already claimed says the same thing one
    step earlier, for the case where the fold has not moved yet. It is asked
    of the build alone, and deliberately: a second *outline* run over a
    finished one is what rejecting a draft asks for by name, so "this stage
    has run before" is a refusal only where running twice means paying
    twice. A `failed` sibling is never one of these either — that is the
    state the retry button exists for, and the retry resumes from what the
    stopped run checkpointed rather than buying it again.
    """
    flow = onboarding.load_state(conn, scope).flows.get(run.course)
    if flow is not None and flow.stage == "done":
        return True
    if flow is not None and (_STAGE_INDEX.get(flow.stage, -1)
                             > _STAGE_INDEX.get(run.stage, len(_STAGE_INDEX))):
        return True
    if run.stage != "build":
        return False
    # The claim in this same transaction has already marked this run
    # `running`, so it is its own sibling until excluded.
    return any(row.id != run.id for row in
               conn.execute(scope.runs_taken(run.course, run.stage)))


def _reason_of(exc: Exception) -> str:
    """The machine reason key a failed stage reports.

    A handler that means something specific says so by carrying a `reason`;
    anything else is a worker error. A key the ledger's vocabulary has never
    heard of would be refused by `append_event`, which would leave the
    failure unrecorded — so an unknown key is treated as the bug it is: the
    failure is still recorded, under the honest reason, with the handler's
    own words in `detail`.
    """
    reason = getattr(exc, "reason", None)
    return reason if reason in onboarding.REASONS else "worker_error"


def main(engine: sa.Engine, poll: float = 2.0, once: bool = False) -> int:
    """Hold the worker lock, clear the last worker's wreckage, and drain.

    One worker per database, enforced by the advisory lock rather than by
    hoping: a second `work` process refuses to start rather than racing the
    first for claims it would mostly skip anyway. Holding the lock is also
    what makes the startup sweep safe to do — see sweep_interrupted.
    """
    # Detached from the pool on purpose. The lock is session-scoped, so this
    # has to be a session that ends when the worker does — a connection
    # returned to the pool is only rolled back, and an advisory lock would
    # ride it into the next borrower.
    lock_conn = engine.connect()
    lock_conn.detach()
    with lock_conn:
        if not db.try_worker_lock(lock_conn):
            print("another worker holds the lock", file=sys.stderr)
            return 1
        # The lock is not transactional: committing here ends the read and
        # leaves the worker holding the lock, rather than sitting idle in a
        # transaction for its whole life.
        lock_conn.commit()

        # The lock is held, so nothing else is running a stage anywhere in
        # this database: whatever is still `running` belongs to a worker that
        # died, and it is failed rather than quietly retried.
        interrupted = sweep_interrupted(engine)
        if interrupted:
            print(f"swept {interrupted} interrupted run(s) from a previous "
                  "worker", file=sys.stderr)

        while True:
            worked = run_once(engine)
            if once:
                return 0
            if not worked:
                time.sleep(poll)
