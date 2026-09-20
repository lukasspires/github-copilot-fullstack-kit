"""Tests for scripts.state_lint — the 8 invariants of
docs/plano-estado-estruturado-e-grafos.md §5.

Positive case: the versioned fixture (read-only). Negative cases: a small
synthetic 2-node document built via scripts.state itself, then mutated
(one deliberate break per invariant, in memory) — this is the "your call"
alternative to 8 static broken-copy files the handoff allows, and avoids
maintaining hand-written TOML fixtures that could themselves contain
transcription errors.
"""

from __future__ import annotations

import datetime
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import scripts.state as st
from scripts import state_lint

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "visible-sessions" / "state.toml"
AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _valid_two_node_doc() -> st.StateDoc:
    """nn=1 writer, accepted; nn=2 reviewer revisa nn=1, accepted with PASS."""

    task = st.Task(
        project="demo-project",
        slug="demo-task",
        title="Demo",
        phase="delivery",
        kit_root="/tmp/kit",
        targets=["/tmp/kit"],
        journal=".agent-state/demo-project/tasks/demo-task/checkpoint.md",
        next_nn=1,
        created_at=AT,
        updated_at=AT,
    )
    doc = st.StateDoc(schema=1, task=task, assignments=[])
    writer = st.add_assignment(
        doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
        targets=["/tmp/kit"], at=AT,
    )
    for to_state in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated", "accepted"):
        st.set_state(doc, writer.nn, to_state, by="test", at=AT)

    reviewer = st.add_assignment(
        doc, role="reviewer", type_="revisão", edge="revisa", predecessor=writer.nn,
        targets=["/tmp/kit"], at=AT,
    )
    for to_state in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated"):
        st.set_state(doc, reviewer.nn, to_state, by="test", at=AT)
    reviewer.receipt_summary = st.ReceiptSummary(status="done", verdict="PASS", profile_ok=True, risks_digest=[])
    st.set_state(doc, reviewer.nn, "accepted", by="test", at=AT)
    return doc


class PositiveFixtureTests(unittest.TestCase):
    def test_all_8_invariants_pass_on_fixture(self):
        results = state_lint.lint_file(FIXTURE)
        for name, errors in results.items():
            self.assertEqual(errors, [], f"{name} unexpectedly failed: {errors}")

    def test_synthetic_valid_doc_also_passes(self):
        doc = _valid_two_node_doc()
        results = state_lint.lint_doc(doc, raw_text=None)
        for name, errors in results.items():
            self.assertEqual(errors, [], f"{name} unexpectedly failed: {errors}")


def _other_checks_pass(results: dict, broken: str) -> list[str]:
    return [name for name, errors in results.items() if name != broken and errors]


