"""Tests for scripts/marina/mcp_server.py — the `marina mcp` stdio server.

JSON-RPC runs in process over StringIO pipes; the manager, launch, the
detached runner and the runner's dependencies are fakes. A temporary kit
root holds one task with an approved envelope.
"""

from __future__ import annotations

import datetime
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.state as st
from scripts.marina import envelope as env_mod
from scripts.marina import mcp_server, runner
from scripts.marina.judge import JudgeAnswer

KIT_ROOT = Path(__file__).resolve().parent.parent
AT = datetime.datetime(2026, 10, 27, 1, 0, 0, tzinfo=datetime.timezone.utc)
ROLE = "node-backend"
TEMPLATE = "## Objective\n\nDo it.\n\n## Write scope\n\n`src/`\n\n## Acceptance criteria\n\n1. Works.\n"
READ_TOOLS = {"task_status", "envelope_show", "sessions", "next_nn", "gate_check", "decision_preview",
              "handoff_validate"}
ACTION_TOOLS = {"envelope_draft", "state_reserve", "launch_node", "run_start", "run_stop"}


class Fixture:
    def __init__(self, tmp: str, *, approve: bool = True):
        self.kit = Path(tmp) / "kit"
        agents = self.kit / ".claude" / "agents"
        agents.mkdir(parents=True)
        for role in (ROLE, "reviewer"):
            shutil.copy(KIT_ROOT / ".claude" / "agents" / f"{role}.md", agents)
        self.target = Path(tmp) / "target"
        self.target.mkdir()
        self.task_dir = self.kit / ".agent-state" / "demo" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.state_path = self.task_dir / "state.toml"
        (self.task_dir / "stage-1-handoff-template.md").write_text(TEMPLATE, encoding="utf-8")
        doc = st.init_state(self.state_path, project="demo", slug="t1", title="Demo", kit_root=str(self.kit),
                            targets=[str(self.target)], at=AT)
        self.raw = {
            "targets": [str(self.target)],
            "branches": {str(self.target): "feat/x"},
            "allowlist": [f"Bash(test -d {self.target})"],
            "review": "each_stage",
            "max_corrections": 1,
            "max_duration": "8h",
            "judge_max_calls": 1,
            "on_pass_with_risks": "judge",
            "stages": [{"role": ROLE, "handoff": "stage-1-handoff-template.md"}],
        }
        envelope = dict(self.raw)
        if approve:
            sha = env_mod.compute_hash(env_mod.parse_envelope(self.raw), task_dir=self.task_dir)
            envelope["approval"] = {"at": AT, "sha256": sha}
        doc.envelope = envelope
        st.write_state(self.state_path, doc)
        self.sessions: list[dict] = []
        self.sessions_error: Exception | None = None
        self.launches: list[tuple] = []
        self.spawns: list[tuple] = []
        self.launch_result = launch_ok()

    def list_sessions(self) -> list[dict]:
        if self.sessions_error is not None:
            raise self.sessions_error
        return list(self.sessions)

    def run_launch(self, state_path, nn, **kwargs):
        self.launches.append((state_path, nn, kwargs))
        return self.launch_result

    def spawn(self, argv, cwd, log_path) -> int:
        self.spawns.append((list(argv), cwd, log_path))
        return 4321

    def runner_deps(self, kit_root: Path) -> runner.RunnerDeps:
        return runner.RunnerDeps(
            list_sessions=self.list_sessions, run_subprocess=None, run_preflight=None,
            git_snapshot=lambda t: "clean\n", git_branch=lambda t: "feat/x",
            judge=lambda q, p: JudgeAnswer("stop", "x"), notify=lambda c: None, sleep=lambda s: None,
            monotonic=lambda: 0.0, now=lambda: AT, pid_alive=lambda pid: False, getpid=lambda: 1,
        )

    def server(self) -> mcp_server.Server:
        deps = mcp_server.McpDeps(list_sessions=self.list_sessions, run_launch=self.run_launch, spawn=self.spawn,
                                  runner_deps=self.runner_deps)
        return mcp_server.Server(self.kit, deps)

    def lock(self) -> None:
        (self.task_dir / runner.LOCK_NAME).write_text('{"pid": 99}', encoding="utf-8")


