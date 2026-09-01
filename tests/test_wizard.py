"""The wizard shell: the gate, the derived screen, and the two invariants.

Everything here runs against the throwaway Postgres of tests/pg.py through
a real `TestClient`, because all three things worth testing are properties
of the running app rather than of a function: a redirect decided by two
queries, a screen chosen by the fold, and a failure sentence that reached a
page from a wording table instead of from an exception.

Two tenants per fixture (T5): an app is built per tenant, so a screen drawn
for one of them can never be a screen drawn from the other's ledger.
"""

import dataclasses
import html
import os
import re
import shutil
import tempfile
import unittest

import sqlalchemy as sa

from curricle import db, onboarding, profile, profilerender, webapp, wizard

from pg import test_engine
# The draft trees the gate screen compiles are planted with the courses
# home's own fixture — including its `broken=` switch, which is what an
# uncompilable draft looks like everywhere else in this suite.
from test_coursesdir import plant
# The lock a live worker holds, taken here by a detached session so the
# welcome banner can be tested in both of its states.
from test_worker import session

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TINYLANG = os.path.join(REPO_ROOT, "examples", "tinylang")


def client(engine, slug: str, roots: list[str] | None = None,
           courses_dir: str | None = None):
    """A test client for a fresh tenant, serving `roots` (usually none)."""
    from fastapi.testclient import TestClient

    with engine.begin() as conn:
        db.create_tenant(conn, slug)
    return TestClient(webapp.create_app(roots or [], tenant_slug=slug,
                                        database_url=str(engine.url),
                                        courses_dir=courses_dir))


class WizardFixture(unittest.TestCase):
    """One courseless tenant with an app in front of it. No tests of its own."""

    ROOTS: list[str] = []
    COURSES_DIR: str | None = None

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        cls.slug = f"wizard-{cls.__name__}"
        cls.client = client(cls.engine, cls.slug, cls.ROOTS, cls.COURSES_DIR)
        with cls.engine.begin() as conn:
            cls.tenant = db.tenant_id_for(conn, cls.slug)
        cls.scope = db.for_tenant(cls.tenant)

    def append(self, kind: str, course: str = "", payload: dict | None = None):
        with self.engine.begin() as conn:
            onboarding.append_event(conn, self.scope, kind, course, payload)

    def screen(self, query: str = "") -> str:
        page = self.client.get(f"/onboarding/{query}")
        self.assertEqual(page.status_code, 200, page.text)
        return page.text

    def save(self, number: str, boxes: dict[str, str]):
        """POST one profile form screen. The redirect is a fact under test,
        so it is never followed here."""
        return self.client.post(f"/onboarding/profile/{number}", data=boxes,
                                follow_redirects=False)

    def profile_rows(self) -> list:
        """The tenant's profile ledger, whole — the fold is not the record."""
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.profile_select()))

    def profile_state(self) -> profile.ProfileState:
        with self.engine.begin() as conn:
            return profile.load_profile(conn, self.scope)

    def onboarding_rows(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.onboarding_select()))

    def current_stop(self) -> str:
        with self.engine.begin() as conn:
            return onboarding.load_state(conn, self.scope).current_stop()

    def satisfy_the_gate(self):
        """A claim in each of the four required fields, through the forms.

        Written by posting the screens rather than by inserting rows: what
        the gate is asked about is the profile fold a learner could actually
        have produced here.
        """
        self.save("1", {"new__background": "Eight years of backend work."})
        self.save("2", {"new__style": "Learns by implementing: pair every "
                                      "idea with something runnable.",
                        "new__pacing": "Four hours a week, two evenings."})
        self.save("3", {"new__calibration": "The failure it prevents first, "
                                            "then the formal statement."})


class GuardTest(unittest.TestCase):
    def test_the_wizard_never_reaches_the_model(self):
        # Belt to test_frontdoor's suspenders, kept in the wizard's own suite
        # so the file's honesty fails in the file's own tests. L1: no model
        # on a request path, ever — the wizard writes request rows and reads
        # outcome rows, and the worker does the rest.
        with open(wizard.__file__, encoding="utf-8") as f:
            source = f.read()
        for forbidden in ("llm", "factory"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class GateTest(WizardFixture):
    """Design §4: the empty tenant meets the wizard, from every route."""

    def test_the_front_door_redirects_to_the_wizard(self):
        page = self.client.get("/", follow_redirects=False)
        self.assertEqual(page.status_code, 307)
        self.assertEqual(page.headers["location"], "/onboarding/")

    def test_the_wizard_itself_is_never_gated(self):
        self.assertEqual(self.client.get("/onboarding/",
                                         follow_redirects=False).status_code, 200)

    def test_the_profile_surface_stays_reachable(self):
        # No state of your account is a state where your data is hostage.
        page = self.client.get("/profile", follow_redirects=False)
        self.assertEqual(page.status_code, 200, page.text)
        post = self.client.post("/api/profile/events", follow_redirects=False,
                                json={"kind": "assert", "field": "pacing",
                                      "key": "pacing-01",
                                      "payload": {"text": "one unit a week",
                                                  "tier": "attested"}})
        self.assertEqual(post.status_code, 200, post.text)


class PublishedProfileGateTest(WizardFixture):
    """The row is the whole difference — its own tenant, because it is a
    one-way change to the fixture's ledger."""

    def test_publishing_a_profile_stops_the_redirect(self):
        # The gate reads the fold: no cookie, no restart, no second place
        # the answer is kept.
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code,
                         307)
        self.append("profile_published")
        page = self.client.get("/", follow_redirects=False)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("No courses are configured yet", page.text)


class CourseTenantGateTest(WizardFixture):
    """A tenant with a course configured is never gated — corpus users."""

    ROOTS = [TINYLANG]

    def test_a_configured_course_exempts_the_tenant(self):
        page = self.client.get("/", follow_redirects=False)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('href="/c/tinylang/"', page.text)
        # And the wizard is still there for them, unasked-for but reachable.
        self.assertIn("What this never does", self.screen())


class ScreenDispatchTest(WizardFixture):
    """O1: the screen is a function of the fold, never of navigation."""

    def test_no_events_lands_on_the_welcome_screen(self):
        page = self.screen()
        self.assertIn("Let us build you a course.", page)
        self.assertIn("Step 1 of 6", page)

    def test_the_profile_sub_screens_are_open_at_the_profile_stop(self):
        # O1 in its permissive half: every screen the fold has opened is
        # reachable by navigation, and at the profile stop that is all six.
        for screen in wizard.SCREEN_ORDER:
            with self.subTest(screen=screen):
                self.assertEqual(
                    self.client.get(f"/onboarding/?screen={screen}").status_code,
                    200)
        self.assertIn("Read it back before you publish",
                      self.screen("?screen=review"))
        self.assertIn("Profile screen 3 of 4", self.screen("?screen=3"))

    def test_a_stop_beyond_the_fold_is_unreachable(self):
        # O1 in its strict half: with the fold at "profile", no navigation
        # reaches a later stop's screen. A screen the vocabulary does not
        # know is sent back to the fold's own screen, at the fold's own URL.
        with self.engine.begin() as conn:
            state = onboarding.load_state(conn, self.scope)
        self.assertEqual(state.current_stop(), "profile")
        for query in ("?screen=scope", "?screen=outline_gate", "?screen=7"):
            with self.subTest(query=query):
                page = self.client.get(f"/onboarding/{query}",
                                       follow_redirects=False)
                self.assertEqual(page.status_code, 307)
                self.assertEqual(page.headers["location"], "/onboarding/")
        self.assertNotIn(wizard.STOP_TITLES["scope"], self.screen("?screen=scope"))
        self.assertEqual(self.screen("?screen=scope"), self.screen())


class DefaultScreenTest(WizardFixture):
    """F10: a bare `/onboarding/` opens where the learner left off.

    The footer promises you can close the tab and pick up where you left
    off, and every redirect in this module lands on `/onboarding/` with
    nothing after it, so `default_screen` is the whole of whether that
    sentence is true. It used to answer "welcome" always, which made the
    promise false on five of the profile stop's six screens.

    One method rather than three, because the three cases are one profile
    growing: an empty one, one with the first gate field answered, and one
    with all four.
    """

    def test_a_url_with_no_screen_resolves_from_the_fold(self):
        # Nothing said yet, so there is nowhere to be resumed to.
        self.assertEqual(wizard.default_screen(self.profile_state()),
                         "welcome")
        self.assertIn("Let us build you a course.", self.screen())

        # Screen 1's gate field is answered; screen 2 is now the first
        # screen still carrying one that is not.
        self.save("1", {"new__background": "Nine years of backend work."})
        self.assertEqual(wizard.default_screen(self.profile_state()), "2")
        self.assertIn("Profile screen 2 of 4", self.screen())

        # Every gate field answered: what is left to come back to is the
        # read-back, which is the screen the publish button is on.
        self.save("2", {"new__style": "Learns by implementing.",
                        "new__pacing": "Four hours a week, two evenings."})
        self.save("3", {"new__calibration": "The failure it prevents first."})
        self.assertEqual(
            onboarding.profile_gate_missing(self.profile_state()), ())
        self.assertEqual(wizard.default_screen(self.profile_state()), "review")
        self.assertIn("Read it back before you publish", self.screen())


class ExplicitScreenOutranksTheDefaultTest(WizardFixture):
    """The default answers a URL that names no screen, and nothing else.

    Its own tenant, because it needs a profile that has been started and the
    case above needs one that has not.
    """

    def test_a_named_screen_is_still_the_screen_that_is_drawn(self):
        self.save("1", {"new__background": "Nine years of backend work."})
        self.assertEqual(wizard.default_screen(self.profile_state()), "2")
        self.assertIn("Let us build you a course.",
                      self.screen("?screen=welcome"))
        self.assertIn("Profile screen 4 of 4", self.screen("?screen=4"))
        self.assertIn("Read it back before you publish",
                      self.screen("?screen=review"))


class ScreenIsIgnoredPastTheProfileTest(WizardFixture):
    """O1's strictest reading, on its own tenant because the fold moves on.

    The sub-screens are navigation *within* the profile stop. Once the fold
    is past it, `?screen=` names nothing: a known value — `review`, a profile
    form — is as inert as an unknown one, because the alternative is a
    profile form drawn over a course build already running.
    """

    def test_a_known_screen_value_does_not_survive_the_profile_stop(self):
        self.append("profile_published")
        self.append("scope_saved", "greek-104", {"topic": "koine"})
        self.append("outline_requested", "greek-104")
        for query in ("?screen=review", "?screen=2", "?screen=welcome"):
            with self.subTest(query=query):
                page = self.screen(query)
                self.assertIn(wizard.PENDING_WORD, page)
                self.assertIn(wizard.STOP_TITLES["outline"], page)
                self.assertNotIn("Read it back before you publish", page)
                self.assertNotIn("Profile screen", page)
                self.assertNotIn("Let us build you a course.", page)


class WelcomeCopyTest(WizardFixture):
    """Stop 0 states what it never does, above the ask — and says so first."""

    def test_the_three_never_promises_are_on_the_page(self):
        page = self.screen()
        self.assertEqual(len(wizard.NEVER_PROMISES), 3)
        for promise in wizard.NEVER_PROMISES:
            self.assertIn(promise, page)
        # Above the ask, not in a footer.
        self.assertLess(page.index(wizard.NEVER_PROMISES[0]),
                        page.index("Begin →"))

    def test_the_worker_banner_says_so_before_the_first_form(self):
        page = self.screen()
        self.assertIn("python -m curricle work", page)
        self.assertIn("is not running", page)
        self.assertLess(page.index("Start the worker before you begin"),
                        page.index("Begin →"))
        # Mark and word, always both: the chip carries an alert mark, and it
        # also says, in words, which state it is in.
        self.assertIn(f'<span class="chip warn state">{wizard._ALERT}'
                      f'{wizard.WORKER_WORD}</span>', page)

    def test_the_banner_goes_away_when_a_worker_holds_the_lock(self):
        with session(self.engine) as holder:
            self.assertTrue(db.try_worker_lock(holder))
            page = self.screen()
        self.assertNotIn("Start the worker before you begin", page)
        self.assertNotIn("python -m curricle work", page)
        self.assertIn("Begin →", page)


class PendingPlaceholderTest(WizardFixture):
    """A machine's turn: the word, the elapsed time, and the refresh tag."""

    def test_pending_shows_the_word_the_elapsed_time_and_the_refresh(self):
        self.append("profile_published")
        self.append("scope_saved", "greek-101", {"topic": "koine"})
        self.append("outline_requested", "greek-101")
        page = self.screen()
        self.assertIn(wizard.PENDING_WORD, page)
        # Elapsed, never a forecast — and under a minute in words, because
        # a figure in seconds is precision this screen cannot keep.
        self.assertIn("less than a minute elapsed", page)
        self.assertIn(wizard.META_REFRESH, page)
        self.assertIn(wizard.STOP_TITLES["outline"], page)
        self.assertNotIn(wizard.WAITING_WORD, page)


