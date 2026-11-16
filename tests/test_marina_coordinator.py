"""Tests for scripts/marina/coordinator.py — the registered coordinator session.

Every test uses a temporary kit root; nothing touches the real `.agent-state/`.
"""

from __future__ import annotations

import datetime
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts.marina import coordinator

SID = "0123abcd-0123-4567-89ab-0123456789ab"
TOKEN = "fake-messaging-token-should-never-be-written"
AT = datetime.datetime(2026, 11, 16, 10, 0, 0, tzinfo=datetime.timezone.utc)
ENV = {"CLAUDE_CODE_AGENT": "marina", "CLAUDE_CODE_SESSION_ID": SID, "CLAUDE_CODE_MESSAGING_TOKEN": TOKEN,
       "HOME": "/home/someone"}


class _Kit:
    def __init__(self, tmp: str, *, project: str = "demo", create: bool = True):
        self.root = Path(tmp) / "kit"
        self.project = project
        self.project_dir = self.root / ".agent-state" / project
        if create:
            self.project_dir.mkdir(parents=True)
        self.file = self.project_dir / coordinator.FILE_NAME

    def register(self, env=ENV, ppid: int = 4321, now=AT) -> bool:
        return coordinator.register(self.root, self.project, env=env, ppid=ppid, now=now)


class RegisterTests(unittest.TestCase):
    def test_marina_with_uuid_writes_session_pid_and_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp)
            self.assertTrue(kit.register())
            loaded = coordinator.load(kit.root, kit.project)
            self.assertEqual((loaded.session_id, loaded.pid, loaded.at), (SID, 4321, AT))

    def test_file_has_exactly_three_keys_and_no_other_environment_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp)
            kit.register()
            text = kit.file.read_text(encoding="utf-8")
            self.assertEqual(set(tomllib.loads(text)), {"session_id", "pid", "at"})
            self.assertNotIn(TOKEN, text)
            self.assertNotIn("/home/someone", text)
            self.assertNotIn("MESSAGING", text)
            self.assertEqual([p.name for p in kit.project_dir.iterdir()], [coordinator.FILE_NAME])

    def test_refusals_write_nothing(self):
        cases = {
            "other agent": {**ENV, "CLAUDE_CODE_AGENT": "kit-tooling"},
            "no agent": {k: v for k, v in ENV.items() if k != "CLAUDE_CODE_AGENT"},
            "no session id": {k: v for k, v in ENV.items() if k != "CLAUDE_CODE_SESSION_ID"},
            "invalid id": {**ENV, "CLAUDE_CODE_SESSION_ID": "not-a-uuid"},
            "uppercase id": {**ENV, "CLAUDE_CODE_SESSION_ID": SID.upper()},
        }
        for label, env in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                kit = _Kit(tmp)
                self.assertFalse(kit.register(env=env))
                self.assertFalse(kit.file.exists())

    def test_project_without_directory_or_bad_slug_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp, create=False)
            self.assertFalse(kit.register())
            self.assertFalse(kit.root.exists())
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp, project="Bad/../slug", create=False)
            (kit.root / ".agent-state").mkdir(parents=True)
            self.assertFalse(kit.register())
            self.assertEqual(list((kit.root / ".agent-state").iterdir()), [])

    def test_second_call_with_same_content_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp)
            self.assertTrue(kit.register())
            os.utime(kit.file, ns=(1, 1))
            before = kit.file.read_bytes()
            self.assertFalse(kit.register(now=AT + datetime.timedelta(hours=1)))
            self.assertEqual(kit.file.read_bytes(), before)
            self.assertEqual(kit.file.stat().st_mtime_ns, 1)

    def test_new_pid_or_session_rewrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp)
            kit.register()
            self.assertTrue(kit.register(ppid=999))
            self.assertEqual(coordinator.load(kit.root, kit.project).pid, 999)
            other = "fedcba98-0123-4567-89ab-0123456789ab"
            self.assertTrue(kit.register(env={**ENV, "CLAUDE_CODE_SESSION_ID": other}, ppid=999))
            self.assertEqual(coordinator.load(kit.root, kit.project).session_id, other)


class LoadTests(unittest.TestCase):
    def test_missing_file_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp)
            self.assertIsNone(coordinator.load(kit.root, kit.project))
            self.assertIsNone(coordinator.load(kit.root, "Bad slug"))

    def test_malformed_files_are_none(self):
        bodies = {
            "not toml": "session_id = \n",
            "binary": b"\xff\xfe\x00",
            "missing pid": f'session_id = "{SID}"\nat = 2026-11-16T10:00:00+00:00\n',
            "extra key": f'session_id = "{SID}"\npid = 1\nat = 2026-11-16T10:00:00+00:00\ntoken = "x"\n',
            "bad id": 'session_id = "x"\npid = 1\nat = 2026-11-16T10:00:00+00:00\n',
            "string pid": f'session_id = "{SID}"\npid = "1"\nat = 2026-11-16T10:00:00+00:00\n',
            "bool pid": f'session_id = "{SID}"\npid = true\nat = 2026-11-16T10:00:00+00:00\n',
            "string at": f'session_id = "{SID}"\npid = 1\nat = "yesterday"\n',
        }
        for label, body in bodies.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                kit = _Kit(tmp)
                if isinstance(body, bytes):
                    kit.file.write_bytes(body)
                else:
                    kit.file.write_text(body, encoding="utf-8")
                self.assertIsNone(coordinator.load(kit.root, kit.project))

    def test_unreadable_path_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _Kit(tmp)
            kit.file.mkdir()
            self.assertIsNone(coordinator.load(kit.root, kit.project))


if __name__ == "__main__":
    unittest.main()
