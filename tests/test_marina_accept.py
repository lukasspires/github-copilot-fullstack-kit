"""Tests for scripts/marina/accept.py — `marina accept`, closing one manually launched node.

A temporary kit holds one task without an envelope (the manual procedure)
and one node launched by `launch_node`. Every boundary is fake: the native
manager (a list of sessions, or `ManagerUnavailable`), `git_snapshot`, the
clock and the pid check. `receipt_lint` runs for real.
"""

from __future__ import annotations

import datetime
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.state as st
from scripts import common
from scripts.marina import accept, runner

KIT_ROOT = Path(__file__).resolve().parent.parent
AT = datetime.datetime(2026, 11, 16, 10, 0, 0, tzinfo=datetime.timezone.utc)
SID = "abcd1234"


class Fixture:
    def __init__(self, tmp: str, *, role: str = "node-backend", state: str = "working",
                 platform: str = "claude", targets: int = 1):
        self.kit = Path(tmp) / "kit"
        agents = self.kit / ".claude" / "agents"
        agents.mkdir(parents=True)
        shutil.copy(KIT_ROOT / ".claude" / "agents" / f"{role}.md", agents)
        (self.kit / "AGENTS.md").write_text("# kit\n", encoding="utf-8")
        self.targets = []
        for n in range(targets):
            target = Path(tmp) / f"target{n}"
            target.mkdir()
            self.targets.append(str(target))
        self.task_dir = self.kit / ".agent-state" / "demo" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.state_path = self.task_dir / "state.toml"
        doc = st.init_state(self.state_path, project="demo", slug="t1", title="Demo", kit_root=str(self.kit),
                            targets=self.targets, at=AT)
        edge, type_ = ("revisa_direta", "revisão") if role == "reviewer" else ("inicia", "implementação")
        reason = "visible sessions unavailable" if platform == "unavailable" else ""
        a = st.add_assignment(doc, role=role, type_=type_, edge=edge, predecessor=0, targets=self.targets,
                              platform=platform, reason=reason, at=AT)
        a.native.id = SID if platform == "claude" else ""
        path = ["prepared", "launched", "working", "finished", "receipt_received", "receipt_validated"]
        for to in path[: path.index(state) + 1]:
            st.append_event(a, to, by="test", at=AT)
        st.write_state(self.state_path, doc)
        self.a = a
        self.role = role
        (self.kit / a.handoff).write_text(
            f"# handoff\n\n- **Absolute profile (read explicitly):** `{agents / (role + '.md')}`\n", encoding="utf-8"
        )
        self.sessions: list[dict] = [self.session("done", "idle")]
        self.manager_error: Exception | None = None
        self.lock_alive = False
        self.snapshot_calls: list[str] = []
        self.snapshot_error: Exception | None = None
        self.manager_calls = 0
        self.projects_root = Path(tmp) / "projects"

    @staticmethod
    def session(state: str, status: str, waiting: str | None = None) -> dict:
        s = {"id": SID, "name": "t1 — x — 01 — implementação", "cwd": "/k", "kind": "background",
             "state": state, "status": status}
        if waiting:
            s["waitingFor"] = waiting
        return s

    # -- fakes ---------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        self.manager_calls += 1
        if self.manager_error is not None:
            raise self.manager_error
        return [dict(s) for s in self.sessions]

    def git_snapshot(self, target: str) -> str:
        self.snapshot_calls.append(target)
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return f"snap {target}\n"

    def deps(self) -> accept.AcceptDeps:
        return accept.AcceptDeps(list_sessions=self.list_sessions, git_snapshot=self.git_snapshot,
                                 now=lambda: AT + datetime.timedelta(minutes=5), pid_alive=lambda pid: self.lock_alive,
                                 projects_root=self.projects_root)

    def accept(self) -> accept.AcceptResult:
        return accept.accept_node(self.state_path, 1, kit_root=self.kit, deps=self.deps())

    # -- files -----------------------------------------------------------------

    def write_receipt(self, *, status: str = "done", verdict: str = "", valid: bool = True) -> None:
        profile = f"- **profile_read:** `{self.kit}/.claude/agents/{self.role}.md`\n" if valid else ""
        text = (
            f"# {self.a.title}\n\n## Status\n\n{status}\n\n## Changed\n\nSomething.\n\n"
            "## Profile and Instructions Read\n\n"
            f"{profile}- **instructions_read:**\n  - `{self.kit}/AGENTS.md`\n\n"
            "## Risks\n\n### RISK 1: something small (Severity: Low)\n\nBody.\n\n## Next\n\nNone.\n"
        )
        if verdict:
            text += f"\n## Verdict\n\n{verdict}\n"
        (self.kit / self.a.receipt).write_text(text, encoding="utf-8")

    def git_after(self) -> Path:
        return self.task_dir / "git-after-01.txt"

    def node(self) -> st.Assignment:
        return st.read_state(self.state_path).get_assignment(1)

    def lock(self, pid: int = 777) -> None:
        (self.task_dir / runner.LOCK_NAME).write_text(f'{{"pid": {pid}}}', encoding="utf-8")