class FailedPlaceholderTest(WizardFixture):
    """A failure arrives as a reason key and leaves as a sentence (O2)."""

    def test_failed_prints_the_wording_and_never_the_exception(self):
        # O2: every (worker stage, reason) has a sentence, and the exception
        # text stays in the row's detail for an operator reading the ledger.
        self.append("profile_published")
        self.append("scope_saved", "greek-102", {"topic": "attic"})
        self.append("outline_requested", "greek-102")
        self.append("outline_failed", "greek-102",
                    {"reason": "compile_failed",
                     "detail": "SchemaError: unknown key 'phazes' at course.phases"})
        page = self.screen()
        self.assertIn(onboarding.WORDING[("outline", "compile_failed")], page)
        self.assertIn(wizard.FAILED_WORD, page)
        for leak in ("SchemaError", "phazes", "Traceback", "compile_failed"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, page)
        # Polling stops on its own: a screen that is not pending does not ask
        # the browser to come back, and shows no duration either.
        self.assertNotIn(wizard.META_REFRESH, page)
        self.assertNotIn('class="elapsed"', page)


class ScopeCopyTest(unittest.TestCase):
    """Stop 6's vocabulary, pinned to the manifest's own."""

    def test_the_modes_are_the_manifests_modes_each_with_a_sentence(self):
        # The radio group writes the string a sidecar will later declare, so
        # a fourth mode in the schema (or a renamed one) has to arrive on
        # this form rather than being silently unofferable.
        from curricle import schema

        self.assertEqual(tuple(value for value, _, _ in wizard.MODE_COPY),
                         schema.COURSE_MODES)
        for _, name, sentence in wizard.MODE_COPY:
            with self.subTest(name=name):
                self.assertTrue(name.strip())
                self.assertTrue(sentence.strip().endswith("."))

    def test_every_asked_field_has_a_label_and_a_line(self):
        for name, (label, explain) in wizard.SCOPE_LABELS.items():
            with self.subTest(field=name):
                self.assertTrue(label.strip())
                self.assertTrue(explain.strip())


class ScopeFormTest(WizardFixture):
    """The form itself: the wire contract, and the three sentences."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            onboarding.append_event(conn, cls.scope, "profile_published", "")

    def test_the_scope_stop_draws_a_form_and_not_a_placeholder(self):
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["scope"], page)
        self.assertIn('action="/onboarding/scope"', page)
        self.assertIn(wizard.SCOPE_LEDE, page)
        self.assertNotIn("This screen is still being built", page)
        # A form is your turn, and nothing on it is waiting on a machine.
        self.assertNotIn(wizard.META_REFRESH, page)

    def test_every_input_the_post_reads_is_on_the_page(self):
        # The wire contract, both directions: the names below are what the
        # POST looks for, so a renamed box would be a field silently never
        # answered.
        page = self.screen()
        for name in ("title", "subject", "hours_lo", "hours_hi", "cadence",
                     "done_looks_like", "out_of_scope", "prior_exposure"):
            with self.subTest(name=name):
                self.assertIn(f'name="{name}"', page)

    def test_each_mode_is_offered_with_its_own_sentence(self):
        page = self.screen()
        for value, name, sentence in wizard.MODE_COPY:
            with self.subTest(mode=value):
                self.assertIn(f'name="mode" value="{value}"', page)
                self.assertIn(name, page)
                self.assertIn(sentence, page)


class ScopeSaveTest(WizardFixture):
    """Saving the scope: three rows, one transaction, no human turn after.

    Its own tenant, because saving a scope is a one-way move of this
    fixture's ledger.
    """

    FORM = {
        "title": "Koine Greek, from the papyri",
        "subject": "Reading documentary papyri of the Roman period",
        "mode": "subject",
        "hours_lo": "4",
        "hours_hi": "6",
        "cadence": "two weekday evenings",
        "done_looks_like": "I can read a documentary papyrus with a lexicon.",
        "out_of_scope": "classical Attic prose\n\nwriting my own grammar\n",
        "prior_exposure": "One year of Attic, ten years ago.",
    }

    def pending_runs(self, course: str) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.runs_pending(course)))

    def test_a_saved_scope_is_a_course_a_request_and_a_queued_run(self):
        self.append("profile_published")
        saved = self.client.post("/onboarding/scope", data=self.FORM,
                                 follow_redirects=False)
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertEqual(saved.headers["location"], "/onboarding/")

        rows = [r for r in self.onboarding_rows()
                if r.kind != "profile_published"]
        self.assertEqual([r.kind for r in rows],
                         ["scope_saved", "outline_requested"])
        # The id is minted from the title and is also the directory the draft
        # will be written into — one string, by construction.
        course = "koine-greek-from-the-papyri"
        self.assertEqual({r.course for r in rows}, {course})
        # The payload shape is a wire contract with the gate screen and with
        # the worker, so it is asserted whole rather than key by key.
        self.assertEqual(rows[0].payload, {
            "title": "Koine Greek, from the papyri",
            "subject": "Reading documentary papyri of the Roman period",
            "mode": "subject",
            "hours_per_week": [4, 6],
            "cadence": "two weekday evenings",
            "done_looks_like": "I can read a documentary papyrus with a "
                               "lexicon.",
            "out_of_scope": ["classical Attic prose",
                             "writing my own grammar"],
            "prior_exposure": "One year of Attic, ten years ago.",
        })
        self.assertEqual(rows[1].payload, {})

        # And the run the second process will claim: written in the same
        # transaction, because there is no human turn between the two stops.
        queued = self.pending_runs(course)
        self.assertEqual([(r.stage, r.status) for r in queued],
                         [("outline", "queued")])
        self.assertIsNone(queued[0].claimed_at)

        # The fold has moved on by itself: what /onboarding/ draws now is a
        # machine's turn, and the form is gone.
        self.assertEqual(self.current_stop(), "outline")
        page = self.screen()
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertNotIn('action="/onboarding/scope"', page)


class ScopeBeforeTheProfileTest(WizardFixture):
    """O1 for a write, from the other side: the stop is not open yet."""

    def test_a_scope_posted_before_publishing_is_refused_and_writes_nothing(self):
        refused = self.client.post("/onboarding/scope",
                                   data=ScopeSaveTest.FORM,
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.onboarding_rows(), [])
        self.assertEqual(self.current_stop(), "profile")


class ScopePastTheStopTest(WizardFixture):
    """O1 for a write, from the near side: the stop is open no longer.

    A published profile is not what opens this form — the *fold's stop* is.
    A tenant whose outline is already being drafted has published a profile
    too, and a second scope from a stale tab would start a second course
    under the first one and queue a run nobody watching this page asked for.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, course, payload in (
                    ("profile_published", "", {}),
                    ("scope_saved", "greek-106", {"title": "Greek"}),
                    ("outline_requested", "greek-106", {})):
                onboarding.append_event(conn, cls.scope, kind, course, payload)

    def test_a_second_scope_from_a_stale_tab_is_refused(self):
        before = len(self.onboarding_rows())
        self.assertEqual(self.current_stop(), "outline")
        refused = self.client.post("/onboarding/scope",
                                   data=ScopeSaveTest.FORM,
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(len(self.onboarding_rows()), before)
        with self.engine.begin() as conn:
            self.assertEqual(
                list(conn.execute(sa.select(db.factory_runs.c.id)
                                  .where(db.factory_runs.c.tenant_id
                                         == self.tenant))), [])
        # And the fold is where it was: the stale post moved nothing.
        self.assertEqual(self.current_stop(), "outline")


class ScopeRefusalTest(WizardFixture):
    """Refuse rather than guess — and refuse without leaving half a course."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            onboarding.append_event(conn, cls.scope, "profile_published", "")

    def post(self, **changes):
        form = dict(ScopeSaveTest.FORM, **changes)
        return self.client.post("/onboarding/scope", data=form,
                                follow_redirects=False)

    def scope_rows(self) -> list:
        return [r for r in self.onboarding_rows()
                if r.kind != "profile_published"]

    def queued(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(
                sa.select(db.factory_runs.c.id)
                .where(db.factory_runs.c.tenant_id == self.tenant)))

    def test_a_missing_required_field_names_it_and_writes_nothing(self):
        # The whole save is one transaction, so a refusal anywhere in it
        # leaves neither a scoped course nor a run nobody asked for.
        refused = self.post(title="")
        self.assertEqual(refused.status_code, 422)
        self.assertIn(wizard.SCOPE_LABELS["title"][0], refused.text)
        self.assertEqual(self.scope_rows(), [])
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.current_stop(), "scope")

    def test_every_other_refusal_names_its_box_too(self):
        for changes, expected in (
                ({"subject": " "}, wizard.SCOPE_LABELS["subject"][0]),
                ({"done_looks_like": ""},
                 wizard.SCOPE_LABELS["done_looks_like"][0]),
                ({"mode": "vibes"}, wizard.SCOPE_LABELS["mode"][0]),
                ({"hours_lo": "several"}, "whole number"),
                ({"hours_lo": "0"}, "at least one"),
                ({"hours_lo": "9", "hours_hi": "2"}, "below the low end")):
            with self.subTest(changes=changes):
                refused = self.post(**changes)
                self.assertEqual(refused.status_code, 422, refused.text)
                self.assertIn(expected, refused.text)
        self.assertEqual(self.scope_rows(), [])
        self.assertEqual(self.queued(), [])

    def test_a_body_this_form_cannot_read_is_refused(self):
        posted = self.client.post("/onboarding/scope",
                                  json=dict(ScopeSaveTest.FORM),
                                  follow_redirects=False)
        self.assertEqual(posted.status_code, 415)
        self.assertEqual(self.scope_rows(), [])


class OutlineRetryTest(WizardFixture):
    """A stopped outline says why in a sentence, and waits for a person.

    The fold is the fuller history on purpose: an outline that was drafted,
    rejected with a note, redrafted and then failed. That is the shape in
    which a note is live at a retry, and the note is the one thing the retry
    has to carry forward.
    """

    NOTE = "Eight weeks is too many — I have four."

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, course, payload in (
                    ("profile_published", "", {}),
                    ("scope_saved", "greek-103", {"title": "Greek"}),
                    ("outline_requested", "greek-103", {}),
                    ("outline_ready", "greek-103",
                     {"plan": {"phase_id": "p1"}, "estimate_usd": "1.20"}),
                    ("outline_rejected", "greek-103", {"note": cls.NOTE}),
                    ("outline_requested", "greek-103", {"note": cls.NOTE}),
                    ("outline_failed", "greek-103",
                     {"reason": "compile_failed", "detail": "SchemaError: …"})):
                onboarding.append_event(conn, cls.scope, kind, course, payload)

    def runs(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.runs_pending("greek-103")))

    # Named to run before the retry below: the retry moves this fixture's
    # ledger on, and the failed screen exists only until it does.
    def test_a_stopped_outline_says_why_and_offers_a_retry(self):
        page = self.screen()
        self.assertIn(onboarding.WORDING[("outline", "compile_failed")], page)
        self.assertIn('action="/onboarding/outline/retry"', page)
        self.assertIn(wizard.FAILED_WORD, page)
        # O2: the machine's word for what happened never reaches the page.
        self.assertNotIn("compile_failed", page)
        self.assertNotIn(wizard.META_REFRESH, page)

    def test_the_button_is_the_scheduler(self):
        # Nothing retries a failed stage on its own: the run row exists
        # because a person asked for it, and the ledger says they did.
        self.assertEqual(self.runs(), [])
        retried = self.client.post("/onboarding/outline/retry",
                                   follow_redirects=False)
        self.assertEqual(retried.status_code, 303, retried.text)
        self.assertEqual(retried.headers["location"], "/onboarding/")
        # The row says what this run was asked to do differently: the note
        # the learner rejected the last outline with, carried forward rather
        # than dropped on the way to the second attempt.
        requested = self.onboarding_rows()[-1]
        self.assertEqual(requested.kind, "outline_requested")
        self.assertEqual(requested.payload, {"note": self.NOTE})
        self.assertEqual([(r.stage, r.status) for r in self.runs()],
                         [("outline", "queued")])
        # The flow is a machine's turn again, so the screen says so — and a
        # second press is refused, because there is no longer a stopped
        # outline to retry.
        self.assertEqual(self.current_stop(), "outline")
        page = self.screen()
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertIn(wizard.META_REFRESH, page)
        self.assertNotIn("/onboarding/outline/retry", page)
        again = self.client.post("/onboarding/outline/retry",
                                 follow_redirects=False)
        self.assertEqual(again.status_code, 409)


class OutlinePendingCopyTest(WizardFixture):
    """Design §4 Stop 7: the stage name, the elapsed time, and nothing it
    would have to invent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, course in (("profile_published", ""),
                                 ("scope_saved", "greek-105"),
                                 ("outline_requested", "greek-105")):
                onboarding.append_event(conn, cls.scope, kind, course,
                                        {"title": "Greek"} if course else {})

    def test_the_pending_screen_forecasts_nothing(self):
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["outline"], page)
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertIn("less than a minute elapsed", page)   # never a forecast
        self.assertIn(wizard.META_REFRESH, page)
        # And it says so, rather than leaving the absence to be noticed: the
        # one number on the screen is the one the ledger already knows.
        self.assertIn("no progress bar", page)
        self.assertNotIn("/onboarding/outline/retry", page)


