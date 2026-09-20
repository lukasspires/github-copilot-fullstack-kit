"""Tests for scripts/gate.py — P_writer, P_reader, P_progresso.

Cross-task P_writer/P_reader tests use the three small SYNTHETIC fixtures
under tests/fixtures/gate-tasks/ (task-a: active writer on
/mnt/example/target-a; task-b: empty, the "current"/proposing task;
task-c: active reader on /mnt/example/target-c) — never
tests/fixtures/visible-sessions/state.toml, which stays untouched.
P_progresso tests build a small correction chain in memory via
scripts.state itself (same pattern as tests/test_state_lint.py), since
nothing about that predicate is cross-task.
"""

from __future__ import annotations

import datetime
import unittest
from pathlib import Path

import scripts.state as st
from scripts import gate

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gate-tasks"
AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _no_sessions() -> list[dict]:
    return []


class LoadTaskDocsTests(unittest.TestCase):
    def test_discovers_all_three_fixture_tasks(self):
        docs = gate.load_task_docs(FIXTURES)
        self.assertEqual({d.task.slug for d in docs}, {"task-a", "task-b", "task-c"})

    def test_exclude_slug_omits_current_task(self):
        docs = gate.load_task_docs(FIXTURES, exclude_slug="task-b")
        self.assertEqual({d.task.slug for d in docs}, {"task-a", "task-c"})

    def test_missing_root_returns_empty(self):
        self.assertEqual(gate.load_task_docs(FIXTURES / "does-not-exist"), [])


class PWriterCrossTaskTests(unittest.TestCase):
    """Acceptance criterion 1: two task fixtures, overlapping vs
    non-overlapping targets, one active writer in task-a."""

    def setUp(self):
        self.doc_b = st.read_state(FIXTURES / "task-b" / "state.toml")
        self.siblings = gate.load_task_docs(FIXTURES, exclude_slug="task-b")

    def test_overlapping_target_with_active_writer_is_refused(self):
        result = gate.evaluate_gate(
            self.doc_b,
            role="node-backend",
            type_="implementação",
            edge="inicia",
            predecessor=0,
            targets=["/mnt/example/target-a"],  # overlaps task-a's active writer
            sibling_docs=self.siblings,
            git_diff_acknowledged=True,
            list_sessions=_no_sessions,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("active writer nn=1" in r and "task-a" in r for r in result.reasons))

    def test_non_overlapping_target_is_allowed(self):
        result = gate.evaluate_gate(
            self.doc_b,
            role="node-backend",
            type_="implementação",
            edge="inicia",
            predecessor=0,
            targets=["/mnt/example/target-b"],  # task-b's own target; no active writer there
            sibling_docs=self.siblings,
            git_diff_acknowledged=True,
            list_sessions=_no_sessions,
        )
        self.assertTrue(result.allowed, result.reasons)


class PReaderCrossTaskTests(unittest.TestCase):
    """Acceptance criterion 2: a reader coexists with a reader (task-c) and
    with a writer in a different task's targets; only an active writer on
    the *same* targets refuses it."""

    def setUp(self):
        self.doc_b = st.read_state(FIXTURES / "task-b" / "state.toml")
        self.siblings = gate.load_task_docs(FIXTURES, exclude_slug="task-b")

    def _propose_reader(self, targets: list[str]) -> gate.GateResult:
        return gate.evaluate_gate(
            self.doc_b,
            role="reviewer",
            type_="revisão",
            edge="revisa_direta",
            predecessor=0,
            targets=targets,
            sibling_docs=self.siblings,
            list_sessions=_no_sessions,
        )

    def test_reader_refused_by_active_writer_on_same_targets(self):
        result = self._propose_reader(["/mnt/example/target-a"])
        self.assertFalse(result.allowed)
        self.assertTrue(any("active writer nn=1" in r for r in result.reasons))

    def test_reader_coexists_with_active_reader_on_same_targets(self):
        result = self._propose_reader(["/mnt/example/target-c"])
        self.assertTrue(result.allowed, result.reasons)

    def test_reader_coexists_with_writer_in_a_different_tasks_targets(self):
        # task-a's active writer is on target-a; a reader proposed on
        # task-b's own target-b is unaffected by it.
        result = self._propose_reader(["/mnt/example/target-b"])
        self.assertTrue(result.allowed, result.reasons)


class GateNeverWritesTest(unittest.TestCase):
    """Acceptance criterion 4: gate never writes/launches anything."""

    def test_source_has_no_subprocess_or_write_call(self):
        text = (Path(__file__).resolve().parent.parent / "scripts" / "gate.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", text)
        self.assertNotIn("subprocess.", text)
        self.assertNotIn("write_text(", text)
        self.assertNotIn("write_state(", text)
        self.assertNotIn('open(', text)

    def test_evaluate_gate_does_not_mutate_the_input_docs(self):
        doc_b = st.read_state(FIXTURES / "task-b" / "state.toml")
        siblings = gate.load_task_docs(FIXTURES, exclude_slug="task-b")
        before = st.dumps_state(doc_b)
        before_siblings = [st.dumps_state(d) for d in siblings]
        gate.evaluate_gate(
            doc_b, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=["/mnt/example/target-a"], sibling_docs=siblings, list_sessions=_no_sessions,
        )
        self.assertEqual(st.dumps_state(doc_b), before)
        self.assertEqual([st.dumps_state(d) for d in siblings], before_siblings)


