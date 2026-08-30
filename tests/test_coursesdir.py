"""The managed courses home, and the courses that appear in it while serving.

Two things are under test and only one of them is about directories. The
first is the configuration posture: `CURRICLE_COURSES_DIR` has no default,
exactly like the database URL, because a guessed courses home serves the
wrong tree as confidently as the right one. These tests patch the
environment rather than reading it — the suite must not behave differently
on a machine where the author happens to have exported the variable.

The second is the gate. A course reaches the app three ways now — a
`--course` flag at startup, the home read at startup, and the home re-read
mid-run when a route misses or the front door draws — and every one of them
has to be the same gate: `load_course` compiles, and a course that does not
compile is an absence. So the compile failure below is checked from both
directions, the route *and* the page, since a rule enforced on one surface
and forgotten on the other is how a broken course gets published.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from curricle import coursehome, db, onboarding, webapp

from pg import test_engine

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TINYLANG = os.path.join(REPO_ROOT, "examples", "tinylang")


def plant(dir_path: str, name: str, *, course_id: str | None = None,
          broken: bool = False) -> str:
    """Copy the example course into `dir_path/name` as a course directory.

    `course_id` renames it — the lazy-registration path looks a slug up by
    directory name, so a second copy needs an identity of its own. `broken`
    points a material at a file that isn't there, which is a compile error
    (not a loader crash): the gate under test is the compiler's verdict.
    """
    root = os.path.join(dir_path, name)
    shutil.copytree(TINYLANG, root)
    sidecar = os.path.join(root, "learning", "course.yaml")
    with open(sidecar, encoding="utf-8") as f:
        text = f.read()
    if course_id:
        text = text.replace("\n  id: tinylang\n", f"\n  id: {course_id}\n", 1)
    if broken:
        text = text.replace("path: interactive/lessons/unit-01-lexer.md",
                            "path: interactive/lessons/not-here.md", 1)
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write(text)
    return root


class ConfigurationTest(unittest.TestCase):
    """No default — an unconfigured caller gets an exception, not a guess."""

    def test_courses_dir_refuses_to_invent_one(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as caught:
                coursehome.courses_dir()
        self.assertIn(coursehome.ENV_DIR, str(caught.exception))
        self.assertIn("no default", str(caught.exception).lower())

    def test_maybe_courses_dir_is_none_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(coursehome.maybe_courses_dir())

    def test_an_empty_value_is_not_configuration(self):
        # Exporting the name and leaving it blank is the same as not having
        # decided, and reads back as a directory called "" if believed.
        with mock.patch.dict(os.environ, {coursehome.ENV_DIR: ""}):
            self.assertIsNone(coursehome.maybe_courses_dir())
            with self.assertRaises(RuntimeError):
                coursehome.courses_dir()

    def test_a_configured_home_is_returned_by_both(self):
        with mock.patch.dict(os.environ, {coursehome.ENV_DIR: "/tmp/courses"}):
            self.assertEqual(coursehome.courses_dir(), "/tmp/courses")
            self.assertEqual(coursehome.maybe_courses_dir(), "/tmp/courses")


class CourseRootsTest(unittest.TestCase):
    """What counts as a course directory: a subdirectory with a sidecar."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="curricle-home-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_finds_a_course_and_skips_everything_else(self):
        course = plant(self.tmp, "tinylang")
        # A directory that is nothing in particular.
        os.makedirs(os.path.join(self.tmp, "notes"))
        # A course mid-creation: the wizard has made its home and dropped a
        # draft in it, and nothing else. A draft is not a course.
        os.makedirs(os.path.join(self.tmp, "half-built", ".draft-onboarding"))
        with open(os.path.join(self.tmp, "half-built", ".draft-onboarding",
                               "scope.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        # And the file every macOS directory grows on its own.
        with open(os.path.join(self.tmp, ".DS_Store"), "wb") as f:
            f.write(b"\x00")
        self.assertEqual(coursehome.course_roots(self.tmp), [course])

    def test_a_root_level_sidecar_counts_too(self):
        # load_course looks in both places; so does this, or a course whose
        # content lives at the repo root would be invisible here and served
        # from a --course flag, which is a difference nobody could explain.
        root = os.path.join(self.tmp, "flat")
        os.makedirs(root)
        with open(os.path.join(root, "course.yaml"), "w", encoding="utf-8") as f:
            f.write("sidecar_version: 1\n")
        self.assertEqual(coursehome.course_roots(self.tmp), [root])

    def test_the_order_is_by_name(self):
        plant(self.tmp, "zeta", course_id="zeta")
        plant(self.tmp, "alpha", course_id="alpha")
        self.assertEqual([os.path.basename(r)
                          for r in coursehome.course_roots(self.tmp)],
                         ["alpha", "zeta"])

    def test_a_home_that_does_not_exist_yet_is_empty_not_an_error(self):
        # The home is created by whoever writes the first course into it;
        # serving before that happens is an ordinary empty instance.
        self.assertEqual(
            coursehome.course_roots(os.path.join(self.tmp, "nope")), [])


class ServedFromTheHomeTest(unittest.TestCase):
    """The app's two sources of courses, and the gate they share."""

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="curricle-home-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def client(self, roots: list[str], slug: str, courses_dir: str | None):
        from fastapi.testclient import TestClient

        with self.engine.begin() as conn:
            tenant = db.create_tenant(conn, slug)
            # Past onboarding, deliberately: the wizard's gate redirects a
            # tenant who has neither a course nor a published profile, and
            # every case below is about a course arriving (or refusing to)
            # for someone already set up. The gate is tested where it lives,
            # in tests/test_wizard.py.
            onboarding.append_event(conn, db.for_tenant(tenant),
                                    "profile_published", "")
        return TestClient(webapp.create_app(
            roots, tenant_slug=slug, database_url=str(self.engine.url),
            courses_dir=courses_dir))

    def test_a_course_in_the_home_is_served_from_startup(self):
        plant(self.tmp, "tinylang")
        c = self.client([], "home-startup", self.tmp)
        page = c.get("/")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('href="/c/tinylang/"', page.text)
        hub = c.get("/c/tinylang/index.html")
        self.assertEqual(hub.status_code, 200, hub.text)
        self.assertIn("Interpreters, end to end", hub.text)

    def test_a_course_added_after_startup_is_served_on_the_next_request(self):
        c = self.client([], "home-lazy-route", self.tmp)
        self.assertEqual(c.get("/c/second/").status_code, 404)
        plant(self.tmp, "second", course_id="second")
        hit = c.get("/c/second/")
        self.assertEqual(hit.status_code, 200, hit.text)
        self.assertIn("Interpreters, end to end", hit.text)

    def test_a_course_added_after_startup_appears_on_the_front_door(self):
        c = self.client([], "home-lazy-door", self.tmp)
        self.assertIn("No courses are configured yet", c.get("/").text)
        plant(self.tmp, "second", course_id="second")
        page = c.get("/")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('href="/c/second/"', page.text)
        self.assertNotIn("No courses are configured yet", page.text)

    def test_a_loaded_course_is_never_recompiled_to_draw_a_card(self):
        # The rescan is per request; the compile is not. Nothing here is
        # cached deliberately enough to survive a "just recompile it" patch,
        # so the count is pinned.
        plant(self.tmp, "tinylang")
        c = self.client([], "home-no-recompile", self.tmp)
        with mock.patch.object(webapp, "load_course",
                               wraps=webapp.load_course) as spy:
            c.get("/")
            c.get("/")
            c.get("/c/tinylang/index.html")
        self.assertEqual(spy.call_count, 0)

    def test_a_course_that_does_not_compile_is_never_served(self):
        # Arriving mid-run, the way a promotion would drop it: the lazy
        # paths are the ones that have to swallow the refusal into absence.
        c = self.client([], "home-broken", self.tmp)
        plant(self.tmp, "broken", course_id="broken", broken=True)
        noise = io.StringIO()
        with contextlib.redirect_stderr(noise):
            self.assertEqual(c.get("/c/broken/").status_code, 404)
            self.assertEqual(c.get("/c/broken/index.html").status_code, 404)
            page = c.get("/")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertNotIn("/c/broken/", page.text)
        self.assertIn("No courses are configured yet", page.text)
        # Absent from the page, but not absent from the operator's terminal:
        # a course that vanishes without a word is indistinguishable from a
        # course the server never noticed.
        self.assertIn("not registered", noise.getvalue())
        self.assertIn("does not compile", noise.getvalue())

    def test_a_directory_whose_course_id_is_not_its_name_is_not_served_as_it(self):
        # The URL says one thing and the sidecar says another; serving the
        # course under the name in the URL would publish it under a slug it
        # never claimed. It registers under its own id and the misnamed
        # address is an ordinary 404 — not a crash, and not a wrong page.
        c = self.client([], "home-misnamed", self.tmp)
        plant(self.tmp, "misnamed", course_id="elsewhere")
        self.assertEqual(c.get("/c/misnamed/").status_code, 404)
        under_its_id = c.get("/c/elsewhere/")
        self.assertEqual(under_its_id.status_code, 200, under_its_id.text)
        self.assertIn("Interpreters, end to end", under_its_id.text)

    def test_a_course_that_stops_compiling_at_startup_stops_the_app(self):
        # Same gate, the loud end of it: at startup there is no page to
        # degrade, so a dirty course is a refusal to start.
        plant(self.tmp, "broken", course_id="broken", broken=True)
        with self.assertRaises(RuntimeError) as caught:
            self.client([], "home-broken-start", self.tmp)
        self.assertIn("does not compile", str(caught.exception))

    def test_a_slug_collision_between_a_flag_and_the_home_refuses(self):
        home_copy = plant(self.tmp, "tinylang")
        with self.assertRaises(RuntimeError) as caught:
            self.client([TINYLANG], "home-collision", self.tmp)
        message = str(caught.exception)
        self.assertIn("tinylang", message)
        self.assertIn(os.path.abspath(TINYLANG), message)
        self.assertIn(home_copy, message)

    def test_two_flag_roots_claiming_one_id_refuse_at_startup(self):
        # The same refusal, arriving the older way. Last-one-wins would make
        # the served course a function of argument order, which is a guess.
        first = plant(self.tmp, "one")
        second = plant(self.tmp, "two")
        with self.assertRaises(RuntimeError) as caught:
            self.client([first, second], "flag-collision", None)
        message = str(caught.exception)
        self.assertIn("tinylang", message)
        self.assertIn(first, message)
        self.assertIn(second, message)

    def test_one_directory_reached_twice_is_not_two_roots(self):
        # A symlink into the courses home, or a home under one, is one
        # course by two names — sameness is the directory, not the spelling.
        course = plant(self.tmp, "tinylang")
        link = os.path.join(self.tmp, "by-another-name")
        os.symlink(course, link)
        c = self.client([course, link], "flag-symlink", None)
        self.assertEqual(c.get("/c/tinylang/index.html").status_code, 200)


if __name__ == "__main__":
    unittest.main()
