"""Tests for scripts/marina/progress.py — the read-only model behind `marina watch`.

Graphs are built in memory with scripts.state; templates, transcripts and
history live in temporary directories. Nothing here reads the real
`.agent-state/` or `~/.claude`.
"""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path

import scripts.state as st
from scripts.marina import envelope as env_mod
from scripts.marina import progress as pg

AT = datetime.datetime(2026, 10, 28, 21, 0, 0, tzinfo=datetime.timezone.utc)
API, FRONT = "/abs/api", "/abs/front"
TEMPLATE = "## Objective\n\nDo it.\n\n## Write scope\n\n- `src/a.py`\n- `tests/test_a.py`\n\n## Acceptance criteria\n\n1. Works.\n"
_VALIDATED = ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated")
_PATHS = {
    "working": ("prepared", "launched", "working"),
    "receipt_missing": ("prepared", "launched", "working", "finished", "receipt_missing"),
    "accepted": (*_VALIDATED, "accepted"),
}
EDGE_TYPE = {"inicia": "implementação", "prossegue": "implementação", "encadeia": "implementação",
             "revisa": "revisão", "corrige": "correção"}


def make_env(*, stages=(("java-backend", None),), review="each_stage", max_corrections=1) -> env_mod.Envelope:
    raw_stages = []
    for n, (role, target) in enumerate(stages, 1):
        stage = {"role": role, "handoff": f"stage-{n}-handoff-template.md"}
        if target:
            stage.update(targets=[target], allowlist=[f"Bash(test -d {target})"])
        raw_stages.append(stage)
    targets = sorted({t for _, t in stages if t} | {API})
    return env_mod.parse_envelope({
        "targets": targets, "branches": {t: "feat/x" for t in targets},
        "allowlist": [f"Bash(test -d {t})" for t in targets], "review": review,
        "max_corrections": max_corrections, "max_duration": "2h", "judge_max_calls": 1,
        "on_pass_with_risks": "accept", "stages": raw_stages,
        "approval": {"at": AT, "sha256": "a" * 64},
    })


class Graph:
    def __init__(self, slug: str = "t1"):
        self.doc = st.StateDoc(schema=1, task=st.Task(
            project="demo", slug=slug, title="Demo", phase="implementation", kit_root="/kit",
            targets=[API, FRONT], journal=f".agent-state/demo/tasks/{slug}/checkpoint.md",
            next_nn=1, created_at=AT, updated_at=AT), assignments=[])

    def add(self, role, edge, pred, state="accepted", *, verdict="", targets=None, minutes=(0, 5), by=None,
            type_=None):
        a = st.add_assignment(self.doc, role=role, type_=type_ or EDGE_TYPE[edge], edge=edge, predecessor=pred,
                              targets=targets or [API], allowlist=["Bash(x)"], at=AT)
        for to in _PATHS[state]:
            minute = minutes[0] if to in ("prepared", "launched", "working") else minutes[1]
            who = by or ("launch-claude" if to == "launched" else "status" if to == "finished" else "test")
            st.set_state(self.doc, a.nn, to, by=who, at=AT + datetime.timedelta(minutes=minute))
            if to == "receipt_validated":
                a.receipt_summary = st.ReceiptSummary(status="done", verdict=verdict, profile_ok=True)
        return a.nn


def history(role: str, type_: str, minutes: list[int]) -> st.StateDoc:
    g = Graph(slug="hist")
    for m in minutes:
        g.add(role, "inicia", 0, minutes=(0, m), type_=type_)  # the edge does not matter for durations
    return g.doc


class ExpansionTests(unittest.TestCase):
    def test_expansion_each_stage_two_stages(self):
        env = make_env(stages=(("java-backend", API), ("angular", FRONT)))
        slots = pg.expansion_slots(env)
        self.assertEqual([(s.stage, s.kind, s.role, s.conditional) for s in slots], [
            (1, "writer", "java-backend", False), (1, "review", "reviewer", False),
            (1, "correction", "java-backend", True), (1, "rereview", "reviewer", True),
            (2, "writer", "angular", False), (2, "review", "reviewer", False),
            (2, "correction", "angular", True), (2, "rereview", "reviewer", True),
        ])

    def test_expansion_final(self):
        env = make_env(stages=(("java-backend", None), ("java-backend", None)), review="final")
        self.assertEqual([(s.stage, s.kind) for s in pg.expansion_slots(env)], [
            (1, "writer"), (2, "writer"), (2, "review"), (2, "correction"), (2, "rereview")])

    def test_expansion_without_corrections(self):
        env = make_env(max_corrections=0)
        self.assertEqual([s.kind for s in pg.expansion_slots(env)], ["writer", "review"])


