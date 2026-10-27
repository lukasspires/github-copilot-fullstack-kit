"""Tests for scripts/marina/decide.py — spec §3.3's decision table.

One test per check and per table row, plus the second consecutive FAIL
and PASS_WITH_RISKS judge policy. Every graph is built in memory with
scripts.state; `decide` itself must never do I/O (checked on its source).
"""

from __future__ import annotations

import datetime
import unittest
from pathlib import Path

import scripts.state as st
from scripts.marina import decide as dm
from scripts.marina import envelope as env_mod
from scripts.marina.decide import Decision, NodeSpec, Observations, Question
from scripts.state_lint import check_edge_compatibility

AT = datetime.datetime(2026, 10, 26, 21, 0, 0, tzinfo=datetime.timezone.utc)
TARGET = "/abs/api"
ALLOW = ["Bash(mvn test)"]
SHA = "a" * 64
ROLE = "java-backend"

_PATHS = {
    "reserved": (),
    "preparation_failed": ("preparation_failed",),
    "prepared": ("prepared",),
    "uncertain": ("prepared", "uncertain"),
    "abandoned": ("prepared", "uncertain", "abandoned"),
    "launched": ("prepared", "launched"),
    "working": ("prepared", "launched", "working"),
    "waiting_approval": ("prepared", "launched", "waiting_approval"),
    "finished": ("prepared", "launched", "working", "finished"),
    "receipt_missing": ("prepared", "launched", "working", "finished", "receipt_missing"),
    "receipt_received": ("prepared", "launched", "working", "finished", "receipt_received"),
    "receipt_invalid": ("prepared", "launched", "working", "finished", "receipt_received", "receipt_invalid"),
}
_VALIDATED = ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated")
for _terminal in ("accepted", "returned", "closed_needs_input", "closed_blocked", "closed_pending"):
    _PATHS[_terminal] = (*_VALIDATED, _terminal)
_PATHS["receipt_validated"] = _VALIDATED


def make_env(**overrides) -> env_mod.Envelope:
    raw = {
        "targets": [TARGET],
        "branches": {TARGET: "feat/x"},
        "allowlist": list(ALLOW),
        "review": "each_stage",
        "max_corrections": 1,
        "max_duration": "8h",
        "judge_max_calls": 1,
        "on_pass_with_risks": "judge",
        "stages": [{"role": ROLE, "handoff": "01-h.md"}, {"role": ROLE, "handoff": "02-h.md"}],
        "approval": {"at": AT, "sha256": SHA},
    }
    raw.update(overrides)
    if raw.get("approval") is None:
        raw.pop("approval")
    return env_mod.parse_envelope(raw)


def obs_ok(**overrides) -> Observations:
    values = {"envelope_sha256": SHA, "branches": {TARGET: "feat/x"}}
    values.update(overrides)
    return Observations(**values)


class Graph:
    """An in-memory task graph; `add` walks each node to the wanted state."""

    def __init__(self):
        self.doc = st.StateDoc(
            schema=1,
            task=st.Task(
                project="demo", slug="t1", title="Demo", phase="implementation", kit_root="/kit",
                targets=[TARGET, "/other"], journal=".agent-state/demo/tasks/t1/checkpoint.md",
                next_nn=1, created_at=AT, updated_at=AT,
            ),
            assignments=[],
        )

    def add(self, role: str, edge: str, predecessor: int, state: str = "accepted", *, verdict: str = "",
            status: str = "done", targets: list[str] | None = None, allowlist: list[str] | None = None,
            digest: list[str] | None = None) -> int:
        a = st.add_assignment(
            self.doc, role=role, type_=dm.EDGE_TYPE.get(edge, "análise"), edge=edge, predecessor=predecessor,
            targets=targets or [TARGET], allowlist=ALLOW if allowlist is None else allowlist, at=AT,
        )
        for to in _PATHS[state]:
            st.set_state(self.doc, a.nn, to, by="test", at=AT)
            if to == "receipt_validated":
                a.receipt_summary = st.ReceiptSummary(
                    status=status, verdict=verdict, profile_ok=True, risks_digest=digest or []
                )
        return a.nn

    def writer(self, edge: str = "inicia", predecessor: int = 0, state: str = "accepted", **kw) -> int:
        return self.add(ROLE, edge, predecessor, state, **kw)

    def review(self, predecessor: int, verdict: str, state: str = "accepted", **kw) -> int:
        return self.add("reviewer", "revisa", predecessor, state, verdict=verdict, **kw)


