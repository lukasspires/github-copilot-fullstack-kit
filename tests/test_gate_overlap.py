"""Tests for the risks-overlap gray zone in scripts/gate.py (F3 Task 2).

`risks_overlap_ratio`/`classify_overlap` split the overlap between two
consecutive FAIL rounds into "no_progress" (>= RISKS_OVERLAP_THRESHOLD),
"gray" and "progress" (< RISKS_OVERLAP_LOWER_THRESHOLD). The verdict of
`evaluate_p_progresso` is unchanged; only its reasons name the band. Kept
apart from tests/test_gate.py; the correction chain is built in memory.
"""

from __future__ import annotations

import datetime
import unittest

import scripts.state as st
from scripts import gate

AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
_TO_VALIDATED = ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated")


def _fail_chain(first_digest: list[str], second_digest: list[str]) -> tuple[st.StateDoc, int]:
    """writer -> reviewer FAIL -> corrige -> reviewer FAIL; returns (doc, latest reviewer nn)."""

    doc = st.StateDoc(
        schema=1,
        task=st.Task(
            project="gate-overlap", slug="overlap-demo", title="Demo", phase="correction",
            kit_root="/tmp/kit", targets=["/tmp/kit"],
            journal=".agent-state/gate-overlap/tasks/overlap-demo/checkpoint.md",
            next_nn=1, created_at=AT, updated_at=AT,
        ),
        assignments=[],
    )

    def node(role: str, type_: str, edge: str, predecessor: int, verdict: str = "", digest: list[str] | None = None) -> int:
        a = st.add_assignment(doc, role=role, type_=type_, edge=edge, predecessor=predecessor, targets=["/tmp/kit"], at=AT)
        for to in _TO_VALIDATED:
            st.set_state(doc, a.nn, to, by="test", at=AT)
        if verdict:
            a.receipt_summary = st.ReceiptSummary(status="done", verdict=verdict, profile_ok=True, risks_digest=digest or [])
        st.set_state(doc, a.nn, "accepted", by="test", at=AT)
        return a.nn

    writer = node("node-backend", "implementação", "inicia", 0)
    first = node("reviewer", "revisão", "revisa", writer, "FAIL", first_digest)
    fix = node("node-backend", "correção", "corrige", first)
    second = node("reviewer", "revisão", "revisa", fix, "FAIL", second_digest)
    return doc, second


class OverlapRatioTests(unittest.TestCase):
    def test_ratio_values(self):
        self.assertAlmostEqual(gate.risks_overlap_ratio(["a", "b"], ["b", "c"]), 1 / 3)
        self.assertEqual(gate.risks_overlap_ratio(["a"], ["a"]), 1.0)
        self.assertIsNone(gate.risks_overlap_ratio([], ["a"]))
        self.assertIsNone(gate.risks_overlap_ratio(["a"], []))

    def test_band_boundaries(self):
        self.assertEqual(gate.classify_overlap(0.5), "no_progress")
        self.assertEqual(gate.classify_overlap(1.0), "no_progress")
        self.assertEqual(gate.classify_overlap(0.49), "gray")
        self.assertEqual(gate.classify_overlap(0.25), "gray")
        self.assertEqual(gate.classify_overlap(0.24), "progress")
        self.assertEqual(gate.classify_overlap(0.0), "progress")
        self.assertEqual(gate.classify_overlap(None), "progress")

    def test_lower_threshold_constant(self):
        self.assertEqual(gate.RISKS_OVERLAP_LOWER_THRESHOLD, 0.25)
        self.assertLess(gate.RISKS_OVERLAP_LOWER_THRESHOLD, gate.RISKS_OVERLAP_THRESHOLD)

    def test_substantially_unchanged(self):
        self.assertTrue(gate.risks_overlap_substantially(["a", "b"], ["a", "b"]))
        self.assertFalse(gate.risks_overlap_substantially(["a"], ["b"]))
        self.assertFalse(gate.risks_overlap_substantially([], ["a"]))
        self.assertFalse(gate.risks_overlap_substantially(["a", "b", "c"], ["c", "d"]))


class PProgressoReasonTests(unittest.TestCase):
    def _reasons(self, first: list[str], second: list[str]) -> list[str]:
        doc, reviewer_nn = _fail_chain(first, second)
        result = gate.evaluate_p_progresso(doc, reviewer_nn=reviewer_nn, user_decided=False)
        self.assertFalse(result.allowed)
        return result.reasons

    def test_second_fail_reason_names_gray_zone(self):
        reasons = self._reasons(["a", "b"], ["b", "c", "d"])  # ratio 0.25
        self.assertIn("overlap ratio 0.25 is in the gray zone [0.25, 0.5)", " ".join(reasons))

    def test_second_fail_reason_names_progress(self):
        reasons = self._reasons(["a", "b", "c"], ["c", "d", "e"])  # ratio 0.2
        self.assertIn("overlap ratio 0.20 indicates progress", " ".join(reasons))

    def test_second_fail_reason_handles_empty_digest(self):
        reasons = self._reasons([], ["a"])
        self.assertIn("overlap ratio n/a indicates progress", " ".join(reasons))

    def test_no_progress_reason_names_ratio(self):
        reasons = self._reasons(["a", "b"], ["a", "b", "c"])  # ratio 0.67
        joined = " ".join(reasons)
        self.assertIn("no progress", joined)
        self.assertIn("(overlap ratio 0.67: same findings", joined)

    def test_user_decided_still_allows_outside_no_progress(self):
        doc, reviewer_nn = _fail_chain(["a", "b"], ["b", "c", "d"])
        self.assertTrue(gate.evaluate_p_progresso(doc, reviewer_nn=reviewer_nn, user_decided=True).allowed)


if __name__ == "__main__":
    unittest.main()