class AcceptFlowTests(unittest.TestCase):
    def test_writer_working_done_receipt_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, targets=2)
            f.write_receipt()
            seen: list[tuple[str, bool]] = []
            real_write = st.write_state

            def spy(path, doc):
                seen.append((doc.get_assignment(1).state, f.git_after().exists()))
                real_write(path, doc)

            with mock.patch.object(accept, "write_state", side_effect=spy):
                result = f.accept()
            self.assertIsNone(result.refused)
            self.assertEqual(result.transitions, ["finished", "receipt_received", "receipt_validated", "accepted"])
            self.assertEqual(result.final_state, "accepted")
            self.assertIn(("receipt_received", True), seen)
            self.assertNotIn(("receipt_received", False), seen)
            self.assertEqual(f.git_after().read_text(encoding="utf-8"),
                             "".join(f"snap {t}\n" for t in f.targets))
            a = f.node()
            self.assertEqual(a.state, "accepted")
            self.assertEqual(a.receipt_summary.status, "done")
            self.assertEqual(a.receipt_summary.risks_digest, ["something small"])
            self.assertEqual({e.by for e in a.events[-4:]}, {"marina-accept"})

    def test_pending_receipt_closes_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt(status="pending")
            result = f.accept()
            self.assertEqual(result.final_state, "closed_pending")
            self.assertEqual(result.transitions[-1], "closed_pending")
            self.assertEqual(f.node().receipt_summary.status, "pending")

    def test_missing_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            result = f.accept()
            self.assertEqual(result.transitions, ["finished", "receipt_missing"])
            self.assertEqual(result.final_state, "receipt_missing")
            self.assertIsNone(result.refused)

    def test_invalid_receipt_keeps_first_error_in_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt(valid=False)
            result = f.accept()
            self.assertEqual(result.transitions, ["finished", "receipt_received", "receipt_invalid"])
            last = f.node().events[-1]
            self.assertEqual(last.to, "receipt_invalid")
            self.assertIn("profile_read", last.note)

    def test_reviewer_writes_no_git_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, role="reviewer")
            f.write_receipt(verdict="PASS")
            result = f.accept()
            self.assertEqual(result.final_state, "accepted")
            self.assertFalse(f.git_after().exists())
            self.assertEqual(f.snapshot_calls, [])
            self.assertEqual(f.node().receipt_summary.verdict, "PASS")

    def test_existing_git_after_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            f.git_after().write_text("earlier\n", encoding="utf-8")
            self.assertEqual(f.accept().final_state, "accepted")
            self.assertEqual(f.git_after().read_text(encoding="utf-8"), "earlier\n")
            self.assertEqual(f.snapshot_calls, [])

    def test_resumes_from_receipt_received(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, state="receipt_received")
            f.write_receipt()
            result = f.accept()
            self.assertEqual(result.transitions, ["receipt_validated", "accepted"])
            self.assertEqual(result.final_state, "accepted")

    def test_unavailable_platform_skips_the_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, platform="unavailable")
            f.write_receipt()
            f.manager_error = common.ManagerUnavailable("should not be called")
            result = f.accept()
            self.assertEqual(result.final_state, "accepted")
            self.assertEqual(f.manager_calls, 0)


