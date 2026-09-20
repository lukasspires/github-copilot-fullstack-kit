"""Tests for scripts/status_claude.py — observes working/waiting_approval/
finished per G2, filtering by the confirmed `cwd` field and/or title
prefix. Every manager call is injected; never the real installed CLI.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import state as st
from scripts import status_claude

AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _write_scratch_state(path, *, assignment_state: str, at: datetime.datetime = AT) -> None:
    """Build a minimal one-assignment `state.toml` at `path`, with that
    assignment already in `assignment_state` (jumping there directly via
    `append_event(..., enforce=False)` — a legitimate test-fixture use of
    that escape hatch, never used by production code). Never touches real
    `.agent-state/` content."""

    task = st.Task(
        project="demo-project",
        slug="demo-task",
        title="Demo task",
        phase="delivery",
        kit_root="/tmp/kit",
        targets=["/tmp/kit"],
        journal=str(Path(path).parent / "checkpoint.md"),
        next_nn=1,
        created_at=at,
        updated_at=at,
    )
    doc = st.StateDoc(schema=1, task=task, assignments=[])
    assignment = st.add_assignment(
        doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
        targets=["/tmp/kit"], at=at,
    )
    if assignment_state != "reserved":
        st.append_event(assignment, assignment_state, by="test-fixture", at=at, enforce=False)
    st.write_state(path, doc)


def _session(**overrides) -> dict:
    base = {"name": "demo-task — node-backend — 01 — implementação", "cwd": "/mnt/kit", "state": "working"}
    base.update(overrides)
    return base


class ClassifySessionTests(unittest.TestCase):
    """Acceptance criterion 8: one fixture example of each classification."""

    def test_working(self):
        self.assertEqual(status_claude.classify_session(_session(state="working")), "working")

    def test_waiting_approval_with_permission_prompt(self):
        session = _session(state="working", status="waiting", waitingFor="permission prompt")
        self.assertEqual(status_claude.classify_session(session), "waiting_approval")

    def test_finished_done(self):
        self.assertEqual(status_claude.classify_session(_session(state="done")), "finished")

    def test_finished_stopped(self):
        self.assertEqual(status_claude.classify_session(_session(state="stopped")), "finished")

    def test_finished_failed(self):
        self.assertEqual(status_claude.classify_session(_session(state="failed")), "finished")

    def test_interactive_session_missing_state_is_unknown_not_an_error(self):
        self.assertEqual(status_claude.classify_session({"name": "interactive"}), "unknown")

    def test_unknown_manager_state_still_fails_loudly(self):
        with self.assertRaises(status_claude.common.ManagerSchemaError):
            status_claude.classify_session(_session(state="sleeping"))


class FindTaskSessionsTests(unittest.TestCase):
    def test_matches_by_cwd(self):
        sessions = [_session(cwd="/mnt/kit"), _session(name="other — x — 01 — implementação", cwd="/mnt/other")]
        hits = status_claude.find_task_sessions(sessions, cwd="/mnt/kit")
        self.assertEqual(len(hits), 1)

    def test_matches_by_title_prefix(self):
        sessions = [_session(), _session(name="other-task — x — 01 — implementação", cwd="/mnt/other")]
        hits = status_claude.find_task_sessions(sessions, title_prefix="demo-task —")
        self.assertEqual(len(hits), 1)

    def test_neither_filter_matches_nothing(self):
        sessions = [_session()]
        self.assertEqual(status_claude.find_task_sessions(sessions), [])

    def test_both_filters_supplied_require_both_to_match(self):
        # Same cwd, different task title: cwd alone would (wrongly) match.
        same_cwd_other_task = _session(name="other-task — x — 01 — implementação", cwd="/mnt/kit")
        sessions = [_session(cwd="/mnt/kit"), same_cwd_other_task]
        hits = status_claude.find_task_sessions(sessions, cwd="/mnt/kit", title_prefix="demo-task —")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["name"], "demo-task — node-backend — 01 — implementação")


class SessionNnTests(unittest.TestCase):
    """`session_nn` parses the `nn` segment of the "<task> — <role> —
    <nn> — <type>" title convention (docs/agent-workflow.md)."""

    def test_parses_nn_from_a_well_formed_title(self):
        self.assertEqual(
            status_claude.session_nn("gate-launch-scripts — kit-tooling — 03 — correção"), 3
        )

    def test_none_for_a_title_without_four_segments(self):
        self.assertIsNone(status_claude.session_nn("interactive"))

    def test_none_when_the_nn_segment_is_not_numeric(self):
        self.assertIsNone(status_claude.session_nn("a — b — not-a-number — c"))


