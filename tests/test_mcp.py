"""The tutor export: protocol, tool surface, write discipline, tenancy.

What these pin: a fresh assistant needs no repo checkout — teach_unit hands
it the contract, the unit, the guide, and the learner in one call; write
tools go through the same validation the web app's routes do (an unknown
subject is a refusal, a checkpoint result becomes a *proposal*); the tenant
is explicit and two tenants never see each other's ledgers; and the module
cannot reach the model (L1).

Runs against a throwaway Postgres cluster (tests/pg.py). The contract is
exercised twice: against `examples/tinylang`, which is in the repository and
never skips, and against the textual-flow corpus, which skips when the private
sibling repo is absent. The example-course class is the one that guarantees
this feature has coverage in a fresh clone — without it, thirteen of these
tests skip and the suite still prints OK.
"""

import io
import json
import os
import unittest

from curricle import db, profile
from curricle import mcpserver
from curricle.mcpserver import TutorServer, handle_message, serve_stdio
from curricle.profilerender import render_skill_md
from curricle.webapp import load_course

from corpuspaths import HAVE_TF, TF_ROOT
from pg import test_engine

# The shipped course, always present — see TutorExportExampleCourseTest.
EXAMPLE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples", "tinylang")


def rpc(id_, method, **params):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params:
        msg["params"] = params
    return msg


def call(server, name, **arguments):
    return handle_message(server, rpc(1, "tools/call",
                                      name=name, arguments=arguments))


def text_of(resp):
    return resp["result"]["content"][0]["text"]


@unittest.skipUnless(HAVE_TF, "textual-flow repo not present")
class TutorExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, "mcp-learner-a")
            cls.b = db.create_tenant(conn, "mcp-learner-b")
        handle = load_course(TF_ROOT)
        cls.server = TutorServer(courses={handle.slug: handle},
                                 engine=cls.engine,
                                 scope=db.for_tenant(cls.a), tenant="a")
        cls.other = TutorServer(courses={handle.slug: handle},
                                engine=cls.engine,
                                scope=db.for_tenant(cls.b), tenant="b")

    # -- protocol -----------------------------------------------------------

    def test_initialize_and_list_over_stdio(self):
        lines = "\n".join(json.dumps(m) for m in [
            rpc(0, "initialize", protocolVersion="2025-06-18",
                capabilities={}, clientInfo={"name": "t", "version": "0"}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            rpc(1, "tools/list"),
        ]) + "\n"
        out = io.StringIO()
        serve_stdio(self.server, stdin=io.StringIO(lines), stdout=out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        # The notification is never answered.
        self.assertEqual([r["id"] for r in responses], [0, 1])
        init = responses[0]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertIn("tools", init["capabilities"])
        names = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertEqual(names, {
            "get_course", "get_profile", "get_progress", "get_lesson_guide",
            "get_question_bank", "whats_next", "teach_unit", "quiz_me",
            "review_exercise", "record_progress_event",
            "propose_profile_evidence"})

    def test_unknown_method_and_parse_error(self):
        resp = handle_message(self.server, rpc(9, "resources/list"))
        self.assertEqual(resp["error"]["code"], -32601)
        out = io.StringIO()
        serve_stdio(self.server, stdin=io.StringIO("not json\n"), stdout=out)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], -32700)

    # -- read tools ---------------------------------------------------------

    def test_course_overview_walks_the_whole_course(self):
        text = text_of(call(self.server, "get_course"))
        self.assertIn("Textual criticism", text)
        self.assertIn("`u1`", text)
        self.assertIn("Track: Koine Greek", text)

    def test_teach_unit_is_a_complete_briefing(self):
        text = text_of(call(self.server, "teach_unit", unit="u1"))
        self.assertIn("Socratic", text)                  # the contract
        self.assertIn("**Build:**", text)                # the unit's rows
        self.assertIn("Lesson guide", text)              # the guide, verbatim
        self.assertIn("## The learner", text)            # the profile
        # Reference links resolved for the plain-markdown medium: the
        # verified URL, never a res: href.
        self.assertNotIn("(res:", text)

    def test_teach_unit_accepts_a_bare_number(self):
        by_num = text_of(call(self.server, "teach_unit", unit="1"))
        by_id = text_of(call(self.server, "teach_unit", unit="u1"))
        self.assertEqual(by_num, by_id)

    def test_whats_next_resumes_at_the_first_unfinished_step(self):
        text = text_of(call(self.server, "whats_next"))
        self.assertIn("`p0-run`", text)

    def test_quiz_me_names_the_ids_results_record_against(self):
        text = text_of(call(self.server, "quiz_me", phase=1))
        self.assertIn("`q-phase-1`", text)
        self.assertIn("recall", text)                    # the bank arrived

    def test_review_exercise_serves_the_brief_and_grader(self):
        text = text_of(call(self.server, "review_exercise", unit="u1"))
        self.assertIn("grader: unit-test", text)
        self.assertIn("run: `python -m unittest test_tei_parser -v`", text)

    def test_missing_guide_is_a_helpful_refusal(self):
        resp = call(self.server, "get_lesson_guide", unit="u5")
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("units with", text_of(resp))

    # -- write tools --------------------------------------------------------

    def test_record_mark_moves_the_summary(self):
        resp = call(self.server, "record_progress_event", kind="mark",
                    subject_id="p0-run", payload={"done": True})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("next up: p0-read", text_of(resp))
        # The other tenant's ledger is untouched (T5: somewhere to leak to).
        self.assertIn("`p0-run`", text_of(call(self.other, "whats_next")))

    def test_invalid_subject_is_a_tool_error_not_a_crash(self):
        resp = call(self.server, "record_progress_event", kind="mark",
                    subject_id="u99", payload={"done": True})
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("not defined", text_of(resp))

    def test_checkpoint_result_becomes_a_proposal(self):
        resp = call(self.server, "record_progress_event",
                    kind="checkpoint_result", subject_id="q-phase-0",
                    payload={"score": 7, "total": 9, "misses": ["initial text"]})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("proposed", text_of(resp))
        with self.engine.begin() as conn:
            pending = profile.load_profile(conn, self.server.scope).pending
        self.assertTrue(any(p.key == "textual-flow--q-phase-0"
                            for p in pending))

    def test_wire_proposals_name_a_source_and_never_claim_demonstrated(self):
        no_source = call(self.server, "propose_profile_evidence",
                         field="style", key="wants-why", text="Asks why.")
        self.assertTrue(no_source["result"]["isError"])
        self.assertIn("source", text_of(no_source))
        demoted = call(self.server, "propose_profile_evidence",
                       field="skip", key="regex", text="Fluent.",
                       tier="demonstrated", source="tutor session")
        self.assertTrue(demoted["result"]["isError"])
        ok = call(self.server, "propose_profile_evidence",
                  field="style", key="wants-why", text="Asks why first.",
                  source="tutor session 2026-08-30")
        self.assertIn("renders nowhere", text_of(ok))
        with self.engine.begin() as conn:
            pending = profile.load_profile(conn, self.server.scope).pending
        self.assertTrue(any(p.key == "wants-why" and p.tier == "attested"
                            for p in pending))


