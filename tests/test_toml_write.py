"""Unit tests for scripts.state.toml_write — the minimal TOML writer.

Deterministic, stdlib-only; no fixtures needed beyond inline literals.
"""

from __future__ import annotations

import datetime
import tomllib
import unittest

from scripts.state import toml_write


class ScalarFormattingTests(unittest.TestCase):
    def test_bool_true_false(self):
        self.assertEqual(toml_write._format_value(True), "true")
        self.assertEqual(toml_write._format_value(False), "false")

    def test_int(self):
        self.assertEqual(toml_write._format_value(0), "0")
        self.assertEqual(toml_write._format_value(42), "42")

    def test_string_escapes(self):
        self.assertEqual(toml_write._format_value("plain"), '"plain"')
        self.assertEqual(toml_write._format_value('has "quotes"'), '"has \\"quotes\\""')
        self.assertEqual(toml_write._format_value("back\\slash"), '"back\\\\slash"')
        self.assertEqual(toml_write._format_value("line\nbreak"), '"line\\nbreak"')
        self.assertEqual(toml_write._format_value("tab\ttab"), '"tab\\ttab"')

    def test_string_preserves_unicode(self):
        # Unicode text (accents, em dash) needs no escaping in a TOML basic string.
        value = "não resolvido — teste"
        self.assertEqual(toml_write._format_value(value), f'"{value}"')

    def test_datetime_rfc3339(self):
        dt = datetime.datetime(2026, 9, 11, 9, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        self.assertEqual(toml_write._format_value(dt), "2026-09-11T09:00:00-03:00")

    def test_array_of_strings(self):
        self.assertEqual(toml_write._format_value(["a", "b"]), '["a", "b"]')

    def test_empty_array(self):
        self.assertEqual(toml_write._format_value([]), "[]")

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            toml_write._format_value(object())


class DumpsStructureTests(unittest.TestCase):
    def test_scalar_then_subtable_then_array_of_tables(self):
        doc = {
            "schema": 1,
            "task": {"project": "demo", "next_nn": 2},
            "assignments": [
                {
                    "nn": 1,
                    "native": {"platform": "claude", "id": ""},
                    "events": [{"at": datetime.datetime(2026, 1, 1), "to": "reserved"}],
                }
            ],
        }
        text = toml_write.dumps(doc)
        self.assertTrue(text.startswith("schema = 1\n"))
        self.assertIn("[task]", text)
        self.assertIn("[[assignments]]", text)
        self.assertIn("[assignments.native]", text)
        self.assertIn("[[assignments.events]]", text)
        # Round-trips through tomllib to an equal structure.
        reparsed = tomllib.loads(text)
        self.assertEqual(reparsed, doc)

    def test_receipt_summary_omitted_when_absent(self):
        doc = {
            "schema": 1,
            "task": {"project": "demo"},
            "assignments": [
                {
                    "nn": 1,
                    "native": {"platform": "claude"},
                    "events": [{"at": datetime.datetime(2026, 1, 1), "to": "reserved"}],
                }
            ],
        }
        text = toml_write.dumps(doc)
        self.assertNotIn("receipt_summary", text)

    def test_empty_list_is_scalar_array_not_array_of_tables(self):
        doc = {"schema": 1, "task": {"allowlist": []}}
        text = toml_write.dumps(doc)
        self.assertIn("allowlist = []", text)
        self.assertNotIn("[[task.allowlist]]", text)

    def test_output_ends_with_single_trailing_newline(self):
        text = toml_write.dumps({"schema": 1})
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
