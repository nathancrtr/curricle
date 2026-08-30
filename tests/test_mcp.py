"""The tutor export: protocol, tool surface, write discipline, tenancy.

What these pin: a fresh assistant needs no repo checkout — teach_unit hands
it the contract, the unit, the guide, and the learner in one call; write
tools go through the same validation the web app's routes do (an unknown
subject is a refusal, a checkpoint result becomes a *proposal*); the tenant
is explicit and two tenants never see each other's ledgers; and the module
cannot reach the model (L1).

Runs against a throwaway Postgres cluster (tests/pg.py) and the textual-flow
corpus, like the progress-service tests beside it.
"""

import io
import json
import unittest

from curricle import db, profile
from curricle import mcpserver
from curricle.mcpserver import TutorServer, handle_message, serve_stdio
from curricle.webapp import load_course

from corpuspaths import HAVE_TF, TF_ROOT
from pg import test_engine


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


class InvariantL1Test(unittest.TestCase):
    def test_the_tutor_export_cannot_reach_the_model(self):
        # L1: the export serves context and accepts evidence; it is not a
        # caller. Same guard the web app carries.
        with open(mcpserver.__file__, encoding="utf-8") as f:
            self.assertNotIn("llm", f.read())


if __name__ == "__main__":
    unittest.main()