# --------------------------------------------------------------------------
# P_progresso (acceptance criterion 3).
# --------------------------------------------------------------------------


def _corrige_chain(doc: st.StateDoc, *, first_digest: list[str], second_digest: list[str]):
    """writer(1,accepted) -> reviewer(2,FAIL,first_digest) -> corrige(3,accepted)
    -> reviewer(4,FAIL,second_digest). Returns nn=4 (the latest FAIL)."""

    writer = st.add_assignment(
        doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
        targets=["/tmp/kit"], at=AT,
    )
    for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated", "accepted"):
        st.set_state(doc, writer.nn, to, by="test", at=AT)

    reviewer1 = st.add_assignment(
        doc, role="reviewer", type_="revisão", edge="revisa", predecessor=writer.nn,
        targets=["/tmp/kit"], at=AT,
    )
    for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated"):
        st.set_state(doc, reviewer1.nn, to, by="test", at=AT)
    reviewer1.receipt_summary = st.ReceiptSummary(status="done", verdict="FAIL", profile_ok=True, risks_digest=first_digest)
    st.set_state(doc, reviewer1.nn, "accepted", by="test", at=AT)

    corrige = st.add_assignment(
        doc, role="node-backend", type_="correção", edge="corrige", predecessor=reviewer1.nn,
        targets=["/tmp/kit"], at=AT,
    )
    for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated", "accepted"):
        st.set_state(doc, corrige.nn, to, by="test", at=AT)

    reviewer2 = st.add_assignment(
        doc, role="reviewer", type_="revisão", edge="revisa", predecessor=corrige.nn,
        targets=["/tmp/kit"], at=AT,
    )
    for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated"):
        st.set_state(doc, reviewer2.nn, to, by="test", at=AT)
    reviewer2.receipt_summary = st.ReceiptSummary(status="done", verdict="FAIL", profile_ok=True, risks_digest=second_digest)
    st.set_state(doc, reviewer2.nn, "accepted", by="test", at=AT)

    return reviewer2.nn


def _base_task() -> st.Task:
    return st.Task(
        project="gate-progresso", slug="progresso-demo", title="Demo", phase="correction",
        kit_root="/tmp/kit", targets=["/tmp/kit"],
        journal=".agent-state/gate-progresso/tasks/progresso-demo/checkpoint.md",
        next_nn=1, created_at=AT, updated_at=AT,
    )


class RisksOverlapTests(unittest.TestCase):
    def test_identical_digests_overlap(self):
        self.assertTrue(gate.risks_overlap_substantially(["a", "b"], ["a", "b"]))

    def test_disjoint_digests_do_not_overlap(self):
        self.assertFalse(gate.risks_overlap_substantially(["a", "b"], ["c", "d"]))

    def test_empty_digest_never_overlaps(self):
        self.assertFalse(gate.risks_overlap_substantially([], ["a"]))
        self.assertFalse(gate.risks_overlap_substantially(["a"], []))


