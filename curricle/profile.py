"""The profile engine: evidence claims, review discipline, a pure fold.

The learner profile is not a document anyone edits — it is a fold over an
append-only evidence ledger, and the skill file everyone reads is a
projection of the fold (profilerender.render_skill_md). Three rules:

- **Tiers come from provenance, not confidence** (job-radar's evidence_tier):
  `demonstrated` — course activity proved it (a checkpoint passed, an
  exercise green); `attested` — the learner said it, or it came from a
  document they authored; `thin` — something else claims it (a syllabus,
  an inference) and nothing corroborates yet.
- **The agent proposes, the human publishes.** An `assert` (the learner's
  own voice) is accepted on arrival. A `propose` — anything the system
  believes about the learner — renders nowhere until an `accept`.
- **Claims have identity.** (field, key) names a claim; a later assert or
  accepted proposal on the same identity supersedes, a `retract` removes.
  Keys are forever, like every other id in this system.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

import sqlalchemy as sa

from . import db
from .schema import Manifest

# Profile sections. Grow this tuple deliberately — renderers know them.
FIELDS = (
    "meta",             # the skill's own frontmatter description
    "background",       # professional history, treated as bridging assets
    "education",        # formal education, positive and negative space
    "tracks",           # prior self-directed courses
    "style",            # learning-style bullets
    "domain_bias",      # exercise domains that land
    "pacing",           # the sizing constant
    "calibration",      # response-calibration procedure blocks
    "skip",             # do-not-scaffold list
    "scaffold",         # build-from-zero list
    "subject_adapters", # how the profile translates across subject classes
    "demonstrated",     # evidence accumulated from course activity
)

TIERS = ("attested", "demonstrated", "thin")


class InvalidProfileEvent(ValueError):
    pass


def validate_profile_event(kind: str, field: str, key: str, payload: dict) -> None:
    if kind not in db.PROFILE_EVENT_KINDS:
        raise InvalidProfileEvent(f"unknown kind {kind!r}")
    if field not in FIELDS:
        raise InvalidProfileEvent(f"unknown field {field!r}")
    if not key:
        raise InvalidProfileEvent("key is required")
    if kind in ("assert", "propose"):
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise InvalidProfileEvent(f"{kind}: payload needs non-empty 'text'")
        tier = payload.get("tier")
        if tier not in TIERS:
            raise InvalidProfileEvent(f"{kind}: payload needs tier in {TIERS}")


def append_profile_event(conn: sa.Connection, scope: db.TenantScope,
                         kind: str, field: str, key: str,
                         payload: dict | None = None) -> None:
    payload = payload or {}
    validate_profile_event(kind, field, key, payload)
    conn.execute(scope.profile_insert(kind=kind, field=field, key=key,
                                      payload=payload))


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------

@dataclass
class Claim:
    field: str
    key: str
    text: str
    tier: str
    source: str | None = None


@dataclass
class Proposal(Claim):
    supersedes: bool = False    # an accepted claim with this identity exists


@dataclass
class ProfileState:
    # claims[field] is insertion-ordered {key: Claim} — renderers rely on it.
    claims: dict[str, dict[str, Claim]] = dc_field(default_factory=dict)
    pending: list[Proposal] = dc_field(default_factory=list)

    def claim(self, field: str, key: str) -> Claim | None:
        return self.claims.get(field, {}).get(key)

    def field_claims(self, field: str) -> list[Claim]:
        return list(self.claims.get(field, {}).values())


def fold(events) -> ProfileState:
    """events: iterable of (kind, field, key, payload), in ledger order."""
    st = ProfileState()
    pending: dict[tuple[str, str], Proposal] = {}   # latest proposal per identity

    def put(field: str, key: str, payload: dict) -> None:
        st.claims.setdefault(field, {})[key] = Claim(
            field=field, key=key, text=payload["text"], tier=payload["tier"],
            source=payload.get("source"))

    for kind, field, key, payload in events:
        ident = (field, key)
        if kind == "assert":
            put(field, key, payload)
            pending.pop(ident, None)
        elif kind == "propose":
            pending[ident] = Proposal(
                field=field, key=key, text=payload["text"],
                tier=payload["tier"], source=payload.get("source"),
                supersedes=st.claim(field, key) is not None)
        elif kind == "accept":
            proposal = pending.pop(ident, None)
            if proposal is not None:
                st.claims.setdefault(field, {})[key] = Claim(
                    field=field, key=key, text=proposal.text,
                    tier=proposal.tier, source=proposal.source)
        elif kind == "reject":
            pending.pop(ident, None)
        elif kind == "retract":
            st.claims.get(field, {}).pop(key, None)
            pending.pop(ident, None)
    st.pending = list(pending.values())
    return st


def load_profile(conn: sa.Connection, scope: db.TenantScope) -> ProfileState:
    rows = conn.execute(scope.profile_select())
    return fold((r.kind, r.field, r.key, r.payload) for r in rows)


# ---------------------------------------------------------------------------
# Evidence producers
# ---------------------------------------------------------------------------

def propose_from_checkpoint(conn: sa.Connection, scope: db.TenantScope,
                            manifest: Manifest, material_id: str,
                            payload: dict) -> None:
    """A checkpoint_result progress event becomes proposed `demonstrated`
    evidence — the misses matter as much as the score. Proposed, never
    asserted: the learner ratifies what the record says about them."""
    material = next((m for m in manifest.materials if m.id == material_id), None)
    title = material.title if material else material_id
    score, total = payload.get("score"), payload.get("total")
    misses = payload.get("misses") or []
    text = (f"{manifest.course.title} — **{title}**: {score}/{total}")
    if misses:
        text += " · missed: " + "; ".join(str(m) for m in misses)
    append_profile_event(
        conn, scope, "propose", "demonstrated",
        key=f"{manifest.course.id}--{material_id}",
        payload={"text": text, "tier": "demonstrated",
                 "source": f"{manifest.course.id}/{material_id}"})


def import_seed(conn: sa.Connection, scope: db.TenantScope,
                claims: list[dict]) -> int:
    """Seed the ledger from a structured document — the one-time act that
    turns a hand-authored profile into evidence. Everything arrives as
    `assert`: the seed is the learner's own document, in their own voice."""
    n = 0
    for c in claims:
        append_profile_event(
            conn, scope, "assert", c["field"], c["key"],
            payload={"text": c["text"], "tier": c.get("tier", "attested"),
                     "source": c.get("source")})
        n += 1
    return n
