"""Tests for scripts/marina/usage_limit.py — usage limit detection in a session transcript.

Every transcript is synthetic: the files under tests/fixtures/transcripts/
or entries built here, copied into a temporary `projects_root/<slug>/` as
`<sessionId>.jsonl`. No real transcript is read.
"""

from __future__ import annotations

import datetime
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.marina import usage_limit as ul

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"
SID = "0123abcd-0123-4567-89ab-0123456789ab"
UTC = datetime.timezone.utc
BRT = datetime.timezone(datetime.timedelta(hours=-3))
NN09_EPOCH = 1794523800  # 2026-11-12T22:50Z = 19:50 -03
NN09_RESETS = datetime.datetime(2026, 11, 12, 22, 50, tzinfo=UTC)


def limit_entry(text: str, *, timestamp: str = "2026-11-12T19:12:00.000Z", info: object = None,
                quota: object = None, api_error: str | None = "usage_limit_reached") -> dict:
    entry: dict = {"type": "assistant", "timestamp": timestamp, "isApiErrorMessage": True, "error": "rate_limit",
                   "message": {"role": "assistant", "model": "<synthetic>",
                               "content": [{"type": "text", "text": text}]}}
    if api_error is not None:
        entry["apiError"] = api_error
    if info is not None:
        entry["apiErrorParams"] = {"rate_limit_info": {"resetsAt": info}}
    if quota is not None:
        entry["quotaLimits"] = {"resetsAt": quota}
    return entry


class Projects:
    def __init__(self, tmp: str):
        self.root = Path(tmp) / "projects"
        (self.root / "-home-user-kit").mkdir(parents=True)

    def path(self, sid: str = SID) -> Path:
        return self.root / "-home-user-kit" / f"{sid}.jsonl"

    def fixture(self, name: str, sid: str = SID) -> None:
        shutil.copy(FIXTURES / name, self.path(sid))

    def entries(self, *entries: dict, sid: str = SID) -> None:
        tail = [{"type": "system", "subtype": "turn_duration"}, {"type": "cost-state"}]
        self.path(sid).write_text("".join(json.dumps(e) + "\n" for e in (*entries, *tail)), encoding="utf-8")

    def detect(self, sid: str = SID, local_tz: datetime.tzinfo | None = BRT) -> ul.UsageLimit | None:
        return ul.detect(sid, self.root, local_tz=local_tz)


class DetectFixtureTests(unittest.TestCase):
    def test_limit_followed_by_system_and_cost_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.fixture("limit-then-system.jsonl")
            limit = p.detect()
            self.assertIsNotNone(limit)
            self.assertEqual(limit.reset_text, "7:50pm (America/Sao_Paulo)")
            self.assertEqual(limit.resets_at, NN09_RESETS)
            self.assertEqual(limit.at, datetime.datetime(2026, 11, 12, 19, 12, tzinfo=UTC))
            self.assertEqual(ul.stop_reason(9, limit), "usage_limit: nn=09 resets 7:50pm (America/Sao_Paulo)")

    def test_other_api_error_is_not_a_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.fixture("other-api-error.jsonl")
            self.assertIsNone(p.detect())

    def test_rate_limit_without_usage_limit_reached_nor_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.fixture("rate-limit-no-resets.jsonl")
            self.assertIsNone(p.detect())

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(Projects(tmp).detect())
            self.assertIsNone(ul.detect(SID, Path(tmp) / "no-such-root"))

    def test_malformed_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.fixture("malformed-line.jsonl")
            limit = p.detect()
            self.assertIsNotNone(limit)
            self.assertEqual(limit.resets_at, NN09_RESETS)

    def test_limit_followed_by_a_normal_message_is_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.fixture("limit-then-normal.jsonl")
            self.assertIsNone(p.detect())

    def test_invalid_session_id_is_never_globbed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.fixture("limit-then-system.jsonl")
            with mock.patch.object(ul, "transcript_tail", side_effect=AssertionError("globbed")):
                for sid in ("*", "", "0123abcd-0123-4567-89ab-0123456789a*", "../x", SID.upper(), None, 42):
                    with self.subTest(sid=sid):
                        self.assertIsNone(ul.detect(sid, p.root))