class FindTaskSessionsDisambiguationTests(unittest.TestCase):
    """Finding 1 (`02-reviewer-receipt.md`): `--id`/`--nn` narrow a
    `cwd`/`title_prefix` match down to one specific assignment, for
    `watch_claude.run_watch` to consume (see `test_watch_claude.py`'s
    `RunWatchAmbiguityTests` for the loud-error side of this fix)."""

    def _same_task_two_assignments(self):
        return [
            _session(name="gate-launch-scripts — kit-tooling — 01 — implementação", cwd="/mnt/kit", state="done", id="aaaaaaaa"),
            _session(name="gate-launch-scripts — reviewer — 02 — revisão", cwd="/mnt/kit", state="working", id="bbbbbbbb"),
        ]

    def test_cwd_and_title_prefix_alone_still_match_both(self):
        hits = status_claude.find_task_sessions(
            self._same_task_two_assignments(), cwd="/mnt/kit", title_prefix="gate-launch-scripts —"
        )
        self.assertEqual(len(hits), 2)

    def test_native_id_narrows_to_exactly_one(self):
        hits = status_claude.find_task_sessions(
            self._same_task_two_assignments(),
            cwd="/mnt/kit",
            title_prefix="gate-launch-scripts —",
            native_id="bbbbbbbb",
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], "bbbbbbbb")

    def test_nn_narrows_to_exactly_one(self):
        hits = status_claude.find_task_sessions(
            self._same_task_two_assignments(),
            cwd="/mnt/kit",
            title_prefix="gate-launch-scripts —",
            nn=2,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], "bbbbbbbb")

    def test_nn_or_native_id_alone_is_a_sufficient_filter(self):
        hits = status_claude.find_task_sessions(self._same_task_two_assignments(), nn=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], "aaaaaaaa")


class ReportTests(unittest.TestCase):
    def test_waiting_approval_prints_literal_attach_instruction(self):
        session = _session(id="182689df", status="waiting", waitingFor="permission prompt")
        lines = status_claude.report([session])
        self.assertEqual(lines[0].attach_message, "claude attach 182689df")

    def test_non_waiting_session_has_no_attach_message(self):
        lines = status_claude.report([_session()])
        self.assertIsNone(lines[0].attach_message)


class MainCliTests(unittest.TestCase):
    def _run_main_with(self, sessions: list[dict], argv: list[str]):
        import scripts.common as common

        original = common.list_manager_sessions
        common.list_manager_sessions = lambda **kwargs: sessions
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = status_claude.main(argv)
            return rc, buf.getvalue()
        finally:
            common.list_manager_sessions = original

    def test_waiting_approval_session_exits_nonzero_and_prints_attach(self):
        session = _session(id="182689df", status="waiting", waitingFor="permission prompt")
        rc, out = self._run_main_with([session], ["--cwd", "/mnt/kit"])
        self.assertEqual(rc, 1)
        self.assertIn("claude attach 182689df", out)

    def test_finished_session_exits_zero(self):
        rc, out = self._run_main_with([_session(state="done")], ["--cwd", "/mnt/kit"])
        self.assertEqual(rc, 0)
        self.assertIn("finished", out)

    def test_missing_filter_arguments_rejected(self):
        buf = io.StringIO()
        with redirect_stdout(io.StringIO()):
            import contextlib

            with contextlib.redirect_stderr(buf):
                rc = status_claude.main([])
        self.assertEqual(rc, 2)
        self.assertIn("--cwd/--title-prefix", buf.getvalue())

    def test_id_alone_satisfies_the_required_filter_check(self):
        session = _session(id="bbbbbbbb", state="working")
        rc, out = self._run_main_with([session], ["--id", "bbbbbbbb"])
        self.assertEqual(rc, 0)
        self.assertIn("working", out)


