"""The onboarding engine: where a tenant is in the wizard, folded from rows.

Third ledger, same discipline as the other two (onboarding-design.md §5):
append-only rows, a pure fold ordered by row id, and a screen that is a
derived view of the fold rather than a thing anybody stores. That is
invariant O1 — the wizard route renders whatever the fold says, and
navigation can reach at most the stops the fold has opened.

What this ledger records is *position*, never content. The profile stop's
substance lives in the profile fold; here a published profile is one row
saying publishing happened, and not one word of any claim. Two ledgers, two
folds, one derived screen: if the two ever disagree about the learner, the
bug is in whichever is acting as a projection of the other, and it is always
this one.

Stages are classified the way job-radar classifies them — human stages wait
on a person, worker stages wait on a machine — because the screens say
different things in the two cases, and a stage whose owner is ambiguous is a
screen that has to guess. Failures arrive as machine reason keys and leave
as sentences: every `(worker stage, reason)` pair has an entry in `WORDING`
and a test fails when one doesn't (invariant O2). Exception text stays in
the `detail` payload for an operator reading the ledger; it never reaches a
learner's screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa

from . import db
from .profile import ProfileState

# The stops, in order, and who owns each one. `profile` is a stage of the
# wizard but never of a course flow: it gates the tenant, once.
STAGE_SEQUENCE = ("profile", "scope", "outline", "outline_gate", "build", "promote")
HUMAN_STAGES = frozenset({"profile", "scope", "outline_gate"})
WORKER_STAGES = frozenset({"outline", "build", "promote"})

# Machine failure reasons. A reason is a key, never prose — the wording table
# below is the only place a failure becomes English.
# `interrupted` is the one nobody's code raises: it is written by the next
# worker to start, over a run whose worker died mid-stage. A crash is not a
# reason to re-spend a learner's money unasked, so the wreckage becomes an
# honest failure with a retry button rather than an automatic re-run.
REASONS = ("budget_exceeded", "validation_failed", "compile_failed",
           "unapproved", "unknown_stage", "worker_error", "interrupted")

# O2: one human sentence per (worker stage, reason), the full cross product.
# The completeness test cannot miss a pair because there is no pair it is
# allowed to consider inapplicable — a reason a stage "can't" raise today is
# exactly the one that arrives unworded the day it can.
WORDING: dict[tuple[str, str], str] = {
    ("outline", "budget_exceeded"):
        "The outline build hit its spending ceiling — raise the stage budget "
        "in models.yaml, then retry.",
    ("outline", "validation_failed"):
        "The outline came back in a shape this system doesn't accept, so it "
        "was thrown away rather than half-kept. Retrying is safe.",
    # No "narrow the scope on the previous screen": from the outline stop
    # there is no previous screen to go back to, and the scope form is behind
    # a stop the fold has closed. The two things a learner can actually do
    # are the button on this screen and, once a draft does come back, the
    # note at the gate — so those are what the sentence names.
    ("outline", "compile_failed"):
        "The drafted outline wouldn't compile, twice, so it was refused. "
        "Nothing partial was kept, so retrying is safe — and a draft that "
        "does come back can be sent round again with a note asking for "
        "something narrower.",
    ("outline", "unapproved"):
        "The outline build ran without an approval on file and stopped "
        "before spending anything. Start it again from the scope screen.",
    ("outline", "unknown_stage"):
        "The worker was handed a stage it doesn't know, so the outline never "
        "started. Nothing was spent; this one is a bug worth reporting.",
    ("outline", "worker_error"):
        "The worker stopped partway through the outline build. Nothing "
        "partial was kept, so retrying is safe.",
    ("outline", "interrupted"):
        "The worker was shut down partway through the outline build and "
        "nothing partial was kept. Retry when you're ready.",

    ("build", "budget_exceeded"):
        "The phase-1 build hit its spending ceiling — raise the stage budget "
        "in models.yaml, then retry to pick up where it stopped.",
    ("build", "validation_failed"):
        "Generated material failed its checks — a test that should have "
        "failed passed, or a quiz arrived without its explanations. Retry to "
        "have it built again.",
    ("build", "compile_failed"):
        "The built materials wouldn't compile into the course, so they were "
        "refused rather than promoted. Retrying is safe.",
    ("build", "unapproved"):
        "The build ran without your approval of the outline and the estimate, "
        "so it stopped before spending anything. Approve the outline first.",
    ("build", "unknown_stage"):
        "The worker was handed a stage it doesn't know, so the build never "
        "started. Nothing was spent; this one is a bug worth reporting.",
    ("build", "worker_error"):
        "The worker stopped partway through the build. Finished materials "
        "were kept, so retrying continues rather than starts over.",
    ("build", "interrupted"):
        "The worker was shut down partway through the build. What it had "
        "already finished was kept — retry when you're ready and it carries "
        "on from there.",

    ("promote", "budget_exceeded"):
        "Promotion stopped against the stage budget before finishing — raise "
        "it in models.yaml, then retry. Your built course is untouched.",
    ("promote", "validation_failed"):
        "The finished course didn't pass its final checks, so it wasn't put "
        "in place. Nothing was lost; retrying runs the checks again.",
    ("promote", "compile_failed"):
        "The course wouldn't compile clean, so it was not published — this "
        "system never serves a course that doesn't compile. Retry to try again.",
    ("promote", "unapproved"):
        "Promotion ran without an approved outline behind it and stopped. "
        "Approve the outline, then let the build finish.",
    ("promote", "unknown_stage"):
        "The worker was handed a stage it doesn't know, so nothing was "
        "published. Your built course is safe; this one is worth reporting.",
    ("promote", "worker_error"):
        "The worker stopped while publishing your course. Nothing partial "
        "was left in place, so retrying is safe.",
    ("promote", "interrupted"):
        "The worker was shut down while publishing your course, so the "
        "course was left unpublished and nothing partial was put in place. "
        "Retry when you're ready.",
}

# The profile fields every factory prompt leans on (design §4, Stops 1–4).
# The rest may be empty — an empty field is an omitted line in the prompt,
# not filler — but a course generated against none of these is the product's
# thesis disproven on the learner's first day.
REQUIRED_PROFILE_FIELDS = ("background", "style", "pacing", "calibration")


def profile_gate_missing(profile_state: ProfileState) -> tuple[str, ...]:
    """Fields from REQUIRED_PROFILE_FIELDS with zero claims in the profile fold."""
    return tuple(f for f in REQUIRED_PROFILE_FIELDS
                 if not profile_state.field_claims(f))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class InvalidOnboardingEvent(ValueError):
    pass


def validate_event(kind: str, course: str, payload: dict) -> None:
    """Refuse anything underspecified — never default a missing piece.

    The payload shapes here are the wire contract between the wizard and the
    worker (both producers) and the screens (the consumer): a `reason` the
    wording table has never heard of, or an approval that forgot the estimate
    the learner was shown, is a row nothing downstream can honestly render.
    """
    if kind not in db.ONBOARDING_EVENT_KINDS:
        raise InvalidOnboardingEvent(f"unknown kind {kind!r}")
    if kind == "profile_published":
        if course != "":
            raise InvalidOnboardingEvent(
                "profile_published: course must be '' — publishing a profile "
                "happens before any course exists")
    elif not course:
        raise InvalidOnboardingEvent(f"{kind}: course is required")
    if not isinstance(payload, dict):
        raise InvalidOnboardingEvent(f"{kind}: payload must be an object")

    if kind in ("outline_failed", "build_failed", "promote_failed"):
        if payload.get("reason") not in REASONS:
            raise InvalidOnboardingEvent(
                f"{kind}: payload needs 'reason' in {REASONS}")
    elif kind == "outline_ready":
        if not isinstance(payload.get("plan"), dict):
            raise InvalidOnboardingEvent(f"{kind}: payload needs 'plan' (object)")
        if not isinstance(payload.get("estimate_usd"), str):
            raise InvalidOnboardingEvent(
                f"{kind}: payload needs 'estimate_usd' (string)")
    elif kind == "outline_approved":
        # O3: the approval row carries the number the learner was shown.
        if not isinstance(payload.get("estimate_usd"), str):
            raise InvalidOnboardingEvent(
                f"{kind}: payload needs 'estimate_usd' (string) — the estimate "
                "the learner approved")
    elif kind == "outline_rejected":
        note = payload.get("note")
        if not isinstance(note, str) or not note.strip():
            raise InvalidOnboardingEvent(f"{kind}: payload needs non-empty 'note'")
    elif kind == "promoted":
        if not isinstance(payload.get("course_id"), str):
            raise InvalidOnboardingEvent(f"{kind}: payload needs 'course_id' (string)")


def append_event(conn: sa.Connection, scope: db.TenantScope, kind: str,
                 course: str, payload: dict | None = None) -> None:
    payload = payload or {}
    validate_event(kind, course, payload)
    conn.execute(scope.onboarding_insert(kind=kind, course=course,
                                         payload=payload))


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------

@dataclass
class CourseFlow:
    """One course's trip through the wizard, as the ledger left it."""

    course_id: str
    stage: str                          # a STAGE_SEQUENCE member past "profile", or "done"
    status: str                         # "waiting" (your turn) | "pending" (a machine's) | "failed"
    reason: str | None = None           # a REASONS key, set only when status == "failed"
    scope: dict | None = None           # the scope_saved payload
    outline: dict | None = None         # latest outline_ready payload {plan, estimate_usd}
    approval: dict | None = None        # latest outline_approved payload
    note: str | None = None             # latest outline_rejected note
    updated_at: datetime | None = None  # the flow's last row's created_at — display only