class DetectShapeTests(unittest.TestCase):
    def test_rate_limit_fallback_with_resets_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.entries(limit_entry("You've hit your limit · resets 7:50pm (America/Sao_Paulo)", api_error=None))
            self.assertEqual(p.detect().resets_at, NN09_RESETS)

    def test_requires_is_api_error_message_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            entry = limit_entry("resets 7:50pm (America/Sao_Paulo)", info=NN09_EPOCH)
            entry["isApiErrorMessage"] = "true"
            p.entries(entry)
            self.assertIsNone(p.detect())

    def test_wrong_types_degrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            entry = limit_entry("x", info=NN09_EPOCH)
            entry["message"] = "not a dict"
            entry["apiErrorParams"] = ["not", "a", "dict"]
            entry["timestamp"] = 12
            p.entries(entry)
            limit = p.detect()
            self.assertIsNotNone(limit)
            self.assertEqual((limit.reset_text, limit.resets_at, limit.at), ("?", None, None))

    def test_never_raises(self):
        with mock.patch.object(ul, "transcript_tail", side_effect=RuntimeError("boom")):
            self.assertIsNone(ul.detect(SID, Path("/nonexistent")))

    def test_text_is_one_truncated_printable_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            long = "resets 7:50pm (America/Sao_Paulo) " + "x" * 200 + "\nsecond line SECRET"
            p.entries(limit_entry(long, info=NN09_EPOCH))
            limit = p.detect()
            self.assertLessEqual(len(limit.reset_text), ul.TEXT_MAX)
            self.assertNotIn("SECRET", limit.reset_text)
            self.assertNotIn("\n", ul.note_for(limit))


