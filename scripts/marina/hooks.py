"""scripts/marina/hooks.py — hook decisions for background specialist sessions.

Each function takes the hook's JSON input and returns `(exit_code, message)`
in Claude Code's hook convention: 0 releases, 2 blocks (the message reaches
the model), 1 is a non-blocking error. Never writes anything.
"""

from __future__ import annotations

from pathlib import Path

from scripts import receipt_lint


def require_receipt(hook_input: dict, *, receipt: Path, handoff: Path) -> tuple[int, str]:
    """Stop hook: keep the session open until its receipt passes receipt-lint."""

    if hook_input.get("stop_hook_active"):
        # Second Stop in the same turn: releasing avoids a block loop (F1, H4).
        return 0, ""
    if not receipt.exists():
        return 2, (
            f"receipt missing: write {receipt} using the canonical structure in docs/agent-workflow.md "
            "before stopping; record any denied command there and use status needs_input or blocked "
            "if acceptance depends on it"
        )
    try:
        handoff.read_text(encoding="utf-8")
    except OSError as exc:
        return 1, f"cannot read handoff {handoff}: {exc}"
    errors, _ = receipt_lint.lint_file(receipt, handoff=handoff)
    if errors:
        return 2, f"receipt {receipt} fails receipt-lint: " + "; ".join(errors[:5])
    return 0, ""
