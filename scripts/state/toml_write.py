"""scripts/state/toml_write.py — minimal TOML writer for the schema-v0 subset.

Deliberately narrow: only the constructs `state.toml` actually uses —
strings, integers, booleans, RFC 3339 datetimes, arrays of strings, arrays
of tables (`[[assignments]]`, `[[assignments.events]]`), and sub-tables
(`[assignments.native]`, `[assignments.receipt_summary]`). No external
dependency; stdlib only.

Not a general-purpose TOML emitter: it walks a plain nested dict built by
`scripts.state.model.StateDoc.to_raw()` and infers table shape from
Python types only (dict -> sub-table, list-of-dict -> array of tables,
anything else -> scalar or scalar array). Round-trip correctness (this
writer's output re-parsed by `tomllib` yields an equal data structure) is
covered by tests/test_toml_write.py and tests/test_state_model.py, not
byte-for-byte text equality with any particular source file.
"""

from __future__ import annotations

import datetime


def dumps(doc: dict) -> str:
    """Serialize a schema-v0 raw document dict to TOML text."""

    lines: list[str] = []
    _write_table_body(lines, doc, ())
    # Drop a possible leading blank line (from the first sub-table/array),
    # keep exactly one trailing newline.
    while lines and lines[0] == "":
        lines.pop(0)
    return "\n".join(lines).rstrip("\n") + "\n"


def _is_subtable(value: object) -> bool:
    return isinstance(value, dict)


def _is_array_of_tables(value: object) -> bool:
    return isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict)


def _write_table_body(lines: list[str], table: dict, path: tuple[str, ...]) -> None:
    scalars = []
    subtables = []
    array_tables = []
    for key, value in table.items():
        if _is_subtable(value):
            subtables.append((key, value))
        elif _is_array_of_tables(value):
            array_tables.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{key} = {_format_value(value)}")

    for key, value in subtables:
        header = ".".join((*path, key))
        lines.append("")
        lines.append(f"[{header}]")
        _write_table_body(lines, value, (*path, key))

    for key, value in array_tables:
        header = ".".join((*path, key))
        for item in value:
            lines.append("")
            lines.append(f"[[{header}]]")
            _write_table_body(lines, item, (*path, key))


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime.datetime):
        return _format_datetime(value)
    if isinstance(value, str):
        return _format_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML scalar type for {value!r}: {type(value)!r}")


def _format_datetime(value: datetime.datetime) -> str:
    # RFC 3339; tomllib round-trips this back to an equal datetime object
    # regardless of "Z" vs "+00:00" spelling, so isoformat() is sufficient.
    return value.isoformat()


_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\t": "\\t",
    "\r": "\\r",
    "\b": "\\b",
    "\f": "\\f",
}


def _format_string(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)
