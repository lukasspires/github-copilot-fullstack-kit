"""Tests for gate's unknown-working-session check (P_writer) against manager states.

Kept apart from tests/test_gate.py. A session that ended its turn but still
reports `state: working` with `status: idle` (CLI 2.1.306, F6 acceptance) is
not working; a busy one is.
"""

from __future__ import annotations

import datetime
import unittest

import scripts.state as st
from scripts import gate

AT = datetime.datetime(2026, 10, 27, 1, 0, 0, tzinfo=datetime.timezone.utc)
TARGET = "/tmp/kit"


def _doc() -> st.StateDoc:
    return st.StateDoc(
        schema=1,
        task=st.Task(project="gate-sessions", slug="sessions-demo", title="Demo", phase="implementation",
                     kit_root=TARGET, targets=[TARGET],
                     journal=".agent-state/gate-sessions/tasks/sessions-demo/checkpoint.md",
                     next_nn=1, created_at=AT, updated_at=AT),
        assignments=[],
    )


def _reasons(session: dict) -> list[str]:
    result = gate.evaluate_gate(
        _doc(), role="node-backend", type_="implementação", edge="inicia", predecessor=0, targets=[TARGET],
        git_diff_acknowledged=True, list_sessions=lambda: [session],
    )
    return [r for r in result.reasons if "unknown working session" in r]


class UnknownWorkingSessionTests(unittest.TestCase):
    def test_busy_session_in_targets_blocks(self):
        session = {"name": "other — node-backend — 01 — implementação", "cwd": TARGET, "state": "working",
                   "status": "busy"}
        self.assertEqual(len(_reasons(session)), 1)

    def test_session_that_ended_its_turn_as_working_idle_does_not_block(self):
        session = {"name": "other — node-backend — 01 — implementação", "cwd": TARGET, "state": "working",
                   "status": "idle"}
        self.assertEqual(_reasons(session), [])


if __name__ == "__main__":
    unittest.main()
