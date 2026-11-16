"""Tests for gate's unknown-working-session check (P_writer) against manager states.

Kept apart from tests/test_gate.py. A session that ended its turn but still
reports `state: working` with `status: idle` (CLI 2.1.306, F6 acceptance) is
not working; a busy one is.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.state as st
from scripts import gate
from scripts.marina import coordinator

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


SID = "0123abcd-0123-4567-89ab-0123456789ab"
COORDINATOR = "registered"  # resolved per test by `_evaluate`, so a missing module fails tests, not the import


def _marina(**overrides) -> dict:
    session = {"id": "c0ffee01", "sessionId": SID, "pid": 4321, "name": "marina (11)", "cwd": TARGET,
               "kind": "interactive", "state": "working", "status": "busy"}
    session.update(overrides)
    return session


def _evaluate(sessions: list[dict], registered: str | None) -> gate.GateResult:
    coord = coordinator.Coordinator(session_id=SID, pid=4321, at=AT) if registered else None
    return gate.evaluate_gate(
        _doc(), role="node-backend", type_="implementação", edge="inicia", predecessor=0, targets=[TARGET],
        git_diff_acknowledged=True, list_sessions=lambda: sessions, coordinator=coord,
    )


class CoordinatorSessionTests(unittest.TestCase):
    """gate-coordenadora: the registered coordinator session (same sessionId and pid) is ignored."""

    def test_registered_coordinator_working_in_target_is_allowed_with_a_note(self):
        result = _evaluate([_marina()], COORDINATOR)
        self.assertTrue(result.allowed, result.reasons)
        self.assertIn(f"coordinator session {SID[:8]} ignored", result.notes)

    def test_same_session_id_with_another_pid_is_refused(self):
        result = _evaluate([_marina(pid=999)], COORDINATOR)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reasons,
                         ["unknown working session with cwd in the new node's targets: 'marina (11)'"])
        self.assertEqual(result.notes, [])

    def test_same_pid_with_another_session_id_is_refused(self):
        result = _evaluate([_marina(sessionId="fedcba98-0123-4567-89ab-0123456789ab")], COORDINATOR)
        self.assertFalse(result.allowed)

    def test_another_unknown_session_alongside_the_coordinator_is_refused_citing_only_it(self):
        other = _marina(id="0badf00d", sessionId="fedcba98-0123-4567-89ab-0123456789ab", pid=77,
                        name="someone else")
        result = _evaluate([_marina(), other], COORDINATOR)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reasons,
                         ["unknown working session with cwd in the new node's targets: 'someone else'"])

    def test_without_registration_the_coordinator_is_refused_as_before(self):
        result = _evaluate([_marina()], None)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reasons,
                         ["unknown working session with cwd in the new node's targets: 'marina (11)'"])
        self.assertEqual(result.notes, [])


class CoordinatorCliTests(unittest.TestCase):
    """`scripts/gate.py` loads the registration from the task's own kit_root and project."""

    def _main(self, kit: Path, state_path: Path) -> tuple[int, str]:
        out = io.StringIO()
        argv = ["--state", str(state_path), "--role", "node-backend", "--type", "implementação", "--edge", "inicia",
                "--predecessor", "0", "--target", TARGET, "--git-diff-acknowledged"]
        with mock.patch("scripts.common.list_manager_sessions", lambda: [_marina()]), \
                contextlib.redirect_stdout(out):
            code = gate.main(argv)
        return code, out.getvalue()

    def test_cli_ignores_the_registered_coordinator_and_refuses_without_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp) / "kit"
            state_path = kit / ".agent-state" / "demo" / "tasks" / "t1" / "state.toml"
            state_path.parent.mkdir(parents=True)
            doc = st.init_state(state_path, project="demo", slug="t1", title="Demo", kit_root=str(kit),
                                targets=[TARGET], at=AT)
            st.write_state(state_path, doc)
            code, out = self._main(kit, state_path)
            self.assertEqual(code, 1, out)
            self.assertIn("unknown working session", out)
            env = {"CLAUDE_CODE_AGENT": "marina", "CLAUDE_CODE_SESSION_ID": SID}
            self.assertTrue(coordinator.register(kit, "demo", env=env, ppid=4321, now=AT))
            code, out = self._main(kit, state_path)
            self.assertEqual(code, 0, out)
            self.assertIn(f"NOTE: coordinator session {SID[:8]} ignored", out)


if __name__ == "__main__":
    unittest.main()
