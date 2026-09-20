"""Tests for scripts/watch_claude.py — bounded polling loop (plan §6.2).

Every test injects a fake clock (a counter, not `time.monotonic`) and a
fixed queue of manager snapshots (never the real installed CLI); `sleep`
is a no-op recorder, never a real `time.sleep`. Acceptance criterion 9.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import tempfile
import unittest
from pathlib import Path

from scripts import state as st
from scripts import watch_claude

AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _session(**overrides) -> dict:
    base = {"name": "demo-task — node-backend — 01 — implementação", "cwd": "/mnt/kit", "state": "working"}
    base.update(overrides)
    return base


def _write_scratch_state(path, *, assignment_state: str, at: datetime.datetime = AT) -> None:
    """Same scratch-fixture helper as `test_status_claude.py` (kept local
    to avoid a cross-test-module import); never touches real
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


class _FakeClock:
    """Advances by a fixed step every time it is read."""

    def __init__(self, step: float = 1.0):
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.t
        self.t += self.step
        return value


class _Queue:
    """Returns each snapshot in order, then repeats the last one."""

    def __init__(self, snapshots: list[list[dict]]):
        self.snapshots = snapshots
        self.calls = 0

    def __call__(self) -> list[dict]:
        idx = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[idx]


class MandatoryArgumentsTests(unittest.TestCase):
    def test_zero_interval_rejected(self):
        with self.assertRaises(ValueError):
            watch_claude.run_watch(lambda: [], interval=0, max_duration=10, title_prefix="x", sleep=lambda s: None, clock=_FakeClock())

    def test_negative_max_duration_rejected(self):
        with self.assertRaises(ValueError):
            watch_claude.run_watch(lambda: [], interval=1, max_duration=-1, title_prefix="x", sleep=lambda s: None, clock=_FakeClock())

    def test_cli_requires_both_arguments(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            watch_claude.main(["--cwd", "/mnt/kit"])  # missing --interval/--max-duration


class RunWatchTests(unittest.TestCase):
    def test_exits_on_observed_state_change(self):
        queue = _Queue([[_session(state="working")], [_session(state="working")], [_session(state="done")]])
        sleeps: list[float] = []
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            sleep=sleeps.append, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_STATE_CHANGED)
        self.assertEqual(outcome.classification, "finished")
        self.assertEqual(sleeps, [5, 5])  # slept twice (working, working) before observing the change

    def test_exits_immediately_on_waiting_approval_never_answers_it(self):
        queue = _Queue([[_session(state="working", status="waiting", waitingFor="permission prompt")]])
        sleeps: list[float] = []
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            sleep=sleeps.append, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_WAITING_APPROVAL)
        self.assertEqual(sleeps, [], "must exit the instant it observes waiting_approval, before ever sleeping")

    def test_times_out_with_last_observed_classification(self):
        queue = _Queue([[_session(state="working")]])  # never changes
        outcome = watch_claude.run_watch(
            queue, interval=1, max_duration=3, title_prefix="demo-task —",
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_TIMED_OUT)
        self.assertEqual(outcome.classification, "working")

    def test_no_matching_session_is_a_stable_none_classification(self):
        queue = _Queue([[]])
        outcome = watch_claude.run_watch(
            queue, interval=1, max_duration=2, title_prefix="demo-task —",
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_TIMED_OUT)
        self.assertIsNone(outcome.classification)

    def test_never_uses_real_sleep_or_wall_clock(self):
        text = (watch_claude.__file__ and __import__("pathlib").Path(watch_claude.__file__).read_text(encoding="utf-8"))
        # time.sleep/time.monotonic are only the *default* parameter values;
        # every test above replaces both, and production code never calls
        # them directly outside that default.
        self.assertNotIn("time.sleep(", text)
        self.assertNotIn("time.monotonic()", text)