class RecordObservedTransitionTests(unittest.TestCase):
    """Finding 2 (tooling-gaps-fix): `record_observed_transition` persists
    one observed G2 transition into a `state.toml`, reusing
    `scripts.state.append_event`/`can_transition` for legality — never
    reimplementing it. Uses a scratch, temp-dir `state.toml` only; never
    real `.agent-state/` content."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_path = Path(self.tmpdir.name) / "state.toml"

    def test_records_legal_transition_and_updates_last_seen(self):
        _write_scratch_state(self.state_path, assignment_state="launched")
        wrote = status_claude.record_observed_transition(self.state_path, 1, "working", at=AT)
        self.assertTrue(wrote)

        doc = st.read_state(self.state_path)
        a = doc.get_assignment(1)
        self.assertEqual(a.state, "working")
        self.assertEqual(a.events[-1].to, "working")
        self.assertEqual(a.events[-1].from_, "launched")
        self.assertEqual(a.events[-1].by, "status")
        self.assertEqual(a.native.last_seen, "working")
        self.assertEqual(a.native.last_seen_at, AT)

    def test_waiting_approval_and_finished_are_also_recordable(self):
        _write_scratch_state(self.state_path, assignment_state="working")
        wrote = status_claude.record_observed_transition(self.state_path, 1, "waiting_approval", at=AT)
        self.assertTrue(wrote)
        self.assertEqual(st.read_state(self.state_path).get_assignment(1).state, "waiting_approval")

    def test_no_write_when_classification_is_unknown(self):
        _write_scratch_state(self.state_path, assignment_state="launched")
        before = self.state_path.read_text(encoding="utf-8")
        wrote = status_claude.record_observed_transition(self.state_path, 1, "unknown", at=AT)
        self.assertFalse(wrote)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_no_write_when_classification_is_none_no_session_matched(self):
        _write_scratch_state(self.state_path, assignment_state="launched")
        before = self.state_path.read_text(encoding="utf-8")
        wrote = status_claude.record_observed_transition(self.state_path, 1, None, at=AT)
        self.assertFalse(wrote)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_no_op_no_duplicate_event_when_already_in_target_state(self):
        _write_scratch_state(self.state_path, assignment_state="working")
        before = self.state_path.read_text(encoding="utf-8")
        wrote = status_claude.record_observed_transition(self.state_path, 1, "working", at=AT)
        self.assertFalse(wrote)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_illegal_transition_warns_to_stderr_and_skips_write_rather_than_raising(self):
        # `prepared` can only legally go to `launched`/`uncertain` (G2); an
        # observed "working" here would be illegal — the defensive guard
        # for launch-claude never having actually run.
        _write_scratch_state(self.state_path, assignment_state="prepared")
        before = self.state_path.read_text(encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            wrote = status_claude.record_observed_transition(self.state_path, 1, "working", at=AT)
        self.assertFalse(wrote)
        self.assertIn("illegal", buf.getvalue())
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)


class MainCliStateRecordingTests(unittest.TestCase):
    """Finding 2 through the real CLI `main()` entry point: `--state`/`--nn`
    required together, and `status-claude`'s existing human-read behavior
    stays unchanged when neither is supplied."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_path = Path(self.tmpdir.name) / "state.toml"

    def _run_main_with(self, sessions: list[dict], argv: list[str]):
        import scripts.common as common

        original = common.list_manager_sessions
        common.list_manager_sessions = lambda **kwargs: sessions
        try:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = status_claude.main(argv)
            return rc, out.getvalue(), err.getvalue()
        finally:
            common.list_manager_sessions = original

    def test_state_without_nn_is_rejected(self):
        rc, out, err = self._run_main_with([], ["--cwd", "/mnt/kit", "--state", str(self.state_path)])
        self.assertEqual(rc, 2)
        self.assertIn("--state requires --nn", err)

    def test_nn_without_state_is_allowed_as_a_pure_filter(self):
        """RISK 2 (tooling-gaps-fix): --nn alone must keep working as a pure
        disambiguation filter, with no persistence attempted — a capability
        already reviewed and endorsed in a prior task (gate-launch-scripts)."""
        session = _session(state="working", cwd="/mnt/kit", name="demo-task — node-backend — 01 — implementação")
        rc, out, err = self._run_main_with([session], ["--nn", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("working", out)
        self.assertEqual(err, "")

    def test_state_and_nn_together_persist_the_observed_transition(self):
        _write_scratch_state(self.state_path, assignment_state="launched")
        session = _session(state="working", cwd="/mnt/kit", name="demo-task — node-backend — 01 — implementação")
        rc, out, err = self._run_main_with(
            [session], ["--cwd", "/mnt/kit", "--nn", "1", "--state", str(self.state_path)]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(st.read_state(self.state_path).get_assignment(1).state, "working")

    def test_without_state_or_nn_behaves_exactly_as_before(self):
        """Regression: `report()`/`main()`'s existing multi-match, human-read
        output is unaffected when `--state`/`--nn` are not supplied — purely
        additive."""

        session = _session(state="done", cwd="/mnt/kit")
        rc, out, err = self._run_main_with([session], ["--cwd", "/mnt/kit"])
        self.assertEqual(rc, 0)
        self.assertIn("finished", out)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