class GateFixture(WizardFixture):
    """A tenant at the outline gate, with a draft on disk to compile.

    The draft is a copy of the example course under the layout the outline
    stage writes — `<home>/<id>/.draft-onboarding/` — because the first half
    of the gate screen *is* a compile of that tree, and a fixture that handed
    the screen a manifest directly would exercise everything except the thing
    this stop does. The course id is the draft sidecar's own, which is what
    minting guarantees in the running system.

    `CURRICLE_COURSES_DIR` is never read here: the app is built with the home
    it serves, so no exported variable can point these tests at a real
    courses directory.
    """

    COURSE = "tinylang"
    # The plan the outline stage would have reported for this course, keyed
    # by the build spec's field names, and a number in its own format.
    PLAN = {"phase_id": "p1", "lesson_unit": "u1", "widget_unit": "u2",
            "widget_concept": "precedence as a table of binding powers",
            "exercise_unit": "u2", "quiz": True, "bank": True}
    ESTIMATE = "1.37"
    # The other half of what the learner is shown: what these roles have
    # left on their budgets, read by the worker when the outline became
    # ready and carried in the same payload as the estimate.
    HEADROOM = "20.00"
    BROKEN = False        # a draft that will not compile
    MISSING = False       # a draft deleted by hand between two screens

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="curricle-gate-")
        plant(os.path.join(cls.tmp, cls.COURSE), wizard.DRAFT_DIR,
              broken=cls.BROKEN)
        if cls.MISSING:
            shutil.rmtree(os.path.join(cls.tmp, cls.COURSE))
        cls.COURSES_DIR = cls.tmp
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        with cls.engine.begin() as conn:
            for kind, payload in (
                    ("profile_published", None),
                    ("scope_saved", {"title": "Interpreters, end to end"}),
                    ("outline_requested", {}),
                    ("outline_ready", dict(
                        {"plan": cls.PLAN, "estimate_usd": cls.ESTIMATE},
                        **({"headroom_usd": cls.HEADROOM}
                           if cls.HEADROOM is not None else {})))):
                onboarding.append_event(
                    conn, cls.scope, kind,
                    "" if kind == "profile_published" else cls.COURSE,
                    payload or {})

    def gate_for(self, outline: dict, spend=None) -> str:
        """The gate as it renders for one `outline_ready` payload.

        Rendered rather than appended, because these are payload shapes the
        fixture's own ledger cannot hold two of: one live outline per course
        is what the wizard writes, and what is under test is the screen's
        reading of a row rather than the ledger's ability to carry it.
        """
        return wizard.outline_gate_screen(
            onboarding.CourseFlow(course_id=self.COURSE, stage="outline_gate",
                                  status="waiting", outline=outline),
            wizard.draft_manifest(self.tmp, self.COURSE), spend).body

    def outline_ready_payload(self) -> dict:
        row, = [r for r in self.onboarding_rows() if r.kind == "outline_ready"]
        return row.payload

    def queued(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(
                sa.select(db.factory_runs.c.stage, db.factory_runs.c.status,
                          db.factory_runs.c.payload)
                .where(db.factory_runs.c.tenant_id == self.tenant)
                .order_by(db.factory_runs.c.id)))


class OutlineGateScreenTest(GateFixture):
    """Stop 8: the drafted course read back, and then the number.

    Read-only, so one tenant serves the lot: nothing here writes a row.
    """

    def test_the_gate_renders_the_outline_it_compiled(self):
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["outline_gate"], page)
        # The course, its phases with their goals, and its units with their
        # glosses — all of it out of a fresh compile of the draft, none of it
        # out of the ledger.
        self.assertIn("Interpreters, end to end", page)
        self.assertIn("Turn source text into a syntax tree you can print, "
                      "test, and trust.", page)
        self.assertIn("Phase 1 — The front end", page)
        self.assertIn("Unit 1 — Characters to tokens", page)
        self.assertIn("Tokens become a tree, and precedence stops being a "
                      "mystery", page)
        # The track ladder, designed for this course, with its stages.
        self.assertIn("Formal grammars", page)
        self.assertIn("Recognise what a lexer can and cannot decide.", page)
        # And the shelf: the link, and the essay as the manifest carries it
        # rather than the shelf markdown read a second time.
        self.assertIn('href="https://craftinginterpreters.com/"', page)
        self.assertIn("The spine of this course, and the rare technical book",
                      page)
        # A phase's entries carry milestone ids beside unit ids, and both
        # get a line: the hub tracks milestones as checkable stones, so an
        # outline that showed only the units would be an approval of fewer
        # things than the course is about to ask for. The id itself never
        # reaches the page, like every other id here.
        self.assertIn("Error messages worth reading", page)
        self.assertIn("Milestone · side-quest", page)
        self.assertNotIn("m-errors", page)
        # The steps of a stepped unit, under the unit that owns them — the
        # three the hub will check off one at a time in phase 0.
        self.assertIn("Project skeleton with one passing test", page)
        self.assertIn("REPL echoes a line and exits cleanly", page)
        # And the count line, in the hub's own arithmetic: the gate used to
        # read back 12 units over a course the hub greeted as 16 steps.
        self.assertIn("3 phases · 5 units · 1 milestone · 8 steps", page)
        # Your turn, so nothing here is watching a machine.
        self.assertIn(wizard.WAITING_WORD, page)
        self.assertNotIn(wizard.META_REFRESH, page)

    def test_the_count_line_is_the_hubs_own_arithmetic(self):
        # Not "the same rule, written out twice" — the hub's actual rows, off
        # the hub's actual page. The gate read back 12 units over a course
        # the hub then greeted as "16 steps from here to done", and the only
        # way that stays fixed is if the two counts come from one place.
        from curricle.hubrender import render_hub
        from test_hubrender import payload

        manifest = wizard.draft_manifest(self.tmp, self.COURSE)
        phases = payload(render_hub(manifest, api="api/events"), "PHASES")
        stones = [row for phase in phases for row in phase["units"]]
        units = {u.id: u for u in manifest.units}
        entries = [e for phase in manifest.phases for e in phase.entries]
        self.assertEqual(
            wizard.count_line(manifest),
            f"{len(phases)} phases · "
            f"{sum(1 for e in entries if e in units)} units · "
            f"{sum(1 for row in stones if row[-1:] == ['m'])} milestone · "
            f"{len(stones)} steps")

    def test_a_term_with_nothing_under_it_is_left_out(self):
        # "0 milestones" is a fact about a shape nobody has; the line says
        # what the course is made of, not what it is missing.
        manifest = wizard.draft_manifest(self.tmp, self.COURSE)
        plain = dataclasses.replace(
            manifest,
            phases=tuple(dataclasses.replace(p, entries=tuple(
                e for e in p.entries if e.startswith("u")))
                for p in manifest.phases))
        self.assertNotIn("milestone", wizard.count_line(plain))

    def test_the_numbers_on_the_screen_are_the_numbers_in_the_ledger(self):
        # O3's first half, now for both figures. Neither is recomputed for
        # the screen and neither is reformatted for it: the bytes the outline
        # stage wrote are the bytes a learner reads, or the row the approval
        # carries would be a number nobody was shown.
        page = self.screen()
        payload = self.outline_ready_payload()
        self.assertEqual(payload["estimate_usd"], self.ESTIMATE)
        self.assertEqual(payload["headroom_usd"], self.HEADROOM)
        self.assertIn(f"about ${payload['estimate_usd']}", page)
        self.assertIn(f"${payload['headroom_usd']}", page)
        # And each is printed with the word that says which one it is: the
        # expectation and the stopping line are not distinguishable by size
        # here, because they are the same size on purpose.
        self.assertIn(wizard.GATE_ESTIMATE_WORD, page)
        self.assertIn(wizard.GATE_HEADROOM_WORD, page)
        # The headroom is not a cap and the sentence under it says so, in
        # the mechanism's own terms: a check made before every call.
        self.assertIn(wizard.GATE_HEADROOM, page)
        self.assertIn("before every call", page)
        # This one covers the estimate several times over, so nothing warns.
        for alarm in (wizard.GATE_SHORT, wizard.GATE_NONE):
            with self.subTest(alarm=alarm):
                self.assertNotIn(alarm, page)

    def test_the_plan_is_a_list_derived_from_its_own_keys(self):
        page = self.screen()
        self.assertIn("Unit 1 · a Socratic lesson", page)
        self.assertIn("Unit 2 · a widget", page)
        self.assertIn("precedence as a table of binding powers", page)
        self.assertIn("Unit 2 · a scaffolded exercise", page)
        self.assertIn("Phase 1 checkpoint quiz", page)
        self.assertIn("Question bank · a new section", page)

    def test_a_concept_that_is_the_gloss_again_is_not_printed_twice(self):
        # The designer role has filled `widget_concept` with the unit's own
        # gloss verbatim. The gloss is three panels up the same page; a
        # parenthetical repeating it is text a learner reads to find out it
        # said nothing.
        manifest = wizard.draft_manifest(self.tmp, self.COURSE)
        gloss = next(u.gloss for u in manifest.units if u.id == "u2")
        items = wizard.plan_items(dict(self.PLAN, widget_concept=gloss),
                                  manifest)
        widget = next(i for i in items if i.name == "the widget")
        self.assertEqual(widget.detail, "")
        self.assertEqual(widget.label, "Unit 2 · a widget")

    def test_a_skipped_artifact_keeps_its_line_and_says_why(self):
        # "No widget" is part of what the estimate is an estimate of, so it
        # is said rather than left out — a plan listing only what it does buy
        # reads as a shorter course rather than a cheaper build. And the
        # reason is a reason: "skipped" reads as something that went wrong.
        items = {i.name: i for i in wizard.plan_items(
            dict(self.PLAN, widget_unit=None, widget_concept=None, bank=False),
            None)}
        self.assertFalse(items["the widget"].bought)
        self.assertEqual(items["the widget"].detail, wizard.UNPLANNED_REASON)
        self.assertFalse(items["the question bank"].bought)
        self.assertEqual(items["the question bank"].detail, "not built for a "
                                                            "new course")
        for item in items.values():
            with self.subTest(item=item.name):
                self.assertNotIn("skipped", item.detail)

    def test_the_estimate_comes_before_the_button(self):
        # Stop 0's third never-promise, kept on the screen it was about: the
        # number is above the decision, not under it.
        page = self.screen()
        self.assertLess(page.index(f"about ${self.ESTIMATE}"),
                        page.index('action="/onboarding/outline/approve"'))

    def test_the_headroom_is_a_figure_the_wizard_never_priced(self):
        # The module still reads no model configuration: the figure on this
        # page is the one the worker read off the ledger and wrote into the
        # row, and a payload from before the worker carried one prints no
        # figure rather than inventing a number to fill the gap.
        page = self.screen()
        self.assertIn(wizard.GATE_HEADROOM, page)
        blind = self.gate_for({"plan": self.PLAN,
                               "estimate_usd": self.ESTIMATE})
        self.assertIn(f"about ${self.ESTIMATE}", blind)
        self.assertIn(wizard.GATE_HEADROOM, blind)
        self.assertNotIn("None", blind)
        self.assertEqual(blind.count("$"), 1)
        # Nothing to compare the estimate against is nothing to warn about.
        for alarm in (wizard.GATE_SHORT, wizard.GATE_NONE):
            with self.subTest(alarm=alarm):
                self.assertNotIn(alarm, blind)

    def test_a_headroom_under_the_estimate_is_said_before_the_button(self):
        # The defect this figure exists to prevent: budgets are per tenant
        # for the life of an account, so a second course can arrive at this
        # screen with less left than the build needs. That is a sentence
        # above the button, not a stopped stage twenty minutes later.
        short = self.gate_for({"plan": self.PLAN,
                               "estimate_usd": self.ESTIMATE,
                               "headroom_usd": "0.90"})
        self.assertIn("$0.90", short)
        self.assertIn(wizard.GATE_SHORT, short)
        self.assertLess(short.index(wizard.GATE_SHORT),
                        short.index('action="/onboarding/outline/approve"'))
        # And the decision stays the learner's: the button is still there.
        self.assertIn('action="/onboarding/outline/approve"', short)

    def test_no_headroom_at_all_warns_and_still_offers_the_button(self):
        none = self.gate_for({"plan": self.PLAN,
                              "estimate_usd": self.ESTIMATE,
                              "headroom_usd": "0.00"})
        self.assertIn("$0.00", none)
        self.assertIn(wizard.GATE_NONE, none)
        self.assertNotIn(wizard.GATE_SHORT, none)
        self.assertIn('action="/onboarding/outline/approve"', none)

    def test_the_drafting_cost_says_so_far_and_counts_the_drafts(self):
        # The figure is every draft this course has paid for, because a
        # rejected outline was drafted again and the ledger holds both. A
        # sentence naming "this outline" would price one draft at the cost
        # of all of them.
        from decimal import Decimal
        once = self.gate_for({"plan": self.PLAN,
                              "estimate_usd": self.ESTIMATE},
                             wizard.Spend(Decimal("1.09"), Decimal(0), 1))
        self.assertIn("Drafting cost so far: $1.09.", once)
        self.assertNotIn("across", once)
        twice = self.gate_for({"plan": self.PLAN,
                               "estimate_usd": self.ESTIMATE},
                              wizard.Spend(Decimal("2.14"), Decimal(0), 2))
        self.assertIn("Drafting cost so far: $2.14, across 2 drafts.", twice)

    def test_both_decisions_are_offered_and_the_note_is_required(self):
        page = self.screen()
        self.assertIn('action="/onboarding/outline/approve"', page)
        self.assertIn('action="/onboarding/outline/reject"', page)
        self.assertIn('name="note"', page)
        self.assertIn("required", page)