class AcceptRefusalTests(unittest.TestCase):
    def _assert_untouched(self, f: Fixture, result: accept.AcceptResult, before: bytes, reason: str) -> None:
        self.assertEqual(result.refused, reason)
        self.assertEqual(result.transitions, [])
        self.assertEqual(f.state_path.read_bytes(), before)
        self.assertFalse(f.git_after().exists())

    def test_session_still_working(self):
        for session in (Fixture.session("working", "busy"),
                        Fixture.session("blocked", "waiting", "permission prompt")):
            with self.subTest(session=session), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                f.write_receipt()
                f.sessions = [session]
                before = f.state_path.read_bytes()
                result = f.accept()
                self._assert_untouched(f, result, before, "session still working")
                self.assertEqual(result.final_state, "working")

    def test_live_run_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            f.lock(777)
            f.lock_alive = True
            before = f.state_path.read_bytes()
            self._assert_untouched(f, f.accept(), before, "marina run is active (pid 777)")

    def test_dead_lock_does_not_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            f.lock(777)
            self.assertEqual(f.accept().final_state, "accepted")

    def test_manager_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            f.manager_error = common.ManagerUnavailable("claude not found")
            before = f.state_path.read_bytes()
            result = f.accept()
            self.assertEqual(result.transitions, [])
            self.assertIn("claude not found", result.refused)
            self.assertEqual(f.state_path.read_bytes(), before)

    def test_missing_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            before = f.state_path.read_bytes()
            result = accept.accept_node(f.state_path, 9, kit_root=f.kit, deps=f.deps())
            self.assertIsNotNone(result.refused)
            self.assertEqual(result.transitions, [])
            self.assertEqual(f.state_path.read_bytes(), before)

    def test_second_run_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            self.assertEqual(f.accept().final_state, "accepted")
            before = f.state_path.read_bytes()
            f.manager_error = common.ManagerUnavailable("not needed")
            result = f.accept()
            self.assertEqual((result.transitions, result.final_state, result.refused), ([], "accepted", None))
            self.assertEqual(f.state_path.read_bytes(), before)

    def _assert_unconfirmed(self, sessions: list[dict], reason: str, *, native_id: str = SID) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            if native_id != SID:
                doc = st.read_state(f.state_path)
                doc.get_assignment(1).native.id = native_id
                st.write_state(f.state_path, doc)
            f.sessions = sessions
            before = f.state_path.read_bytes()
            result = f.accept()
            self._assert_untouched(f, result, before, reason)
            self.assertEqual(result.final_state, "working")
            self.assertEqual(f.snapshot_calls, [])

    def test_session_absent_from_manager(self):
        self._assert_unconfirmed([dict(Fixture.session("done", "idle"), id="other999")],
                                 "session not found in manager")

    def test_empty_native_id(self):
        self._assert_unconfirmed([Fixture.session("done", "idle")], "native id is empty", native_id="")

    def test_two_matching_sessions(self):
        self._assert_unconfirmed([Fixture.session("done", "idle"), Fixture.session("done", "idle")],
                                 "more than one session matches")

    def test_session_state_unknown(self):
        unknown = Fixture.session("done", "idle")
        del unknown["state"], unknown["status"]
        self._assert_unconfirmed([unknown], "session state unknown")

    def _assert_no_manager_call(self, state: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, state=state)
            f.write_receipt()
            f.sessions = []
            result = f.accept()
            self.assertIsNone(result.refused)
            self.assertEqual(result.final_state, "accepted")
            self.assertEqual(f.manager_calls, 0)

    def test_finished_node_does_not_consult_the_manager(self):
        self._assert_no_manager_call("finished")

    def test_receipt_received_node_does_not_consult_the_manager(self):
        self._assert_no_manager_call("receipt_received")

    def test_git_after_is_on_disk_before_finished_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            seen: list[tuple[str, bool]] = []
            real_write = st.write_state

            def spy(path, doc):
                seen.append((doc.get_assignment(1).state, f.git_after().exists()))
                real_write(path, doc)

            with mock.patch.object(accept, "write_state", side_effect=spy):
                result = f.accept()
            self.assertEqual(result.final_state, "accepted")
            self.assertEqual(seen[0], ("finished", True))

    def test_git_after_write_failure_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            before = f.state_path.read_bytes()
            real_write_text = Path.write_text

            def failing(self_path, *args, **kwargs):
                if self_path.name == "git-after-01.txt":
                    raise OSError("disk full")
                return real_write_text(self_path, *args, **kwargs)

            with mock.patch.object(Path, "write_text", failing):
                result = f.accept()
            self._assert_untouched(f, result, before, "git-after not written: disk full")
            self.assertEqual(result.final_state, "working")

    def test_git_snapshot_failure_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.write_receipt()
            f.snapshot_error = OSError("git failed")
            before = f.state_path.read_bytes()
            result = f.accept()
            self.assertEqual(result.transitions, [])
            self.assertIn("git failed", result.refused)
            self.assertEqual(result.final_state, "working")
            self.assertEqual(f.state_path.read_bytes(), before)
            self.assertFalse(f.git_after().exists())


