"""scripts/marina/mcp_server.py — `marina mcp`, the stdio MCP server for interactive Marina (spec §3.4).

JSON-RPC 2.0, one message per line on stdin/stdout: `initialize`,
`notifications/initialized`, `ping`, `tools/list` and `tools/call`. Only
JSON-RPC goes to stdout. A tool error becomes an `isError` result, never a
crash or a traceback on stdout.

Tools (docs/plano-f5-servidor-mcp-2026-10.md):

- read (`readOnlyHint`): `task_status`, `envelope_show`, `sessions`,
  `next_nn`, `gate_check`, `decision_preview`, `handoff_validate`;
- write and action: `envelope_draft` (always clears the approval),
  `state_reserve`, `launch_node`, `run_start` (refuses without a valid
  approval), `run_stop`.

No tool approves an envelope: only `marina approve` on a TTY does. The kit
root is the server's own and never a tool argument; `project`/`task` must
fullmatch `^[a-z0-9-]+$`. The four tools that change state refuse while a
`marina run` holds the task lock (plan decision 6). Writes stay inside the
task directory.

Minimum tested Claude CLI version: 2.1.306 — through `launch_claude` and the
manager listing; the detached `run_start` child is this kit's own CLI.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, TextIO

from scripts import common, gate, handoff_sync, launch_claude, status_claude
from scripts.marina import envelope as env_mod
from scripts.marina import runner
from scripts.state import StateDoc, StateError, add_assignment, dumps_state, read_state

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "marina", "version": "0.5.0"}
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class ToolError(Exception):
    """A tool refused or failed; reported as an `isError` result."""


@dataclasses.dataclass
class McpDeps:
    list_sessions: Callable[[], list[dict]]
    run_launch: Callable[..., Any]
    spawn: Callable[[list[str], Path, Path], int]
    runner_deps: Callable[[Path], runner.RunnerDeps]


def _spawn_detached(argv: list[str], cwd: Path, log_path: Path) -> int:
    with log_path.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def default_mcp_deps() -> McpDeps:
    return McpDeps(
        list_sessions=common.list_manager_sessions,
        run_launch=launch_claude.run_launch,
        spawn=_spawn_detached,
        runner_deps=runner.default_deps,
    )


# --------------------------------------------------------------------------
# Tool table
# --------------------------------------------------------------------------

_TASK = {"project": {"type": "string"}, "task": {"type": "string"}}
_NODE = {
    "role": {"type": "string"},
    "type": {"type": "string"},
    "edge": {"type": "string"},
    "predecessor": {"type": "integer"},
    "targets": {"type": "array", "items": {"type": "string"}},
}
_TOOLS: list[tuple[str, str, dict, list[str], bool]] = [
    ("task_status", "Task lock, envelope approval and nodes (read-only).", {}, [], True),
    ("envelope_show", "The task's envelope, its validation errors and whether the approval still matches.", {}, [],
     True),
    ("sessions", "Native manager sessions of this task, with their classification (read-only).", {}, [], True),
    ("next_nn", "The next assignment number of the task.", {}, [], True),
    ("gate_check", "Evaluate gate for a proposed node (read-only).",
     {**_NODE, "git_diff_acknowledged": {"type": "boolean"}, "user_decided": {"type": "boolean"}},
     ["role", "type", "edge", "predecessor", "targets"], True),
    ("decision_preview", "The decision marina run would take now, without side effects.", {}, [], True),
    ("handoff_validate", "Validate one node's handoff without changing it.", {"nn": {"type": "integer"}}, ["nn"], True),
    ("envelope_draft", "Write the task's [envelope] (never its approval) and clear any approval.",
     {"envelope": {"type": "object"}}, ["envelope"], False),
    ("state_reserve", "Reserve a new node (state add, by marina); run gate_check first.",
     {**_NODE, "allowlist": {"type": "array", "items": {"type": "string"}}, "platform": {"type": "string"},
      "reason": {"type": "string"}, "note": {"type": "string"}},
     ["role", "type", "edge", "predecessor", "targets", "allowlist"], False),
    ("launch_node", "Launch one reserved or prepared node outside an envelope (preflight + launch_claude).",
     {"nn": {"type": "integer"}}, ["nn"], False),
    ("run_start", "Start marina run detached for an approved envelope; log in the task's marina-run.log.",
     {"interval": {"type": "number"}, "max_duration": {"type": "string"}, "notify_cmd": {"type": "string"}},
     ["interval", "max_duration"], False),
    ("run_stop", "Ask a running marina run to stop at its next iteration.", {}, [], False),
]
_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {**_TASK, **properties},
        "required": ["project", "task", *required],
        "additionalProperties": False,
    }


def _check_arguments(schema: dict, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be an object")
    extra = sorted(set(arguments) - set(schema["properties"]))
    if extra:
        raise ToolError(f"unexpected argument(s): {', '.join(extra)}")
    missing = [k for k in schema["required"] if k not in arguments]
    if missing:
        raise ToolError(f"missing argument(s): {', '.join(missing)}")
    for key, value in arguments.items():
        spec = schema["properties"][key]
        expected = _JSON_TYPES[spec["type"]]
        if isinstance(value, bool) and expected is not bool:
            raise ToolError(f"argument {key} has the wrong type")
        if not isinstance(value, expected):
            raise ToolError(f"argument {key} has the wrong type")
        if "items" in spec and not all(isinstance(item, str) for item in value):
            raise ToolError(f"argument {key} items must be strings")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------


class Server:
    def __init__(self, kit_root: Path, deps: McpDeps):
        self.kit_root = Path(kit_root)
        self.deps = deps
        self._handlers = {name: getattr(self, f"_tool_{name}") for name, *_ in _TOOLS}
        self._schemas = {name: _schema(props, required) for name, _, props, required, _ in _TOOLS}

    def tools(self) -> list[dict]:
        out = []
        for name, description, _, _, read_only in _TOOLS:
            tool = {"name": name, "description": description, "inputSchema": self._schemas[name]}
            if read_only:
                tool["annotations"] = {"readOnlyHint": True}
            out.append(tool)
        return out

    # -- JSON-RPC ----------------------------------------------------------------

    def handle(self, message: Any) -> dict | None:
        if not isinstance(message, dict):
            return _error(None, -32600, "message must be a JSON object")
        msg_id = message.get("id")
        is_notification = "id" not in message
        method = message.get("method")
        if not isinstance(method, str):
            return None if is_notification else _error(msg_id, -32600, "missing method")
        params = message.get("params") or {}
        if method == "initialize":
            result: Any = self._initialize(params)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tools()}
        elif method == "tools/call":
            if is_notification:
                return None  # a notification never runs a tool: nothing to answer, nothing done
            if not isinstance(params, dict) or params.get("name") not in self._handlers:
                return None if is_notification else _error(msg_id, -32602, f"unknown tool: {params.get('name') if isinstance(params, dict) else params!r}")
            result = self._call(params["name"], params.get("arguments", {}))
        elif method.startswith("notifications/"):
            return None
        else:
            return None if is_notification else _error(msg_id, -32601, f"method not found: {method}")
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _initialize(self, params: Any) -> dict:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}

    def _call(self, name: str, arguments: Any) -> dict:
        try:
            _check_arguments(self._schemas[name], arguments)
            payload, is_error = self._handlers[name](**arguments), False
        except ToolError as exc:
            payload, is_error = {"error": str(exc)}, True
        except Exception as exc:  # noqa: BLE001 — a tool failure is a result, never a crash
            payload, is_error = {"error": f"{type(exc).__name__}: {exc}"}, True
        if isinstance(payload, tuple):
            payload, is_error = payload
        text = json.dumps(_jsonable(payload), ensure_ascii=False, indent=2)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    # -- helpers -----------------------------------------------------------------

    def _state_path(self, project: str, task: str) -> Path:
        for label, value in (("project", project), ("task", task)):
            if not _SLUG_RE.fullmatch(value):
                raise ToolError(f"{label} must match ^[a-z0-9-]+$, got {value!r}")
        path = self.kit_root / ".agent-state" / project / "tasks" / task / "state.toml"
        if not path.is_file():
            raise ToolError(f"no state.toml for {project}/{task}")
        return path

    @staticmethod
    def _refuse_if_running(state_path: Path) -> None:
        if (state_path.parent / runner.LOCK_NAME).exists():
            raise ToolError("a marina run holds this task's lock; use run_stop or wait for it to end")

    @staticmethod
    def _write_doc(state_path: Path, doc: StateDoc) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".state.toml.", dir=state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(dumps_state(doc))
            os.replace(tmp, state_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _approved_envelope(self, doc: StateDoc, task_dir: Path) -> env_mod.Envelope:
        try:
            env = env_mod.envelope_from_doc(doc)
        except env_mod.EnvelopeError as exc:
            raise ToolError(f"envelope is malformed: {exc}") from exc
        if env is None:
            raise ToolError("the task has no [envelope]")
        errors = env_mod.validate_envelope(env, doc=doc, kit_root=self.kit_root, task_dir=task_dir)
        if errors:
            raise ToolError("envelope is invalid: " + "; ".join(errors))
        if env.approval is None:
            raise ToolError("envelope is not approved; the user runs `marina approve` in a terminal")
        if env_mod.compute_hash(env, task_dir=task_dir) != env.approval.sha256:
            raise ToolError("envelope or a stage template changed since approval (hash differs); approve again")
        return env

    # -- read tools --------------------------------------------------------------

    def _tool_task_status(self, project: str, task: str) -> dict:
        state_path = self._state_path(project, task)
        doc = read_state(state_path)
        nodes = [
            {"nn": a.nn, "role": a.role, "edge": a.edge, "type": a.type, "state": a.state,
             "predecessor": a.predecessor, "native_id": a.native.id}
            for a in sorted(doc.assignments, key=lambda a: a.nn)
        ]
        return {"lines": runner.status_lines(state_path), "nodes": nodes, "next_nn": doc.task.next_nn}

    def _tool_envelope_show(self, project: str, task: str) -> dict:
        state_path = self._state_path(project, task)
        doc = read_state(state_path)
        if doc.envelope is None:
            return {"envelope": None, "approved": False, "approval_matches": False, "sha256": None, "errors": []}
        try:
            env = env_mod.parse_envelope(doc.envelope)
        except env_mod.EnvelopeError as exc:
            return {"envelope": doc.envelope, "approved": False, "approval_matches": False, "sha256": None,
                    "errors": [str(exc)]}
        errors = env_mod.validate_envelope(env, doc=doc, kit_root=self.kit_root, task_dir=state_path.parent)
        try:
            sha = env_mod.compute_hash(env, task_dir=state_path.parent)
        except OSError as exc:
            sha, errors = None, [*errors, f"cannot hash the envelope: {exc}"]
        approved = env.approval is not None
        return {"envelope": doc.envelope, "approved": approved,
                "approval_matches": approved and sha == env.approval.sha256, "sha256": sha, "errors": errors}

    def _tool_sessions(self, project: str, task: str) -> dict:
        doc = read_state(self._state_path(project, task))
        try:
            sessions = self.deps.list_sessions()
        except common.ManagerUnavailable as exc:
            return {"available": False, "reason": str(exc)}
        prefix = f"{doc.task.slug} —"
        matches = status_claude.find_task_sessions(sessions, title_prefix=prefix)
        return {"available": True, "sessions": [
            {"id": s.get("id"), "name": s.get("name"), "state": s.get("state"), "status": s.get("status"),
             "classification": status_claude.classify_session(s)}
            for s in matches
        ]}

    def _tool_next_nn(self, project: str, task: str) -> dict:
        return {"next_nn": read_state(self._state_path(project, task)).task.next_nn}

    def _tool_gate_check(self, project: str, task: str, role: str, type: str, edge: str, predecessor: int,
                         targets: list[str], git_diff_acknowledged: bool = False, user_decided: bool = False) -> dict:
        state_path = self._state_path(project, task)
        doc = read_state(state_path)
        result = gate.evaluate_gate(
            doc, role=role, type_=type, edge=edge, predecessor=predecessor, targets=targets,
            sibling_docs=gate.load_task_docs(state_path.parent.parent, exclude_slug=doc.task.slug),
            git_diff_acknowledged=git_diff_acknowledged, user_decided=user_decided,
            list_sessions=self.deps.list_sessions,
        )
        return {"allowed": result.allowed, "reasons": result.reasons, "notes": result.notes}

    def _tool_decision_preview(self, project: str, task: str) -> dict:
        state_path = self._state_path(project, task)
        decision = runner.preview_decision(state_path, kit_root=self.kit_root,
                                           deps=self.deps.runner_deps(self.kit_root))
        return runner.decision_to_dict(decision)

    def _tool_handoff_validate(self, project: str, task: str, nn: int) -> Any:
        state_path = self._state_path(project, task)
        doc = read_state(state_path)
        try:
            a = doc.get_assignment(nn)
            handoff_sync.validate_task_paths(state_path, doc, a, self.kit_root)
            path = self.kit_root / a.handoff
            handoff_sync.validate_location(path, state_path.parent)
            profile = handoff_sync.validate_handoff(path.read_text(encoding="utf-8"), a, self.kit_root)
            handoff_sync.validate_launch_metadata(a)
        except (handoff_sync.HandoffError, StateError, OSError) as exc:
            return {"ok": False, "error": str(exc)}, True
        return {"ok": True, "profile": profile}

    # -- write and action tools --------------------------------------------------

    def _tool_envelope_draft(self, project: str, task: str, envelope: dict) -> dict:
        state_path = self._state_path(project, task)
        self._refuse_if_running(state_path)
        if "approval" in envelope:
            raise ToolError("a draft never carries [envelope.approval]; only `marina approve` records it")
        try:
            env = env_mod.parse_envelope(envelope)
        except env_mod.EnvelopeError as exc:
            raise ToolError(str(exc)) from exc
        doc = read_state(state_path)
        had_approval = isinstance(doc.envelope, dict) and "approval" in doc.envelope
        doc.envelope = env_mod.envelope_to_raw(env)
        doc.task.updated_at = datetime.datetime.now().astimezone()
        self._write_doc(state_path, doc)
        errors = env_mod.validate_envelope(env, doc=doc, kit_root=self.kit_root, task_dir=state_path.parent)
        try:
            sha = env_mod.compute_hash(env, task_dir=state_path.parent)
        except OSError:
            sha = None
        return {"written": True, "approval_cleared": had_approval, "errors": errors, "sha256": sha}

    def _tool_state_reserve(self, project: str, task: str, role: str, type: str, edge: str, predecessor: int,
                            targets: list[str], allowlist: list[str], platform: str = "claude", reason: str = "",
                            note: str = "") -> dict:
        state_path = self._state_path(project, task)
        self._refuse_if_running(state_path)
        doc = read_state(state_path)
        try:
            a = add_assignment(doc, role=role, type_=type, edge=edge, predecessor=predecessor, targets=targets,
                               platform=platform, reason=reason, allowlist=allowlist, note=note, by="marina")
        except StateError as exc:
            raise ToolError(str(exc)) from exc
        self._write_doc(state_path, doc)
        return {"nn": a.nn, "title": a.title, "handoff": a.handoff, "receipt": a.receipt}

    def _tool_launch_node(self, project: str, task: str, nn: int) -> Any:
        state_path = self._state_path(project, task)
        self._refuse_if_running(state_path)
        result = self.deps.run_launch(state_path, nn, kit_root=self.kit_root)
        payload = {"ok": result.ok, "session_id": result.session_id, "reasons": list(result.reasons),
                   "notes": list(result.notes)}
        return payload, not result.ok

    def _tool_run_start(self, project: str, task: str, interval: float, max_duration: str,
                        notify_cmd: str | None = None) -> dict:
        state_path = self._state_path(project, task)
        self._refuse_if_running(state_path)
        if not interval > 0:
            raise ToolError("interval must be > 0")
        try:
            env_mod.parse_duration(max_duration)
        except env_mod.EnvelopeError as exc:
            raise ToolError(str(exc)) from exc
        task_dir = state_path.parent
        self._approved_envelope(read_state(state_path), task_dir)
        argv = [sys.executable, str(self.kit_root / "scripts" / "marina" / "__main__.py"), "run", project, task,
                "--interval", f"{interval:g}", "--max-duration", max_duration]
        if notify_cmd:
            argv += ["--notify-cmd", notify_cmd]
        argv += ["--kit-root", str(self.kit_root)]
        log = task_dir / runner.LOG_NAME
        return {"pid": self.deps.spawn(argv, self.kit_root, log), "log": str(log)}

    def _tool_run_stop(self, project: str, task: str) -> Any:
        requested = runner.request_stop(self._state_path(project, task))
        return {"requested": requested}, not requested


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin: TextIO, stdout: TextIO, *, kit_root: Path, deps: McpDeps) -> int:
    """Answer one JSON-RPC message per line until EOF."""

    server = Server(kit_root, deps)
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response: dict | None = _error(None, -32700, f"parse error: {exc}")
        else:
            try:
                response = server.handle(message)
            except Exception as exc:  # noqa: BLE001 — never die on one message
                print(f"marina mcp: internal error: {exc}", file=sys.stderr)
                response = _error(message.get("id") if isinstance(message, dict) else None, -32603, "internal error")
        if response is not None:
            # ASCII-only, so a non-UTF-8 locale cannot break the stream.
            stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
            stdout.flush()
    return 0