def launch_ok():
    return mock.Mock(ok=True, session_id="abcdef01", reasons=[], notes=[])


def request(method: str, params: dict | None = None, id_: int | None = 1) -> dict:
    message = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        message["id"] = id_
    if params is not None:
        message["params"] = params
    return message


def call(server: mcp_server.Server, name: str, **arguments) -> tuple[bool, dict]:
    response = server.handle(request("tools/call", {"name": name, "arguments": arguments}))
    result = response["result"]
    return result["isError"], json.loads(result["content"][0]["text"])


class ProtocolTests(unittest.TestCase):
    def test_initialize_negotiates_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Fixture(tmp).server()
            result = server.handle(request("initialize", {"protocolVersion": "2025-03-26"}))["result"]
            self.assertEqual(result["protocolVersion"], "2025-03-26")
            self.assertIn("tools", result["capabilities"])
            self.assertEqual(result["serverInfo"]["name"], "marina")
            other = server.handle(request("initialize", {"protocolVersion": "1999-01-01"}))["result"]
            self.assertEqual(other["protocolVersion"], "2025-06-18")

    def test_tools_list_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Fixture(tmp).server().handle(request("tools/list"))["result"]["tools"]
            names = {t["name"] for t in tools}
            self.assertEqual(names, READ_TOOLS | ACTION_TOOLS)
            self.assertFalse([n for n in names if "approv" in n])
            for tool in tools:
                self.assertEqual(tool["inputSchema"]["type"], "object")
                self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_read_tools_are_annotated(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Fixture(tmp).server().handle(request("tools/list"))["result"]["tools"]
            read = {t["name"] for t in tools if t.get("annotations", {}).get("readOnlyHint")}
            self.assertEqual(read, READ_TOOLS)

    def test_ping(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Fixture(tmp).server().handle(request("ping"))["result"], {})

    def test_parse_error_then_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            lines = "not json\n" + json.dumps(request("ping", id_=2)) + "\n" + json.dumps(request("tools/list", id_=3)) + "\n"
            out = io.StringIO()
            code = mcp_server.serve(io.StringIO(lines), out, kit_root=fx.kit, deps=fx.server().deps)
            self.assertEqual(code, 0)
            responses = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(responses[0]["error"]["code"], -32700)
            self.assertEqual(responses[1]["id"], 2)
            self.assertEqual(len(responses[2]["result"]["tools"]), 12)

    def test_unknown_method_and_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Fixture(tmp).server()
            self.assertEqual(server.handle(request("nope"))["error"]["code"], -32601)
            missing = server.handle(request("tools/call", {"name": "approve", "arguments": {}}))
            self.assertEqual(missing["error"]["code"], -32602)
            self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 5})["error"]["code"], -32600)
            self.assertEqual(server.handle(request("tools/call", {"arguments": {}}))["error"]["code"], -32602)

    def test_notification_gets_no_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Fixture(tmp).server()
            self.assertIsNone(server.handle(request("notifications/initialized", id_=None)))
            self.assertIsNone(server.handle(request("nope", id_=None)))

    def test_tools_call_notification_executes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            before = fx.state_path.read_bytes()
            server = fx.server()
            for name, arguments in (("envelope_draft", {"envelope": fx.raw}),
                                    ("run_start", {"interval": 30, "max_duration": "2h"}),
                                    ("launch_node", {"nn": 1})):
                with self.subTest(tool=name):
                    message = request("tools/call", {"name": name, "arguments": {"project": "demo", "task": "t1",
                                                                                 **arguments}}, id_=None)
                    self.assertIsNone(server.handle(message))
            self.assertEqual(fx.state_path.read_bytes(), before)
            self.assertEqual((fx.spawns, fx.launches), ([], []))

    def test_stdout_is_ascii(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            line = json.dumps(request("tools/call", {"name": "task_status",
                                                     "arguments": {"project": "demo", "task": "t1"}}))
            out = io.StringIO()
            mcp_server.serve(io.StringIO(line + "\n"), out, kit_root=fx.kit, deps=fx.server().deps)
            self.assertTrue(out.getvalue().isascii())
            self.assertIn("task: t1 — Demo", json.loads(json.loads(out.getvalue())["result"]["content"][0]["text"])["lines"])

    def test_stdout_only_jsonrpc(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            fx.sessions_error = RuntimeError("boom")
            lines = "\n".join(json.dumps(m) for m in (
                request("initialize", {"protocolVersion": "2025-06-18"}),
                request("notifications/initialized", id_=None),
                request("tools/call", {"name": "sessions", "arguments": {"project": "demo", "task": "t1"}}, id_=2),
                request("tools/call", {"name": "task_status", "arguments": {"project": "demo", "task": "t1"}}, id_=3),
            )) + "\n"
            out = io.StringIO()
            mcp_server.serve(io.StringIO(lines), out, kit_root=fx.kit, deps=fx.server().deps)
            for line in out.getvalue().splitlines():
                self.assertEqual(json.loads(line)["jsonrpc"], "2.0")
            self.assertEqual(len(out.getvalue().splitlines()), 3)


class ReadToolTests(unittest.TestCase):
    def test_task_status_and_next_nn(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            server = fx.server()
            error, payload = call(server, "task_status", project="demo", task="t1")
            self.assertFalse(error)
            self.assertIn("task: t1 — Demo", payload["lines"])
            self.assertEqual((payload["nodes"], payload["next_nn"]), ([], 1))
            self.assertEqual(call(server, "next_nn", project="demo", task="t1"), (False, {"next_nn": 1}))

    def test_envelope_show_reports_approval_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            server = fx.server()
            error, payload = call(server, "envelope_show", project="demo", task="t1")
            self.assertFalse(error)
            self.assertEqual((payload["approved"], payload["approval_matches"], payload["errors"]), (True, True, []))
            self.assertIsInstance(payload["envelope"]["approval"]["at"], str)
            (fx.task_dir / "stage-1-handoff-template.md").write_text(TEMPLATE + "x\n", encoding="utf-8")
            self.assertFalse(call(server, "envelope_show", project="demo", task="t1")[1]["approval_matches"])

    def test_sessions_filters_by_task_and_handles_unavailable_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            fx.sessions = [
                {"id": "a1b2c3d4", "name": "t1 — node-backend — 01 — implementação", "cwd": str(fx.kit),
                 "state": "working", "status": "busy"},
                {"id": "ffffffff", "name": "other — reviewer — 01 — revisão", "cwd": str(fx.kit),
                 "state": "done", "status": "idle"},
            ]
            error, payload = call(fx.server(), "sessions", project="demo", task="t1")
            self.assertFalse(error)
            self.assertEqual([(s["id"], s["classification"]) for s in payload["sessions"]], [("a1b2c3d4", "working")])
            fx.sessions_error = runner.common.ManagerUnavailable("no claude")
            self.assertEqual(call(fx.server(), "sessions", project="demo", task="t1")[1]["available"], False)

    def test_gate_check_returns_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            error, payload = call(fx.server(), "gate_check", project="demo", task="t1", role=ROLE,
                                  type="implementação", edge="revisa", predecessor=0, targets=[str(fx.target)])
            self.assertFalse(error)
            self.assertFalse(payload["allowed"])
            self.assertTrue(payload["reasons"])
            ok = call(fx.server(), "gate_check", project="demo", task="t1", role=ROLE, type="implementação",
                      edge="inicia", predecessor=0, targets=[str(fx.target)], git_diff_acknowledged=True)[1]
            self.assertTrue(ok["allowed"], ok)

    def test_decision_preview_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            before = {p.name: p.read_bytes() for p in fx.task_dir.iterdir()}
            error, payload = call(fx.server(), "decision_preview", project="demo", task="t1")
            self.assertFalse(error)
            self.assertEqual((payload["kind"], payload["node"]["edge"]), ("launch", "inicia"))
            self.assertEqual({p.name: p.read_bytes() for p in fx.task_dir.iterdir()}, before)

    def test_handoff_validate_ok_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            server = fx.server()
            call(server, "state_reserve", project="demo", task="t1", role=ROLE, type="implementação", edge="inicia",
                 predecessor=0, targets=[str(fx.target)], allowlist=["Bash(true)"])
            error, payload = call(server, "handoff_validate", project="demo", task="t1", nn=1)
            self.assertTrue(error)
            self.assertFalse(payload["ok"])
            doc = st.read_state(fx.state_path)
            from scripts.marina import handoff_gen
            text = handoff_gen.render_stage_handoff(doc, doc.get_assignment(1), kit_root=fx.kit, template_text=TEMPLATE)
            (fx.kit / doc.get_assignment(1).handoff).write_text(text, encoding="utf-8")
            error, payload = call(server, "handoff_validate", project="demo", task="t1", nn=1)
            self.assertFalse(error, payload)
            self.assertEqual(payload["profile"], str(fx.kit / ".claude" / "agents" / f"{ROLE}.md"))

    def test_bad_slugs_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Fixture(tmp).server()
            for project, task in (("..", "t1"), ("demo", "../t1"), ("Demo", "t1"), ("demo", "t1\n"), ("demo", "")):
                with self.subTest(project=project, task=task):
                    error, payload = call(server, "task_status", project=project, task=task)
                    self.assertTrue(error)
                    self.assertIn("error", payload)

    def test_kit_root_argument_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            error, payload = call(Fixture(tmp).server(), "task_status", project="demo", task="t1", kit_root="/etc")
            self.assertTrue(error)
            self.assertIn("kit_root", payload["error"])

    def test_array_items_must_be_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            before = fx.state_path.read_bytes()
            server = fx.server()
            for targets, allowlist in (([1], ["Bash(true)"]), ([str(fx.target)], [{}])):
                with self.subTest(targets=targets, allowlist=allowlist):
                    error, payload = call(server, "state_reserve", project="demo", task="t1", role=ROLE,
                                          type="implementação", edge="inicia", predecessor=0, targets=targets,
                                          allowlist=allowlist)
                    self.assertTrue(error)
                    self.assertIn("items", payload["error"])
            self.assertTrue(call(server, "gate_check", project="demo", task="t1", role=ROLE, type="implementação",
                                 edge="inicia", predecessor=0, targets=[None])[0])
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_missing_task_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(call(Fixture(tmp).server(), "task_status", project="demo", task="t9")[0])

    def test_tool_exception_is_error_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            fx.sessions_error = RuntimeError("manager exploded")
            error, payload = call(fx.server(), "sessions", project="demo", task="t1")
            self.assertTrue(error)
            self.assertIn("manager exploded", payload["error"])


class ActionToolTests(unittest.TestCase):
    def test_envelope_draft_clears_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            server = fx.server()
            error, payload = call(server, "envelope_draft", project="demo", task="t1", envelope=fx.raw)
            self.assertFalse(error, payload)
            self.assertEqual((payload["written"], payload["approval_cleared"], payload["errors"]), (True, True, []))
            self.assertRegex(payload["sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(call(server, "envelope_show", project="demo", task="t1")[1]["approved"])

    def test_envelope_draft_refuses_approval_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            before = fx.state_path.read_bytes()
            draft = dict(fx.raw, approval={"at": "2026-10-27T00:00:00+00:00", "sha256": "a" * 64})
            error, payload = call(fx.server(), "envelope_draft", project="demo", task="t1", envelope=draft)
            self.assertTrue(error)
            self.assertIn("approval", payload["error"])
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_envelope_draft_refuses_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            before = fx.state_path.read_bytes()
            for draft in (dict(fx.raw, surprise=1), {"targets": []}, "not an object"):
                with self.subTest(draft=draft):
                    self.assertTrue(call(fx.server(), "envelope_draft", project="demo", task="t1", envelope=draft)[0])
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_envelope_draft_writes_with_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            error, payload = call(fx.server(), "envelope_draft", project="demo", task="t1",
                                  envelope=dict(fx.raw, max_corrections=2))
            self.assertFalse(error)
            self.assertTrue(any("max_corrections" in e for e in payload["errors"]))
            self.assertEqual(st.read_state(fx.state_path).envelope["max_corrections"], 2)

    def test_state_reserve_reserves_next_nn(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            error, payload = call(fx.server(), "state_reserve", project="demo", task="t1", role=ROLE,
                                  type="implementação", edge="inicia", predecessor=0, targets=[str(fx.target)],
                                  allowlist=["Bash(true)"], note="manual")
            self.assertFalse(error, payload)
            self.assertEqual(payload["nn"], 1)
            a = st.read_state(fx.state_path).get_assignment(1)
            self.assertEqual((a.state, a.events[0].by, a.events[0].note), ("reserved", "marina", "manual"))
            bad = call(fx.server(), "state_reserve", project="demo", task="t1", role=ROLE, type="x", edge="inicia",
                       predecessor=0, targets=[str(fx.target)], allowlist=["Bash(true)"])
            self.assertTrue(bad[0])

    def test_launch_node_calls_injected_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            error, payload = call(fx.server(), "launch_node", project="demo", task="t1", nn=1)
            self.assertFalse(error)
            self.assertEqual(payload["session_id"], "abcdef01")
            self.assertEqual(fx.launches[0][:2], (fx.state_path, 1))
            self.assertEqual(fx.launches[0][2]["kit_root"], fx.kit)
            fx.launch_result = mock.Mock(ok=False, session_id=None, reasons=["preflight failed"], notes=[])
            self.assertTrue(call(fx.server(), "launch_node", project="demo", task="t1", nn=1)[0])

    def test_run_start_spawns_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            error, payload = call(fx.server(), "run_start", project="demo", task="t1", interval=30,
                                  max_duration="2h", notify_cmd="notify-send x")
            self.assertFalse(error, payload)
            self.assertEqual(payload["pid"], 4321)
            argv, cwd, log = fx.spawns[0]
            self.assertEqual(argv[1:], [str(fx.kit / "scripts" / "marina" / "__main__.py"), "run", "demo", "t1",
                                        "--interval", "30", "--max-duration", "2h", "--notify-cmd", "notify-send x",
                                        "--kit-root", str(fx.kit)])
            self.assertEqual((cwd, log), (fx.kit, fx.task_dir / "marina-run.log"))

    def test_run_start_refuses_without_valid_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            unapproved = Fixture(tmp, approve=False)
            self.assertTrue(call(unapproved.server(), "run_start", project="demo", task="t1", interval=30,
                                 max_duration="2h")[0])
            self.assertEqual(unapproved.spawns, [])
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            (fx.task_dir / "stage-1-handoff-template.md").write_text(TEMPLATE + "edit\n", encoding="utf-8")
            error, payload = call(fx.server(), "run_start", project="demo", task="t1", interval=30, max_duration="2h")
            self.assertTrue(error)
            self.assertIn("hash", payload["error"])
            self.assertEqual(fx.spawns, [])
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            doc = st.read_state(fx.state_path)
            doc.envelope["max_corrections"] = 2
            st.write_state(fx.state_path, doc)
            self.assertTrue(call(fx.server(), "run_start", project="demo", task="t1", interval=30,
                                 max_duration="2h")[0])
            self.assertEqual(fx.spawns, [])

    def test_run_start_bad_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            for interval, duration in ((0, "2h"), (30, "1d"), (-1, "2h")):
                with self.subTest(interval=interval, duration=duration):
                    self.assertTrue(call(fx.server(), "run_start", project="demo", task="t1", interval=interval,
                                         max_duration=duration)[0])
            self.assertEqual(fx.spawns, [])

    def test_run_stop_with_and_without_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            self.assertTrue(call(fx.server(), "run_stop", project="demo", task="t1")[0])
            fx.lock()
            self.assertEqual(call(fx.server(), "run_stop", project="demo", task="t1"), (False, {"requested": True}))
            self.assertTrue((fx.task_dir / runner.STOP_NAME).exists())

    def test_actions_refused_while_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            fx.lock()
            before = fx.state_path.read_bytes()
            server = fx.server()
            calls = (
                ("envelope_draft", {"envelope": fx.raw}),
                ("state_reserve", {"role": ROLE, "type": "implementação", "edge": "inicia", "predecessor": 0,
                                   "targets": [str(fx.target)], "allowlist": ["Bash(true)"]}),
                ("launch_node", {"nn": 1}),
                ("run_start", {"interval": 30, "max_duration": "2h"}),
            )
            for name, arguments in calls:
                with self.subTest(tool=name):
                    error, payload = call(server, name, project="demo", task="t1", **arguments)
                    self.assertTrue(error)
                    self.assertIn("marina run", payload["error"])
            self.assertEqual(fx.state_path.read_bytes(), before)
            self.assertEqual((fx.launches, fx.spawns), ([], []))

    def test_default_spawn_detaches(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "marina-run.log"
            with mock.patch.object(runner.subprocess, "Popen") as popen:
                popen.return_value.pid = 77
                pid = mcp_server.default_mcp_deps().spawn(["python3", "x"], Path(tmp), log)
            self.assertEqual(pid, 77)
            kwargs = popen.call_args.kwargs
            self.assertTrue(kwargs["start_new_session"])
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["stderr"], subprocess.STDOUT)
            self.assertEqual(kwargs["cwd"], str(tmp))
            self.assertTrue(log.exists())


class ConfigurationTests(unittest.TestCase):
    def _tool_names(self) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return {t["name"] for t in Fixture(tmp).server().tools()}

    def test_mcp_json_registers_server(self):
        config = json.loads((KIT_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(config["mcpServers"]["marina"], {"command": "python3", "args": ["-m", "scripts.marina", "mcp"]})

    def test_settings_preapprove_only_read_tools(self):
        settings = json.loads((KIT_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        allow = settings["permissions"]["allow"]
        self.assertEqual(sorted(allow), sorted(f"mcp__marina__{n}" for n in READ_TOOLS))
        with tempfile.TemporaryDirectory() as tmp:
            annotated = {t["name"] for t in Fixture(tmp).server().tools() if t.get("annotations", {}).get("readOnlyHint")}
        self.assertEqual({a.removeprefix("mcp__marina__") for a in allow}, annotated)

    def test_marina_profile_lists_every_tool(self):
        text = (KIT_ROOT / ".claude" / "agents" / "marina.md").read_text(encoding="utf-8")
        tools_line = next(line for line in text.split("---")[1].splitlines() if line.startswith("tools:"))
        tools = json.loads(tools_line.split(":", 1)[1])
        for name in self._tool_names():
            self.assertIn(f"mcp__marina__{name}", tools)
        for base in ("Read", "Bash", "Edit", "Write", "Agent(Explore)"):
            self.assertIn(base, tools)

    def test_module_entry_point(self):
        lines = json.dumps(request("initialize", {"protocolVersion": "2025-06-18"})) + "\n" + json.dumps(
            request("tools/list", id_=2)) + "\n"
        proc = subprocess.run([sys.executable, "-m", "scripts.marina", "mcp"], cwd=KIT_ROOT, input=lines,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in responses], [1, 2])
        self.assertEqual(len(responses[1]["result"]["tools"]), 12)


if __name__ == "__main__":
    unittest.main()