class LegacyOutlineRowTest(GateFixture):
    """An `outline_ready` written before the worker carried the headroom.

    The ledger is append-only and rows do not get rewritten, so the release
    that adds a figure has to be able to read the rows that came before it.
    Such a gate prints one number and still takes a decision; the approval
    it writes carries what was on the screen and no key for what was not.
    """

    HEADROOM = None

    def test_a_row_without_the_figure_still_gates_and_still_approves(self):
        page = self.screen()
        self.assertNotIn("headroom_usd", page)
        self.assertIn(f"about ${self.ESTIMATE}", page)
        self.assertEqual(page.count("$"), 1)

        approved = self.client.post("/onboarding/outline/approve",
                                    follow_redirects=False)
        self.assertEqual(approved.status_code, 303, approved.text)
        approval, = [r.payload for r in self.onboarding_rows()
                     if r.kind == "outline_approved"]
        self.assertEqual(approval["estimate_usd"], self.ESTIMATE)
        self.assertEqual(approval["plan"], self.PLAN)
        # Absent, not null: a `None` in the row would be a number nobody was
        # shown, which is exactly what O3 exists to prevent.
        self.assertNotIn("headroom_usd", approval)


class OutlineGateEscapingTest(GateFixture):
    """The first screen that reads learner-side text back as markup.

    Two sources meet here and both are escaped where they are interpolated:
    the compiled draft, which a model wrote from a learner's own scope, and
    the plan out of the ledger.
    """

    PLAN = dict(GateFixture.PLAN,
                widget_concept="binding powers & <b>precedence</b>")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Edited after planting, because the draft is compiled per request:
        # what the screen renders is whatever is on disk when it is drawn.
        sidecar = os.path.join(cls.tmp, cls.COURSE, wizard.DRAFT_DIR,
                               "learning", "course.yaml")
        with open(sidecar, encoding="utf-8") as f:
            text = f.read()
        text = text.replace("title: Interpreters, end to end",
                            "title: Interpreters <b>&</b> ends")
        text = text.replace("Unit 2's technique, in one sitting.",
                            "Unit 2's <b>technique</b> & why.")
        with open(sidecar, "w", encoding="utf-8") as f:
            f.write(text)

    def test_nothing_from_the_draft_or_the_plan_renders_as_markup(self):
        page = self.screen()
        self.assertIn("Interpreters &lt;b&gt;&amp;&lt;/b&gt; ends", page)
        self.assertIn("Unit 2&#x27;s &lt;b&gt;technique&lt;/b&gt; &amp; why.",
                      page)
        self.assertIn("binding powers &amp; &lt;b&gt;precedence&lt;/b&gt;",
                      page)
        for leak in ("<b>&</b>", "<b>technique</b>", "<b>precedence</b>"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, page)


class OutlineApproveTest(GateFixture):
    """O3's producer: the row that lets money be spent.

    Invariant O3 (design §5): "no token is spent without an upstream ledger
    row recording the learner's approval and the estimate they were shown."
    The approval echoes `outline_ready`'s payload rather than reading a
    number off the form, so the numbers on the screen and the numbers in
    the ledger are the same bytes by construction — which is what the
    byte-equality assertions below are pinning. Both of them: the screen now
    shows an estimate *and* what is left before the build refuses, and a
    row echoing half of what was shown is half a record of the decision.

    Its own tenant, because approving is a one-way move of this ledger.
    """

    def test_approving_records_the_numbers_shown_and_queues_the_build(self):
        page = self.screen()
        approved = self.client.post("/onboarding/outline/approve",
                                    follow_redirects=False)
        self.assertEqual(approved.status_code, 303, approved.text)
        self.assertEqual(approved.headers["location"], "/onboarding/")

        rows = [r for r in self.onboarding_rows()
                if r.kind in ("outline_approved", "build_requested")]
        self.assertEqual([r.kind for r in rows],
                         ["outline_approved", "build_requested"])
        approval = rows[0].payload
        # O3, byte for byte: not numbers computed again at approval time,
        # and not ones posted by the form — the ones the ledger already held
        # and the screen had just printed.
        outline = self.outline_ready_payload()
        for number in ("estimate_usd", "headroom_usd"):
            with self.subTest(number=number):
                self.assertEqual(approval[number], outline[number])
                self.assertIsInstance(approval[number], str)
                self.assertIn(f"${approval[number]}", page)
        # The plan travels with it: what gets built is what was approved.
        self.assertEqual(approval["plan"], self.PLAN)
        self.assertEqual(rows[1].payload, {})

        # And the run the second process will claim, written in the same
        # transaction: there is no human turn between Stops 8 and 9.
        self.assertEqual([(r.stage, r.status) for r in self.queued()],
                         [("build", "queued")])

    def test_the_fold_moves_to_the_build_and_a_second_approval_is_refused(self):
        # Named to run after the approval above: same tenant, same ledger.
        self.assertEqual(self.current_stop(), "build")
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["build"], page)
        self.assertIn("Building your phase-1 materials", page)
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertIn("less than a minute elapsed", page)   # never a forecast
        self.assertIn(wizard.META_REFRESH, page)
        self.assertNotIn("This screen is still being built", page)
        self.assertNotIn('action="/onboarding/outline/approve"', page)
        # O1 for a write, from a tab that still has the button on it: a
        # second approval would be a second build queued over the first.
        again = self.client.post("/onboarding/outline/approve",
                                 follow_redirects=False)
        self.assertEqual(again.status_code, 409)
        self.assertEqual([(r.stage, r.status) for r in self.queued()],
                         [("build", "queued")])


class PlanAgreementTest(GateFixture):
    """The gate and the build screen cannot describe different builds.

    They did: the gate said the question bank was skipped and the build
    screen, two clicks later, named it among "the lesson, the widget, the
    exercise, the checkpoint quiz and the question bank you approved". One
    was a sentence somebody typed; the other was derived. Now both come out
    of `plan_items`, so this fixture buys no bank — the shape a brand-new
    course actually gets — and asserts that neither screen offers one.
    """

    COURSE = "tinylang"
    PLAN = dict(GateFixture.PLAN, bank=False)

    def test_the_gate_names_the_bank_only_to_say_why_it_is_not_bought(self):
        page = self.screen()
        self.assertIn("Question bank", page)
        self.assertIn("not built for a new course", page)
        self.assertNotIn("Question bank · a new section", page)

    def test_then_the_build_screen_lists_exactly_what_the_gate_listed(self):
        self.client.post("/onboarding/outline/approve", follow_redirects=False)
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["build"], page)
        bought = [item.name for item in wizard.plan_items(self.PLAN, None)
                  if item.bought]
        self.assertEqual(bought, ["the lesson", "the widget", "the exercise",
                                  "the checkpoint quiz"])
        self.assertIn("The lesson, the widget, the exercise and the checkpoint "
                      "quiz you approved are being written", page)
        # The defect this test exists for: nothing on the waiting screen
        # claims the learner approved something the gate refused to sell.
        self.assertNotIn("question bank", page)

    def test_an_approval_with_no_plan_still_says_something_true(self):
        # A ledger that somehow carries an approval without a plan is a row
        # this screen must still render: it names the artifacts it cannot
        # list rather than listing artifacts nobody bought.
        self.assertEqual(wizard.build_inventory({}),
                         "The materials you approved are being written and "
                         "checked one at a time.")


class BuildFailedTest(WizardFixture):
    """Stop 9's failed face, and the button that carries on rather than starts.

    The fold is a whole approved flow, because the retry's promise depends
    on what is upstream of the failure: an approval that still stands, and a
    draft holding whatever the stopped run had already finished. Nothing
    here reads the draft — the screen is the ledger's, like every other one
    — but the sentences it prints are only true of that shape.
    """

    COURSE = "greek-107"
    REASON = "validation_failed"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, payload in (
                    ("profile_published", None),
                    ("scope_saved", {"title": "Greek"}),
                    ("outline_requested", {}),
                    ("outline_ready", {"plan": {"phase_id": "p1"},
                                       "estimate_usd": "1.37"}),
                    ("outline_approved", {"plan": {"phase_id": "p1"},
                                          "estimate_usd": "1.37"}),
                    ("build_requested", {}),
                    ("build_failed", {"reason": cls.REASON,
                                      "detail": "ValidationFailed: quiz "
                                                "question 3 has no why"})):
                onboarding.append_event(
                    conn, cls.scope, kind,
                    "" if kind == "profile_published" else cls.COURSE,
                    payload or {})

    def runs(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.runs_pending(self.COURSE)))

    # Named to run before the retry below: the retry moves this fixture's
    # ledger on, and the failed screen exists only until it does.
    def test_a_stopped_build_says_why_and_offers_to_carry_on(self):
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["build"], page)
        self.assertIn(onboarding.WORDING[("build", self.REASON)], page)
        self.assertIn('action="/onboarding/build/retry"', page)
        self.assertIn(wizard.BUILD_RETRY_ASIDE, page)
        self.assertIn(wizard.FAILED_WORD, page)
        # O2: neither the machine's word for what happened nor the exception
        # behind it reaches the page. Both are in the row, for an operator.
        self.assertNotIn(self.REASON, page)
        self.assertNotIn("ValidationFailed", page)
        self.assertNotIn(wizard.META_REFRESH, page)
        # And no second approval is asked for: the row upstream still stands.
        self.assertNotIn('action="/onboarding/outline/approve"', page)

    def test_the_button_is_the_scheduler_and_asks_for_no_new_approval(self):
        self.assertEqual(self.runs(), [])
        retried = self.client.post("/onboarding/build/retry",
                                   follow_redirects=False)
        self.assertEqual(retried.status_code, 303, retried.text)
        self.assertEqual(retried.headers["location"], "/onboarding/")

        # One request row and one run — and no `outline_approved`, because
        # O3 is satisfied by the approval already in the ledger and a run
        # that stopped did not spend it.
        requested = self.onboarding_rows()[-1]
        self.assertEqual((requested.kind, requested.payload),
                         ("build_requested", {}))
        self.assertEqual([r.kind for r in self.onboarding_rows()]
                         .count("outline_approved"), 1)
        self.assertEqual([(r.stage, r.status) for r in self.runs()],
                         [("build", "queued")])

        # A machine's turn again, so the screen says so — and a second press
        # is refused, because there is no longer a stopped build to resume.
        self.assertEqual(self.current_stop(), "build")
        page = self.screen()
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertIn(wizard.META_REFRESH, page)
        self.assertNotIn("/onboarding/build/retry", page)
        again = self.client.post("/onboarding/build/retry",
                                 follow_redirects=False)
        self.assertEqual(again.status_code, 409)


class BuildRetryBeforeTheBuildTest(GateFixture):
    """A build retry from a flow that is not at a stopped build at all."""

    COURSE = "tinylang"

    def test_a_retry_at_the_gate_is_refused_and_writes_nothing(self):
        refused = self.client.post("/onboarding/build/retry",
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual([r.kind for r in self.onboarding_rows()]
                         .count("build_requested"), 0)
        self.assertEqual(self.queued(), [])


class PromotePendingTest(WizardFixture):
    """Stop 10's pending face: no second gate, and nothing forecast.

    Design §4 put no human turn between the build and the publication, so
    this screen has no ask on it — a button here would be a decision the
    learner already took at the outline gate being asked for twice.
    """

    COURSE = "greek-108"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, payload in (
                    ("profile_published", None),
                    ("scope_saved", {"title": "Greek"}),
                    ("outline_ready", {"plan": {"phase_id": "p1"},
                                       "estimate_usd": "1.37"}),
                    ("outline_approved", {"plan": {"phase_id": "p1"},
                                          "estimate_usd": "1.37"}),
                    ("build_requested", {}),
                    ("build_ready", {"artifacts": ["interactive/x"],
                                     "costs": {"lesson-writer": "$0.02"}})):
                onboarding.append_event(
                    conn, cls.scope, kind,
                    "" if kind == "profile_published" else cls.COURSE,
                    payload or {})

    def test_the_publishing_screen_waits_and_asks_for_nothing(self):
        self.assertEqual(self.current_stop(), "promote")
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["promote"], page)
        self.assertIn("Installing your course", page)
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertIn("less than a minute elapsed", page)   # never a forecast
        self.assertIn(wizard.META_REFRESH, page)
        self.assertNotIn("This screen is still being built", page)
        self.assertNotIn("<button", page)
        # Nothing from the build's payload is on it: this stop reports
        # position, and the artifacts are the next screen's business.
        self.assertNotIn("interactive/x", page)


