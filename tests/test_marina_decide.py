"""Tests for scripts/marina/decide.py — spec §3.3's decision table.

One test per check and per table row, plus the second consecutive FAIL
and PASS_WITH_RISKS judge policy. Every graph is built in memory with
scripts.state; `decide` itself must never do I/O (checked on its source).
"""

from __future__ import annotations

import dataclasses
import datetime
import unittest
from pathlib import Path

import scripts.state as st
from scripts.gate import find_fail_review_chain
from scripts.marina import decide as dm
from scripts.marina import envelope as env_mod
from scripts.marina import usage_limit as ul
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
            digest: list[str] | None = None, type_: str | None = None) -> int:
        a = st.add_assignment(
            self.doc, role=role, type_=type_ or dm.EDGE_TYPE.get(edge, "análise"), edge=edge, predecessor=predecessor,
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

    def replace(self, nn: int, state: str = "accepted", **kw) -> int:
        """A `substitui` node with the replaced node's role and type, as Marina opens it."""

        original = self.doc.get_assignment(nn)
        kw.setdefault("type_", original.type)
        return self.add(original.role, "substitui", nn, state, **kw)


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


class ReplacementTests(unittest.TestCase):
    """A4 part 1: a `substitui` opened by Marina stands for the node it replaces."""

    def test_acc_envelope_graph_is_done(self):
        # marina-acc/acc-envelope: inicia accepted, revisa receipt_missing, substitui accepted PASS.
        g = Graph()
        w = g.writer()
        r = g.review(w, "", "receipt_missing")
        g.replace(r, verdict="PASS")
        env = make_env(stages=[{"role": ROLE, "handoff": "01-h.md"}])
        self.assertEqual(dm.graph_errors(g.doc, env), [])
        self.assertEqual(decide(g, env=env), Decision("done"))

    def test_replacement_accepted_without_receipt_summary_stops(self):
        # acc-envelope's nn=03 was accepted with `state set`, which records no receipt summary.
        g = Graph()
        w = g.writer()
        r = g.review(w, "", "receipt_missing")
        n = g.replace(r, verdict="PASS")
        g.doc.get_assignment(n).receipt_summary = None
        self.assertEqual(decide(g), Decision("stop", reason="verdict_missing"))

    def test_replaced_reviewer_pass_opens_next_stage(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "", "receipt_invalid")
        g.replace(r, verdict="PASS")
        self.assertEqual(decide(g).node, NodeSpec(ROLE, "implementação", "prossegue", w, (TARGET,), tuple(ALLOW), 2))

    def test_replaced_opener_is_reviewed_and_followed(self):
        g = Graph()
        w1 = g.writer(state="receipt_invalid")
        w2 = g.replace(w1)
        self.assertEqual(
            decide(g).node, NodeSpec("reviewer", "revisão", "revisa", w2, (TARGET,), tuple(ALLOW), 1)
        )
        g.review(w2, "PASS")
        self.assertEqual(decide(g).node, NodeSpec(ROLE, "implementação", "prossegue", w2, (TARGET,), tuple(ALLOW), 2))

    def test_replaced_reviewer_fail_opens_corrige_after_the_replacement(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "", "receipt_missing")
        r2 = g.replace(r1, verdict="FAIL")
        d = decide(g)
        self.assertEqual((d.node.edge, d.node.role, d.node.predecessor, d.node.stage), ("corrige", ROLE, r2, 1))
        g.writer("corrige", r2, "reserved")
        self.assertEqual(check_edge_compatibility(g.doc), [])

    def test_replaced_reviewer_pass_with_risks_asks_about_the_replacement(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "", "receipt_missing")
        r2 = g.replace(r1, verdict="PASS_WITH_RISKS")
        self.assertEqual(
            decide(g), Decision("ask_judge", question=Question("pass_with_risks", r2, ("continue", "stop")))
        )

    def test_replaced_corrige_is_reviewed_as_a_correction(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "FAIL")
        c1 = g.writer("corrige", r, "receipt_missing")
        c2 = g.replace(c1)
        d = decide(g, review="final")
        self.assertEqual((d.node.edge, d.node.predecessor, d.node.stage), ("revisa", c2, 1))

    def test_second_fail_is_found_through_a_replaced_reviewer(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "FAIL", digest=["a"])
        c = g.writer("corrige", r1)
        r2 = g.review(c, "", "receipt_missing")
        r3 = g.replace(r2, verdict="FAIL", digest=["a"])
        self.assertEqual([a.nn for a in find_fail_review_chain(g.doc, r3)], [r3, r1])
        self.assertEqual(decide(g), Decision("stop", reason="second_fail"))

    def test_second_fail_is_found_through_a_replaced_corrige(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "FAIL", digest=["a"])
        c1 = g.writer("corrige", r1, "receipt_invalid")
        c2 = g.replace(c1)
        r2 = g.review(c2, "FAIL", digest=["a"])
        self.assertEqual([a.nn for a in find_fail_review_chain(g.doc, r2)], [r2, r1])
        self.assertEqual(decide(g), Decision("stop", reason="second_fail"))

    def test_replaced_corrige_counts_once_in_its_stage(self):
        g = Graph()
        w1 = g.writer()
        r1 = g.review(w1, "FAIL")
        c1 = g.writer("corrige", r1, "receipt_missing")
        c2 = g.replace(c1)
        g.review(c2, "PASS")
        w2 = g.writer("prossegue", w1)
        r3 = g.review(w2, "FAIL")
        self.assertEqual([dm.stage_of(g.doc, n) for n in (c1, c2, w2)], [1, 1, 2])
        d = decide(g)
        self.assertEqual((d.kind, d.node.edge, d.node.predecessor, d.node.stage), ("launch", "corrige", r3, 2))

    def test_failed_replacement_stops_like_any_node(self):
        for state in ("receipt_missing", "receipt_invalid"):
            with self.subTest(state=state):
                g = Graph()
                w = g.writer()
                r = g.review(w, "", "receipt_missing")
                g.replace(r, state)
                self.assertEqual(decide(g), Decision("stop", reason=state))

    def test_graph_errors_refuse_replacements_outside_the_contract(self):
        def accepted_predecessor(g):
            w = g.writer()
            g.replace(w, "working")

        def replaced_replacement(g):
            w = g.writer()
            r1 = g.review(w, "", "receipt_missing")
            r2 = g.replace(r1, "receipt_missing")
            g.replace(r2, "working")

        def terminal_without_receipt(state):
            def build(g):
                w = g.writer()
                r = g.review(w, "", state)
                g.replace(r, "working")
            return build

        def different(**kw):
            def build(g):
                w = g.writer()
                r = g.review(w, "", "receipt_missing")
                g.replace(r, "working", **kw)
            return build

        def duplicate(g):
            w = g.writer()
            r = g.review(w, "", "receipt_missing")
            g.replace(r, "receipt_missing")
            g.replace(r, "working")

        def dangling(predecessor):
            def build(g):
                w = g.writer()
                r = g.review(w, "", "receipt_missing")
                n = g.replace(r, "working")
                g.doc.get_assignment(n).predecessor = predecessor(n)
            return build

        def other_allowlist(g):
            w = g.writer()
            r = g.review(w, "", "receipt_missing")
            g.replace(r, verdict="PASS", allowlist=["Bash(mvn verify)"])
            g.writer("prossegue", w, "working")

        def other_role(g):
            w = g.writer()
            r = g.review(w, "", "receipt_missing")
            g.add("architect", "substitui", r, "working", type_="revisão")

        cases = {
            "accepted predecessor": accepted_predecessor,
            "replaces a substitui": replaced_replacement,
            "preparation_failed": terminal_without_receipt("preparation_failed"),
            "abandoned": terminal_without_receipt("abandoned"),
            "other role": other_role,
            "other type": different(type_="análise"),
            "other targets": different(targets=["/other"]),
            "other allowlist": other_allowlist,
            "duplicate": duplicate,
            "missing predecessor": dangling(lambda n: 99),
            "later predecessor": dangling(lambda n: n),
        }
        for name, build in cases.items():
            with self.subTest(case=name):
                g = Graph()
                build(g)
                self.assertNotEqual(dm.graph_errors(g.doc, make_env()), [])
                d = decide(g)
                self.assertEqual((d.kind, d.reason.split(":")[0]), ("stop", "graph_outside_envelope"))

    def test_nodes_must_follow_the_replacement_not_the_replaced_node(self):
        # nn=08 finding F2: a stale predecessor would shorten the second-FAIL chain.
        def corrige_after_replaced_reviewer(g):
            w = g.writer()
            r1 = g.review(w, "", "receipt_missing")
            g.replace(r1, verdict="FAIL")
            g.writer("corrige", r1, "working")

        def revisa_after_replaced_writer(g):
            w1 = g.writer(state="receipt_invalid")
            g.replace(w1)
            g.review(w1, "", "working")

        def prossegue_after_replaced_opener(g):
            w1 = g.writer(state="receipt_missing")
            w2 = g.replace(w1)
            g.review(w2, "PASS")
            g.writer("prossegue", w1, "working")

        cases = {
            "corrige": corrige_after_replaced_reviewer,
            "revisa": revisa_after_replaced_writer,
            "prossegue": prossegue_after_replaced_opener,
        }
        for name, build in cases.items():
            with self.subTest(edge=name):
                g = Graph()
                build(g)
                errors = dm.graph_errors(g.doc, make_env())
                self.assertTrue(any("was replaced" in e for e in errors), errors)
                self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_effective_node_helpers(self):
        g = Graph()
        w = g.writer()
        r1 = g.review(w, "", "receipt_missing")
        r2 = g.replace(r1, verdict="PASS")
        doc = g.doc
        self.assertEqual(st.replaced_node(doc, doc.get_assignment(r2)).nn, r1)
        self.assertEqual(st.effective_edge(doc, doc.get_assignment(r2)), "revisa")
        self.assertEqual(st.effective_edge(doc, doc.get_assignment(w)), "inicia")
        self.assertEqual(st.reviewed_writer(doc, doc.get_assignment(r2)).nn, w)
        self.assertEqual(st.reviewed_writer(doc, doc.get_assignment(r1)).nn, w)
        doc.get_assignment(r2).predecessor = r2
        self.assertEqual(st.effective_edge(doc, doc.get_assignment(r2)), "substitui")


class PreEnvelopePrefixTests(unittest.TestCase):
    """An `analisa` run by the manual procedure before the envelope stays in the task."""

    def test_pre_envelope_analisa_prefix_opens_inicia(self):
        g = Graph()
        a = g.add("architect", "analisa", 0)
        d = decide(g)
        self.assertEqual((d.kind, d.reason), ("launch", ""))
        self.assertEqual(
            d,
            Decision("launch", node=NodeSpec(ROLE, "implementação", "inicia", 0, (TARGET,), tuple(ALLOW), 1)),
        )
        self.assertEqual(dm.graph_errors(g.doc, make_env()), [])
        self.assertEqual([n.nn for n in dm.pre_envelope_prefix(g.doc)], [a])
        # The gate's P0 (state_lint's G3 table) accepts that inicia after the analysis.
        nn = g.writer(state="reserved")
        self.assertEqual([e for e in check_edge_compatibility(g.doc) if f"nn={nn}" in e], [])

    def test_two_analisa_prefix_then_working_writer_follows_the_writer(self):
        g = Graph()
        g.add("architect", "analisa", 0)
        g.add("data-analyst", "analisa", 0)
        g.writer(state="working")
        self.assertEqual(len(dm.pre_envelope_prefix(g.doc)), 2)
        self.assertEqual(dm.graph_errors(g.doc, make_env()), [])
        plain = Graph()
        plain.writer(state="working")
        self.assertEqual(decide(g), decide(plain))
        self.assertEqual(decide(g), Decision("wait"))

    def test_prefix_then_accepted_writer_opens_its_review(self):
        g = Graph()
        g.add("architect", "analisa", 0)
        w = g.writer()
        self.assertEqual(
            decide(g), Decision("launch", node=NodeSpec("reviewer", "revisão", "revisa", w, (TARGET,), tuple(ALLOW), 1))
        )

    def test_unaccepted_analisa_is_not_a_prefix(self):
        for state in ("working", "closed_blocked", "receipt_missing", "returned"):
            with self.subTest(state=state):
                g = Graph()
                g.add("architect", "analisa", 0, state)
                self.assertEqual(dm.pre_envelope_prefix(g.doc), [])
                d = decide(g)
                self.assertEqual((d.kind, d.reason.split(":")[0]), ("stop", "graph_outside_envelope"))

    def test_working_analisa_is_graph_outside_envelope(self):
        g = Graph()
        g.add("architect", "analisa", 0, "working")
        d = decide(g)
        self.assertEqual(
            d, Decision("stop", reason="graph_outside_envelope: nn=1: the first node must be inicia with predecessor 0")
        )

    def test_closed_blocked_analisa_is_graph_outside_envelope(self):
        g = Graph()
        g.add("architect", "analisa", 0, "closed_blocked", status="blocked")
        g.writer(state="working")
        d = decide(g)
        self.assertEqual((d.kind, d.reason.split(":")[0]), ("stop", "graph_outside_envelope"))

    def test_prefix_ends_at_first_non_prefix_node(self):
        g = Graph()
        a = g.add("architect", "analisa", 0)
        g.writer(state="working")
        g.add("architect", "analisa", 0)
        self.assertEqual([n.nn for n in dm.pre_envelope_prefix(g.doc)], [a])
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_analisa_with_predecessor_is_not_a_prefix(self):
        g = Graph()
        g.add("architect", "analisa", 0)
        g.add("architect", "analisa", 1)
        self.assertEqual(len(dm.pre_envelope_prefix(g.doc)), 1)
        self.assertEqual(decide(g).reason.split(":")[0], "graph_outside_envelope")

    def test_predecessor_in_prefix_names_the_pre_envelope_analysis(self):
        # F1 (analisa-pre-envelope review): "is not an earlier node" misled when
        # the predecessor exists but belongs to the pre-envelope prefix.
        g = Graph()
        a = g.add("architect", "analisa", 0)
        g.writer()
        nn = g.review(a, "PASS", state="working")
        d = decide(g)
        self.assertEqual(
            d, Decision("stop", reason=f"graph_outside_envelope: nn={nn}: predecessor {a} is a pre-envelope analysis")
        )


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


FRONT = "/abs/front"
API_ALLOW = [f"Bash(mvn -f {TARGET}/pom.xml test)"]
FRONT_ALLOW = [f"Bash(npm --prefix {FRONT} test)"]
BOTH = {TARGET: "feat/x", FRONT: "feat/x"}


def multi_env(**overrides) -> env_mod.Envelope:
    """Two stages, two roles, each with its own target and allowlist (F7)."""

    values = {
        "targets": [TARGET, FRONT],
        "branches": dict(BOTH),
        "allowlist": [f"Bash(git -C {TARGET} diff *)", f"Bash(git -C {FRONT} diff *)"],
        "stages": [
            {"role": ROLE, "handoff": "01-h.md", "targets": [TARGET], "allowlist": list(API_ALLOW)},
            {"role": "angular", "handoff": "02-h.md", "targets": [FRONT], "allowlist": list(FRONT_ALLOW)},
        ],
    }
    values.update(overrides)
    return make_env(**values)


class MultiRoleTests(unittest.TestCase):
    """F7: `encadeia` between stages of different roles, each node with its stage's scope."""

    def _decide(self, g: Graph, **env_overrides) -> Decision:
        return dm.decide(g.doc, multi_env(**env_overrides), obs_ok(branches=dict(BOTH)))

    @staticmethod
    def _api(g: Graph, role: str, edge: str, pred: int, state: str = "accepted", **kw) -> int:
        return g.add(role, edge, pred, state, targets=[TARGET], allowlist=list(API_ALLOW), **kw)

    @staticmethod
    def _front(g: Graph, role: str, edge: str, pred: int, state: str = "accepted", **kw) -> int:
        return g.add(role, edge, pred, state, targets=[FRONT], allowlist=list(FRONT_ALLOW), **kw)

    def test_empty_graph_launches_stage_one_with_its_scope(self):
        d = self._decide(Graph())
        self.assertEqual(d.node, NodeSpec(ROLE, "implementação", "inicia", 0, (TARGET,), tuple(API_ALLOW), 1))

    def test_multi_role_review_uses_stage_scope(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        d = self._decide(g)
        self.assertEqual(d.node, NodeSpec("reviewer", "revisão", "revisa", 1, (TARGET,), tuple(API_ALLOW), 1))

    def test_multi_role_pass_opens_encadeia_with_next_stage_scope(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        self._api(g, "reviewer", "revisa", 1, verdict="PASS")
        d = self._decide(g)
        self.assertEqual(d.node, NodeSpec("angular", "implementação", "encadeia", 1, (FRONT,), tuple(FRONT_ALLOW), 2))

    def test_same_role_still_opens_prossegue(self):
        g = Graph()
        g.writer()
        g.review(1, "PASS")
        self.assertEqual(decide(g).node.edge, "prossegue")

    def test_multi_role_fail_corrects_with_stage_role_and_scope(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        self._api(g, "reviewer", "revisa", 1, verdict="PASS")
        self._front(g, "angular", "encadeia", 1)
        self._front(g, "reviewer", "revisa", 3, verdict="FAIL")
        d = self._decide(g)
        self.assertEqual(d.node, NodeSpec("angular", "correção", "corrige", 4, (FRONT,), tuple(FRONT_ALLOW), 2))

    def test_last_stage_pass_is_done(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        self._api(g, "reviewer", "revisa", 1, verdict="PASS")
        self._front(g, "angular", "encadeia", 1)
        self._front(g, "reviewer", "revisa", 3, verdict="PASS")
        self.assertEqual(self._decide(g).kind, "done")

    def test_encadeia_node_with_wrong_targets_is_graph_outside_envelope(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        self._api(g, "reviewer", "revisa", 1, verdict="PASS")
        g.add("angular", "encadeia", 1, "working", targets=[TARGET], allowlist=list(FRONT_ALLOW))
        d = self._decide(g)
        self.assertEqual(d.kind, "stop")
        self.assertTrue(d.reason.startswith("graph_outside_envelope"), d.reason)

    def test_stage_allowlist_mismatch_is_envelope_changed(self):
        g = Graph()
        g.add(ROLE, "inicia", 0, "working", targets=[TARGET], allowlist=list(FRONT_ALLOW))
        self.assertEqual(self._decide(g).reason, "envelope_changed")

    def test_encadeia_with_the_same_role_is_graph_outside_envelope(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        self._api(g, "reviewer", "revisa", 1, verdict="PASS")
        self._front(g, ROLE, "encadeia", 1, "working")
        self.assertTrue(self._decide(g).reason.startswith("graph_outside_envelope"))

    def test_replacement_of_encadeia_follows_its_stage(self):
        g = Graph()
        self._api(g, ROLE, "inicia", 0)
        self._api(g, "reviewer", "revisa", 1, verdict="PASS")
        self._front(g, "angular", "encadeia", 1, "receipt_missing")
        self._front(g, "angular", "substitui", 3, type_="implementação")
        d = self._decide(g)
        self.assertEqual(d.node, NodeSpec("reviewer", "revisão", "revisa", 4, (FRONT,), tuple(FRONT_ALLOW), 2))


LIMIT = ul.UsageLimit("7:50pm (America/Sao_Paulo)", datetime.datetime(2026, 11, 12, 22, 50, tzinfo=datetime.timezone.utc))
LIMIT_REASON = "usage_limit: nn={nn:02d} resets 7:50pm (America/Sao_Paulo)"


def _annotate(g: Graph, nn: int, note: str) -> None:
    """Put `note` on the event that brought node `nn` to its current state."""

    a = g.doc.get_assignment(nn)
    a.events[-1] = dataclasses.replace(a.events[-1], note=note)


class UsageLimitTests(unittest.TestCase):
    """limite-uso stage 1: the observation goes into the note, and the note stops the run."""

    def test_finished_without_receipt_records_the_limit(self):
        g = Graph()
        nn = g.writer(state="finished")
        d = decide(g, obs=obs_ok(receipt_exists=False, usage_limit=LIMIT))
        self.assertEqual(d, Decision("transition", nn=nn, to="receipt_missing", reason=ul.note_for(LIMIT)))

    def test_finished_with_receipt_ignores_the_limit(self):
        g = Graph()
        nn = g.writer(state="finished")
        d = decide(g, obs=obs_ok(receipt_exists=True, usage_limit=LIMIT))
        self.assertEqual(d, Decision("transition", nn=nn, to="receipt_received"))

    def test_receipt_invalid_note_follows_the_first_lint_error(self):
        g = Graph()
        nn = g.writer(state="receipt_received")
        summary = st.ReceiptSummary(status="", verdict="", profile_ok=False, risks_digest=[])
        d = decide(g, obs=obs_ok(receipt_lint=(("missing status", "other"), summary), usage_limit=LIMIT))
        self.assertEqual(d, Decision("transition", nn=nn, to="receipt_invalid",
                                     reason=f"missing status; {ul.note_for(LIMIT)}"))

    def test_receipt_missing_with_the_note_stops_with_usage_limit(self):
        for state in ("receipt_missing", "receipt_invalid"):
            with self.subTest(state=state):
                g = Graph()
                nn = g.writer(state=state)
                _annotate(g, nn, ul.with_note("missing status" if state == "receipt_invalid" else "", LIMIT))
                self.assertEqual(decide(g), Decision("stop", reason=LIMIT_REASON.format(nn=nn)))

    def test_unparsed_limit_says_so(self):
        g = Graph()
        nn = g.writer(state="receipt_missing")
        _annotate(g, nn, ul.note_for(ul.UsageLimit("7:50pm (Mars/Olympus)", None)))
        self.assertEqual(decide(g).reason, f"usage_limit: nn={nn:02d} resets 7:50pm (Mars/Olympus) (unparsed)")

    def test_without_the_note_the_reason_is_unchanged(self):
        for state, note in (("receipt_missing", ""), ("receipt_invalid", "missing status")):
            with self.subTest(state=state):
                g = Graph()
                nn = g.writer(state=state)
                _annotate(g, nn, note)
                self.assertEqual(decide(g), Decision("stop", reason=state))

    def test_reviewer_and_corrector_stop_the_same_way(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "", "receipt_missing")
        _annotate(g, r, ul.note_for(LIMIT))
        self.assertEqual(decide(g), Decision("stop", reason=LIMIT_REASON.format(nn=r)))
        g = Graph()
        w = g.writer()
        r = g.review(w, "FAIL")
        c = g.writer("corrige", r, "receipt_invalid")
        _annotate(g, c, ul.with_note("missing status", LIMIT))
        self.assertEqual(decide(g), Decision("stop", reason=LIMIT_REASON.format(nn=c)))

    def test_manual_replacement_stays_valid(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _annotate(g, w, ul.note_for(LIMIT))
        g.replace(w, "working")
        self.assertEqual(dm.graph_errors(g.doc, make_env()), [])
        self.assertEqual(decide(g), Decision("wait"))


READY = LIMIT.resets_at + datetime.timedelta(seconds=ul.USAGE_LIMIT_MARGIN)


def _limited(g: Graph, nn: int, *, limit: ul.UsageLimit = LIMIT, by: str = "marina-run") -> None:
    """Record `limit` on the event that put node `nn` in receipt_missing/receipt_invalid, by `by`."""

    a = g.doc.get_assignment(nn)
    base = "missing status" if a.state == "receipt_invalid" else ""
    a.events[-1] = dataclasses.replace(a.events[-1], note=ul.with_note(base, limit), by=by)


def _auto_replace(g: Graph, nn: int, state: str = "accepted", **kw) -> int:
    """A `substitui` the run opened on a usage limit (reserved by marina-run with the audit note)."""

    r = g.replace(nn, state, **kw)
    a = g.doc.get_assignment(r)
    a.events[0] = dataclasses.replace(a.events[0], by="marina-run",
                                      note=f"usage_limit: substitui nn={nn:02d}; resets_at=x; esperou 1s")
    return r


def wobs(now: datetime.datetime, deadline: datetime.datetime | None = None, **kw) -> Observations:
    return obs_ok(now=now, deadline=deadline or now + datetime.timedelta(hours=8), **kw)


class UsageLimitWaitTests(unittest.TestCase):
    """limite-uso stage 2: with `on_usage_limit = "wait"` the run waits, then opens one `substitui`."""

    def _decide(self, g: Graph, now: datetime.datetime, deadline=None, **env_overrides) -> Decision:
        env_overrides.setdefault("on_usage_limit", "wait")
        return decide(g, obs=wobs(now, deadline), **env_overrides)

    def test_stop_policy_keeps_stopping(self):
        for overrides in ({}, {"on_usage_limit": "stop"}):
            with self.subTest(overrides=overrides):
                g = Graph()
                w = g.writer(state="receipt_missing")
                _limited(g, w)
                self.assertEqual(decide(g, obs=wobs(READY), **overrides),
                                 Decision("stop", reason=LIMIT_REASON.format(nn=w)))

    def test_waits_until_resets_at_plus_margin(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _limited(g, w)
        for now in (LIMIT.resets_at - datetime.timedelta(hours=2), LIMIT.resets_at,
                    READY - datetime.timedelta(seconds=1)):
            with self.subTest(now=now):
                self.assertEqual(self._decide(g, now),
                                 Decision("wait", nn=w, reason="usage_limit until 2026-11-12T22:55:00+00:00"))

    def test_opens_one_substitui_with_the_replaced_node_scope(self):
        for state in ("receipt_missing", "receipt_invalid"):
            with self.subTest(state=state):
                g = Graph()
                w = g.writer(state=state)
                _limited(g, w)
                d = self._decide(g, READY)
                self.assertEqual(d.kind, "launch")
                self.assertEqual(d.node, NodeSpec(ROLE, "implementação", "substitui", w, (TARGET,), tuple(ALLOW), 1))
                waited = int((READY - g.doc.get_assignment(w).events[-1].at).total_seconds())
                self.assertEqual(d.reason, f"usage_limit: substitui nn={w:02d}; "
                                           f"resets_at=2026-11-12T22:50:00+00:00; esperou {waited}s")

    def test_note_recorded_by_marina_accept_also_reopens(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _limited(g, w, by="marina-accept")
        self.assertEqual(self._decide(g, READY).kind, "launch")

    def test_note_by_another_writer_only_stops(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _limited(g, w, by="marina")
        self.assertEqual(self._decide(g, READY), Decision("stop", reason=LIMIT_REASON.format(nn=w)))

    def test_reset_after_the_deadline_stops_at_once(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _limited(g, w)
        now = LIMIT.resets_at - datetime.timedelta(hours=1)
        for deadline in (READY, LIMIT.resets_at):
            with self.subTest(deadline=deadline):
                self.assertEqual(self._decide(g, now, deadline),
                                 Decision("stop", reason=LIMIT_REASON.format(nn=w) + " (after max_duration)"))

    def test_replacement_on_the_limit_stops(self):
        for state in ("receipt_missing", "receipt_invalid"):
            with self.subTest(state=state):
                g = Graph()
                w = g.writer(state="receipt_missing")
                _limited(g, w)
                r = _auto_replace(g, w, state)
                _limited(g, r)
                self.assertEqual(self._decide(g, READY),
                                 Decision("stop", reason=LIMIT_REASON.format(nn=r) + " (replacement)"))

    def test_unparsed_reset_stops(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _limited(g, w, limit=ul.UsageLimit("7:50pm (Mars/Olympus)", None))
        self.assertEqual(self._decide(g, READY),
                         Decision("stop", reason=f"usage_limit: nn={w:02d} resets 7:50pm (Mars/Olympus) (unparsed)"))

    def _two_reopens(self) -> tuple[Graph, int]:
        """Stage 1's writer and reviewer each reopened by the run; stage 2's writer hits the limit."""

        g = Graph()
        w1 = g.writer(state="receipt_missing")
        _limited(g, w1)
        w2 = _auto_replace(g, w1)
        r1 = g.review(w2, "", "receipt_missing")
        _limited(g, r1)
        _auto_replace(g, r1, verdict="PASS")
        w3 = g.writer("prossegue", w2, "receipt_missing")
        _limited(g, w3)
        return g, w3

    def test_third_reopen_in_the_task_stops(self):
        g, w3 = self._two_reopens()
        self.assertEqual(dm.graph_errors(g.doc, make_env(on_usage_limit="wait")), [])
        self.assertEqual(dm.USAGE_LIMIT_MAX_REOPENS, 2)
        self.assertEqual(self._decide(g, READY),
                         Decision("stop", reason=LIMIT_REASON.format(nn=w3) + " (max reopens)"))

    def test_manual_replacements_do_not_count(self):
        g = Graph()
        w1 = g.writer(state="receipt_missing")
        w2 = g.replace(w1)
        r1 = g.review(w2, "", "receipt_missing")
        g.replace(r1, verdict="PASS")
        w3 = g.writer("prossegue", w2, "receipt_missing")
        _limited(g, w3)
        self.assertEqual(self._decide(g, READY).node.edge, "substitui")

    def test_reviewer_and_corrector_are_reopened_the_same_way(self):
        g = Graph()
        w = g.writer()
        r = g.review(w, "", "receipt_missing")
        _limited(g, r)
        self.assertEqual(self._decide(g, READY).node,
                         NodeSpec("reviewer", "revisão", "substitui", r, (TARGET,), tuple(ALLOW), 1))
        g = Graph()
        w = g.writer()
        r = g.review(w, "FAIL")
        c = g.writer("corrige", r, "receipt_invalid")
        _limited(g, c)
        self.assertEqual(self._decide(g, READY).node,
                         NodeSpec(ROLE, "correção", "substitui", c, (TARGET,), tuple(ALLOW), 1))

    def test_reopened_corrige_counts_once_in_max_corrections(self):
        g = Graph()
        w1 = g.writer()
        r1 = g.review(w1, "FAIL")
        c1 = g.writer("corrige", r1, "receipt_missing")
        _limited(g, c1)
        c2 = _auto_replace(g, c1)
        g.review(c2, "PASS")
        w2 = g.writer("prossegue", w1)
        r3 = g.review(w2, "FAIL")
        d = self._decide(g, READY)
        self.assertEqual((d.kind, d.node.edge, d.node.predecessor, d.node.stage), ("launch", "corrige", r3, 2))

    def test_wait_policy_needs_the_clock(self):
        g = Graph()
        w = g.writer(state="receipt_missing")
        _limited(g, w)
        with self.assertRaises(dm.MissingObservation):
            decide(g, on_usage_limit="wait")