@dataclass
class OnboardingState:
    profile_published: bool = False
    # flows is insertion-ordered by first sighting of the course, like every
    # other dict this house folds into — screens rely on it.
    flows: dict[str, CourseFlow] = field(default_factory=dict)

    def active(self) -> CourseFlow | None:
        """The newest flow still going. A promoted course is finished business."""
        live = [f for f in self.flows.values() if f.stage != "done"]
        return live[-1] if live else None

    def current_stop(self) -> str:
        """The stop the wizard shows — derived, never stored.

        A tenant who has promoted a course and started nothing new re-enters
        at Stop 6 (design §4, Stop 10): the profile stops never re-gate
        someone who has already published one.
        """
        if not self.profile_published:
            return "profile"
        flow = self.active()
        return flow.stage if flow is not None else "scope"


def _at(flow: CourseFlow, stage: str, status: str,
        reason: str | None = None) -> None:
    # reason belongs to a failure and to nothing else: any move off "failed"
    # clears it, so no screen can read a stale key beside a live stage.
    flow.stage, flow.status = stage, status
    flow.reason = reason if status == "failed" else None


def fold(events) -> OnboardingState:
    """events: iterable of (kind, course, payload, created_at), in ledger order.

    Ledger order means row id. `created_at` is carried through to the flow for
    display — "waiting since" — and takes part in no decision here.

    `promoted` is absorbing: once a course flow has reached "done", every
    later row for that course id is ignored. A promoted course is finished
    business, and a stale outcome from a run that was still in flight when it
    landed must not resurrect it.
    """
    st = OnboardingState()
    for kind, course, payload, created_at in events:
        payload = payload or {}
        if kind == "profile_published":
            st.profile_published = True
            continue
        flow = st.flows.get(course)
        if flow is None:
            # Ordinarily the first row for a course is its scope_saved; a
            # ledger that starts elsewhere still folds, because a fold reads
            # what happened rather than what should have.
            flow = st.flows[course] = CourseFlow(
                course_id=course, stage="outline", status="waiting")
        if flow.stage == "done":
            # Two runs queued by a double-clicked retry both report; the loser
            # reports second. Ledgers keep the row — the fold declines to act
            # on it, rather than the writer pretending it never arrived.
            continue
        if kind == "scope_saved":
            _at(flow, "outline", "waiting")
            flow.scope = payload
        elif kind == "outline_requested":
            _at(flow, "outline", "pending")
        elif kind == "outline_failed":
            _at(flow, "outline", "failed", payload.get("reason"))
        elif kind == "outline_ready":
            _at(flow, "outline_gate", "waiting")
            flow.outline = payload
        elif kind == "outline_rejected":
            # The gate stays where it is; the following outline_requested is
            # what moves the flow back to a machine's turn.
            flow.note = payload.get("note")
        elif kind == "outline_approved":
            _at(flow, "build", "waiting")
            flow.approval = payload
        elif kind == "build_requested":
            _at(flow, "build", "pending")
        elif kind == "build_failed":
            _at(flow, "build", "failed", payload.get("reason"))
        elif kind == "build_ready":
            # Straight to promote, pending: the worker enqueues it with no
            # human turn between (design §4 rejected a second gate).
            _at(flow, "promote", "pending")
        elif kind == "promote_requested":
            # The retry of a failed promotion — the only way a flow leaves
            # promote/failed, exactly as outline_requested and
            # build_requested are for their stages. Without it the wizard
            # would keep showing "failed" over a run that is already going.
            _at(flow, "promote", "pending")
        elif kind == "promote_failed":
            _at(flow, "promote", "failed", payload.get("reason"))
        elif kind == "promoted":
            _at(flow, "done", "waiting")
        flow.updated_at = created_at
    return st


def load_state(conn: sa.Connection, scope: db.TenantScope) -> OnboardingState:
    """The module's only I/O. Rows arrive in id order; the fold does the rest."""
    rows = conn.execute(scope.onboarding_select())
    return fold((r.kind, r.course, r.payload, r.created_at) for r in rows)