class PromoteFailedTest(WizardFixture):
    """Stop 10's failed face, and the one retry in the wizard that is free.

    The fold is a whole built flow, because what the screen promises depends
    on what is behind the failure: materials that were bought and kept, and
    a publication that appends its row only after the compile at the course's
    own final location. Nothing partial is in place, so nothing on this
    screen has to warn about anything.
    """

    COURSE = "greek-109"
    REASON = "compile_failed"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, payload in (
                    ("profile_published", None),
                    ("scope_saved", {"title": "Greek"}),
                    ("outline_ready", {"plan": {"phase_id": "p1"},
                                       "estimate_usd": "1.37"}),
                    ("outline_approved", {"plan": {"phase_id": "p1"},
                                          "estimate_usd": "1.37"}),
                    ("build_requested", {}),
                    ("build_ready", {"artifacts": ["interactive/x"],
                                     "costs": {"lesson-writer": "$0.02"}}),
                    ("promote_failed", {"reason": cls.REASON,
                                        "detail": "ValidationFailed: unit u9 "
                                                  "is in no phase"})):
                onboarding.append_event(
                    conn, cls.scope, kind,
                    "" if kind == "profile_published" else cls.COURSE,
                    payload or {})

    def runs(self) -> list:
        with self.engine.begin() as conn:
            return list(conn.execute(self.scope.runs_pending(self.COURSE)))

    # Named to run before the retry below: the retry moves this fixture's
    # ledger on, and the failed screen exists only until it does.
    def test_a_stopped_publication_says_why_and_offers_to_try_again(self):
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["promote"], page)
        self.assertIn(onboarding.WORDING[("promote", self.REASON)], page)
        self.assertIn('action="/onboarding/promote/retry"', page)
        self.assertIn(wizard.PROMOTE_RETRY_ASIDE, page)
        self.assertIn(wizard.FAILED_WORD, page)
        # O2: neither the machine's word for what happened nor the exception
        # behind it reaches the page. Both are in the row, for an operator.
        self.assertNotIn(self.REASON, page)
        self.assertNotIn("ValidationFailed", page)
        self.assertNotIn(wizard.META_REFRESH, page)
        # And the placeholder is gone: this stop has a screen of its own in
        # both of the states it can be in.
        self.assertNotIn("This screen is still being built", page)

    def test_the_button_appends_the_request_row_and_queues_the_run(self):
        self.assertEqual(self.runs(), [])
        retried = self.client.post("/onboarding/promote/retry",
                                   follow_redirects=False)
        self.assertEqual(retried.status_code, 303, retried.text)
        self.assertEqual(retried.headers["location"], "/onboarding/")

        requested = self.onboarding_rows()[-1]
        self.assertEqual((requested.kind, requested.course, requested.payload),
                         ("promote_requested", self.COURSE, {}))
        self.assertEqual([(r.stage, r.status) for r in self.runs()],
                         [("promote", "queued")])

        # A machine's turn again, so the screen says so rather than showing a
        # stale failure over a run that is already going — which is the whole
        # reason the request row exists. And a second press is refused.
        self.assertEqual(self.current_stop(), "promote")
        page = self.screen()
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertIn(wizard.META_REFRESH, page)
        self.assertNotIn("/onboarding/promote/retry", page)
        again = self.client.post("/onboarding/promote/retry",
                                 follow_redirects=False)
        self.assertEqual(again.status_code, 409)


class PromoteRetryBeforeTheStopTest(GateFixture):
    """A promotion retry from a flow that has not reached the stop at all."""

    def test_a_retry_at_the_gate_is_refused_and_writes_nothing(self):
        refused = self.client.post("/onboarding/promote/retry",
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual([r.kind for r in self.onboarding_rows()]
                         .count("promote_requested"), 0)
        self.assertEqual(self.queued(), [])


class LandingCardTest(WizardFixture):
    """Stop 10's last face: the course, and the two ways to work on it.

    The courses home is a temp directory holding nothing — the card reads it
    for a path to print and never for a course, so there is nothing to plant.
    """

    COURSE = "greek-110"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="curricle-landing-")
        cls.COURSES_DIR = cls.tmp
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        with cls.engine.begin() as conn:
            for kind, payload in (
                    ("profile_published", None),
                    ("scope_saved", {"title": "Greek"}),
                    ("outline_ready", {"plan": {"phase_id": "p1"},
                                       "estimate_usd": "1.37"}),
                    ("outline_approved", {"plan": {"phase_id": "p1"},
                                          "estimate_usd": "1.37"}),
                    ("build_ready", {"artifacts": [], "costs": {}}),
                    ("promoted", {"course_id": cls.COURSE})):
                onboarding.append_event(
                    conn, cls.scope, kind,
                    "" if kind == "profile_published" else cls.COURSE,
                    payload or {})

    def test_the_card_is_what_a_finished_setup_lands_on(self):
        # The fold re-enters at Stop 6 for a second course, and the screen
        # under that stop with a finished flow behind it is the card.
        self.assertEqual(self.current_stop(), "scope")
        page = self.screen()
        self.assertIn(wizard.STOP_TITLES["done"], page)
        self.assertIn(f'href="/c/{self.COURSE}/index.html"', page)
        # Every step behind the learner, and none under them.
        self.assertIn("All 6 steps done", page)
        self.assertNotIn('class="now"', page)
        # Nothing is forecast and nothing is counted: done marks and next-up
        # are the hub's derived answer, and a copy here would be a second one.
        self.assertNotIn(wizard.META_REFRESH, page)
        self.assertNotIn("0 of", page)

    def test_the_snippet_is_filled_in_for_this_course_and_this_tenant(self):
        page = self.screen()
        block = page.split('<pre class="snippet">')[1].split("</pre>")[0]
        self.assertIn(self.slug, block)
        self.assertIn(os.path.join(self.tmp, self.COURSE), block)
        # Escaped like everything else on the page — the quotes a config
        # block is made of are entities by the time they reach the browser.
        self.assertIn("&quot;curricle-tutor&quot;", block)
        self.assertIn("&quot;mcp&quot;", block)
        # And the committed page is named, for the day the tab is closed.
        self.assertIn(wizard.MCP_DOC, page)

    def test_the_block_says_where_it_goes_before_it_says_what_it_is(self):
        # A filled-in config with no destination is an answer to a question
        # the card never asked. The sentence names no file: `docs/mcp-
        # config.md` names none either, and a path this repository has never
        # seen is not one to send a stranger to edit.
        page = self.screen()
        self.assertIn(wizard.MCP_DEST, page)
        self.assertLess(page.index(wizard.MCP_DEST),
                        page.index('<pre class="snippet">'))
        for invented in ("~/.claude.json", "claude_desktop_config.json"):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, page)

    def test_only_the_path_can_wrap_in_the_snippet(self):
        # One argument per line at two-space indents. Column-aligned
        # continuations put the course path at column 15 of a block that
        # wraps at 400px, so the one value nobody can eyeball broke across
        # three lines and read as corrupt.
        block = wizard.mcp_config("/home/someone/curricle-courses/a-course",
                                  "someone")
        lines = block.splitlines()
        for line in lines:
            indent = len(line) - len(line.lstrip(" "))
            with self.subTest(line=line):
                self.assertEqual(indent % 2, 0)
        self.assertIn('        "-m",', lines)
        self.assertIn('        "--course",', lines)
        self.assertIn('        "/home/someone/curricle-courses/a-course",',
                      lines)
        # Every line but the path's is short enough that nothing else can be
        # the thing that wraps.
        self.assertTrue(all(len(line) <= 32 for line in lines
                            if "curricle-courses" not in line), lines)

    def test_the_card_can_be_asked_for_by_name(self):
        # A card is a page you can come back to, not a moment that passes.
        page = self.screen(f"?course={self.COURSE}")
        self.assertIn(wizard.STOP_TITLES["done"], page)
        self.assertIn(f'href="/c/{self.COURSE}/index.html"', page)

    def test_naming_no_finished_course_is_the_way_to_the_scope_form(self):
        # The link the card itself carries, and the second-course re-entry
        # design §4 Stop 10 asks for. `?course=` names nothing, because no
        # minted id is empty.
        self.assertIn('href="/onboarding/?course="', self.screen())
        for query in ("?course=", "?course=never-existed"):
            with self.subTest(query=query):
                page = self.screen(query)
                self.assertIn(wizard.STOP_TITLES["scope"], page)
                self.assertNotIn(wizard.STOP_TITLES["done"], page)