def decide(graph: Graph, env=None, obs=None, **env_overrides) -> Decision:
    return dm.decide(graph.doc, make_env(**env_overrides) if env is None else env, obs or obs_ok())


class EnvelopeChecksTests(unittest.TestCase):
    def test_no_envelope(self):
        self.assertEqual(dm.decide(Graph().doc, None, obs_ok()), Decision("stop", reason="no_envelope"))

    def test_not_approved(self):
        self.assertEqual(decide(Graph(), approval=None).reason, "not_approved")

    def test_envelope_invalid(self):
        d = decide(Graph(), obs=obs_ok(envelope_errors=("max_corrections must be 0 or 1",)))
        self.assertEqual((d.kind, d.reason), ("stop", "envelope_invalid"))

    def test_hash_mismatch(self):
        self.assertEqual(decide(Graph(), obs=obs_ok(envelope_sha256="b" * 64)).reason, "envelope_changed")

    def test_branch_mismatch(self):
        for branches in ({TARGET: "main"}, {}):
            with self.subTest(branches=branches):
                self.assertEqual(decide(Graph(), obs=obs_ok(branches=branches)).reason, "envelope_changed")

    def test_allowlist_mismatch(self):
        g = Graph()
        g.writer(state="working", allowlist=["Bash(mvn verify)"])
        self.assertEqual(decide(g).reason, "envelope_changed")

    def test_graph_outside_envelope_for_analisa_edge(self):
        g = Graph()
        w = g.writer()
        g.add("reviewer", "analisa", w, "working")
        d = decide(g)
        self.assertEqual((d.kind, d.reason.split(":")[0]), ("stop", "graph_outside_envelope"))

    def test_graph_outside_envelope_for_foreign_target(self):
        g = Graph()
        g.writer(state="working", targets=["/other"])
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_graph_outside_envelope_for_wrong_role(self):
        g = Graph()
        g.add("angular", "inicia", 0, "working")
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_graph_outside_envelope_beyond_last_stage(self):
        g = Graph()
        w1 = g.writer()
        r1 = g.review(w1, "PASS")
        w2 = g.writer("prossegue", w1)
        g.review(w2, "PASS")
        g.writer("prossegue", w2, "working")
        self.assertIsNotNone(r1)
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_dangling_predecessor_is_graph_outside_envelope(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "PASS")
        g.doc.get_assignment(r).predecessor = 99
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_predecessor_cycle_is_graph_outside_envelope(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "PASS")
        g.doc.get_assignment(r).predecessor = r
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_revisa_after_revisa_is_graph_outside_envelope(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "FAIL")
        g.review(r1, "FAIL")
        d = decide(g)
        self.assertEqual((d.kind, d.reason.split(":")[0]), ("stop", "graph_outside_envelope"))

    def test_corrige_after_writer_is_graph_outside_envelope(self):
        g = Graph()
        w = g.writer()
        g.writer("corrige", w, "working")
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_type_mismatch_is_graph_outside_envelope(self):
        g = Graph()
        w = g.writer(state="working")
        g.doc.get_assignment(w).type = "correção"
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")