class FillTests(unittest.TestCase):
    def test_fill_and_counts_happy_path(self):
        g = Graph()
        g.add("java-backend", "inicia", 0)
        g.add("reviewer", "revisa", 1, "working")
        slots, extra = pg.fill_slots(g.doc, make_env())
        self.assertEqual(extra, [])
        self.assertEqual([s.node.nn if s.node else None for s in slots], [1, 2, None, None])
        self.assertEqual(pg.counts(slots), (1, 2, 4))

    def test_fail_activates_correction_slots(self):
        g = Graph()
        g.add("java-backend", "inicia", 0)
        g.add("reviewer", "revisa", 1, verdict="FAIL")
        slots, _ = pg.fill_slots(g.doc, make_env())
        self.assertTrue(all(s.active for s in slots))
        self.assertEqual(pg.counts(slots), (2, 4, 4))

    def test_replacement_fills_the_original_slot(self):
        g = Graph()
        g.add("java-backend", "inicia", 0, "receipt_missing")
        g.add("java-backend", "substitui", 1, type_="implementação")
        slots, extra = pg.fill_slots(g.doc, make_env())
        self.assertEqual((slots[0].node.nn, extra), (2, []))
        self.assertEqual(pg.counts(slots)[0], 1)

    def test_node_outside_expansion_is_extra(self):
        g = Graph()
        g.add("java-backend", "inicia", 0)
        g.add("architect", "revisa", 1, type_="análise")
        g.doc.assignments[1].edge = "analisa"
        slots, extra = pg.fill_slots(g.doc, make_env())
        self.assertEqual([a.nn for a in extra], [2])


class EstimateTests(unittest.TestCase):
    def test_duration_stats_uses_observed_pairs_only(self):
        observed = history("java-backend", "implementação", [2, 4, 6, 8, 10])
        manual = Graph(slug="manual")
        for _ in range(5):
            manual.add("java-backend", "inicia", 0, minutes=(0, 90), by="marina")
        stats = pg.duration_stats([observed, manual.doc])
        self.assertEqual(stats[("java-backend", "implementação")], pg.Stats(n=5, p50=360.0, p80=480.0))

    def test_stats_below_min_samples_absent(self):
        self.assertEqual(pg.duration_stats([history("reviewer", "revisão", [1, 2, 3, 4])]), {})

    def test_estimate_remaining_and_over_typical(self):
        stats = {("java-backend", "implementação"): pg.Stats(5, 300.0, 600.0),
                 ("reviewer", "revisão"): pg.Stats(5, 60.0, 120.0)}
        g = Graph()
        g.add("java-backend", "inicia", 0, "working", minutes=(0, 0))
        slots, _ = pg.fill_slots(g.doc, make_env())
        est = pg.estimate(slots, stats, AT + datetime.timedelta(minutes=2))
        self.assertEqual((est.low, est.high, est.over_typical, est.missing), (240.0, 600.0, False, ()))
        late = pg.estimate(slots, stats, AT + datetime.timedelta(minutes=12))
        self.assertEqual((late.low, late.high, late.over_typical), (60.0, 120.0, True))

    def test_estimate_without_base(self):
        g = Graph()
        slots, _ = pg.fill_slots(g.doc, make_env())
        est = pg.estimate(slots, {}, AT)
        self.assertIsNone(est.low)
        self.assertEqual(est.missing, (("java-backend", "implementação"), ("reviewer", "revisão")))

    def test_node_window(self):
        g = Graph()
        g.add("java-backend", "inicia", 0, minutes=(1, 4))
        start, end, elapsed = pg.node_window(g.doc.assignments[0], AT + datetime.timedelta(hours=1))
        self.assertEqual((start, end, elapsed), (AT + datetime.timedelta(minutes=1),
                                                 AT + datetime.timedelta(minutes=4), 180.0))