class GateScansTheHomeBeforeRedirectingTest(WizardFixture):
    """The manual dropper: a course copied in while the gate is still firing.

    Promotion lifts the gate for wizard users by giving them a course, and a
    published profile lifts it anyway. This is the other case — a tenant who
    never started the wizard and put a course in the home by hand — where
    the front door's lazy rescan is exactly the thing the gate is standing
    in front of, so the scan happens at the moment of the redirect instead.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="curricle-gatescan-")
        cls.COURSES_DIR = cls.tmp
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)

    def test_a_course_that_appears_after_startup_lifts_the_gate(self):
        # Empty home, no published profile: the gate fires, having looked.
        self.assertEqual(self.client.get("/", follow_redirects=False)
                         .status_code, 307)
        plant(self.tmp, "tinylang")
        page = self.client.get("/", follow_redirects=False)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('href="/c/tinylang/"', page.text)
        # No row was written to lift it: registration is a fact about the
        # filesystem, and the ledger still says this tenant never started.
        self.assertEqual(self.onboarding_rows(), [])


class OutlineRejectTest(GateFixture):
    """Rejecting: two rows carrying the note, and Stop 7 again."""

    NOTE = "Four phases is too many — I have eight weeks, not sixteen."

    def test_a_rejection_is_two_rows_and_a_run_that_carries_the_note(self):
        rejected = self.client.post("/onboarding/outline/reject",
                                    data={"note": self.NOTE},
                                    follow_redirects=False)
        self.assertEqual(rejected.status_code, 303, rejected.text)
        self.assertEqual(rejected.headers["location"], "/onboarding/")
        rows = self.onboarding_rows()[-2:]
        self.assertEqual([r.kind for r in rows],
                         ["outline_rejected", "outline_requested"])
        # The note is on both rows, so neither has to be read through the
        # other: one says this outline was rejected, one says another was
        # asked for, and both say what for.
        for row in rows:
            with self.subTest(kind=row.kind):
                self.assertEqual(row.payload["note"], self.NOTE)
        # And on the run, which exists to answer it.
        self.assertEqual([(r.stage, r.status, r.payload) for r in self.queued()],
                         [("outline", "queued", {"note": self.NOTE})])
        # The fold is back at a machine's turn, and the gate is gone.
        self.assertEqual(self.current_stop(), "outline")
        page = self.screen()
        self.assertIn(wizard.PENDING_WORD, page)
        self.assertNotIn('action="/onboarding/outline/reject"', page)

    def test_a_second_rejection_from_a_stale_tab_is_refused(self):
        # Named to run after the rejection above: the stop it belongs to is
        # behind this ledger now.
        again = self.client.post("/onboarding/outline/reject",
                                 data={"note": "and narrower still"},
                                 follow_redirects=False)
        self.assertEqual(again.status_code, 409)


class OutlineRejectRefusalTest(GateFixture):
    """An empty note is refused, and the refusal writes nothing."""

    def test_a_note_free_rejection_is_refused_in_words(self):
        for note in ("", "   ", "\n"):
            with self.subTest(note=repr(note)):
                refused = self.client.post("/onboarding/outline/reject",
                                           data={"note": note},
                                           follow_redirects=False)
                self.assertEqual(refused.status_code, 422, refused.text)
                self.assertIn("note saying what to change", refused.text)
        # Nothing written, and the learner is still at their own gate.
        self.assertEqual([r.kind for r in self.onboarding_rows()][-1],
                         "outline_ready")
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.current_stop(), "outline_gate")

    def test_a_body_this_form_cannot_read_is_refused(self):
        posted = self.client.post("/onboarding/outline/reject",
                                  json={"note": "smuggled"},
                                  follow_redirects=False)
        self.assertEqual(posted.status_code, 415)
        self.assertEqual(self.queued(), [])


class ApproveBeforeTheGateTest(WizardFixture):
    """O1 for a write: the stop is not open yet, so neither is the spend."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as conn:
            for kind, course in (("profile_published", ""),
                                 ("scope_saved", "greek-108"),
                                 ("outline_requested", "greek-108")):
                onboarding.append_event(conn, cls.scope, kind, course,
                                        {"title": "Greek"} if course else {})

    def test_an_approval_with_no_outline_ready_is_refused(self):
        # There is no estimate on the ledger to carry, and an approval row
        # without one is the one row O3 must never see.
        before = len(self.onboarding_rows())
        refused = self.client.post("/onboarding/outline/approve",
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(len(self.onboarding_rows()), before)
        self.assertEqual(self.current_stop(), "outline")

    def test_a_rejection_before_the_gate_is_refused_too(self):
        refused = self.client.post("/onboarding/outline/reject",
                                   data={"note": "narrower, please"},
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)


class DirtyDraftGateTest(GateFixture):
    """The compiler refuses rather than guesses, and so does the screen."""

    BROKEN = True

    def test_an_uncompilable_draft_gets_a_panel_and_no_spend_button(self):
        page = self.screen()
        self.assertIn("The drafted outline cannot be read back", page)
        self.assertIn(wizard.FAILED_WORD, page)
        # A spend button over an outline this system cannot read would be a
        # promise about a course nobody can see.
        self.assertNotIn('action="/onboarding/outline/approve"', page)
        self.assertNotIn(f"${self.ESTIMATE}", page)
        # Nothing partial either: no phase, no unit, no shelf entry.
        for partial in ("Phase 1 — The front end", "Characters to tokens",
                        "The resource shelf"):
            with self.subTest(partial=partial):
                self.assertNotIn(partial, page)
        # What is offered instead is the redraft, which is the only move
        # left at a gate with nothing to review.
        self.assertIn('action="/onboarding/outline/retry"', page)
        # The compiler's findings are an operator's, not a learner's: they
        # name files nobody on this screen has ever seen.
        self.assertNotIn("not-here.md", page)

    def test_the_approval_is_refused_as_well_as_undrawn(self):
        # A button that is absent from a page is not a rule.
        refused = self.client.post("/onboarding/outline/approve",
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("no longer compiles", refused.text)
        self.assertEqual([r.kind for r in self.onboarding_rows()][-1],
                         "outline_ready")
        self.assertEqual(self.queued(), [])

    def test_the_redraft_starts_the_stage_over(self):
        # Named to run last: it moves this fixture's ledger off the gate.
        retried = self.client.post("/onboarding/outline/retry",
                                   follow_redirects=False)
        self.assertEqual(retried.status_code, 303, retried.text)
        self.assertEqual(self.onboarding_rows()[-1].kind, "outline_requested")
        self.assertEqual([(r.stage, r.status) for r in self.queued()],
                         [("outline", "queued")])
        self.assertEqual(self.current_stop(), "outline")


class MissingDraftGateTest(GateFixture):
    """A draft deleted by hand between two screens reads the same way."""

    MISSING = True

    def test_a_draft_that_is_gone_is_the_same_honest_panel(self):
        page = self.screen()
        self.assertIn("The drafted outline cannot be read back", page)
        self.assertNotIn('action="/onboarding/outline/approve"', page)
        self.assertIn('action="/onboarding/outline/retry"', page)
        self.assertIsNone(wizard.draft_manifest(self.tmp, self.COURSE))
        # And an unconfigured home is the same absence rather than a crash:
        # a wizard with nowhere to look has no outline to show.
        self.assertIsNone(wizard.draft_manifest(None, self.COURSE))


class HealthyGateRedraftTest(GateFixture):
    """The redraft button is not a second way out of a working gate."""

    def test_a_redraft_over_a_readable_outline_is_refused(self):
        # Rejecting with a note is the way back to Stop 7 from here, and it
        # is that way because the note is what the next draft is briefed
        # with. A note-free redraft would spend the stage again to ask the
        # same question, so the retry route asks the draft for itself.
        page = self.screen()
        self.assertNotIn('action="/onboarding/outline/retry"', page)
        refused = self.client.post("/onboarding/outline/retry",
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.current_stop(), "outline_gate")


class ProfileCopyTest(unittest.TestCase):
    """Every field that belongs on a form has words; the one that doesn't,
    doesn't (design §4)."""

    def test_every_field_but_demonstrated_has_a_label_and_two_examples(self):
        for field in profile.FIELDS:
            if field == "demonstrated":
                continue
            with self.subTest(field=field):
                explanation, examples = wizard.FIELD_COPY[field]
                self.assertTrue(explanation.strip())
                self.assertEqual(len(examples), 2)
                self.assertTrue(all(x.strip() for x in examples))
                self.assertTrue(wizard.FIELD_LABELS[field].strip())
        self.assertEqual(set(wizard.FIELD_COPY),
                         set(profile.FIELDS) - {"demonstrated"})
        self.assertNotIn("demonstrated", wizard.FIELD_COPY)

    def test_the_four_screens_between_them_cover_every_field_on_a_form(self):
        # Plus `meta`, which is screen 1's description line rather than one of
        # its fields — the one claim identity the wizard never mints.
        asked = {f for _, _, fields in wizard.PROFILE_SCREENS for f in fields}
        self.assertEqual(asked | {"meta"}, set(wizard.FIELD_COPY))

    def test_the_calibration_screen_says_why_those_three_are_the_product(self):
        # Design §4's own sentence, on the screen it was written for.
        self.assertIn("the difference between a course that re-explains your "
                      "degree and one that builds only what you lack",
                      wizard.form_screen("3", profile.ProfileState()).body)

    def test_demonstrated_appears_on_no_form_screen(self):
        # Its absence is the tier system working: that field is written by
        # course activity through the checkpoint→propose pipe, and a box a
        # learner types into could only ever hold something attested.
        for number, _, _ in wizard.PROFILE_SCREENS:
            with self.subTest(screen=number):
                body = wizard.form_screen(number, profile.ProfileState()).body
                self.assertNotIn("demonstrated", body)


class KeyMintingRuleTest(unittest.TestCase):
    """The permanent key-identity contract, as a function."""

    def test_numbers_are_two_digits_and_start_at_one(self):
        self.assertEqual(wizard.next_key([], "background"), "background-01")

    def test_only_this_field_s_own_numbered_keys_count(self):
        spent = [("style", "style-07"), ("background", "swe"),
                 ("background", "background-02"),
                 ("background", "background-sub-01")]
        self.assertEqual(wizard.next_key(spent, "background"), "background-03")


class BoxRowsTest(unittest.TestCase):
    """F2: a box opens at the size of what it holds, not at a fixed three.

    `field-sizing:content` does the real work wherever a browser has the
    property; this is the fallback, and it is what stops a four-line saved
    claim coming back sliced through its last line on the one screen whose
    whole promise is that your own words are read back to you.
    """

    def test_an_empty_box_opens_at_two_rows(self):
        # Three rows around one sentence is two blank lines of nothing.
        self.assertEqual(wizard.box_rows(""), 2)

    def test_a_short_claim_keeps_the_floor(self):
        self.assertEqual(wizard.box_rows("Four hours a week."), 2)

    def test_a_long_claim_gets_a_row_for_every_eighty_columns(self):
        self.assertEqual(wizard.box_rows("x" * 160), 2)
        self.assertEqual(wizard.box_rows("x" * 161), 3)
        self.assertEqual(wizard.box_rows("x" * 400), 5)

    def test_a_short_claim_of_many_lines_is_counted_by_its_lines(self):
        # 101 characters over six lines. Counted over the whole string it
        # would open at two rows and clip four of them — and the box beside
        # this one says in words that line breaks stay inside a claim, so
        # the fallback has to hold what that sentence invites.
        claim = "\n".join(["Tokens become s-expressions."] * 6)[:101]
        self.assertEqual(len(claim), 101)
        self.assertEqual(wizard.box_rows(claim), 4)
        self.assertEqual(
            wizard.box_rows("\n".join(["Tokens become s-expressions."] * 6)), 6)

    def test_a_blank_line_still_occupies_a_row(self):
        self.assertEqual(wizard.box_rows("one\n\ntwo"), 3)


def box_sizes(page: str) -> dict[str, int]:
    """{textarea name: its `rows`} for every box on a rendered screen.

    Read off the markup rather than asserted as a substring, because the
    property under test is that the number *varies with the text* — and a
    substring assertion for one size happily passes against a page where
    every box is that size.
    """
    sizes = {}
    for tag in re.findall(r"<textarea\b[^>]*>", page):
        name = re.search(r'name="([^"]+)"', tag)
        rows = re.search(r'rows="(\d+)"', tag)
        if name and rows:
            sizes[name.group(1)] = int(rows.group(1))
    return sizes


class SavedBoxSizeTest(WizardFixture):
    """The same rule, where it is spent: on the read-back screen itself.

    One method, because the three sizes have to be on one screen at once:
    two saved claims of different lengths and an empty Add box. And none of
    the three may be three, which is what `rows` used to be for all of them —
    a box that happens to come out at the old constant pins nothing.
    """

    SHORT = "Nine years as a backend engineer, mostly Python over Postgres."
    LONG = ("Nine years as a backend engineer, mostly Python services over "
            "Postgres and Kafka, with a couple of years of Go and a long "
            "stretch of production on-call that taught me more about "
            "distributed systems than any amount of the reading ever did, "
            "and rather more about pager fatigue than I wanted to know.")

    def test_each_box_comes_back_at_the_size_of_what_it_holds(self):
        self.assertEqual((wizard.box_rows(self.LONG),
                          wizard.box_rows(self.SHORT)), (4, 2))
        self.save("1", {"new__background": self.LONG})
        self.save("1", {"new__background": self.SHORT})
        sizes = box_sizes(self.screen("?screen=1"))
        self.assertEqual(sizes["claim__background__background-01"], 4)
        self.assertEqual(sizes["claim__background__background-02"], 2)
        # ...and the Add box under them holds nothing, so it opens at the
        # floor. Nothing on the screen is the three every box used to be.
        self.assertEqual(sizes["new__background"], 2)
        self.assertNotIn(3, sizes.values())


class ClaimLabelTest(WizardFixture):
    """F5 and F3: what a box is called, and which newline rule it keeps."""

    def test_a_claim_is_labelled_by_position_and_identified_by_its_key(self):
        self.save("1", {"new__background": "Nine years of backend work.\n"
                                           "Plenty of parsers, all by hand."})
        page = self.screen("?screen=1")
        self.assertIn('<span class="claimkey">Claim 1</span>', page)
        self.assertIn('<span class="claimkey">Claim 2</span>', page)
        # The key is still the identity — it names the box the POST reads
        # back — and it rides in `title` for an operator who wants it. What
        # it no longer does is caption a learner's own sentence.
        self.assertIn('name="claim__background__background-01"', page)
        self.assertIn('title="background-02"', page)
        self.assertNotIn("BACKGROUND-01", page)
        self.assertNotIn("text-transform:uppercase", page)

    def test_every_box_on_a_screen_has_an_accessible_name_of_its_own(self):
        # "Claim 1" is the right words on screen and the wrong accessible
        # name: screen 1 carries three fields, so a form list read aloud
        # would be "Claim 1, Claim 1, Claim 1" — worse than the key it
        # replaced. The field's own heading rides in `aria-label`, with the
        # visible words inside it.
        self.save("1", {"new__background": "Nine years of backend work.",
                        "new__education": "BS in information systems."})
        page = self.screen("?screen=1")
        for name in ('aria-label="Professional background, claim 1"',
                     'aria-label="Formal education, claim 1"',
                     'aria-label="Professional background, add a claim"',
                     'aria-label="Formal education, add a claim"',
                     'aria-label="Prior courses and tracks, add a claim"',
                     'aria-label="Skill description"'):
            with self.subTest(name=name):
                self.assertEqual(page.count(name), 1)

    def test_both_newline_rules_are_printed_where_each_one_applies(self):
        # Two identical boxes with opposite rules: the one above splits on
        # nothing, the Add box splits on every line. Words, since there is
        # no script on this page to make them one control.
        self.save("1", {"new__background": "Nine years of backend work."})
        page = self.screen("?screen=1")
        self.assertIn('<span class="claimkey">Add a claim</span>', page)
        self.assertIn("<b>For example</b>", page)
        # Placement is the whole finding: each rule has to sit by the box it
        # is true of, or the two sentences have simply swapped the lie.
        self.assertLess(page.index("A box is one claim; line breaks stay "
                                   "inside it."),
                        page.index('name="claim__background__'))
        self.assertLess(page.index('name="new__background"'),
                        page.index("Each line becomes its own claim."))


class OneForwardActionTest(WizardFixture):
    """F4: Save is the only way forward, and saving nothing costs nothing.

    The forward pill sat outside the `<form>`, forty pixels under the submit
    button, wearing the same arrow; pressing it after typing discarded the
    typing without a word. Dropping it is only safe because a screen
    submitted untouched writes no rows and still moves the learner on, so
    that property is asserted here rather than assumed.
    """

    def test_the_only_forward_link_is_the_submit_button(self):
        page = self.screen("?screen=2")
        self.assertIn("Save this screen →", page)
        self.assertIn('<a class="back" href="/onboarding/?screen=1">', page)
        self.assertNotIn('href="/onboarding/?screen=3"', page)

    def test_saving_an_untouched_screen_writes_nothing_and_moves_on(self):
        before = len(self.profile_rows())
        posted = self.save("2", {"new__style": "", "new__domain_bias": "",
                                 "new__pacing": ""})
        self.assertEqual(posted.status_code, 303)
        self.assertEqual(posted.headers["location"], "/onboarding/?screen=3")
        self.assertEqual(len(self.profile_rows()), before)


class ScreenFourForwardActionTest(WizardFixture):
    """F4's worst case, on its own tenant because it needs a met gate.

    Screen 4 carried three ways to the review at once: the Save button, a
    "Review and publish →" pill in the nav row, and a second copy of the
    same link trailing the gate sentence. Save is the whole of it now.
    """

    def test_the_review_is_reached_by_saving_and_by_nothing_else(self):
        self.satisfy_the_gate()
        self.assertEqual(
            onboarding.profile_gate_missing(self.profile_state()), ())
        page = self.screen("?screen=4")
        self.assertIn("Save this screen →", page)
        self.assertIn('<a class="back" href="/onboarding/?screen=3">', page)
        self.assertNotIn('href="/onboarding/?screen=review"', page)
        self.assertNotIn("Review and publish", page)
        # ...and Save is genuinely that way through.
        posted = self.save("4", {"new__subject_adapters": ""})
        self.assertEqual(posted.headers["location"], "/onboarding/?screen=review")


class ProfileFormRoundTripTest(WizardFixture):
    """A screen saved is claims on the ledger, in the learner's own voice."""

    def test_two_new_lines_become_two_attested_claims(self):
        saved = self.save("1", {"new__background": "Eight years of Go.\n\n"
                                                   "Twenty of Python.\n"})
        self.assertEqual(saved.status_code, 303)
        self.assertEqual(saved.headers["location"], "/onboarding/?screen=2")
        rows = self.profile_rows()
        self.assertEqual([(r.kind, r.field, r.key) for r in rows],
                         [("assert", "background", "background-01"),
                          ("assert", "background", "background-02")])
        for row in rows:
            with self.subTest(key=row.key):
                # The tier comes from provenance — you said it — and the form
                # names no source, because the source is the person posting.
                self.assertEqual(row.payload["tier"], "attested")
                self.assertIsNone(row.payload.get("source"))
        # The agent proposes and the human publishes; a form is the human,
        # so a round trip through it leaves no proposal to review.
        self.assertEqual([r for r in rows if r.kind == "propose"], [])
        page = self.screen("?screen=1")
        self.assertIn('name="claim__background__background-01"', page)
        self.assertIn("Eight years of Go.", page)
        self.assertIn("Twenty of Python.", page)

    def test_an_unknown_screen_number_is_not_a_screen(self):
        for number in ("5", "0", "review", "welcome"):
            with self.subTest(number=number):
                self.assertEqual(self.save(number, {}).status_code, 404)

    def test_a_body_this_form_cannot_read_is_refused(self):
        # Refusing beats guessing: a body in another encoding, or bytes that
        # are not text at all, both parse to no boxes — and no boxes is
        # indistinguishable from a screen cleared of every claim on it.
        json_body = self.client.post("/onboarding/profile/1",
                                     json={"new__background": "smuggled"},
                                     follow_redirects=False)
        self.assertEqual(json_body.status_code, 415)
        not_text = self.client.post(
            "/onboarding/profile/1", content=b"new__background=\xff\xfe",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False)
        self.assertEqual(not_text.status_code, 415)
        self.assertEqual(self.profile_rows(), [])


class ProposedKeyIsSpentTest(WizardFixture):
    """A number an agent has offered is spent too, accepted or not.

    The MCP tools can propose on any (field, key), and an accepted proposal
    becomes a claim with no `assert` row anywhere behind it. Minting only
    over asserts would hand that live claim's identity to a new sentence and
    supersede it without a word — the failure the "keys are forever" rule
    exists to prevent, arriving from the other producer.
    """

    def test_the_form_never_mints_over_an_accepted_proposal(self):
        for kind, payload in (("propose", {"text": "reaches it through "
                                                   "failure modes",
                                           "tier": "thin",
                                           "source": "tutor/session-3"}),
                              ("accept", {})):
            with self.engine.begin() as conn:
                profile.append_profile_event(conn, self.scope, kind, "style",
                                             "style-01", payload)
        self.assertEqual(self.save("2", {"new__style": "learns by "
                                                       "implementing"})
                         .status_code, 303)
        claims = self.profile_state().field_claims("style")
        self.assertEqual([(c.key, c.text) for c in claims],
                         [("style-01", "reaches it through failure modes"),
                          ("style-02", "learns by implementing")])


class ClaimEscapingTest(WizardFixture):
    """A claim is the one thing on a form screen that came from outside it."""

    def test_a_claim_is_escaped_where_it_is_read_back(self):
        self.save("2", {"new__style": 'show me <b>the code</b> & the trace'})
        page = self.screen("?screen=2")
        self.assertIn("show me &lt;b&gt;the code&lt;/b&gt; &amp; the trace", page)
        self.assertNotIn("<b>the code</b>", page)


class KeyMintingTest(WizardFixture):
    """Keys are forever: a number that has named a claim is spent."""

    def test_a_retracted_number_is_never_minted_again(self):
        self.save("1", {"new__background": "first\nsecond"})
        # Delete one from the middle and add another in the same save.
        self.save("1", {"claim__background__background-01": "",
                        "claim__background__background-02": "second",
                        "new__background": "third"})
        # Then delete the *highest* number, in a save of its own — the case
        # that tells the two candidate rules apart. The fold, asked
        # afterwards, has never heard of background-03 and would hand its
        # number straight back out; the ledger has not forgotten it.
        self.save("1", {"claim__background__background-02": "second",
                        "claim__background__background-03": ""})
        self.save("1", {"claim__background__background-02": "second",
                        "new__background": "fourth"})
        # Asserted against the rows, not the fold: the whole rule is about
        # the ledger remembering what the fold has dropped.
        self.assertEqual([(r.kind, r.key) for r in self.profile_rows()],
                         [("assert", "background-01"),
                          ("assert", "background-02"),
                          ("retract", "background-01"),
                          ("assert", "background-03"),
                          ("retract", "background-03"),
                          ("assert", "background-04")])
        claims = self.profile_state().field_claims("background")
        self.assertEqual([(c.key, c.text) for c in claims],
                         [("background-02", "second"),
                          ("background-04", "fourth")])


class ClaimEditTest(WizardFixture):
    """Editing a box re-asserts its key; leaving it alone writes nothing."""

    def test_a_changed_box_supersedes_and_an_unchanged_one_is_silent(self):
        self.save("2", {"new__pacing": "four hours a week"})
        self.save("2", {"claim__pacing__pacing-01": "two hours a week"})
        self.assertEqual([(r.kind, r.key) for r in self.profile_rows()],
                         [("assert", "pacing-01"), ("assert", "pacing-01")])
        claims = self.profile_state().field_claims("pacing")
        self.assertEqual([(c.key, c.text) for c in claims],
                         [("pacing-01", "two hours a week")])
        self.save("2", {"claim__pacing__pacing-01": "two hours a week"})
        self.assertEqual(len(self.profile_rows()), 2)


class MetaDescriptionTest(WizardFixture):
    """Screen 1's description line writes the key the projection reads."""

    def test_the_description_is_never_a_minted_key(self):
        self.save("1", {"claim__meta__description": "Learning profile for a "
                                                    "fictional tester."})
        self.assertEqual([(r.field, r.key) for r in self.profile_rows()],
                         [("meta", "description")])
        self.assertIn("Learning profile for a fictional tester.",
                      self.screen("?screen=1"))
        self.save("1", {"claim__meta__description": ""})
        self.assertEqual([(r.kind, r.key) for r in self.profile_rows()],
                         [("assert", "description"), ("retract", "description")])


class GateDisplayTest(WizardFixture):
    """The gate, in words on every form screen — shown here, enforced later."""

    def test_the_missing_required_fields_are_named(self):
        # Screen 2 asks for two of the four, so the sentence itself is read
        # rather than the page: a label on a form is not the gate speaking.
        gate = self.screen("?screen=2").split(wizard.GATE_LEAD)[1][:300]
        for field in onboarding.REQUIRED_PROFILE_FIELDS:
            with self.subTest(field=field):
                self.assertIn(wizard.FIELD_LABELS[field], gate)
        self.save("1", {"new__background": "eight years of backend work"})
        self.save("2", {"new__style": "learns by implementing",
                        "new__pacing": "four hours a week"})
        self.save("3", {"new__calibration": "the failure first, then the "
                                            "formal statement"})
        self.assertEqual(onboarding.profile_gate_missing(self.profile_state()), ())
        for number in ("1", "2", "3", "4"):
            with self.subTest(screen=number):
                page = self.screen(f"?screen={number}")
                self.assertNotIn(wizard.GATE_LEAD, page)
                # A satisfied gate says so and stops there. It used to trail
                # a second "Review and publish →" link, which was a third
                # forward route on a screen whose one forward action is Save
                # (F4); the sentence is the whole of what this line says now.
                self.assertIn("has a claim on the record", page)
                self.assertNotIn("Review and publish", page)


class ClosedScreenRefusesTest(WizardFixture):
    """O1 for a write: a published profile never re-gates, so it never
    re-saves either."""

    def test_posting_a_form_after_publishing_is_refused(self):
        self.assertEqual(self.save("1", {"new__background": "before"}).status_code,
                         303)
        self.append("profile_published")
        self.assertEqual(self.save("1", {"new__background": "after"}).status_code,
                         409)
        self.assertEqual([r.payload["text"] for r in self.profile_rows()],
                         ["before"])


class ReviewScreenTest(WizardFixture):
    """Stop 5 shows the artifact itself, whole, under design §4's caption."""

    def test_the_projection_is_the_page(self):
        self.satisfy_the_gate()
        page = self.screen("?screen=review")
        self.assertIn(wizard.REVIEW_CAPTION, page)
        # The exact document, not a second rendering of the same claims: what
        # is on the screen is `render_skill_md` and the escaping, and nothing
        # else has had an opinion about it.
        projection = profilerender.render_skill_md(self.profile_state())
        start = page.index('<pre class="projection">')
        pre = page[start:page.index("</pre>", start)]
        self.assertIn(html.escape(projection), pre)
        self.assertIn("Learns by implementing", pre)
        # Edit loops back to the forms; the styled view of the same claims is
        # a link away; and the gate is met, so the confirm form is drawn.
        self.assertIn('href="/onboarding/?screen=1"', page)
        self.assertIn("See it as a page", page)
        self.assertIn('action="/onboarding/profile/publish"', page)

    def test_a_claim_is_escaped_inside_the_projection(self):
        # The document is a learner's sentences top to bottom, and the review
        # screen is the one place they are read back as markup.
        self.save("4", {"new__subject_adapters": "assume <b>engineering</b> "
                                                 "judgment & weak formalism"})
        page = self.screen("?screen=review")
        self.assertIn("assume &lt;b&gt;engineering&lt;/b&gt; judgment &amp; "
                      "weak formalism", page)
        self.assertNotIn("<b>engineering</b>", page)


class ReviewGateTest(WizardFixture):
    """The gate at the review: named in words, and enforced at the POST."""

    def test_an_unmet_gate_names_the_field_and_draws_no_button(self):
        # Three of the four required fields — the fourth is the test.
        self.save("2", {"new__style": "learns by implementing",
                        "new__pacing": "four hours a week"})
        self.save("3", {"new__calibration": "the failure first"})
        self.assertEqual(onboarding.profile_gate_missing(self.profile_state()),
                         ("background",))
        page = self.screen("?screen=review")
        self.assertIn(wizard.GATE_LEAD, page)
        self.assertIn(wizard.FIELD_LABELS["background"], page)
        self.assertNotIn("/onboarding/profile/publish", page)

    def test_publishing_under_an_unmet_gate_is_refused(self):
        # A button that is absent from a page is not a rule: the POST asks
        # `profile_gate_missing` for itself, and refuses in the same words.
        refused = self.client.post("/onboarding/profile/publish",
                                   follow_redirects=False)
        self.assertEqual(refused.status_code, 422)
        self.assertIn(wizard.FIELD_LABELS["background"], refused.text)
        self.assertEqual(self.onboarding_rows(), [])
        self.assertEqual(self.current_stop(), "profile")


class PublishProfileTest(WizardFixture):
    """One row saying publishing happened — and never a word of a claim."""

    def test_publishing_moves_the_fold_and_opens_the_rest_of_the_setup(self):
        self.satisfy_the_gate()
        published = self.client.post("/onboarding/profile/publish",
                                     follow_redirects=False)
        self.assertEqual(published.status_code, 303, published.text)
        self.assertEqual(published.headers["location"], "/onboarding/")
        # The onboarding ledger records position, never content (design §5):
        # one row, no course, and an empty payload holding no claim.
        rows = self.onboarding_rows()
        self.assertEqual([(r.kind, r.course, r.payload) for r in rows],
                         [("profile_published", "", {})])
        self.assertEqual(self.current_stop(), "scope")
        # The gate from issue 05 stops firing, for the front door and for the
        # wizard alike: what /onboarding/ shows now is the next stop.
        self.assertEqual(self.client.get("/", follow_redirects=False)
                         .status_code, 200)
        self.assertIn(wizard.STOP_TITLES["scope"], self.screen())
        # Asserted in the same test because it is the same one-way ledger:
        # O1 for a write, from a tab that still has the button on it.
        again = self.client.post("/onboarding/profile/publish",
                                 follow_redirects=False)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.onboarding_rows()), 1)