class PProgressoTests(unittest.TestCase):
    def test_first_fail_in_chain_has_nothing_to_compare_and_is_allowed(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        writer = st.add_assignment(
            doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=["/tmp/kit"], at=AT,
        )
        for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated", "accepted"):
            st.set_state(doc, writer.nn, to, by="test", at=AT)
        reviewer = st.add_assignment(
            doc, role="reviewer", type_="revisão", edge="revisa", predecessor=writer.nn,
            targets=["/tmp/kit"], at=AT,
        )
        for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated"):
            st.set_state(doc, reviewer.nn, to, by="test", at=AT)
        reviewer.receipt_summary = st.ReceiptSummary(status="done", verdict="FAIL", profile_ok=True, risks_digest=["x"])
        st.set_state(doc, reviewer.nn, "accepted", by="test", at=AT)

        result = gate.evaluate_p_progresso(doc, reviewer_nn=reviewer.nn, user_decided=False)
        self.assertTrue(result.allowed, result.reasons)

    def test_overlapping_digests_refuse_regardless_of_user_decided(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        latest_nn = _corrige_chain(
            doc,
            first_digest=["worktree isolation risk", "permission model risk"],
            second_digest=["worktree isolation risk", "permission model risk"],
        )
        refused = gate.evaluate_p_progresso(doc, reviewer_nn=latest_nn, user_decided=False)
        self.assertFalse(refused.allowed)
        self.assertTrue(any("no progress" in r for r in refused.reasons))

        still_refused = gate.evaluate_p_progresso(doc, reviewer_nn=latest_nn, user_decided=True)
        self.assertFalse(still_refused.allowed, "overlap is not fixable by user_decided; `analisa` is the way out")

    def test_distinct_digests_second_consecutive_fail_needs_user_decision(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        latest_nn = _corrige_chain(
            doc,
            first_digest=["worktree isolation risk"],
            second_digest=["unrelated new finding about receipt parsing"],
        )
        refused = gate.evaluate_p_progresso(doc, reviewer_nn=latest_nn, user_decided=False)
        self.assertFalse(refused.allowed)
        self.assertTrue(any("second consecutive FAIL" in r for r in refused.reasons))

    def test_distinct_digests_allowed_once_user_decided(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        latest_nn = _corrige_chain(
            doc,
            first_digest=["worktree isolation risk"],
            second_digest=["unrelated new finding about receipt parsing"],
        )
        allowed = gate.evaluate_p_progresso(doc, reviewer_nn=latest_nn, user_decided=True)
        self.assertTrue(allowed.allowed, allowed.reasons)

    def test_not_a_fail_reviewer_node_is_refused(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        writer = st.add_assignment(
            doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=["/tmp/kit"], at=AT,
        )
        result = gate.evaluate_p_progresso(doc, reviewer_nn=writer.nn, user_decided=False)
        self.assertFalse(result.allowed)
        self.assertTrue(any("not an accepted reviewer node" in r for r in result.reasons))


class EvaluateGateCorrigeIntegrationTest(unittest.TestCase):
    """`corrige` routed through the top-level evaluate_gate (not just the
    lower-level evaluate_p_progresso) — same chain, full P0+P_writer+P_progresso."""

    def test_corrige_refused_without_user_decision_then_allowed_with_it(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        latest_nn = _corrige_chain(
            doc,
            first_digest=["worktree isolation risk"],
            second_digest=["unrelated new finding about receipt parsing"],
        )
        refused = gate.evaluate_gate(
            doc, role="node-backend", type_="correção", edge="corrige", predecessor=latest_nn,
            targets=["/tmp/kit"], git_diff_acknowledged=True, user_decided=False, list_sessions=_no_sessions,
        )
        self.assertFalse(refused.allowed)

        allowed = gate.evaluate_gate(
            doc, role="node-backend", type_="correção", edge="corrige", predecessor=latest_nn,
            targets=["/tmp/kit"], git_diff_acknowledged=True, user_decided=True, list_sessions=_no_sessions,
        )
        self.assertTrue(allowed.allowed, allowed.reasons)


# --------------------------------------------------------------------------
# P0 (edge legality) and predecessor-closed/git-diff plumbing.
# --------------------------------------------------------------------------


class P0AndWriterPlumbingTests(unittest.TestCase):
    def test_unknown_edge_is_refused(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        result = gate.evaluate_gate(
            doc, role="node-backend", type_="implementação", edge="nope", predecessor=0,
            targets=["/tmp/kit"], list_sessions=_no_sessions,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("unknown edge" in r for r in result.reasons))

    def test_revisa_without_a_qualifying_predecessor_is_refused(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        writer = st.add_assignment(
            doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=["/tmp/kit"], at=AT,
        )
        # writer stays "reserved" (never even prepared) -> not accepted/closed_pending.
        result = gate.evaluate_gate(
            doc, role="reviewer", type_="revisão", edge="revisa", predecessor=writer.nn,
            targets=["/tmp/kit"], list_sessions=_no_sessions,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("edge=revisa" in r for r in result.reasons))

    def test_writer_without_git_diff_acknowledged_is_refused(self):
        doc = st.StateDoc(schema=1, task=_base_task(), assignments=[])
        writer = st.add_assignment(
            doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=["/tmp/kit"], at=AT,
        )
        for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated", "accepted"):
            st.set_state(doc, writer.nn, to, by="test", at=AT)
        result = gate.evaluate_gate(
            doc, role="node-backend", type_="correção", edge="continua", predecessor=writer.nn,
            targets=["/tmp/kit"], git_diff_acknowledged=False, list_sessions=_no_sessions,
        )
        # edge=continua also requires predecessor in closed_needs_input/closed_pending,
        # so this is refused for that reason too; the git-diff reason must still appear.
        self.assertFalse(result.allowed)
        self.assertTrue(any("git status/diff" in r for r in result.reasons))

    def test_manager_unavailable_is_noted_not_fatal(self):
        doc = st.read_state(FIXTURES / "task-b" / "state.toml")

        def unavailable():
            raise gate.common.ManagerUnavailable("claude not found on PATH")

        result = gate.evaluate_gate(
            doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=["/mnt/example/target-b"], git_diff_acknowledged=True, list_sessions=unavailable,
        )
        self.assertTrue(result.allowed, result.reasons)
        self.assertTrue(any("unavailable" in n for n in result.notes))


if __name__ == "__main__":
    unittest.main()
