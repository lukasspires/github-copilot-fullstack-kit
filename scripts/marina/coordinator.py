"""scripts/marina/coordinator.py — the registered coordinator session (Marina's main session).

The writer gate refuses any `working` native session whose `cwd` is in the
new node's targets and whose name is not an active node's title. When the
kit is its own target, that includes Marina's main session. The manager
item (`claude agents --json --all`) has no agent field, so Marina's MCP
server records which session is hers, and the gate ignores exactly that
one (same `sessionId` and same `pid`) in that check only.

`register` writes `<kit_root>/.agent-state/<project>/coordinator.toml` with
exactly `session_id`, `pid` and `at`, and only when:

- `CLAUDE_CODE_AGENT` is `marina`;
- `CLAUDE_CODE_SESSION_ID` is a UUID;
- the project slug matches `^[a-z0-9-]+$` and `.agent-state/<project>/` exists.

`pid` is the MCP server's parent process, the session itself. No other
environment variable is ever read into the file. The write is atomic (a
sibling temporary file and `os.replace`) and happens only when the
`session_id` or `pid` changes. `load` never raises: a missing, unreadable
or malformed file is `None`.
"""

from __future__ import annotations

import dataclasses
import datetime
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Mapping

FILE_NAME = "coordinator.toml"
COORDINATOR_AGENT = "marina"
_SESSION_ID_RE = re.compile(r"^[0-9a-f-]{36}$")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_KEYS = frozenset({"session_id", "pid", "at"})


@dataclasses.dataclass(frozen=True)
class Coordinator:
    session_id: str
    pid: int
    at: datetime.datetime


def path_for(kit_root: str | Path, project: str) -> Path:
    return Path(kit_root) / ".agent-state" / project / FILE_NAME


def _valid_pid(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def load(kit_root: str | Path, project: str) -> Coordinator | None:
    """The registered coordinator of `project`, or None (never raises)."""

    if not isinstance(project, str) or not _SLUG_RE.fullmatch(project):
        return None
    try:
        with path_for(kit_root, project).open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, ValueError):  # tomllib.TOMLDecodeError and UnicodeDecodeError are ValueErrors
        return None
    if set(data) != _KEYS:
        return None
    session_id, pid, at = data["session_id"], data["pid"], data["at"]
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return None
    if not _valid_pid(pid) or not isinstance(at, datetime.datetime):
        return None
    return Coordinator(session_id=session_id, pid=pid, at=at)


def _render(session_id: str, pid: int, at: datetime.datetime) -> str:
    return f'session_id = "{session_id}"\npid = {pid}\nat = {at.isoformat()}\n'


def register(
    kit_root: str | Path,
    project: str,
    env: Mapping[str, str] = os.environ,
    ppid: int | None = None,
    now: datetime.datetime | None = None,
) -> bool:
    """Record the calling session as the project's coordinator; True when the file was written.

    `ppid` defaults to `os.getppid()`: the MCP server's parent, the session process.
    """

    if env.get("CLAUDE_CODE_AGENT") != COORDINATOR_AGENT:
        return False
    session_id = env.get("CLAUDE_CODE_SESSION_ID")
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return False
    if not isinstance(project, str) or not _SLUG_RE.fullmatch(project):
        return False
    project_dir = Path(kit_root) / ".agent-state" / project
    if not project_dir.is_dir():
        return False
    pid = os.getppid() if ppid is None else ppid
    if not _valid_pid(pid):
        return False
    current = load(kit_root, project)
    if current is not None and (current.session_id, current.pid) == (session_id, pid):
        return False
    at = now if now is not None else datetime.datetime.now()
    if at.tzinfo is None:
        at = at.astimezone()
    at = at.replace(microsecond=0)
    fd, tmp = tempfile.mkstemp(prefix=f".{FILE_NAME}.", dir=project_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_render(session_id, pid, at))
        os.replace(tmp, path_for(kit_root, project))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True
