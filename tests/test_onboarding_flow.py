"""The exit criterion, end to end: empty tenant to a served course.

onboarding-design.md's whole claim in one file — "browser only, terminal
never, from empty tenant to a phase-1-complete hub". Nothing here is stubbed
except the model: the wizard's real routes over a real `TestClient`, the real
worker claiming real queued rows out of the throwaway Postgres, the real
compiler as the gate at every stop it gates, and the real course tree written
to and moved around a temp directory that is the courses home for the length
of the class.

The one seam is `worker.RUNNER_FACTORY`, and it is the seam the whole design
put there: L1 says no model on a request path, so the stages that call one
run in the other process, and a scripted transport is what the other process
takes instead of a key. The transport is `curricle.scripted`'s own — the
same one `python -m curricle work --scripted` hands the worker — so this
walk is also the proof that the scripted worker reaches a served course. `llm._anthropic_send` is replaced by a tripwire for
the length of the walk, so a path that somehow reached the real transport
would fail this suite rather than reach the network.

The flow runs once, in `setUpClass`, because it is a flow: each step's
premise is the step before it, and seven independent tests re-walking it
would be seven copies of the same walk. The methods below assert against
what that walk recorded and against the database it left behind.
"""

import json
import os
import shutil
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

import sqlalchemy as sa

from curricle import (coursehome, db, factory, llm, onboarding, scripted,
                      webapp, wizard, worker)
from curricle.compiler import compile_course
from curricle.sidecar import load_sidecar

from pg import test_engine

# The roles a phase-1 build buys for a brand-new course, and the two the
# outline buys. Every one of them is a real contract under roles/ — the audit
# below asserts that every metered row names one, which is what makes "the
# fake runner's call log is the only spend" a claim about the ledger and not
# about the fake.
#
# `bank-author` is deliberately not among them: a bank section is appended to
# an existing question bank, a new course has none, so `default_build_plan`
# does not buy one and the estimate at the gate does not charge for one.
BUILD_ROLES = frozenset({"exercise-author", "lesson-writer", "quiz-author",
                         "widget-builder"})
OUTLINE_ROLES = frozenset({"curriculum-designer", "resource-curator"})

# The title the scope form is filled in with, and the id minting turns it
# into. Not the script's own name: the scripted designer answers under the
# id and title its prompt carries, and this walk is what proves it — the
# outline stage treats a sidecar declaring some other id as a compiler
# finding, and promotion refuses to publish a course into a directory that
# does not carry its name.
TITLE = "Manifests, gently"
COURSE_ID = "manifests-gently"

# One claim per required profile field, in the learner's own voice. The
# minimum the publish gate accepts, which is deliberately what this walks:
# the gate is a rule about coverage, not about length.
PROFILE_FORMS = {
    "1": {"new__background": "Eight years of backend services in Go and "
                             "Python, mostly over Postgres."},
    "2": {"new__style": "Learns by implementing — pair every abstract idea "
                        "with something runnable.",
          "new__pacing": "About four hours a week, as two evening sessions."},
    "3": {"new__calibration": "Open with the failure the idea prevents, show "
                              "it concretely, then name it formally."},
    "4": {"new__subject_adapters": "Whatever the subject, bridge from "
                                   "hands-on intuition to the formal idea."},
}

SCOPE_FORM = {
    "title": TITLE,
    "subject": "Course manifests",
    "mode": "subject",
    "hours_lo": "4",
    "hours_hi": "6",
    "cadence": "two weekday evenings",
    "done_looks_like": "I can write a sidecar that compiles and say what the "
                       "compiler refuses.",
    "out_of_scope": "writing a compiler of my own",
    "prior_exposure": "I have read one manifest and nothing else.",
}


def no_network(*args, **kwargs):
    raise AssertionError("this walk reached the real transport")


