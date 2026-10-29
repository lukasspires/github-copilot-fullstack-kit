"""scripts/marina/watch.py — `marina watch`, the terminal view of one task (F8).

Read only: every second it rebuilds `progress.build_view` from the task
files and redraws; the native manager is polled every `manager_interval`
seconds (a failure keeps the view going with "manager indisponível"), and
past tasks' events are reloaded every `HISTORY_INTERVAL` seconds. The only
write is the `s` key, which asks the run to stop exactly like `marina stop`.
`--once`, or no TTY, prints one snapshot and returns.

Minimum tested Claude CLI version: 2.1.311 (through `progress` and the
manager listing).
"""

from __future__ import annotations

import dataclasses
import datetime
import shutil
import time
from pathlib import Path
from typing import Callable, TextIO

from scripts import common
from scripts.marina import progress, runner
from scripts.state import StateDoc, StateError, read_state

HISTORY_INTERVAL = 60.0
REDRAW_SECONDS = 1.0


@dataclasses.dataclass
class WatchDeps:
    list_sessions: Callable[[], list[dict]]
    now: Callable[[], datetime.datetime]
    monotonic: Callable[[], float]
    pid_alive: Callable[[int], bool]
    projects_root: Path
    terminal_width: Callable[[], int]


def default_watch_deps() -> WatchDeps:
    return WatchDeps(
        list_sessions=common.list_manager_sessions,
        now=lambda: datetime.datetime.now().astimezone(),
        monotonic=time.monotonic,
        pid_alive=runner._pid_alive,
        projects_root=Path.home() / ".claude" / "projects",
        terminal_width=lambda: shutil.get_terminal_size((100, 40)).columns,
    )


def _history(kit_root: Path) -> list[StateDoc]:
    """Every task's state under kit_root, for durations; an unreadable one is skipped."""

    docs: list[StateDoc] = []
    for path in sorted((Path(kit_root) / ".agent-state").glob("*/tasks/*/state.toml")):
        try:
            docs.append(read_state(path))
        except (StateError, OSError, ValueError):
            continue
    return docs


def _sessions(deps: WatchDeps) -> list[dict] | None:
    try:
        return deps.list_sessions()
    except (common.ManagerUnavailable, common.ManagerSchemaError):
        return None


class _Source:
    """Caches the manager listing and the history between redraws."""

    def __init__(self, state_path: Path, kit_root: Path, deps: WatchDeps, manager_interval: float):
        self.state_path, self.kit_root, self.deps = state_path, kit_root, deps
        self.manager_interval = manager_interval
        self.sessions: list[dict] | None = None
        self.sessions_at = self.history_at = -float("inf")
        self.history: list[StateDoc] = []
        self.last_lines: list[str] = []

    def view(self) -> progress.View:
        t = self.deps.monotonic()
        if t - self.sessions_at >= self.manager_interval:
            self.sessions, self.sessions_at = _sessions(self.deps), t
        if t - self.history_at >= HISTORY_INTERVAL:
            self.history, self.history_at = _history(self.kit_root), t
        return progress.build_view(
            self.state_path, kit_root=self.kit_root, now=self.deps.now(), sessions=self.sessions,
            pid_alive=self.deps.pid_alive, projects_root=self.deps.projects_root, history_docs=self.history,
        )


    def lines(self, width: int) -> list[str]:
        """The rendered screen; while state.toml is unreadable (a writer
        mid-write, a malformed draft) the last good screen plus a warning."""

        try:
            self.last_lines = progress.render(self.view(), width)
        except (StateError, OSError, ValueError) as exc:
            if not self.last_lines:
                return [f"marina watch: não consegui ler o estado: {exc}"[:width]]
            return [*self.last_lines, f"aviso: estado ilegível agora, mostrando a última leitura ({exc})"[:width]]
        return self.last_lines


def _loop(screen, source: _Source) -> int:  # pragma: no cover - needs a real terminal
    import curses

    curses.curs_set(0)
    screen.timeout(int(REDRAW_SECONDS * 1000))
    notice = ""
    while True:
        height, width = screen.getmaxyx()
        lines = source.lines(max(width - 1, 20))
        if notice:
            lines.append(notice)
        screen.erase()
        for row, line in enumerate(lines[: max(height - 1, 1)]):
            try:
                screen.addstr(row, 0, line)
            except curses.error:
                pass
        screen.refresh()
        key = screen.getch()
        if key in (ord("q"), ord("Q"), 27):
            return 0
        if key in (ord("s"), ord("S")):
            requested = runner.request_stop(source.state_path)
            notice = "parada pedida; a run para na próxima iteração" if requested else "nenhuma run em andamento"


def run_watch(
    state_path: Path,
    *,
    kit_root: Path,
    once: bool,
    stdout: TextIO,
    isatty: Callable[[], bool],
    manager_interval: float,
    deps: WatchDeps,
) -> int:
    """Show the task; `once` (or no TTY) prints a single snapshot."""

    source = _Source(Path(state_path), Path(kit_root), deps, manager_interval)
    if once or not isatty():
        lines = source.lines(max(deps.terminal_width(), 40))
        print("\n".join(lines), file=stdout)
        return 0 if source.last_lines else 1
    import curses  # pragma: no cover - needs a real terminal

    try:  # pragma: no cover
        return curses.wrapper(_loop, source)
    except KeyboardInterrupt:  # pragma: no cover
        return 0
