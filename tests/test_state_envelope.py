"""Tests for the optional `[envelope]` table in `state.toml` (F3 Task 1).

The state layer keeps `[envelope]` as an opaque table: it must survive
every read/write cycle (otherwise any `state set` would silently drop an
approved envelope), and the minimal TOML writer must quote keys that are
not bare (`branches` keys are absolute paths). Inline literals only.
"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts import state
from scripts.state import StateError, toml_write

SPEC_ENVELOPE_TOML = """\
schema = 1

[task]
project = "demo"
slug = "t1"
title = "Demo"
phase = "implementation"
kit_root = "/kit"
targets = ["/abs/api"]
journal = ".agent-state/demo/tasks/t1/checkpoint.md"
next_nn = 1
created_at = 2026-10-25T20:00:00-03:00
updated_at = 2026-10-25T20:00:00-03:00

[envelope]
targets            = ["/abs/api"]
branches           = { "/abs/api" = "feat/x" }
allowlist          = ["Bash(mvn test)"]
review             = "each_stage"
max_corrections    = 1
max_duration       = "8h"
judge_max_calls    = 4
on_pass_with_risks = "judge"

[[envelope.stages]]
role    = "java-backend"
handoff = "01-java-backend-handoff.md"

[[envelope.stages]]
role    = "java-backend"
handoff = "stage-2-handoff-template.md"

[envelope.approval]
at     = 2026-10-25T21:00:00-03:00
sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
"""

NO_ENVELOPE_TOML = SPEC_ENVELOPE_TOML.split("[envelope]")[0]


class EnvelopeRoundTripTests(unittest.TestCase):
    def test_envelope_table_round_trips(self):
        doc = state.parse_state_text(SPEC_ENVELOPE_TOML)
        written = tomllib.loads(state.dumps_state(doc))
        self.assertEqual(written["envelope"], tomllib.loads(SPEC_ENVELOPE_TOML)["envelope"])

    def test_state_without_envelope_has_none_and_writes_no_table(self):
        doc = state.parse_state_text(NO_ENVELOPE_TOML)
        self.assertIsNone(doc.envelope)
        self.assertNotIn("envelope", tomllib.loads(state.dumps_state(doc)))

    def test_envelope_survives_set_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.toml"
            original = state.parse_state_text(SPEC_ENVELOPE_TOML)
            state.write_state(path, original)
            doc = state.read_state(path)
            state.add_assignment(
                doc, role="java-backend", type_="implementação", edge="inicia", predecessor=0, targets=["/abs/api"]
            )
            state.write_state(path, doc)
            doc = state.read_state(path)
            state.set_state(doc, 1, "prepared")
            state.write_state(path, doc)
            self.assertEqual(state.read_state(path).envelope, original.envelope)

    def test_non_table_envelope_refused(self):
        with self.assertRaisesRegex(StateError, r"\[envelope\] must be a table"):
            state.parse_state_text(NO_ENVELOPE_TOML.replace("schema = 1\n", 'schema = 1\nenvelope = "x"\n'))


class KeyQuotingTests(unittest.TestCase):
    def test_non_bare_keys_are_quoted(self):
        doc = {"t": {"/abs/api": "x", "a.b": "y", "ok_key-1": "z"}}
        text = toml_write.dumps(doc)
        self.assertEqual(tomllib.loads(text), doc)
        self.assertIn('"/abs/api" = "x"', text)
        self.assertIn('ok_key-1 = "z"', text)

    def test_non_bare_table_headers_are_quoted(self):
        doc = {"outer": {"/abs/api": {"k": "v"}}}
        self.assertEqual(tomllib.loads(toml_write.dumps(doc)), doc)


if __name__ == "__main__":
    unittest.main()