class ProjectionHookTest(unittest.TestCase):
    """The installed SKILL.md follows the ledger, and only when configured.

    The target is a temp path in every one of these, and the rule that says
    so is older than the wizard: `~/.claude/skills/learner-profile/SKILL.md`
    is a real person's real file, and a test that wrote to it would be the
    hand-editing this projection exists to retire, done by a machine.
    """

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        cls.engine = test_engine()
        cls.tmp = tempfile.TemporaryDirectory(prefix="curricle-skill-")
        cls.out = os.path.join(cls.tmp.name, "SKILL.md")
        cls.slug = "wizard-hook"
        with cls.engine.begin() as conn:
            db.create_tenant(conn, cls.slug)
        cls.client = TestClient(webapp.create_app(
            [], tenant_slug=cls.slug, database_url=str(cls.engine.url),
            profile_skill_out=cls.out))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def installed(self) -> str:
        with open(self.out, encoding="utf-8") as f:
            return f.read()

    def test_the_target_is_a_temp_path_and_never_the_real_skill_file(self):
        self.assertTrue(self.out.startswith(tempfile.gettempdir()))
        self.assertFalse(self.out.startswith(os.path.expanduser("~/.claude")))

    def test_a_claim_through_the_api_re_renders_the_projection(self):
        posted = self.client.post("/api/profile/events", json={
            "kind": "assert", "field": "pacing", "key": "pacing-01",
            "payload": {"text": "four hours a week, two evenings",
                        "tier": "attested"}})
        self.assertEqual(posted.status_code, 200, posted.text)
        self.assertIn("four hours a week, two evenings", self.installed())

    def test_a_wizard_save_re_renders_the_projection(self):
        self.client.post("/onboarding/profile/1",
                         data={"new__background": "eight years of backend work"},
                         follow_redirects=False)
        installed = self.installed()
        self.assertIn("eight years of backend work", installed)
        # Whole, not partial: the file is a complete render, which is what
        # the temp-file-and-rename buys. And no debris beside it — a writer
        # that left its temp files would be one that had not renamed them.
        self.assertTrue(installed.startswith("---\nname: learner-profile"))
        self.assertTrue(installed.rstrip().endswith("re-render.*"))
        self.assertEqual(os.listdir(self.tmp.name), ["SKILL.md"])

    def test_publishing_re_renders_too(self):
        # Publishing writes no claim, so the render is the same bytes as the
        # last one — unconditional and idempotent beats a rule about which
        # events could have moved the fold.
        for number, boxes in (("1", {"new__background": "backend work"}),
                              ("2", {"new__style": "learns by implementing",
                                     "new__pacing": "four hours a week"}),
                              ("3", {"new__calibration": "the failure first"})):
            self.client.post(f"/onboarding/profile/{number}", data=boxes,
                             follow_redirects=False)
        before = self.installed()
        published = self.client.post("/onboarding/profile/publish",
                                     follow_redirects=False)
        self.assertEqual(published.status_code, 303, published.text)
        self.assertEqual(self.installed(), before)
        self.assertEqual(os.listdir(self.tmp.name), ["SKILL.md"])


