"""Tests for `state add` / `state set` / `state next-nn`
(scripts/state/__init__.py operations and the scripts/state/__main__.py
CLI wrapper). Uses a small synthetic state.toml built via the library
itself, never the versioned fixture (kept read-only) and never real
.agent-state/ contents.
"""

from __future__ import annotations

import datetime
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import scripts.state as st
from scripts.state import __main__ as state_cli
from scripts.state.model import StateError

AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _minimal_doc() -> st.StateDoc:
    task = st.Task(
        project="demo-project",
        slug="demo-task",
        title="Demo task",
        phase="implementation",
        kit_root="/tmp/kit",
        targets=["/tmp/kit"],
        journal=".agent-state/demo-project/tasks/demo-task/checkpoint.md",
        next_nn=1,
        created_at=AT,
        updated_at=AT,
    )
    return st.StateDoc(schema=1, task=task, assignments=[])


class AddAssignmentTests(unittest.TestCase):
    def test_add_first_node_derives_paths_and_title(self):
        doc = _minimal_doc()
        a = st.add_assignment(
            doc,
            role="node-backend",
            type_="implementação",
            edge="inicia",
            predecessor=0,
            targets=["/tmp/kit"],
            platform="claude",
            at=AT,
        )
        self.assertEqual(a.nn, 1)
        self.assertEqual(a.mode, "writer")
        self.assertEqual(a.state, "reserved")
        self.assertEqual(a.title, "demo-task — node-backend — 01 — implementação")
        self.assertEqual(a.handoff, ".agent-state/demo-project/tasks/demo-task/01-node-backend-handoff.md")
        self.assertEqual(a.receipt, ".agent-state/demo-project/tasks/demo-task/01-node-backend-receipt.md")
        self.assertEqual(doc.task.next_nn, 2)
        self.assertEqual(a.events[0].to, "reserved")
        self.assertEqual(a.events[0].from_, "")

    def test_add_reader_role_derives_reader_mode(self):
        doc = _minimal_doc()
        a = st.add_assignment(
            doc, role="reviewer", type_="revisão", edge="inicia", predecessor=0, targets=["/tmp/kit"], at=AT
        )
        self.assertEqual(a.mode, "reader")

    def test_add_unknown_predecessor_raises(self):
        doc = _minimal_doc()
        with self.assertRaises(StateError):
            st.add_assignment(
                doc, role="node-backend", type_="implementação", edge="continua",
                predecessor=5, targets=["/tmp/kit"], at=AT,
            )

    def test_add_unavailable_without_reason_raises(self):
        doc = _minimal_doc()
        with self.assertRaises(StateError):
            st.add_assignment(
                doc, role="reviewer", type_="análise", edge="analisa", predecessor=0,
                targets=["/tmp/kit"], platform="unavailable", at=AT,
            )

    def test_add_unavailable_with_reason_ok(self):
        doc = _minimal_doc()
        a = st.add_assignment(
            doc, role="reviewer", type_="análise", edge="analisa", predecessor=0,
            targets=["/tmp/kit"], platform="unavailable", reason="ambiente proibiu subtarefas", at=AT,
        )
        self.assertEqual(a.native.platform, "unavailable")

    def test_second_add_increments_nn(self):
        doc = _minimal_doc()
        st.add_assignment(doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0, targets=["/tmp/kit"], at=AT)
        second = st.add_assignment(
            doc, role="reviewer", type_="revisão", edge="revisa_direta", predecessor=0, targets=["/tmp/kit"], at=AT
        )
        self.assertEqual(second.nn, 2)
        self.assertEqual(doc.task.next_nn, 3)