class TransientUnknownTests(unittest.TestCase):
    """Finding 3 (tooling-gaps-fix): a real evidence scenario — a session's
    manager entry was caught mid-shutdown by one poll, classifying
    transiently as `"unknown"`, even though the very next poll correctly
    resolved to `"finished"`. `run_watch` must not mistake the transient
    `"unknown"` poll for a reportable `state_changed` exit."""

    def _unknown_session(self):
        # No `state`/`status` at all — the documented "interactive session
        # omits these fields" shape, which classify_session resolves to
        # "unknown" without raising (see status_claude.classify_session).
        return {"name": "demo-task — node-backend — 01 — implementação", "cwd": "/mnt/kit"}

    def test_transient_unknown_does_not_exit_and_next_real_change_does(self):
        queue = _Queue(
            [[_session(state="working")], [self._unknown_session()], [_session(state="done")]]
        )
        sleeps: list[float] = []
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            sleep=sleeps.append, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_STATE_CHANGED)
        self.assertEqual(outcome.classification, "finished")
        # Slept on poll 1 (working) and poll 2 (transient unknown) before
        # exiting on poll 3 (finished) — the transient unknown poll must
        # not itself trigger an exit.
        self.assertEqual(sleeps, [5, 5])

    def test_unknown_on_the_very_first_poll_is_not_transient(self):
        # No prior real classification to be "transient" relative to —
        # first_pass already suppresses the state_changed check here,
        # same as any other first-poll classification.
        queue = _Queue([[self._unknown_session()], [_session(state="done")]])
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_STATE_CHANGED)
        self.assertEqual(outcome.classification, "finished")

    def test_timeout_while_stuck_in_transient_unknown_reports_unknown(self):
        # unknown never resolves before max_duration: existing timeout
        # behavior applies, reporting the last poll's genuine classification.
        queue = _Queue([[_session(state="working")], [self._unknown_session()]])
        outcome = watch_claude.run_watch(
            queue, interval=1, max_duration=2, title_prefix="demo-task —",
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_TIMED_OUT)
        self.assertEqual(outcome.classification, "unknown")

    def test_waiting_approval_still_exits_immediately_regardless_of_unknown(self):
        queue = _Queue(
            [
                [_session(state="working")],
                [self._unknown_session()],
                [_session(state="working", status="waiting", waitingFor="permission prompt")],
            ]
        )
        outcome = watch_claude.run_watch(
            queue, interval=1, max_duration=1000, title_prefix="demo-task —",
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_WAITING_APPROVAL)


class RunWatchAmbiguityTests(unittest.TestCase):
    """Regression for Finding 1 (`02-reviewer-receipt.md`): two sessions of
    the same task sharing `cwd`/`title_prefix`, different states.
    `run_watch` must no longer silently pick `matches[0]` (the old,
    pre-fix behavior would have returned `timed_out`/`classification=
    'finished'` here, wrongly reporting the *other*, already-finished
    session instead of raising) — it must either resolve correctly via a
    supplied `--id`/`--nn`, or raise `AmbiguousSessionError` loudly when
    ambiguity remains.
    """

    def _two_sessions(self):
        # Same task, same cwd, same title prefix — the real shape after a
        # task's second assignment (exactly Finding 1's real-manager case:
        # 01-kit-tooling finished, 02-reviewer still working).
        finished = _session(
            name="gate-launch-scripts — kit-tooling — 01 — implementação",
            cwd="/mnt/kit",
            state="done",
            id="aaaaaaaa",
        )
        working = _session(
            name="gate-launch-scripts — reviewer — 02 — revisão",
            cwd="/mnt/kit",
            state="working",
            id="bbbbbbbb",
        )
        return [finished, working]

    def test_ambiguous_after_all_filters_raises_loudly_not_matches_zero(self):
        queue = _Queue([self._two_sessions()])
        with self.assertRaises(watch_claude.AmbiguousSessionError) as ctx:
            watch_claude.run_watch(
                queue,
                interval=1,
                max_duration=2,
                cwd="/mnt/kit",
                title_prefix="gate-launch-scripts —",
                sleep=lambda s: None,
                clock=_FakeClock(step=1),
            )
        self.assertIn("2 sessions", str(ctx.exception))
        self.assertIn("--id or --nn", str(ctx.exception))

    def test_id_disambiguates_to_the_correct_working_session(self):
        queue = _Queue([self._two_sessions()])
        outcome = watch_claude.run_watch(
            queue,
            interval=1,
            max_duration=2,
            cwd="/mnt/kit",
            title_prefix="gate-launch-scripts —",
            native_id="bbbbbbbb",
            sleep=lambda s: None,
            clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_TIMED_OUT)
        self.assertEqual(outcome.classification, "working")
        self.assertEqual(outcome.session["id"], "bbbbbbbb")

    def test_nn_disambiguates_to_the_correct_working_session(self):
        queue = _Queue([self._two_sessions()])
        outcome = watch_claude.run_watch(
            queue,
            interval=1,
            max_duration=2,
            cwd="/mnt/kit",
            title_prefix="gate-launch-scripts —",
            nn=2,
            sleep=lambda s: None,
            clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_TIMED_OUT)
        self.assertEqual(outcome.classification, "working")
        self.assertEqual(outcome.session["id"], "bbbbbbbb")

    def test_id_still_ambiguous_if_it_matches_more_than_one_session(self):
        # Both sessions given the same id: --id alone does not guarantee
        # disambiguation if the caller's data is itself ambiguous — still
        # a loud error, never a silent pick.
        sessions = self._two_sessions()
        for session in sessions:
            session["id"] = "cccccccc"
        queue = _Queue([sessions])
        with self.assertRaises(watch_claude.AmbiguousSessionError):
            watch_claude.run_watch(
                queue,
                interval=1,
                max_duration=2,
                cwd="/mnt/kit",
                title_prefix="gate-launch-scripts —",
                native_id="cccccccc",
                sleep=lambda s: None,
                clock=_FakeClock(step=1),
            )