class StateRowTests(unittest.TestCase):
    def test_empty_graph_launches_stage_one(self):
        self.assertEqual(
            decide(Graph()),
            Decision("launch", node=NodeSpec(ROLE, "implementação", "inicia", 0, (TARGET,), tuple(ALLOW), 1)),
        )

    def test_reserved_and_prepared_stop(self):
        for state in ("reserved", "prepared"):
            with self.subTest(state=state):
                g = Graph()
                g.writer(state=state)
                self.assertEqual(decide(g), Decision("stop", reason="node_not_launched"))

    def test_launched_and_working_wait(self):
        for state in ("launched", "working"):
            with self.subTest(state=state):
                g = Graph()
                g.writer(state=state)
                self.assertEqual(decide(g), Decision("wait"))

    def test_waiting_approval_notifies_once(self):
        g = Graph()
        g.writer(state="waiting_approval")
        self.assertEqual(decide(g, obs=obs_ok(notified=False)), Decision("wait", notify=True))
        self.assertEqual(decide(g, obs=obs_ok(notified=True)), Decision("wait", notify=False))

    def test_uncertain_found_absent_unknown(self):
        g = Graph()
        nn = g.writer(state="uncertain")
        self.assertEqual(decide(g, obs=obs_ok(manager_match="found")), Decision("transition", nn=nn, to="launched"))
        self.assertEqual(decide(g, obs=obs_ok(manager_match="absent")), Decision("transition", nn=nn, to="abandoned"))
        self.assertEqual(decide(g, obs=obs_ok(manager_match=None)), Decision("wait"))

    def test_finished_with_and_without_receipt(self):
        g = Graph()
        nn = g.writer(state="finished")
        self.assertEqual(decide(g, obs=obs_ok(receipt_exists=True)), Decision("transition", nn=nn, to="receipt_received"))
        self.assertEqual(decide(g, obs=obs_ok(receipt_exists=False)), Decision("transition", nn=nn, to="receipt_missing"))

    def test_finished_requires_observation(self):
        g = Graph()
        g.writer(state="finished")
        with self.assertRaises(dm.MissingObservation):
            decide(g)

    def test_receipt_lint_pass_and_fail(self):
        g = Graph()
        nn = g.writer(state="receipt_received")
        summary = st.ReceiptSummary(status="done", profile_ok=True)
        self.assertEqual(
            decide(g, obs=obs_ok(receipt_lint=((), summary))),
            Decision("transition", nn=nn, to="receipt_validated", receipt_summary=summary),
        )
        self.assertEqual(
            decide(g, obs=obs_ok(receipt_lint=(("missing status", "x"), summary))),
            Decision("transition", nn=nn, to="receipt_invalid", reason="missing status"),
        )
        with self.assertRaises(dm.MissingObservation):
            decide(g)

    def test_receipt_validated_status_mapping(self):
        for status, to in (("done", "accepted"), ("pending", "closed_pending"),
                           ("needs_input", "closed_needs_input"), ("blocked", "closed_blocked")):
            with self.subTest(status=status):
                g = Graph()
                nn = g.writer(state="receipt_validated", status=status)
                self.assertEqual(decide(g), Decision("transition", nn=nn, to=to))

    def test_receipt_validated_without_summary(self):
        g = Graph()
        nn = g.writer(state="receipt_validated")
        g.doc.get_assignment(nn).receipt_summary = None
        self.assertEqual(decide(g), Decision("stop", reason="receipt_summary_missing"))

    def test_terminal_states_stop_with_state_name(self):
        for state in ("receipt_missing", "receipt_invalid", "abandoned", "preparation_failed", "returned",
                      "closed_needs_input", "closed_blocked", "closed_pending"):
            with self.subTest(state=state):
                g = Graph()
                g.writer(state=state)
                self.assertEqual(decide(g), Decision("stop", reason=state))


class AcceptedWriterTests(unittest.TestCase):
    def test_writer_accepted_each_stage_opens_revisa(self):
        g = Graph()
        w = g.writer()
        self.assertEqual(
            decide(g), Decision("launch", node=NodeSpec("reviewer", "revisão", "revisa", w, (TARGET,), tuple(ALLOW), 1))
        )

    def test_final_review_middle_stage_opens_prossegue(self):
        g = Graph()
        w = g.writer()
        d = decide(g, review="final")
        self.assertEqual(d.node, NodeSpec(ROLE, "implementação", "prossegue", w, (TARGET,), tuple(ALLOW), 2))

    def test_final_review_last_stage_opens_revisa(self):
        g = Graph()
        w1 = g.writer()
        w2 = g.writer("prossegue", w1)
        d = decide(g, review="final")
        self.assertEqual((d.node.edge, d.node.predecessor, d.node.stage), ("revisa", w2, 2))

    def test_corrige_accepted_opens_revisa(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "FAIL")
        c = g.writer("corrige", r)
        d = decide(g)
        self.assertEqual((d.node.edge, d.node.role, d.node.predecessor, d.node.type), ("revisa", "reviewer", c, "revisão"))


