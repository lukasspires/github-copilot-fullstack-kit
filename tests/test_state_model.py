"""Tests for scripts.state (read/write/round-trip) and scripts.state.model.

Uses the versioned fixture tests/fixtures/visible-sessions/state.toml
(read-only here; never modified) plus small inline fixtures for the
model's structural validation. Deterministic, no network, no real
.agent-state/ contents.
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import scripts.state as st
from scripts.state.model import StateError, mode_for_role

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "visible-sessions" / "state.toml"


class ImportTests(unittest.TestCase):
    def test_import_scripts_state(self):
        # Acceptance criterion 1: `import scripts.state` works with stdlib only.
        import scripts.state  # noqa: F401


class ModeForRoleTests(unittest.TestCase):
    def test_reader_roles(self):
        for role in ("reviewer", "architect", "analista-redmine"):
            self.assertEqual(mode_for_role(role), "reader")

    def test_writer_roles(self):
        for role in ("node-backend", "kit-tooling", "angular", "coordinator"):
            self.assertEqual(mode_for_role(role), "writer")


class ReadFixtureTests(unittest.TestCase):
    def setUp(self):
        self.doc = st.read_state(FIXTURE)

    def test_task_fields(self):
        self.assertEqual(self.doc.task.project, "github-copilot-fullstack-kit")
        self.assertEqual(self.doc.task.slug, "visible-sessions")
        self.assertEqual(self.doc.task.next_nn, 6)

    def test_five_assignments_in_order(self):
        self.assertEqual([a.nn for a in self.doc.assignments], [1, 2, 3, 4, 5])

    def test_node1_preparation_failed(self):
        a = self.doc.get_assignment(1)
        self.assertEqual(a.state, "preparation_failed")
        self.assertEqual(a.events[-1].by, "preflight")

    def test_node2_receipt_summary(self):
        a = self.doc.get_assignment(2)
        self.assertEqual(a.receipt_summary.verdict, "PASS_WITH_RISKS")
        self.assertIn("permission enforcement reliance on instructions", a.receipt_summary.risks_digest)

    def test_node4_unavailable_platform_has_reason(self):
        a = self.doc.get_assignment(4)
        self.assertEqual(a.native.platform, "unavailable")
        self.assertTrue(a.native.reason.strip())

    def test_get_assignment_missing_raises(self):
        with self.assertRaises(StateError):
            self.doc.get_assignment(999)


class RoundTripTests(unittest.TestCase):
    """Acceptance criterion 2: read + rewrite yields an equal data structure."""

    def test_round_trip_equals_original_parse(self):
        original_raw = tomllib.loads(FIXTURE.read_text(encoding="utf-8"))
        doc = st.read_state(FIXTURE)
        rewritten_text = st.dumps_state(doc)
        rewritten_raw = tomllib.loads(rewritten_text)
        self.assertEqual(rewritten_raw, original_raw)

    def test_round_trip_is_idempotent(self):
        doc = st.read_state(FIXTURE)
        text1 = st.dumps_state(doc)
        doc2 = st.parse_state_text(text1)
        text2 = st.dumps_state(doc2)
        self.assertEqual(tomllib.loads(text1), tomllib.loads(text2))


class StructuralValidationTests(unittest.TestCase):
    def test_missing_task_field_raises(self):
        raw = {"schema": 1, "task": {"project": "demo"}}
        with self.assertRaises(StateError):
            st.StateDoc.from_raw(raw)

    def test_bad_slug_raises(self):
        raw = {
            "schema": 1,
            "task": {
                "project": "Not Ok",
                "slug": "ok",
                "title": "t",
                "phase": "review",
                "kit_root": "/x",
                "targets": ["/x"],
                "journal": "j.md",
                "next_nn": 1,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
            "assignments": [],
        }
        with self.assertRaises(StateError):
            st.StateDoc.from_raw(raw)

    def test_unsupported_schema_version_raises(self):
        with self.assertRaises(StateError):
            st.StateDoc.from_raw({"schema": 2, "task": {}})

    def test_assignment_missing_native_raises(self):
        raw = tomllib.loads(FIXTURE.read_text(encoding="utf-8"))
        broken = dict(raw)
        broken["assignments"] = [dict(raw["assignments"][0])]
        del broken["assignments"][0]["native"]
        with self.assertRaises(StateError):
            st.StateDoc.from_raw(broken)

    def test_assignment_no_events_raises(self):
        raw = tomllib.loads(FIXTURE.read_text(encoding="utf-8"))
        broken = dict(raw)
        broken["assignments"] = [dict(raw["assignments"][0])]
        broken["assignments"][0]["events"] = []
        with self.assertRaises(StateError):
            st.StateDoc.from_raw(broken)


if __name__ == "__main__":
    unittest.main()
