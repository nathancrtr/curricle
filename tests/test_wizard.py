"""The wizard shell: the gate, the derived screen, and the two invariants.

Everything here runs against the throwaway Postgres of tests/pg.py through
a real `TestClient`, because all three things worth testing are properties
of the running app rather than of a function: a redirect decided by two
queries, a screen chosen by the fold, and a failure sentence that reached a
page from a wording table instead of from an exception.

Two tenants per fixture (T5): an app is built per tenant, so a screen drawn
for one of them can never be a screen drawn from the other's ledger.
"""

import html
import os
import tempfile
import unittest

from curricle import db, onboarding, profile, profilerender, webapp, wizard

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
                self.assertIn("Review and publish", page)


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