class AcceptedReviewerTests(unittest.TestCase):
    def test_pass_opens_next_stage_with_writer_as_predecessor(self):
        g = Graph()
        w = g.writer()
        g.review(w, "PASS")
        self.assertEqual(
            decide(g).node, NodeSpec(ROLE, "implementação", "prossegue", w, (TARGET,), tuple(ALLOW), 2)
        )

    def test_pass_on_last_stage_is_done(self):
        g = Graph()
        w1 = g.writer()
        g.review(w1, "PASS")
        w2 = g.writer("prossegue", w1)
        g.review(w2, "PASS")
        self.assertEqual(decide(g), Decision("done"))

    def test_final_review_pass_is_done(self):
        g = Graph()
        w1 = g.writer()
        w2 = g.writer("prossegue", w1)
        g.review(w2, "PASS")
        self.assertEqual(decide(g, review="final"), Decision("done"))

    def test_pass_after_correction_opens_next_stage_from_stage_opener(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "FAIL")
        c = g.writer("corrige", r1)
        g.review(c, "PASS")
        d = decide(g)
        self.assertEqual((d.node.edge, d.node.predecessor), ("prossegue", w))
        nn = g.writer("prossegue", d.node.predecessor, "reserved")
        self.assertEqual([e for e in check_edge_compatibility(g.doc) if f"nn={nn}" in e], [])

    def test_pass_with_risks_accept(self):
        g = Graph()
        w = g.writer()
        g.review(w, "PASS_WITH_RISKS")
        self.assertEqual(decide(g, on_pass_with_risks="accept").node.edge, "prossegue")

    def test_pass_with_risks_stop(self):
        g = Graph()
        w = g.writer()
        g.review(w, "PASS_WITH_RISKS")
        self.assertEqual(decide(g, on_pass_with_risks="stop"), Decision("stop", reason="pass_with_risks"))

    def _pwr(self) -> tuple[Graph, Question]:
        g = Graph()
        w = g.writer()
        r = g.review(w, "PASS_WITH_RISKS")
        return g, Question("pass_with_risks", r, ("continue", "stop"))

    def test_pass_with_risks_judge_asks(self):
        g, question = self._pwr()
        self.assertEqual(decide(g), Decision("ask_judge", question=question))

    def test_judge_answer_continue(self):
        g, question = self._pwr()
        self.assertEqual(decide(g, obs=obs_ok(judge_answer=(question, "continue"))).node.edge, "prossegue")

    def test_judge_answer_stop(self):
        g, question = self._pwr()
        self.assertEqual(decide(g, obs=obs_ok(judge_answer=(question, "stop"))), Decision("stop", reason="judge_stop"))

    def test_judge_answer_invalid_option(self):
        g, question = self._pwr()
        self.assertEqual(
            decide(g, obs=obs_ok(judge_answer=(question, "launch_anyway"))), Decision("stop", reason="judge_failed")
        )

    def test_judge_answer_for_other_question_is_ignored(self):
        g, question = self._pwr()
        other = Question("pass_with_risks", question.nn + 7, question.options)
        self.assertEqual(decide(g, obs=obs_ok(judge_answer=(other, "continue"))).kind, "ask_judge")

    def test_judge_quota_exhausted(self):
        g, _ = self._pwr()
        self.assertEqual(decide(g, obs=obs_ok(judge_calls_used=1)), Decision("stop", reason="judge_failed"))
        self.assertEqual(decide(g, judge_max_calls=0), Decision("stop", reason="judge_failed"))

    def test_fail_opens_corrige_with_writer_role(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "FAIL")
        self.assertEqual(
            decide(g).node, NodeSpec(ROLE, "correção", "corrige", r, (TARGET,), tuple(ALLOW), 1)
        )

    def test_fail_with_zero_quota_stops(self):
        g = Graph()
        w = g.writer()
        g.review(w, "FAIL")
        self.assertEqual(decide(g, max_corrections=0), Decision("stop", reason="max_corrections"))

    def test_second_consecutive_fail_stops_even_with_quota(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "FAIL", digest=["a"])
        c = g.writer("corrige", r1)
        g.review(c, "FAIL", digest=["b"])
        self.assertEqual(decide(g), Decision("stop", reason="second_fail"))

    def test_correction_quota_is_per_stage(self):
        g = Graph()
        w1 = g.writer()
        r1 = g.review(w1, "FAIL")
        c1 = g.writer("corrige", r1)
        g.review(c1, "PASS")
        w2 = g.writer("prossegue", w1)
        r2 = g.review(w2, "FAIL")
        self.assertEqual(decide(g).node.predecessor, r2)

    def test_verdict_missing(self):
        g = Graph()
        w = g.writer()
        g.review(w, "")
        self.assertEqual(decide(g), Decision("stop", reason="verdict_missing"))


class HelperTests(unittest.TestCase):
    def test_stage_of(self):
        g = Graph()
        w1 = g.writer()
        r1 = g.review(w1, "FAIL")
        c1 = g.writer("corrige", r1)
        r2 = g.review(c1, "PASS")
        w2 = g.writer("prossegue", w1)
        self.assertEqual([dm.stage_of(g.doc, n) for n in (w1, r1, c1, r2, w2)], [1, 1, 1, 1, 2])

    def test_graph_errors_empty_for_valid_chain(self):
        g = Graph()
        w = g.writer()
        g.review(w, "PASS")
        self.assertEqual(dm.graph_errors(g.doc, make_env()), [])

    def test_decide_has_no_io(self):
        source = Path(dm.__file__).read_text(encoding="utf-8")
        for forbidden in ("open(", "subprocess", "os.environ", "datetime.now", "time.", "Path(", "read_state"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