class TutorExportExampleCourseTest(unittest.TestCase):
    """The same contract, against the course that ships with the repository.

    Deliberately not a subclass of the class above: its assertions are about
    textual-flow's content, and generalising them into a fixture-parametrised
    base would blunt both. What is shared is the *contract* — protocol shape,
    what a briefing contains, what a refusal says, what a write does — and
    that is what is restated here in the example course's own terms.

    This class never skips. That is its whole reason for existing.
    """

    @classmethod
    def setUpClass(cls):
        cls.engine = test_engine()
        with cls.engine.begin() as conn:
            cls.a = db.create_tenant(conn, "mcp-example-a")
            cls.b = db.create_tenant(conn, "mcp-example-b")
        handle = load_course(EXAMPLE_ROOT)
        cls.slug = handle.slug
        cls.server = TutorServer(courses={handle.slug: handle},
                                 engine=cls.engine,
                                 scope=db.for_tenant(cls.a), tenant="a")
        cls.other = TutorServer(courses={handle.slug: handle},
                                engine=cls.engine,
                                scope=db.for_tenant(cls.b), tenant="b")

    # -- protocol -----------------------------------------------------------

    def test_the_whole_tool_surface_is_advertised(self):
        resp = handle_message(self.server, rpc(1, "tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(names, {
            "get_course", "get_profile", "get_progress", "get_lesson_guide",
            "get_question_bank", "whats_next", "teach_unit", "quiz_me",
            "review_exercise", "record_progress_event",
            "propose_profile_evidence"})

    def test_every_advertised_tool_declares_a_schema(self):
        resp = handle_message(self.server, rpc(1, "tools/list"))
        for tool in resp["result"]["tools"]:
            self.assertTrue(tool.get("description"), tool["name"])
            self.assertEqual(tool["inputSchema"]["type"], "object",
                             tool["name"])

    def test_initialize_over_stdio(self):
        lines = "\n".join(json.dumps(m) for m in [
            rpc(0, "initialize", protocolVersion="2025-06-18",
                capabilities={}, clientInfo={"name": "t", "version": "0"}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            rpc(1, "tools/list"),
        ]) + "\n"
        out = io.StringIO()
        serve_stdio(self.server, stdin=io.StringIO(lines), stdout=out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in responses], [0, 1])
        self.assertEqual(responses[0]["result"]["protocolVersion"],
                         "2025-06-18")

    # -- read tools ---------------------------------------------------------

    def test_course_overview_names_units_and_the_track(self):
        text = text_of(call(self.server, "get_course"))
        self.assertIn("Interpreters, end to end", text)
        self.assertIn("`u1`", text)
        self.assertIn("Track: Formal grammars", text)

    def test_teach_unit_is_a_complete_briefing(self):
        text = text_of(call(self.server, "teach_unit", unit="u1"))
        self.assertIn("Socratic", text)          # the contract
        self.assertIn("**Build:**", text)        # the unit's rows
        self.assertIn("Lesson guide", text)      # the guide, verbatim
        self.assertIn("## The learner", text)    # the profile
        # Refs resolved for the plain-markdown medium: the verified URL,
        # never a res: href travelling over the wire.
        self.assertNotIn("(res:", text)
        self.assertIn("craftinginterpreters.com", text)

    def test_teach_unit_accepts_a_bare_number(self):
        self.assertEqual(text_of(call(self.server, "teach_unit", unit="2")),
                         text_of(call(self.server, "teach_unit", unit="u2")))

    def test_teach_unit_without_a_guide_still_briefs(self):
        # Only u1 has a lesson guide. The rest must degrade to the unit's own
        # rows rather than refuse — a tutor with no guide still teaches.
        text = text_of(call(self.server, "teach_unit", unit="u3"))
        self.assertIn("No written guide", text)
        self.assertIn("**Build:**", text)

    def test_whats_next_starts_at_the_first_step(self):
        text = text_of(call(self.server, "whats_next"))
        self.assertIn("`p0-skeleton`", text)

    def test_quiz_me_names_the_ids_results_record_against(self):
        text = text_of(call(self.server, "quiz_me", phase=1))
        self.assertIn("`quiz-p1`", text)
        self.assertIn("Question Bank", text)     # the bank arrived

    def test_quiz_me_out_of_scope_says_not_to_record(self):
        text = text_of(call(self.server, "quiz_me", phase=2))
        self.assertIn("do not record", text)

    def test_review_exercise_serves_the_brief_and_grader(self):
        text = text_of(call(self.server, "review_exercise", unit="u2"))
        self.assertIn("grader: unit-test", text)
        self.assertIn("unit-02-starter", text)
        self.assertIn("Pratt", text)             # task.md, verbatim

    def test_review_exercise_without_one_is_a_refusal(self):
        resp = call(self.server, "review_exercise", unit="u1")
        self.assertTrue(resp["result"]["isError"])

    def test_missing_guide_is_a_helpful_refusal(self):
        resp = call(self.server, "get_lesson_guide", unit="u4")
        self.assertTrue(resp["result"]["isError"])
        # It says which units *do* have one, so the caller can recover.
        self.assertIn("units with", text_of(resp))
        self.assertIn("u1", text_of(resp))

    # -- write tools --------------------------------------------------------

    def test_record_mark_moves_the_summary_and_stays_in_its_tenant(self):
        resp = call(self.server, "record_progress_event", kind="mark",
                    subject_id="p0-skeleton", payload={"done": True})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("next up: p0-repl", text_of(resp))
        # T5: the other tenant has somewhere to leak to, and doesn't.
        self.assertIn("`p0-skeleton`", text_of(call(self.other, "whats_next")))

    def test_invalid_subject_is_a_tool_error_not_a_crash(self):
        resp = call(self.server, "record_progress_event", kind="mark",
                    subject_id="u99", payload={"done": True})
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("not defined", text_of(resp))

    def test_checkpoint_result_becomes_a_proposal(self):
        resp = call(self.server, "record_progress_event",
                    kind="checkpoint_result", subject_id="quiz-p1",
                    payload={"score": 6, "total": 8,
                             "misses": ["maximal munch"]})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("proposed", text_of(resp))
        with self.engine.begin() as conn:
            pending = profile.load_profile(conn, self.server.scope).pending
        claim = next(p for p in pending if p.key == f"{self.slug}--quiz-p1")
        # The misses ride along: they are the evidence, not the score.
        self.assertIn("maximal munch", claim.text)
        self.assertEqual(claim.tier, "demonstrated")

    def test_wire_proposals_name_a_source_and_never_claim_demonstrated(self):
        no_source = call(self.server, "propose_profile_evidence",
                         field="style", key="traces-by-hand",
                         text="Traces parsers by hand.")
        self.assertTrue(no_source["result"]["isError"])
        self.assertIn("source", text_of(no_source))

        demoted = call(self.server, "propose_profile_evidence",
                       field="skip", key="recursion", text="Fluent.",
                       tier="demonstrated", source="tutor session")
        self.assertTrue(demoted["result"]["isError"])

        ok = call(self.server, "propose_profile_evidence",
                  field="style", key="traces-by-hand",
                  text="Traces parsers by hand before reading the code.",
                  source="tutor session 2026-08-30")
        self.assertIn("renders nowhere", text_of(ok))
        with self.engine.begin() as conn:
            state = profile.load_profile(conn, self.server.scope)
        self.assertTrue(any(p.key == "traces-by-hand" and p.tier == "attested"
                            for p in state.pending))
        # Pending is pending: the projection must not have moved.
        self.assertNotIn("Traces parsers by hand", render_skill_md(state))


class InvariantL1Test(unittest.TestCase):
    def test_the_tutor_export_cannot_reach_the_model(self):
        # L1: the export serves context and accepts evidence; it is not a
        # caller. Same guard the web app carries.
        with open(mcpserver.__file__, encoding="utf-8") as f:
            self.assertNotIn("llm", f.read())


if __name__ == "__main__":
    unittest.main()