class MainCliAmbiguityTests(unittest.TestCase):
    """Same scenario, through the real CLI `main()` entry point."""

    def _sessions(self):
        return [
            _session(
                name="gate-launch-scripts — kit-tooling — 01 — implementação",
                cwd="/mnt/kit",
                state="done",
                id="aaaaaaaa",
            ),
            _session(
                name="gate-launch-scripts — reviewer — 02 — revisão",
                cwd="/mnt/kit",
                state="working",
                id="bbbbbbbb",
            ),
        ]

    def _run_main_with(self, sessions, argv):
        import scripts.common as common

        original = common.list_manager_sessions
        common.list_manager_sessions = lambda **kwargs: sessions
        try:
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = watch_claude.main(argv)
            return rc, out.getvalue(), err.getvalue()
        finally:
            common.list_manager_sessions = original

    def test_ambiguous_sessions_exit_nonzero_with_loud_error(self):
        rc, out, err = self._run_main_with(
            self._sessions(),
            ["--interval", "1", "--max-duration", "1", "--cwd", "/mnt/kit", "--title-prefix", "gate-launch-scripts —"],
        )
        self.assertEqual(rc, 2)
        self.assertIn("--id or --nn", err)
        self.assertEqual(out, "")

    def test_id_flag_disambiguates_through_the_cli(self):
        rc, out, err = self._run_main_with(
            self._sessions(),
            [
                "--interval", "1", "--max-duration", "1",
                "--cwd", "/mnt/kit", "--title-prefix", "gate-launch-scripts —",
                "--id", "bbbbbbbb",
            ],
        )
        self.assertEqual(rc, 0)
        self.assertIn("working", out)