class IoAndActivityTests(unittest.TestCase):
    def _task_dir(self, tmp: str, template: str = TEMPLATE) -> Path:
        task_dir = Path(tmp) / ".agent-state" / "demo" / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "stage-1-handoff-template.md").write_text(template, encoding="utf-8")
        return task_dir

    def test_stage_io_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = self._task_dir(tmp)
            g = Graph()
            g.add("java-backend", "inicia", 0, "working")
            slots, _ = pg.fill_slots(g.doc, make_env())
            inputs, outputs = pg.stage_io(g.doc, make_env(), slots[0], kit_root=Path(tmp), task_dir=task_dir)
        self.assertTrue(any("01-java-backend-handoff.md" in line for line in inputs), inputs)
        self.assertIn("`src/a.py`", outputs)
        self.assertTrue(any("01-java-backend-receipt.md" in line for line in outputs), outputs)
        self.assertTrue(any("git-after-01.txt" in line for line in outputs), outputs)

    def test_stage_io_from_template_sections(self):
        template = TEMPLATE + "\n## Expected inputs\n\n- schema v2\n\n## Expected outputs\n\n- migration 0042\n"
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = self._task_dir(tmp, template)
            slots = pg.expansion_slots(make_env())
            inputs, outputs = pg.stage_io(Graph().doc, make_env(), slots[0], kit_root=Path(tmp), task_dir=task_dir)
        self.assertEqual((inputs, outputs), (["schema v2"], ["migration 0042"]))

    def test_stage_io_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = self._task_dir(tmp)
            g = Graph()
            g.add("java-backend", "inicia", 0)
            g.add("reviewer", "revisa", 1, "working")
            slots, _ = pg.fill_slots(g.doc, make_env())
            inputs, outputs = pg.stage_io(g.doc, make_env(), slots[1], kit_root=Path(tmp), task_dir=task_dir)
        self.assertTrue(any("01-java-backend-receipt.md" in line for line in inputs), inputs)
        self.assertTrue(any("verdict" in line for line in outputs), outputs)

    def _transcript(self, root: Path, lines: list) -> None:
        folder = root / "-kit"
        folder.mkdir(parents=True)
        with (folder / "abc-123.jsonl").open("w", encoding="utf-8") as fh:
            for line in lines:
                fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")

    def test_last_activity_reads_last_tool_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = lambda name, inp, ts: {"type": "assistant", "timestamp": ts, "message": {"content": [
                {"type": "tool_use", "name": name, "input": inp}]}}
            self._transcript(root, [tool("Read", {"file_path": "/a"}, "2026-10-28T21:00:00Z"),
                                    tool("Bash", {"command": "python3 -m unittest discover -s /abs/api"},
                                         "2026-10-28T21:01:00Z"),
                                    {"type": "user", "message": {"content": "x"}}])
            text, at = pg.last_activity("abc-123", root)
        self.assertEqual(text, "Bash python3 -m unittest discover -s /abs/api")
        self.assertEqual(at, datetime.datetime(2026, 10, 28, 21, 1, tzinfo=datetime.timezone.utc))

    def test_last_activity_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(pg.last_activity("abc-123", root))
            self.assertIsNone(pg.last_activity("", root))
            self._transcript(root, ["not json", {"type": "assistant", "message": {"content": "text"}}])
            self.assertIsNone(pg.last_activity("abc-123", root))


class ViewTests(unittest.TestCase):
    def _fixture(self, tmp: str, *, envelope: bool = True) -> Path:
        kit = Path(tmp) / "kit"
        task_dir = kit / ".agent-state" / "demo" / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "stage-1-handoff-template.md").write_text(TEMPLATE, encoding="utf-8")
        g = Graph()
        g.add("java-backend", "inicia", 0)
        g.add("reviewer", "revisa", 1, "working")
        g.doc.task.kit_root = str(kit)
        if envelope:
            g.doc.envelope = env_mod.envelope_to_raw(make_env())
        st.write_state(task_dir / "state.toml", g.doc)
        return task_dir / "state.toml"

    def _view(self, state_path: Path, *, sessions=None) -> pg.View:
        return pg.build_view(state_path, kit_root=state_path.parents[4], now=AT + datetime.timedelta(minutes=8),
                             sessions=sessions, pid_alive=lambda pid: False, projects_root=state_path.parent,
                             history_docs=[])

    def test_view_without_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            view = self._view(self._fixture(tmp, envelope=False))
            lines = pg.render(view, 100)
        self.assertIn("envelope: nenhum", "\n".join(lines))
        self.assertEqual([a.nn for a in view.extra], [1, 2])

    def test_render_lists_slots_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            view = self._view(self._fixture(tmp), sessions=[])
            text = "\n".join(pg.render(view, 100))
        self.assertIn("1/2", text)
        self.assertIn("1/4", text)
        self.assertIn("java-backend", text)
        self.assertIn("reviewer", text)
        self.assertIn("sem base", text)
        self.assertIn("só se FAIL", text)
        self.assertIn("02-reviewer-receipt.md", text)

    def test_render_finished_round_has_nothing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = self._fixture(tmp)
            doc = st.read_state(state_path)
            for to in ("finished", "receipt_received", "receipt_validated"):
                st.set_state(doc, 2, to, by="test", at=AT)
            doc.get_assignment(2).receipt_summary = st.ReceiptSummary(status="done", verdict="PASS", profile_ok=True)
            st.set_state(doc, 2, "accepted", by="test", at=AT)
            st.write_state(state_path, doc)
            text = "\n".join(pg.render(self._view(state_path, sessions=[]), 100))
        self.assertIn("nada pendente", text)
        self.assertNotIn("fim provável", text)

    def test_render_manager_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "\n".join(pg.render(self._view(self._fixture(tmp), sessions=None), 100))
        self.assertIn("manager indisponível", text)

    def test_render_respects_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            view = self._view(self._fixture(tmp), sessions=[])
            for width in (40, 59, 100):
                with self.subTest(width=width):
                    self.assertTrue(all(len(line) <= width for line in pg.render(view, width)))


if __name__ == "__main__":
    unittest.main()
