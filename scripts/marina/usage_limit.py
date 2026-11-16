#!/usr/bin/env python3
"""scripts/marina/usage_limit.py — detect an account usage limit in a session transcript.

When the account reaches its usage limit mid-node, the session ends without
a receipt and `marina run` sees only `receipt_missing`/`receipt_invalid`.
`detect` reads the end of the session transcript
(`<projects_root>/*/<sessionId>.jsonl`) and returns a `UsageLimit` when the
last `type == "assistant"` entry (not the last line: `system`, `last-prompt`
and `cost-state` entries follow it) is the limit's API error message.

The transcript format is NOT documented. The fields read here
(`isApiErrorMessage`, `apiError`, `error`, `apiErrorParams.rate_limit_info.resetsAt`,
`quotaLimits.resetsAt`, `timestamp`, `message.content`) were observed in Claude
CLI versions 2.1.322 and 2.1.323. Minimum tested Claude CLI version: 2.1.322.
Anything unexpected degrades to None, and `detect` never raises.

Decisions 1 and 2 of the limite-uso architect analysis (2026-11-16):

- the structured epoch wins (`rate_limit_info.resetsAt`, else
  `quotaLimits.resetsAt`; when both differ, the larger); the `resets …`
  text is only a fallback, parsed with `zoneinfo` and never silently
  falling back to the local zone when a named zone is unknown;
- the reset time must fall in `(message − 1 min, message + 8 days]`,
  otherwise it is unparsed (`resets_at = None`);
- the observation is persisted in the event note as
  `usage_limit resets_at=<iso|?> text="<≤80>"` (`note_for`) and rebuilt
  from it (`from_note`), so `state.toml` keeps its format.

Only the truncated `resets …` text ever leaves this module, never a
transcript line.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import re
import zoneinfo
from pathlib import Path

USAGE_LIMIT_MARGIN = 300  # seconds after resets_at before reopening (stage 2)
TRANSCRIPT_TAIL = 256 * 1024
TEXT_MAX = 80
WINDOW_BEFORE = datetime.timedelta(minutes=1)
WINDOW_AFTER = datetime.timedelta(days=8)

_SESSION_ID_RE = re.compile(r"^[0-9a-f-]{36}$")
_RESETS_RE = re.compile(
    r"resets (?:(?P<mon>[A-Z][a-z]{2}) (?P<day>\d{1,2}),? (?:at )?)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*"
    r"(?P<ap>am|pm)(?: \((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*|UTC)\))?"
)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_NOTE_RE = re.compile(r'usage_limit resets_at=(?P<at>\S+) text="(?P<text>[^"]*)"\s*$')


@dataclasses.dataclass(frozen=True)
class UsageLimit:
    reset_text: str
    resets_at: datetime.datetime | None
    at: datetime.datetime | None = None


def default_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


# --------------------------------------------------------------------------
# Transcript
# --------------------------------------------------------------------------


def transcript_tail(session_id: str, projects_root: Path) -> str | None:
    """The last `TRANSCRIPT_TAIL` bytes of `<projects_root>/*/<session_id>.jsonl`; None if unreadable.

    Shared with `progress.last_activity`; it does not validate `session_id`
    (callers that build a glob from untrusted input validate it first).
    """

    if not session_id:
        return None
    try:
        matches = sorted(Path(projects_root).glob(f"*/{session_id}.jsonl"))
        if not matches:
            return None
        with matches[0].open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(size - TRANSCRIPT_TAIL, 0))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def _parse_timestamp(text: object) -> datetime.datetime | None:
    if not isinstance(text, str):
        return None
    try:
        at = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def _last_assistant(tail: str) -> dict | None:
    for line in reversed(tail.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("type") == "assistant":
            return entry
    return None


def _message_text(entry: dict) -> str:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c["text"] for c in content
                         if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
    return ""


def _clean(text: str) -> str:
    """One printable line, no double quotes, at most `TEXT_MAX` characters."""

    text = text.splitlines()[0] if text else ""
    text = "".join(ch for ch in text if ch.isprintable()).replace('"', "'").strip()
    return text[:TEXT_MAX]


# --------------------------------------------------------------------------
# Reset time
# --------------------------------------------------------------------------


def _in_window(resets_at: datetime.datetime, at: datetime.datetime) -> bool:
    return at - WINDOW_BEFORE < resets_at <= at + WINDOW_AFTER


def _epoch(entry: dict) -> int | None:
    values = []
    params = entry.get("apiErrorParams")
    info = params.get("rate_limit_info") if isinstance(params, dict) else None
    quota = entry.get("quotaLimits")
    for holder in (info, quota):
        value = holder.get("resetsAt") if isinstance(holder, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            values.append(value)
    return max(values) if values else None


def resets_from_text(text: str, at: datetime.datetime,
                     local_tz: datetime.tzinfo | None) -> datetime.datetime | None:
    """The reset time a `resets …` text names, relative to the message time `at`; None if unparsed."""

    match = _RESETS_RE.search(text)
    if match is None:
        return None
    if match["tz"]:
        try:
            zone: datetime.tzinfo = zoneinfo.ZoneInfo(match["tz"])
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            return None
    elif local_tz is not None:
        zone = local_tz
    else:
        return None
    hour, minute = int(match["h"]), int(match["m"] or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if match["ap"] == "pm" else 0)
    local = at.astimezone(zone)
    if match["mon"]:
        if match["mon"] not in _MONTHS:
            return None
        month, day = _MONTHS.index(match["mon"]) + 1, int(match["day"])
        try:
            candidate = datetime.datetime(local.year, month, day, hour, minute, tzinfo=zone)
            if candidate < local:
                candidate = candidate.replace(year=local.year + 1)
        except ValueError:
            return None
    else:
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += datetime.timedelta(days=1)
    return candidate


def _resets_at(entry: dict, text: str, at: datetime.datetime | None,
               local_tz: datetime.tzinfo | None) -> datetime.datetime | None:
    if at is None:
        return None
    epoch = _epoch(entry)
    if epoch is not None:
        resets_at = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    else:
        resets_at = resets_from_text(text, at, local_tz)
    if resets_at is None or not _in_window(resets_at, at):
        return None
    return resets_at


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def _detect(session_id: str, projects_root: Path, local_tz: datetime.tzinfo | None) -> UsageLimit | None:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return None
    tail = transcript_tail(session_id, projects_root)
    if tail is None:
        return None
    entry = _last_assistant(tail)
    if entry is None or entry.get("isApiErrorMessage") is not True:
        return None
    text = _message_text(entry)
    index = text.find("resets ")
    if entry.get("apiError") != "usage_limit_reached" and not (entry.get("error") == "rate_limit" and index >= 0):
        return None
    after = text[index:] if index >= 0 else ""
    at = _parse_timestamp(entry.get("timestamp"))
    resets_at = _resets_at(entry, after.splitlines()[0] if after else "", at, local_tz)
    reset_text = _clean(after[len("resets "):]) if after else ""
    if not reset_text:
        reset_text = resets_at.isoformat() if resets_at is not None else "?"
    return UsageLimit(reset_text=reset_text, resets_at=resets_at, at=at)


def detect(session_id: str, projects_root: Path, *, local_tz: datetime.tzinfo | None = None) -> UsageLimit | None:
    """The usage limit that ended session `session_id`, or None; never raises.

    `local_tz` is the zone of a `resets …` text without one (the run passes
    the tzinfo of its own clock); None means the system's local zone.
    """

    try:
        if local_tz is None:
            local_tz = datetime.datetime.now().astimezone().tzinfo
        return _detect(session_id, Path(projects_root), local_tz)
    except Exception:  # noqa: BLE001 — undocumented format: any surprise degrades to None
        return None


# --------------------------------------------------------------------------
# Persistence in the event note, and wording
# --------------------------------------------------------------------------


def note_for(limit: UsageLimit) -> str:
    """`usage_limit resets_at=<iso|?> text="<≤80>"` for an event note."""

    at = limit.resets_at.astimezone(datetime.timezone.utc).isoformat() if limit.resets_at is not None else "?"
    return f'usage_limit resets_at={at} text="{_clean(limit.reset_text)}"'


def with_note(base: str, limit: UsageLimit | None) -> str:
    """`base` with the limit's note appended (after a lint error, for `receipt_invalid`)."""

    if limit is None:
        return base
    return f"{base}; {note_for(limit)}" if base else note_for(limit)


def from_note(note: str) -> UsageLimit | None:
    """The `UsageLimit` a note written by `note_for`/`with_note` records; None otherwise."""

    if not isinstance(note, str):
        return None
    match = _NOTE_RE.search(note)
    if match is None:
        return None
    resets_at = None
    if match["at"] != "?":
        try:
            resets_at = datetime.datetime.fromisoformat(match["at"])
        except ValueError:
            resets_at = None
        if resets_at is not None and resets_at.tzinfo is None:
            resets_at = None
    return UsageLimit(reset_text=match["text"], resets_at=resets_at)


def describe(limit: UsageLimit) -> str:
    """`resets <text>`, with ` (unparsed)` when no reset time was interpreted."""

    return f"resets {limit.reset_text}" + ("" if limit.resets_at is not None else " (unparsed)")


def stop_reason(nn: int, limit: UsageLimit) -> str:
    """`usage_limit: nn=NN resets <text>` — the run's stop reason."""

    return f"usage_limit: nn={nn:02d} {describe(limit)}"