class RunWatchStateRecordingTests(unittest.TestCase):
    """Finding 2 (tooling-gaps-fix): `run_watch` persists the observed
    transition into `state.toml` at the point it exits reporting
    `state_changed`, when `state_path`/`nn` are both supplied — the same
    `status_claude.record_observed_transition` used by `status-claude`.
    Uses a scratch, temp-dir `state.toml` only; never real
    `.agent-state/` content, and never a real clock/sleep."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_path = Path(self.tmpdir.name) / "state.toml"

    def test_records_on_state_changed_exit(self):
        _write_scratch_state(self.state_path, assignment_state="launched")
        queue = _Queue([[_session(state="working")], [_session(state="working")], [_session(state="done")]])
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            nn=1, state_path=str(self.state_path),
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_STATE_CHANGED)
        self.assertEqual(outcome.classification, "finished")

        doc = st.read_state(self.state_path)
        a = doc.get_assignment(1)
        self.assertEqual(a.state, "finished")
        self.assertEqual(a.events[-1].by, "status")
        self.assertEqual(a.native.last_seen, "finished")

    def test_does_not_record_on_waiting_approval_exit(self):
        """Finding 2's recording is scoped to the `state_changed` exit
        only (explicit in the handoff) — not the `waiting_approval` exit,
        which always fires immediately regardless of whether the
        classification is actually new."""

        _write_scratch_state(self.state_path, assignment_state="working")
        queue = _Queue([[_session(state="working", status="waiting", waitingFor="permission prompt")]])
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            nn=1, state_path=str(self.state_path),
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_WAITING_APPROVAL)
        # No write attempted: still exactly where the fixture put it.
        self.assertEqual(st.read_state(self.state_path).get_assignment(1).state, "working")

    def test_no_recording_when_state_path_not_supplied(self):
        _write_scratch_state(self.state_path, assignment_state="launched")
        before = self.state_path.read_text(encoding="utf-8")
        queue = _Queue([[_session(state="working")], [_session(state="done")]])
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_STATE_CHANGED)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_no_recording_for_the_transient_unknown_guard_case(self):
        """Findings 2 and 3 compose correctly: a transient `unknown` never
        exits (Finding 3), so it never reaches the recording point either
        (Finding 2) — only the eventual real transition is persisted."""

        _write_scratch_state(self.state_path, assignment_state="launched")
        unknown_session = {"name": "demo-task — node-backend — 01 — implementação", "cwd": "/mnt/kit"}
        queue = _Queue([[_session(state="working")], [unknown_session], [_session(state="done")]])
        outcome = watch_claude.run_watch(
            queue, interval=5, max_duration=1000, title_prefix="demo-task —",
            nn=1, state_path=str(self.state_path),
            sleep=lambda s: None, clock=_FakeClock(step=1),
        )
        self.assertEqual(outcome.reason, watch_claude.REASON_STATE_CHANGED)
        self.assertEqual(outcome.classification, "finished")
        self.assertEqual(st.read_state(self.state_path).get_assignment(1).state, "finished")


class MainCliStateArgumentValidationTests(unittest.TestCase):
    """`--state`/`--nn` required together at the CLI layer (Finding 2);
    the actual persistence integration is covered above at the `run_watch`
    level with a fully deterministic fake clock."""

    def _run_main_with(self, sessions, argv):
        import scripts.common as common

        original = common.list_manager_sessions
        common.list_manager_sessions = lambda **kwargs: sessions
        try:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = watch_claude.main(argv)
            return rc, out.getvalue(), err.getvalue()
        finally:
            common.list_manager_sessions = original

    def test_state_without_nn_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.toml")
            rc, out, err = self._run_main_with(
                [],
                ["--interval", "1", "--max-duration", "1", "--cwd", "/mnt/kit", "--state", state_path],
            )
        self.assertEqual(rc, 2)
        self.assertIn("--state requires --nn", err)

    def test_nn_without_state_is_allowed_as_a_pure_filter(self):
        """RISK 2 (tooling-gaps-fix): --nn alone must keep working as a pure
        disambiguation filter, with no persistence attempted — a capability
        already reviewed and endorsed in a prior task (gate-launch-scripts).
        No fake clock is injectable through main(); this incurs one real,
        short (~1s) sleep, matching the pre-existing accepted pattern for a
        real-CLI-level watch-claude test (see RISK 3 of this same task's own
        receipt) rather than skipping coverage of this argv path."""
        session = {"id": "sess1", "cwd": "/mnt/kit", "name": "demo-task — node-backend — 01 — implementação", "state": "done"}
        rc, out, err = self._run_main_with(
            [session], ["--interval", "1", "--max-duration", "1", "--cwd", "/mnt/kit", "--nn", "1"]
        )
        self.assertEqual(rc, 0)
        self.assertIn("classification='finished'", out)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
