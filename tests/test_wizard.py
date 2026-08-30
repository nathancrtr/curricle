"""The wizard shell: the gate, the derived screen, and the two invariants.

Everything here runs against the throwaway Postgres of tests/pg.py through
a real `TestClient`, because all three things worth testing are properties
of the running app rather than of a function: a redirect decided by two
queries, a screen chosen by the fold, and a failure sentence that reached a
page from a wording table instead of from an exception.

Two tenants per fixture (T5): an app is built per tenant, so a screen drawn
for one of them can never be a screen drawn from the other's ledger.
"""

import os
import unittest

from curricle import db, onboarding, webapp, wizard

from pg import test_engine
# The lock a live worker holds, taken here by a detached session so the
# welcome banner can be tested in both of its states.
from test_worker import session

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TINYLANG = os.path.join(REPO_ROOT, "examples", "tinylang")


def client(engine, slug: str, roots: list[str] | None = None):
    """A test client for a fresh tenant, serving `roots` (usually none)."""
    from fastapi.testclient import TestClient

    with engine.begin() as conn:
        db.create_tenant(conn, slug)
    return TestClient(webapp.create_app(roots or [], tenant_slug=slug,
                                        database_url=str(engine.url)))


class WizardFixture(unittest.TestCase):
    """One courseless tenant with an app in front of it. No tests of its own."""

    ROOTS: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        cls.slug = f"wizard-{cls.__name__}"
        cls.client = client(cls.engine, cls.slug, cls.ROOTS)
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
        for screen in wizard.PROFILE_SCREENS:
            with self.subTest(screen=screen):
                self.assertEqual(
                    self.client.get(f"/onboarding/?screen={screen}").status_code,
                    200)
        self.assertIn("Read it back before you publish",
                      self.screen("?screen=review"))
        self.assertIn("Profile, screen 3 of 4", self.screen("?screen=3"))

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
        self.assertIn("seconds elapsed", page)          # elapsed, never a forecast
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
        self.assertNotIn('<span class="elapsed">', page)


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
            timedelta(seconds=3): "3 seconds elapsed",
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