TRANSCRIPT_SID = "0123abcd-0123-4567-89ab-0123456789ab"
LIMIT_NOTE = 'usage_limit resets_at=2026-11-12T22:50:00+00:00 text="7:50pm (America/Sao_Paulo)"'


class AcceptUsageLimitTests(unittest.TestCase):
    """limite-uso stage 1: `marina accept` records the same usage limit note as the run."""

    @staticmethod
    def _limit(f: Fixture, transcript: str | None = "limit-then-system.jsonl") -> None:
        f.sessions = [dict(f.session("done", "idle"), sessionId=TRANSCRIPT_SID)]
        if transcript:
            folder = f.projects_root / "-kit"
            folder.mkdir(parents=True)
            shutil.copy(Path(__file__).resolve().parent / "fixtures" / "transcripts" / transcript,
                        folder / f"{TRANSCRIPT_SID}.jsonl")

    def test_receipt_missing_records_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            self._limit(f)
            result = f.accept()
            self.assertEqual(result.transitions, ["finished", "receipt_missing"])
            self.assertEqual(f.node().events[-1].note, LIMIT_NOTE)
            self.assertEqual(f.node().events[-1].by, "marina-accept")
            self.assertEqual(result.usage_limit.reset_text, "7:50pm (America/Sao_Paulo)")

    def test_receipt_invalid_from_finished_cites_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, state="finished")
            self._limit(f)
            f.write_receipt(valid=False)
            result = f.accept()
            self.assertEqual(result.transitions, ["receipt_received", "receipt_invalid"])
            note = f.node().events[-1].note
            self.assertTrue(note.endswith("; " + LIMIT_NOTE), note)
            self.assertIsNotNone(result.usage_limit)
            self.assertNotIn("You've hit", f.state_path.read_text(encoding="utf-8"))

    def test_without_transcript_nothing_changes(self):
        for transcript in (None, "limit-then-normal.jsonl"):
            with self.subTest(transcript=transcript), tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                self._limit(f, transcript)
                result = f.accept()
                self.assertEqual(result.transitions, ["finished", "receipt_missing"])
                self.assertEqual(f.node().events[-1].note, "")
                self.assertIsNone(result.usage_limit)

    def test_unavailable_manager_for_a_finished_node_is_not_a_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, state="finished")
            f.manager_error = common.ManagerUnavailable("down")
            result = f.accept()
            self.assertIsNone(result.refused)
            self.assertEqual(result.transitions, ["receipt_missing"])
            self.assertIsNone(result.usage_limit)


if __name__ == "__main__":
    unittest.main()