class ResetTimeTests(unittest.TestCase):
    def _resets(self, text: str, **kw) -> datetime.datetime | None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Projects(tmp)
            p.entries(limit_entry(text, **{k: v for k, v in kw.items() if k != "local_tz"}))
            limit = p.detect(local_tz=kw.get("local_tz", BRT))
            self.assertIsNotNone(limit)
            return limit.resets_at

    def test_epoch_from_rate_limit_info(self):
        self.assertEqual(self._resets("resets 7:50pm (America/Sao_Paulo)", info=NN09_EPOCH), NN09_RESETS)

    def test_epoch_from_quota_limits(self):
        self.assertEqual(self._resets("resets 7:50pm (America/Sao_Paulo)", quota=NN09_EPOCH), NN09_RESETS)

    def test_divergent_epochs_take_the_larger(self):
        later = NN09_EPOCH + 3600
        self.assertEqual(self._resets("resets 7:50pm", info=NN09_EPOCH, quota=later),
                         NN09_RESETS + datetime.timedelta(hours=1))
        self.assertEqual(self._resets("resets 7:50pm", info=later, quota=NN09_EPOCH),
                         NN09_RESETS + datetime.timedelta(hours=1))

    def test_bool_epoch_is_ignored(self):
        self.assertEqual(self._resets("resets 7:50pm (America/Sao_Paulo)", info=True), NN09_RESETS)

    def test_text_only_with_zone(self):
        self.assertEqual(self._resets("You've hit your 5-hour limit · resets 7:50pm (America/Sao_Paulo)"),
                         NN09_RESETS)

    def test_text_only_without_zone_uses_injected_local_zone(self):
        self.assertEqual(self._resets("resets 7:50pm", local_tz=BRT), NN09_RESETS)
        self.assertEqual(self._resets("resets 7:50pm", local_tz=UTC),
                         datetime.datetime(2026, 11, 12, 19, 50, tzinfo=UTC))

    def test_text_rolls_to_the_next_day(self):
        # 2026-11-13T02:30Z is 23:30 on the 12th in São Paulo; 1am is the next local day.
        self.assertEqual(self._resets("resets 1am (America/Sao_Paulo)", timestamp="2026-11-13T02:30:00Z"),
                         datetime.datetime(2026, 11, 13, 4, 0, tzinfo=UTC))
        # The same wall time as the message is not "after" it.
        self.assertEqual(self._resets("resets 4:12pm (America/Sao_Paulo)"),
                         datetime.datetime(2026, 11, 13, 19, 12, tzinfo=UTC))

    def test_text_with_date_across_the_new_year(self):
        self.assertEqual(self._resets("resets Jan 2 at 9am (UTC)", timestamp="2026-12-30T12:00:00Z"),
                         datetime.datetime(2027, 1, 2, 9, 0, tzinfo=UTC))
        self.assertEqual(self._resets("resets Nov 14, 2:40pm (America/Sao_Paulo)"),
                         datetime.datetime(2026, 11, 14, 17, 40, tzinfo=UTC))

    def test_unknown_zone_is_unparsed_not_local(self):
        limit_at = self._resets("resets 7:50pm (Mars/Olympus_Mons)")
        self.assertIsNone(limit_at)

    def test_epoch_outside_the_window_is_unparsed(self):
        message = datetime.datetime(2026, 11, 12, 19, 12, tzinfo=UTC)
        too_late = int((message + datetime.timedelta(days=8, seconds=1)).timestamp())
        too_early = int((message - datetime.timedelta(minutes=2)).timestamp())
        edge = int((message + datetime.timedelta(days=8)).timestamp())
        self.assertIsNone(self._resets("resets 7:50pm (America/Sao_Paulo)", info=too_late))
        self.assertIsNone(self._resets("resets 7:50pm (America/Sao_Paulo)", info=too_early))
        self.assertIsNotNone(self._resets("resets 7:50pm (America/Sao_Paulo)", info=edge))

    def test_text_date_outside_the_window_is_unparsed(self):
        self.assertIsNone(self._resets("resets Dec 25 at 9am (UTC)"))

    def test_unparsed_reason(self):
        limit = ul.UsageLimit("7:50pm (Mars/Olympus_Mons)", None)
        self.assertEqual(ul.stop_reason(9, limit), "usage_limit: nn=09 resets 7:50pm (Mars/Olympus_Mons) (unparsed)")


class NoteTests(unittest.TestCase):
    def test_round_trip(self):
        limit = ul.UsageLimit("7:50pm (America/Sao_Paulo)", NN09_RESETS)
        note = ul.note_for(limit)
        self.assertEqual(note, 'usage_limit resets_at=2026-11-12T22:50:00+00:00 text="7:50pm (America/Sao_Paulo)"')
        back = ul.from_note(note)
        self.assertEqual((back.reset_text, back.resets_at), (limit.reset_text, limit.resets_at))

    def test_round_trip_unparsed(self):
        note = ul.note_for(ul.UsageLimit('a "quoted" text', None))
        back = ul.from_note(note)
        self.assertEqual((back.reset_text, back.resets_at), ("a 'quoted' text", None))

    def test_after_a_lint_error(self):
        limit = ul.UsageLimit("7:50pm (America/Sao_Paulo)", NN09_RESETS)
        note = ul.with_note("missing status", limit)
        self.assertTrue(note.startswith("missing status; usage_limit resets_at="))
        self.assertEqual(ul.from_note(note).resets_at, NN09_RESETS)
        self.assertEqual(ul.with_note("missing status", None), "missing status")
        self.assertEqual(ul.with_note("", None), "")

    def test_other_notes(self):
        for note in ("", "missing status", "stage 1", "usage_limit", None):
            with self.subTest(note=note):
                self.assertIsNone(ul.from_note(note))

    def test_margin_constant(self):
        self.assertEqual(ul.USAGE_LIMIT_MARGIN, 300)


if __name__ == "__main__":
    unittest.main()