class ProjectionHookOffTest(unittest.TestCase):
    """Default: off. No path, no file, anywhere."""

    def test_an_unconfigured_app_writes_no_projection(self):
        import inspect

        self.assertIsNone(inspect.signature(webapp.create_app)
                          .parameters["profile_skill_out"].default)
        engine = test_engine()
        with tempfile.TemporaryDirectory(prefix="curricle-skill-") as empty:
            # Nothing points here; the directory is the witness that the hook
            # does not go looking for somewhere to write when nobody has said
            # where. A default that had quietly become the real skill file
            # would fail on the line above instead.
            c = client(engine, "wizard-hook-off")
            posted = c.post("/api/profile/events", json={
                "kind": "assert", "field": "pacing", "key": "pacing-01",
                "payload": {"text": "four hours a week", "tier": "attested"}})
            self.assertEqual(posted.status_code, 200, posted.text)
            self.assertEqual(c.post("/onboarding/profile/1",
                                    data={"new__background": "backend work"},
                                    follow_redirects=False).status_code, 303)
            self.assertEqual(os.listdir(empty), [])


class StatusRouteTest(WizardFixture):
    """The waiting screens' poll: three fields off the same fold.

    The route exists so that eleven minutes of building is eleven minutes of
    a page holding still rather than a hundred and thirty full reloads. What
    it returns is what a waiting page needs to know whether anything has
    happened, and nothing else — no course content, no payloads, no plan.
    """

    def test_the_status_is_the_fold_in_three_fields(self):
        self.assertEqual(self.client.get("/onboarding/status").json(),
                         {"stop": "profile", "status": "waiting",
                          "elapsed": "just started"})
        self.append("profile_published")
        self.append("scope_saved", "greek-120", {"title": "Greek"})
        self.append("outline_requested", "greek-120")
        status = self.client.get("/onboarding/status")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.headers["content-type"], "application/json")
        self.assertEqual(status.json(),
                         {"stop": "outline", "status": "pending",
                          "elapsed": "less than a minute elapsed"})

    def test_then_the_answer_moves_when_the_fold_does(self):
        # Named to run after the outline above: the fold moves, and so does
        # the answer — which is the whole of what the script watches for.
        self.append("outline_ready", "greek-120",
                    {"plan": {"phase_id": "p1"}, "estimate_usd": "1.10"})
        self.assertEqual(self.client.get("/onboarding/status").json()["stop"],
                         "outline_gate")
        self.assertEqual(self.client.get("/onboarding/status").json()["status"],
                         "waiting")


class StatusRouteIsScopedTest(unittest.TestCase):
    """T5, on the newest route: one app, one tenant, one answer.

    Two apps over the same database, each built for its own tenant. The
    route takes no argument naming a tenant and could not be pointed at
    another one if it did — the scope is the app's, resolved at startup.
    """

    def test_each_apps_status_is_its_own_tenants(self):
        engine = test_engine()
        mine = client(engine, "wizard-status-mine")
        theirs = client(engine, "wizard-status-theirs")
        with engine.begin() as conn:
            scope = db.for_tenant(db.tenant_id_for(conn, "wizard-status-mine"))
            onboarding.append_event(conn, scope, "profile_published", "", {})
            onboarding.append_event(conn, scope, "scope_saved", "mine",
                                    {"title": "Mine"})
            onboarding.append_event(conn, scope, "outline_requested",
                                    "mine", {})
        self.assertEqual(mine.get("/onboarding/status").json()["stop"],
                         "outline")
        self.assertEqual(theirs.get("/onboarding/status").json()["stop"],
                         "profile")


class WaitingScreenPollTest(WizardFixture):
    """F12/F25: the page holds still, and the meta refresh is the fallback.

    The rule the wizard keeps is that the *forms* carry no JavaScript — "the
    page a learner types into". A waiting screen has no inputs, and a full
    reload every five seconds under an eleven-minute wait resets scroll,
    selection and focus every time, which `prefers-reduced-motion` cannot
    govern. So this screen polls, swaps the elapsed line in place, and
    navigates only when the ledger says there is another screen to be on.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        walked = (("profile_published", ""), ("scope_saved", "greek-121"),
                  ("outline_requested", "greek-121"))
        with cls.engine.begin() as conn:
            for kind, course in walked:
                onboarding.append_event(conn, cls.scope, kind, course,
                                        {"title": "Greek"} if course else {})

    def test_a_watching_screen_polls_and_falls_back_to_the_meta_tag(self):
        page = self.screen()
        self.assertIn(wizard.NOSCRIPT_REFRESH, page)
        self.assertIn('content="30"', page)
        self.assertIn(wizard.POLL_JS, page)
        # The two facts the script compares against, from the fold the page
        # was drawn from — not spliced into the script's source.
        self.assertIn('data-stop="outline"', page)
        self.assertIn('data-status="pending"', page)
        self.assertIn('id="wait-elapsed"', page)

    def test_the_script_asks_the_route_that_exists(self):
        # Two spellings of one path — the route's and the script's literal —
        # held together here rather than by hope.
        self.assertIn(wizard.STATUS_PATH, wizard.POLL_JS)
        self.assertEqual(self.client.get(wizard.STATUS_PATH).status_code, 200)

    def test_then_a_screen_that_is_not_waiting_carries_neither(self):
        # The polling stops by construction, script or no script.
        self.append("outline_ready", "greek-121",
                    {"plan": {"phase_id": "p1"}, "estimate_usd": "1.10"})
        page = self.screen()
        self.assertNotIn(wizard.META_REFRESH, page)
        self.assertNotIn("<script", page)
        self.assertNotIn('id="wait-elapsed"', page)


class SpendTest(unittest.TestCase):
    """The receipt's arithmetic, over rows from the two ledgers.

    The token ledger has no course column, so what a course cost is the
    metered rows inside that course's own window in the onboarding ledger,
    split at the approval. This is that windowing, on synthetic rows: a
    stage bought before the course started, one after it was published, and
    the two the course actually paid for.
    """

    @staticmethod
    def rows(*pairs):
        from types import SimpleNamespace
        return [SimpleNamespace(kind=kind, created_at=when)
                for kind, when in pairs]

    @staticmethod
    def ledger(*pairs):
        from decimal import Decimal
        from types import SimpleNamespace
        return [SimpleNamespace(cost_usd=Decimal(cost), created_at=when)
                for cost, when in pairs]

    def setUp(self):
        from datetime import datetime, timedelta, timezone
        self.t0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self.at = lambda minutes: self.t0 + timedelta(minutes=minutes)

    def test_the_split_is_the_approval_and_the_window_is_the_course(self):
        from decimal import Decimal
        spend = wizard.course_spend(
            self.rows(("scope_saved", self.at(0)),
                      ("outline_requested", self.at(1)),
                      ("outline_ready", self.at(7)),
                      ("outline_approved", self.at(9)),
                      ("promoted", self.at(21))),
            self.ledger(("0.40", self.at(-30)),    # another course, earlier
                        ("0.91", self.at(3)),      # the designer
                        ("0.18", self.at(6)),      # the curator
                        ("2.02", self.at(15)),     # the build
                        ("5.00", self.at(40))))    # another course, later
        self.assertEqual(spend.drafts, 1)
        self.assertEqual(spend.draft, Decimal("1.09"))
        self.assertEqual(spend.build, Decimal("2.02"))
        self.assertEqual(spend.total, Decimal("3.11"))

    def test_before_the_approval_everything_is_drafting(self):
        # Two drafts and a rejection between them: money spent answering a
        # note is money spent drafting, and the gate says so before the
        # decision rather than after it. The figure is both drafts, so the
        # sentence that prints it counts them rather than calling the sum
        # the cost of "this outline".
        from decimal import Decimal
        spend = wizard.course_spend(
            self.rows(("scope_saved", self.at(0)),
                      ("outline_requested", self.at(1)),
                      ("outline_rejected", self.at(8)),
                      ("outline_requested", self.at(9))),
            self.ledger(("1.09", self.at(4)), ("1.05", self.at(12))))
        self.assertEqual(spend.draft, Decimal("2.14"))
        self.assertEqual(spend.build, Decimal(0))
        self.assertEqual(spend.drafts, 2)

    def test_a_course_with_no_rows_totals_nothing_rather_than_everything(self):
        from decimal import Decimal
        spend = wizard.course_spend([], self.ledger(("9.99", self.at(1))))
        self.assertEqual((spend.draft, spend.build, spend.total),
                         (Decimal(0), Decimal(0), Decimal(0)))

    def test_the_total_is_the_two_printed_figures_added(self):
        # A total rounded from the raw sum can come out a cent away from the
        # two figures printed beside it; a receipt whose own arithmetic does
        # not check is worse than no receipt.
        from decimal import Decimal
        spend = wizard.Spend(Decimal("1.085"), Decimal("2.015"))
        self.assertEqual(wizard.dollars(spend.draft), "$1.09")
        self.assertEqual(wizard.dollars(spend.build), "$2.02")
        self.assertEqual(wizard.dollars(spend.total), "$3.11")

    def test_the_receipt_names_the_estimate_it_was_approved_at(self):
        from decimal import Decimal
        line = wizard.receipt_line(wizard.Spend(Decimal("1.09"),
                                                Decimal("2.02")), "1.70")
        self.assertIn("<b>$3.11</b>", line)
        self.assertIn("$1.09 to draft", line)
        self.assertIn("$2.02 to build", line)
        self.assertIn("approved at about $1.70", line)

    def test_a_ledger_with_nothing_in_it_says_so_rather_than_zeroes(self):
        from decimal import Decimal
        self.assertEqual(wizard.receipt_line(wizard.Spend(Decimal(0),
                                                          Decimal(0)), "1.70"),
                         wizard.RECEIPT_NONE)


class StateChipTest(unittest.TestCase):
    """Design §5: always mark *and* word, never one without the other.

    Color is the reinforcement here, so the word is checked and the tint is
    not: a screen read with every color stripped out of it still says which
    of the waits it is in.
    """

    def test_every_status_chip_carries_a_mark_and_a_word(self):
        for status, word in (("pending", wizard.PENDING_WORD),
                             ("waiting", wizard.WAITING_WORD),
                             ("failed", wizard.FAILED_WORD)):
            with self.subTest(status=status):
                chip = wizard._chip(status)
                self.assertIn("<svg", chip)
                self.assertIn(word, chip)


class ElapsedWordsTest(unittest.TestCase):
    """Elapsed time in words — the one number this screen is allowed."""

    def test_reads_from_seconds_to_hours(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cases = {
            # Under a minute is words, not a figure: a second-precision
            # count is precision a page refreshed every five seconds cannot
            # keep, and it read as a stuck clock when it tried.
            timedelta(seconds=3): "less than a minute elapsed",
            timedelta(seconds=59): "less than a minute elapsed",
            timedelta(seconds=61): "1 minute elapsed",
            timedelta(minutes=9): "9 minutes elapsed",
            timedelta(hours=1, minutes=1): "1 hour 1 minute elapsed",
            timedelta(hours=3, minutes=20): "3 hours 20 minutes elapsed",
        }
        for delta, words in cases.items():
            with self.subTest(delta=delta):
                self.assertEqual(wizard.elapsed_words(now - delta), words)

    def test_a_flow_with_no_row_time_invents_no_duration(self):
        self.assertEqual(wizard.elapsed_words(None), "just started")


if __name__ == "__main__":
    unittest.main()