class NegativeInvariantTests(unittest.TestCase):
    """One deliberate break per invariant; each isolated to its own copy."""

    def setUp(self):
        self.doc = _valid_two_node_doc()

    def test_1_nn_sequence_broken(self):
        self.doc.assignments[1].nn = 3  # gap: 1, 3 instead of 1, 2
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["nn_sequence"])

    def test_1_next_nn_broken(self):
        self.doc.task.next_nn = 99
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["nn_sequence"])
        self.assertEqual(_other_checks_pass(results, "nn_sequence"), [])

    def test_2_predecessor_does_not_exist(self):
        self.doc.assignments[1].predecessor = 7
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["predecessor_exists"])

    def test_2_predecessor_not_less_than_nn(self):
        self.doc.assignments[0].predecessor = 1  # nn=1 predecessor=1 (not < nn)
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["predecessor_exists"])

    def test_3_edge_incompatible_with_predecessor_state(self):
        # Rewind the writer to `working` (not accepted/closed_pending) but
        # keep the reviewer's edge=revisa pointing at it.
        self.doc.assignments[0].state = "working"
        self.doc.assignments[0].events[-1].to = "working"
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["edge_compatibility"])
        self.assertEqual(_other_checks_pass(results, "edge_compatibility"), [])

    def test_4_two_active_writers_overlapping_targets(self):
        # Two independent writer nodes (edge=inicia, predecessor=0, so
        # invariant 3 stays satisfied), both moved to an active state with
        # the same target, to isolate the break to invariant 4 only.
        first = st.add_assignment(
            self.doc, role="node-backend", type_="implementação", edge="inicia",
            predecessor=0, targets=["/tmp/kit"], at=AT,
        )
        second = st.add_assignment(
            self.doc, role="node-backend", type_="implementação", edge="inicia",
            predecessor=0, targets=["/tmp/kit"], at=AT,
        )
        st.set_state(self.doc, first.nn, "prepared", by="test", at=AT)
        st.set_state(self.doc, second.nn, "prepared", by="test", at=AT)
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["single_active_writer"])
        self.assertEqual(_other_checks_pass(results, "single_active_writer"), [])

    def test_5_state_does_not_match_last_event(self):
        # Mutate the reviewer node (nn=2): nothing else references it as a
        # predecessor, so this stays isolated to invariant 5.
        self.doc.assignments[1].state = "returned"  # events[-1].to is still "accepted"
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["state_matches_events"])
        self.assertEqual(_other_checks_pass(results, "state_matches_events"), [])

    def test_5_events_not_monotonic(self):
        # All events share timestamp AT (constructed with a fixed clock);
        # push one middle event earlier to create a single out-of-order
        # pair without touching the final state/event.to.
        events = self.doc.assignments[0].events
        self.assertGreaterEqual(len(events), 3)
        events[1].at = events[0].at - datetime.timedelta(hours=1)
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["state_matches_events"])
        self.assertEqual(_other_checks_pass(results, "state_matches_events"), [])

    def test_6_unavailable_without_reason(self):
        self.doc.assignments[1].native.platform = "unavailable"
        self.doc.assignments[1].native.reason = ""
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["native_metadata"])
        self.assertEqual(_other_checks_pass(results, "native_metadata"), [])

    def test_6_codex_with_id_without_host(self):
        self.doc.assignments[1].native.platform = "codex"
        self.doc.assignments[1].native.id = "thread-123"
        self.doc.assignments[1].native.host = ""
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["native_metadata"])

    def test_7_mode_incoherent_with_role(self):
        self.doc.assignments[1].mode = "writer"  # role=reviewer implies reader
        results = state_lint.lint_doc(self.doc)
        self.assertTrue(results["mode_matches_role"])
        self.assertEqual(_other_checks_pass(results, "mode_matches_role"), [])

    def test_8_secret_heuristic_matches(self):
        raw_text = "note = \"api_key: AKIAABCDEFGHIJKLMNOP\"\n" + st.dumps_state(self.doc)
        results = state_lint.lint_doc(self.doc, raw_text=raw_text)
        self.assertTrue(results["no_secrets"])
        self.assertEqual(_other_checks_pass(results, "no_secrets"), [])

    def test_8_clean_text_has_no_secret_finding(self):
        raw_text = st.dumps_state(self.doc)
        results = state_lint.lint_doc(self.doc, raw_text=raw_text)
        self.assertEqual(results["no_secrets"], [])


class MainCliTests(unittest.TestCase):
    def test_main_defaults_to_fixture_and_exits_0(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_lint.main([])
        self.assertEqual(rc, 0)
        self.assertIn("PASS nn_sequence", buf.getvalue())

    def test_main_reports_failure_with_nonzero_exit(self):
        import tempfile

        doc = _valid_two_node_doc()
        doc.assignments[0].nn = 3
        with tempfile.TemporaryDirectory() as tmp:
            broken_path = Path(tmp) / "broken.toml"
            st.write_state(broken_path, doc)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = state_lint.main([str(broken_path)])
            self.assertEqual(rc, 1)
            self.assertIn("FAIL nn_sequence", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
