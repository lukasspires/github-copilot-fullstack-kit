#!/usr/bin/env python3
"""scripts/marina/__main__.py — `python3 scripts/marina/__main__.py hook require-receipt ...`.

Invoked by path from the Stop hook that `launch_claude` puts in each
background session's `--settings`, from whatever cwd the session has.

Minimum tested Claude CLI version: 2.1.306 — Stop hooks passed through
`--settings` fire in `--bg` sessions, exit 2 reopens the turn and the
re-entry carries `stop_hook_active` (docs/achados-f1-spike-hooks-e-juiza-2026-10.md).

Read-only: never writes anything; it only reads the receipt and handoff
named on its command line.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.marina import cli

if __name__ == "__main__":
    sys.exit(cli.main())