class InitStateTests(unittest.TestCase):
    """Finding 1 (`tooling-gaps-fix/01-kit-tooling-handoff.md`): `state
    init` bootstraps a brand-new task's `[task]` header from scratch,
    something none of `add`/`set`/`next-nn` can do (they all call
    `read_state` first)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_path = Path(self.tmpdir.name) / "tasks" / "demo-task" / "state.toml"
        # Mirrors the real precondition: the coordinator already created the
        # task directory (for handoffs/receipts) before running `state init`.
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def test_init_creates_valid_minimal_doc(self):
        doc = st.init_state(
            str(self.state_path),
            project="demo-project",
            slug="demo-task",
            title="Demo task",
            kit_root="/tmp/kit",
            targets=["/tmp/kit"],
            at=AT,
        )
        self.assertEqual(doc.schema, 1)
        self.assertEqual(doc.task.next_nn, 1)
        self.assertEqual(doc.task.created_at, AT)
        self.assertEqual(doc.task.updated_at, AT)
        self.assertEqual(doc.task.phase, "intake")
        self.assertEqual(doc.assignments, [])

    def test_init_derives_journal_as_sibling_checkpoint(self):
        doc = st.init_state(
            str(self.state_path),
            project="demo-project",
            slug="demo-task",
            title="Demo task",
            kit_root="/tmp/kit",
            targets=["/tmp/kit"],
            at=AT,
        )
        self.assertEqual(
            doc.task.journal,
            str(self.state_path.parent / "checkpoint.md").replace("\\", "/"),
        )

    def test_init_writes_a_file_read_state_and_state_lint_accept(self):
        doc = st.init_state(
            str(self.state_path),
            project="demo-project",
            slug="demo-task",
            title="Demo task",
            kit_root="/tmp/kit",
            targets=["/tmp/kit"],
            at=AT,
        )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        st.write_state(self.state_path, doc)

        reread = st.read_state(self.state_path)
        self.assertEqual(reread.task.slug, "demo-task")
        self.assertEqual(reread.assignments, [])

        from scripts import state_lint

        results = state_lint.lint_file(self.state_path)
        for name, errors in results.items():
            self.assertEqual(errors, [], f"{name}: {errors}")

    def test_init_refuses_to_overwrite_existing_file(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("not a real state.toml", encoding="utf-8")
        with self.assertRaises(StateError):
            st.init_state(
                str(self.state_path),
                project="demo-project",
                slug="demo-task",
                title="Demo task",
                kit_root="/tmp/kit",
                targets=["/tmp/kit"],
                at=AT,
            )
        # Refusal must not touch the pre-existing content.
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "not a real state.toml")

    def test_init_rejects_invalid_project_slug(self):
        with self.assertRaises(StateError):
            st.init_state(
                str(self.state_path),
                project="Not Valid",
                slug="demo-task",
                title="Demo task",
                kit_root="/tmp/kit",
                targets=["/tmp/kit"],
                at=AT,
            )

    def test_init_rejects_invalid_slug(self):
        with self.assertRaises(StateError):
            st.init_state(
                str(self.state_path),
                project="demo-project",
                slug="Not Valid",
                title="Demo task",
                kit_root="/tmp/kit",
                targets=["/tmp/kit"],
                at=AT,
            )

    def test_init_cli_end_to_end(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_cli.main(
                [
                    "init",
                    "--state", str(self.state_path),
                    "--project", "demo-project",
                    "--slug", "demo-task",
                    "--title", "Demo task",
                    "--kit-root", "/tmp/kit",
                    "--target", "/tmp/kit",
                    "--at", "2026-01-01T10:00:00+00:00",
                ]
            )
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertIn("demo-project", buf.getvalue())

        doc = st.read_state(self.state_path)
        self.assertEqual(doc.task.slug, "demo-task")
        self.assertEqual(doc.task.next_nn, 1)

    def test_init_cli_refuses_existing_file_with_nonzero_exit(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("existing", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_cli.main(
                [
                    "init",
                    "--state", str(self.state_path),
                    "--project", "demo-project",
                    "--slug", "demo-task",
                    "--title", "Demo task",
                    "--kit-root", "/tmp/kit",
                    "--target", "/tmp/kit",
                ]
            )
        self.assertNotEqual(rc, 0)

    def test_init_then_add_then_set_full_chain(self):
        state_cli.main(
            [
                "init",
                "--state", str(self.state_path),
                "--project", "demo-project",
                "--slug", "demo-task",
                "--title", "Demo task",
                "--kit-root", "/tmp/kit",
                "--target", "/tmp/kit",
                "--at", "2026-01-01T10:00:00+00:00",
            ]
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_cli.main(
                [
                    "add",
                    "--state", str(self.state_path),
                    "--role", "node-backend",
                    "--type", "implementação",
                    "--edge", "inicia",
                    "--predecessor", "0",
                    "--target", "/tmp/kit",
                    "--at", "2026-01-01T10:05:00+00:00",
                ]
            )
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertEqual(buf.getvalue().strip(), "1")

        doc = st.read_state(self.state_path)
        self.assertEqual(doc.get_assignment(1).nn, 1)
        self.assertEqual(doc.get_assignment(1).state, "reserved")


class SetStateTests(unittest.TestCase):
    def setUp(self):
        self.doc = _minimal_doc()
        self.a = st.add_assignment(
            self.doc, role="node-backend", type_="implementação", edge="inicia",
            predecessor=0, targets=["/tmp/kit"], at=AT,
        )

    def test_legal_transition_updates_state_and_appends_event(self):
        st.set_state(self.doc, 1, "prepared", by="preflight", at=AT)
        self.assertEqual(self.a.state, "prepared")
        self.assertEqual(self.a.events[-1].to, "prepared")
        self.assertEqual(self.a.events[-1].from_, "reserved")

    def test_illegal_transition_raises(self):
        with self.assertRaises(StateError):
            st.set_state(self.doc, 1, "accepted", at=AT)

    def test_set_unknown_nn_raises(self):
        with self.assertRaises(StateError):
            st.set_state(self.doc, 99, "prepared", at=AT)


class NextNnTests(unittest.TestCase):
    def test_next_nn_starts_at_one(self):
        doc = _minimal_doc()
        self.assertEqual(st.next_nn(doc), 1)

    def test_next_nn_after_add(self):
        doc = _minimal_doc()
        st.add_assignment(doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0, targets=["/tmp/kit"], at=AT)
        self.assertEqual(st.next_nn(doc), 2)


class CliTests(unittest.TestCase):
    """Exercises the argparse wiring end-to-end against a temp file."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_path = Path(self.tmpdir.name) / "state.toml"
        st.write_state(self.state_path, _minimal_doc())

    def _run(self, argv: list[str]) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_cli.main(argv)
        self.assertEqual(rc, 0, buf.getvalue())
        return buf.getvalue()

    def test_add_then_next_nn_then_set(self):
        out = self._run(
            [
                "add",
                "--state", str(self.state_path),
                "--role", "node-backend",
                "--type", "implementação",
                "--edge", "inicia",
                "--predecessor", "0",
                "--target", "/tmp/kit",
                "--at", "2026-01-01T10:00:00+00:00",
            ]
        )
        self.assertEqual(out.strip(), "1")

        out = self._run(["next-nn", "--state", str(self.state_path)])
        self.assertEqual(out.strip(), "2")

        out = self._run(
            [
                "set", "--state", str(self.state_path), "--nn", "1", "--to", "prepared",
                "--by", "preflight", "--at", "2026-01-01T11:00:00+00:00",
            ]
        )
        self.assertIn("nn=1 -> prepared", out)

        doc = st.read_state(self.state_path)
        self.assertEqual(doc.get_assignment(1).state, "prepared")

    def test_cli_reports_error_with_nonzero_exit(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = state_cli.main(["next-nn", "--state", str(Path(self.tmpdir.name) / "missing.toml")])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