class OnboardingFlowTest(unittest.TestCase):
    """Design §4, Stops 0–10, walked once through the routes and the worker."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        cls.engine = test_engine()
        cls.tmp = tempfile.mkdtemp(prefix="curricle-flow-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        # The home the worker writes into comes from the environment and the
        # home the app serves comes from its argument: both are this temp
        # directory, and neither can be a real one for the length of the walk.
        cls.env = mock.patch.dict(os.environ, {coursehome.ENV_DIR: cls.tmp})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)

        cls.slug = "flow-tenant"
        with cls.engine.begin() as conn:
            cls.tenant = db.create_tenant(conn, cls.slug)
            # The queue is global by construction — the worker claims across
            # tenants — so whatever another module left queued is retired
            # before this walk drives the worker to idle.
            conn.execute(sa.update(db.factory_runs)
                         .where(db.factory_runs.c.status.in_(("queued",
                                                              "running")))
                         .values(status="done", finished_at=sa.func.now()))
        cls.scope = db.for_tenant(cls.tenant)
        cls.client = TestClient(webapp.create_app(
            [], tenant_slug=cls.slug, database_url=str(cls.engine.url),
            courses_dir=cls.tmp))
        cls.send = scripted.ScriptedSend()
        with mock.patch.object(llm, "_anthropic_send", no_network):
            cls.walk()

    # ---- the walk -------------------------------------------------------

    @classmethod
    def drain(cls, once: bool = False) -> None:
        """Run the worker to idle, with the scripted transport in its hand.

        `once` stops after a single claimed run, for the one place this walk
        has to see the disk between two stages: promotion deletes the phase's
        checkpoint manifest, and that manifest is the inventory the published
        course gets checked against.
        """
        with mock.patch.object(
                worker, "RUNNER_FACTORY",
                lambda engine, scope: llm.Runner(engine, scope, send=cls.send)):
            while worker.run_once(cls.engine):
                if once:
                    return

    @classmethod
    def walk(cls) -> None:
        c = cls.client
        # 1. An empty tenant is sent to the wizard from the front door.
        cls.first_visit = c.get("/", follow_redirects=False)

        # 2. The four profile screens, then publish.
        cls.saves = [c.post(f"/onboarding/profile/{number}", data=boxes,
                            follow_redirects=False)
                     for number, boxes in PROFILE_FORMS.items()]
        cls.published = c.post("/onboarding/profile/publish",
                               follow_redirects=False)

        # 3. The scope form, and the outline stage it queues.
        cls.scoped = c.post("/onboarding/scope", data=SCOPE_FORM,
                            follow_redirects=False)
        cls.drain()

        # 4. The gate, read and answered.
        cls.gate_page = c.get("/onboarding/").text
        cls.approved = c.post("/onboarding/outline/approve",
                              follow_redirects=False)

        # 5. The build, then the promotion chained behind it — claimed one
        #    run at a time so the phase's checkpoint can be read between
        #    them. It is the full inventory of what was bought, and
        #    promotion deletes it on its way through.
        cls.drain(once=True)
        with open(os.path.join(cls.tmp, COURSE_ID, worker.DRAFT_DIR, "learning",
                               "interactive", f".draft-{worker.PHASE_ID}",
                               "manifest.json"), encoding="utf-8") as f:
            cls.checkpoint = json.load(f)
        cls.drain()

        # 6. The course as a learner meets it, and the front door listing it.
        cls.hub = c.get(f"/c/{COURSE_ID}/index.html")
        cls.front_door = c.get("/", follow_redirects=False)
        cls.landing = c.get("/onboarding/").text

    # ---- what the walk left behind --------------------------------------

    def rows(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.onboarding_select()))

    def spend(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(
                sa.select(db.token_ledger)
                .where(db.token_ledger.c.tenant_id == self.tenant)
                .order_by(db.token_ledger.c.id)))

    def kinds(self) -> list[str]:
        return [r.kind for r in self.rows()]

    def payload(self, kind: str) -> dict:
        return next(r.payload for r in self.rows() if r.kind == kind)

    # ---- steps 1-6 ------------------------------------------------------

    def test_step_1_an_empty_tenant_is_sent_to_the_wizard(self):
        self.assertEqual(self.first_visit.status_code, 307)
        self.assertEqual(self.first_visit.headers["location"], "/onboarding/")

    def test_step_2_the_profile_forms_publish_in_the_learners_own_voice(self):
        for save in self.saves:
            self.assertEqual(save.status_code, 303, save.text)
        self.assertEqual(self.published.status_code, 303, self.published.text)
        # Position, never content: the onboarding ledger says publishing
        # happened and holds not one word of any claim.
        self.assertEqual(self.payload("profile_published"), {})
        with self.engine.begin() as conn:
            tiers = {r.payload.get("tier")
                     for r in conn.execute(self.scope.profile_select())}
        self.assertEqual(tiers, {"attested"})

    def test_step_3_the_scope_form_mints_the_id_and_queues_the_outline(self):
        self.assertEqual(self.scoped.status_code, 303, self.scoped.text)
        scope_saved = next(r for r in self.rows() if r.kind == "scope_saved")
        self.assertEqual(scope_saved.course, COURSE_ID)
        self.assertEqual(scope_saved.payload["title"], TITLE)
        self.assertIn("outline_ready", self.kinds())
        self.assertEqual(sorted(set(self.send.roles()) & OUTLINE_ROLES),
                         sorted(OUTLINE_ROLES))

    def test_step_4_the_gate_shows_the_outline_and_the_numbers(self):
        # Compiled off the draft on disk, not read back out of a row: the
        # course's own title and unit headings are on the page.
        self.assertIn(TITLE, self.gate_page)
        self.assertIn("Unit 1 — What a manifest is", self.gate_page)
        outline = self.payload("outline_ready")
        # Both numbers, both out of the payload the worker wrote: what the
        # build is expected to cost, and what these roles have left before
        # one of them refuses.
        self.assertIn(f"about ${outline['estimate_usd']}", self.gate_page)
        self.assertIn(f"${outline['headroom_usd']}", self.gate_page)
        # This account had bought nothing on the build roles before the
        # gate, so there is more left than the estimate needs and no
        # warning belongs on the page.
        self.assertNotIn(wizard.GATE_SHORT, self.gate_page)
        self.assertNotIn(wizard.GATE_NONE, self.gate_page)
        # And what has already been spent getting here, off the token ledger
        # — the one figure on this page that is a bill rather than a guess.
        drafting = sum((Decimal(r.cost_usd) for r in self.spend()
                        if r.stage in OUTLINE_ROLES), Decimal(0))
        self.assertIn(f"Drafting cost so far: ${drafting:.2f}.",
                      self.gate_page)
        self.assertEqual(self.approved.status_code, 303, self.approved.text)

    def test_step_4_the_headroom_covered_what_the_build_then_spent(self):
        # The figure is what these roles had left when the outline became
        # ready. This account was empty at that point, so it was the whole
        # of their budgets — and the walk then proves the figure was not a
        # decoration: what the build actually bought fits inside it, role by
        # role and in total.
        config = llm.load_models_config()
        plan = self.payload("outline_ready")["plan"]
        planned = {role for key, role in factory.PLAN_ROLES if plan.get(key)}
        self.assertEqual(planned, BUILD_ROLES)
        headroom = Decimal(self.payload("outline_ready")["headroom_usd"])
        self.assertEqual(headroom,
                         sum((config.budget_for_stage(role)
                              for role in planned), Decimal(0)))
        built = sum((Decimal(r.cost_usd) for r in self.spend()
                     if r.stage in BUILD_ROLES), Decimal(0))
        self.assertLess(built, headroom)

    def test_step_6_the_landing_prints_the_receipt(self):
        # The promise Stop 0 makes about money, made checkable: the total,
        # split at the approval, beside the estimate it was approved at. The
        # split is asserted against the roles rather than against the clock
        # the wizard windows by — two independent answers to "what did the
        # drafting cost", and they have to agree.
        spend = self.spend()
        drafting = sum((Decimal(r.cost_usd) for r in spend
                        if r.stage in OUTLINE_ROLES), Decimal(0))
        building = sum((Decimal(r.cost_usd) for r in spend
                        if r.stage in BUILD_ROLES), Decimal(0))
        def cents(amount: Decimal) -> Decimal:
            return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        self.assertIn(f"${cents(drafting):.2f} to draft", self.landing)
        self.assertIn(f"${cents(building):.2f} to build", self.landing)
        # The total is the two printed figures added, not the raw sum
        # rounded: a receipt whose own arithmetic does not check is worse
        # than no receipt.
        self.assertIn(f"<b>${cents(drafting) + cents(building):.2f}</b>",
                      self.landing)
        approved = self.payload("outline_approved")["estimate_usd"]
        self.assertIn(f"approved at about ${approved}", self.landing)

    def test_step_5_the_build_and_the_promotion_reach_promoted(self):
        self.assertEqual(self.kinds()[-1], "promoted")
        self.assertEqual(self.payload("promoted"), {"course_id": COURSE_ID})
        # The roles a phase-1 build buys for a new course, and no bank
        # section — the plan the learner approved did not name one, because
        # this course has no question bank for it to be appended to.
        self.assertEqual(sorted(set(self.send.roles()) & BUILD_ROLES),
                         sorted(BUILD_ROLES))
        self.assertNotIn("bank-author", self.send.roles())
        self.assertFalse(self.payload("outline_ready")["plan"]["bank"])
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, COURSE_ID, worker.DRAFT_DIR)))
        with self.engine.begin() as conn:
            runs = [(r.stage, r.status, r.reason) for r in conn.execute(
                sa.select(db.factory_runs)
                .where(db.factory_runs.c.tenant_id == self.tenant)
                .order_by(db.factory_runs.c.id))]
        self.assertEqual(runs, [("outline", "done", None),
                                ("build", "done", None),
                                ("promote", "done", None)])

    def test_step_5_every_artifact_the_phase_bought_is_in_the_course(self):
        # The inventory, whole, checked against the checkpoint rather than
        # against paths this test happens to know: promotion moves what the
        # phase bought, all of it, and registers each material in the
        # sidecar the compile then reads back. A promotion that moved the
        # lesson and forgot the rest passes every other step here.
        root = os.path.join(self.tmp, COURSE_ID)
        sidecar_path = os.path.join(root, *coursehome.SIDECAR_NAMES[0].split(os.sep))
        manifest, issues = compile_course(root, load_sidecar(sidecar_path))
        self.assertIsNotNone(manifest, [str(i) for i in issues])
        material_ids = {m.id for m in manifest.materials}

        artifacts = self.checkpoint["artifacts"]
        self.assertEqual(len(artifacts), len(BUILD_ROLES))
        for artifact in artifacts:
            with self.subTest(artifact=artifact["rel_path"] or artifact["note"]):
                self.assertTrue(artifact["rel_path"])   # no bank in this plan
                self.assertTrue(os.path.exists(
                    os.path.join(root, "learning", artifact["rel_path"])))
                self.assertIn(artifact["material"]["id"], material_ids)

    def test_step_6_the_course_is_served_and_the_front_door_lists_it(self):
        # Registration is the pull path: nothing called into this process,
        # and the course was picked up off the filesystem by the routes.
        self.assertEqual(self.hub.status_code, 200, self.hub.text)
        self.assertIn(TITLE, self.hub.text)
        self.assertEqual(self.front_door.status_code, 200,
                         self.front_door.text)
        self.assertIn(f'href="/c/{COURSE_ID}/"', self.front_door.text)

    def test_step_6_the_landing_card_offers_the_two_onward_paths(self):
        self.assertIn(f'href="/c/{COURSE_ID}/index.html"', self.landing)
        block = self.landing.split('<pre class="snippet">')[1].split("</pre>")[0]
        self.assertIn(self.slug, block)
        self.assertIn(os.path.join(self.tmp, COURSE_ID), block)

    # ---- step 7: the exit criterion --------------------------------------

    def test_the_exit_criterion_holds_end_to_end(self):
        """O3, L2 and the budgets, audited over the walk's own ledgers.

        Three claims, and each of them is falsifiable against rows rather
        than against anything this test arranged. Every metered call names a
        role that has a contract on disk (L2 — there is one path to a model
        and it labels its spend). The learner's approval is upstream in the
        onboarding ledger of every build-stage spend and carries the number
        they were shown (O3 — no token is spent without a row recording the
        approval and the estimate). And no stage went past its configured
        ceiling, which is the promise Stop 0 makes in those words.
        """
        spend = self.spend()
        self.assertTrue(spend)
        config = llm.load_models_config()

        # L2: every row is a real role contract, and there are exactly as
        # many rows as the scripted transport was asked for calls — so the
        # ledger records this walk's spend and no other.
        for row in spend:
            with self.subTest(stage=row.stage):
                self.assertTrue(os.path.isfile(
                    os.path.join(llm.roles_dir(), f"{row.stage}.md")))
        self.assertEqual(len(spend), len(self.send.calls))
        self.assertEqual(set(r.stage for r in spend),
                         BUILD_ROLES | OUTLINE_ROLES)

        # O3, by ledger order and by wall clock: the approval is a row above
        # `build_ready` in the onboarding ledger, and it committed before the
        # first token the build stage spent.
        rows = self.rows()
        approval = next(r for r in rows if r.kind == "outline_approved")
        ready = next(r for r in rows if r.kind == "build_ready")
        self.assertLess(approval.id, ready.id)
        first_build_spend = min(r.created_at for r in spend
                                if r.stage in BUILD_ROLES)
        self.assertLess(approval.created_at, first_build_spend)

        # And it carries the numbers that were on the screen, byte for byte
        # — the approval echoes `outline_ready`'s own payload rather than
        # reading figures off a form. Both of them: the learner was shown
        # what the build is expected to cost and what was left before it
        # refuses, and a row echoing half of that is half a record of the
        # decision.
        outline = next(r for r in rows if r.kind == "outline_ready")
        for number in ("estimate_usd", "headroom_usd"):
            with self.subTest(number=number):
                self.assertEqual(approval.payload[number],
                                 outline.payload[number])
                self.assertIn(f"${outline.payload[number]}", self.gate_page)
        self.assertEqual(approval.payload["plan"], outline.payload["plan"])
        self.assertIn(f"about ${outline.payload['estimate_usd']}",
                      self.gate_page)

        # Per-stage budget compliance: each stage's summed cost is inside the
        # ceiling models.yaml configures for it.
        for stage in sorted(set(r.stage for r in spend)):
            with self.subTest(stage=stage):
                total = sum((Decimal(r.cost_usd) for r in spend
                             if r.stage == stage), Decimal(0))
                self.assertLessEqual(total, config.budget_for_stage(stage))

    def test_the_whole_walk_issued_no_network_call(self):
        # The scripted transport's log is the only spend there was: seven
        # calls answered here, seven rows metered, and the real transport
        # replaced by a tripwire that would have failed the class in
        # `setUpClass` had anything reached it.
        self.assertEqual(sorted(self.send.roles()),
                         sorted(BUILD_ROLES | OUTLINE_ROLES))
        spend = self.spend()
        self.assertEqual(len(spend), len(self.send.calls))
        # And every one of those rows names a model from the one file that
        # is allowed to name one, which is what makes them rows about calls
        # that went through the metered path rather than around it.
        self.assertLessEqual({r.model for r in spend},
                             set(llm.load_models_config().tiers.values()))


if __name__ == "__main__":
    unittest.main()
