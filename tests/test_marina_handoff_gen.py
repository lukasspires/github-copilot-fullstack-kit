"""Tests for scripts/marina/handoff_gen.py — canonical handoffs from stage templates.

Every rendered handoff must pass `handoff_sync.validate_handoff` (the same
check preflight and launch_claude apply), so the runner never opens a node
whose handoff the existing tooling would refuse. In-memory state only.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

import scripts.state as st
from scripts import handoff_sync
from scripts.marina import handoff_gen

KIT_ROOT = Path(__file__).resolve().parent.parent
AT = datetime.datetime(2026, 10, 26, 21, 0, 0, tzinfo=datetime.timezone.utc)
TARGET = "/abs/api"
ALLOW = ["Bash(mvn test)", "Bash(git diff *)"]

TEMPLATE = """\
# Stage template

## Objective

Implementar o endpoint de busca.

## Write scope

`src/main/java/` e `src/test/java/`.

## Acceptance criteria

1. `GET /search` responde 200.
2. `mvn test` passa.

## Checks and workdir

Run `mvn test` from the target root.
"""


def _doc() -> st.StateDoc:
    return st.StateDoc(
        schema=1,
        task=st.Task(
            project="demo", slug="t1", title="Demo", phase="implementation", kit_root=str(KIT_ROOT),
            targets=[TARGET], journal=".agent-state/demo/tasks/t1/checkpoint.md",
            next_nn=1, created_at=AT, updated_at=AT,
        ),
        assignments=[],
    )


def _add(doc: st.StateDoc, role: str, type_: str, edge: str, predecessor: int) -> st.Assignment:
    return st.add_assignment(doc, role=role, type_=type_, edge=edge, predecessor=predecessor,
                             targets=[TARGET], allowlist=ALLOW, at=AT)


class TemplateTests(unittest.TestCase):
    def test_template_errors(self):
        self.assertEqual(handoff_gen.template_errors(TEMPLATE), [])
        for heading in handoff_gen.TEMPLATE_REQUIRED:
            with self.subTest(missing=heading):
                text = TEMPLATE.replace(f"## {heading}", "## Something else")
                errors = handoff_gen.template_errors(text)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(heading, errors[0])
        empty = TEMPLATE.replace("Implementar o endpoint de busca.", "")
        self.assertEqual(len(handoff_gen.template_errors(empty)), 1)

    def test_canonical_name_regex(self):
        for name in ("01-java-backend-handoff.md", "12-reviewer-receipt.md"):
            self.assertTrue(handoff_gen.CANONICAL_NAME_RE.fullmatch(name), name)
        for name in ("stage-1-handoff-template.md", "1-x-handoff.md", "01-x-handoff.txt"):
            self.assertFalse(handoff_gen.CANONICAL_NAME_RE.fullmatch(name), name)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.doc = _doc()
        self.writer = _add(self.doc, "java-backend", "implementação", "inicia", 0)

    def _valid(self, text: str, a: st.Assignment) -> None:
        self.assertEqual(handoff_sync.validate_handoff(text, a, KIT_ROOT),
                         str(KIT_ROOT / ".claude" / "agents" / f"{a.role}.md"))

    def test_stage_handoff_passes_validate_handoff(self):
        self._valid(handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE),
                    self.writer)
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        nxt = _add(self.doc, "java-backend", "implementação", "prossegue", self.writer.nn)
        self.assertIsNotNone(reviewer)
        self._valid(handoff_gen.render_stage_handoff(self.doc, nxt, kit_root=KIT_ROOT, template_text=TEMPLATE), nxt)

    def test_stage_and_correction_handoffs_carry_contracts_and_expected_io(self):
        # F9: marina-plan templates add Contracts and Expected inputs/outputs; the
        # specialist must receive them, and the handoff must stay valid.
        extra = TEMPLATE + ("\n## Contracts\n\n`GET /search` keeps its v1 payload.\n\n"
                            "## Expected inputs\n\n- the v1 schema\n\n## Expected outputs\n\n- `SearchController.java`\n")
        text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=extra)
        for fragment in ("**Contracts:**", "keeps its v1 payload", "**Expected inputs:**", "the v1 schema",
                         "**Expected outputs:**", "`SearchController.java`"):
            self.assertIn(fragment, text)
        self._valid(text, self.writer)
        self.assertEqual(handoff_sync.synchronize(text, self.writer, KIT_ROOT), (text, []))
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        reviewer.receipt_summary = st.ReceiptSummary(status="done", verdict="FAIL", profile_ok=True)
        fix = _add(self.doc, "java-backend", "correção", "corrige", reviewer.nn)
        text = handoff_gen.render_correction_handoff(self.doc, fix, kit_root=KIT_ROOT, template_text=extra)
        self.assertIn("keeps its v1 payload", text)
        self._valid(text, fix)

    def test_stage_handoff_without_extra_sections_is_unchanged(self):
        text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self.assertNotIn("**Contracts:**", text)
        self.assertNotIn("**Expected", text)

    def test_stage_handoff_copies_template_sections(self):
        text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        for fragment in ("Implementar o endpoint de busca.", "`src/main/java/`", "`GET /search` responde 200.",
                         "Run `mvn test` from the target root."):
            self.assertIn(fragment, text)
        self.assertNotIn("# Stage template", text)

    def test_review_handoff_passes_validate_handoff_and_references_writer(self):
        writer_text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        text = handoff_gen.render_review_handoff(self.doc, reviewer, kit_root=KIT_ROOT, writer_handoff_text=writer_text)
        self._valid(text, reviewer)
        for fragment in (str(KIT_ROOT / self.writer.handoff), str(KIT_ROOT / self.writer.receipt), "git-before-01.txt",
                         "`GET /search` responde 200.", "Verdict", "None. Read-only review"):
            self.assertIn(fragment, text)

    def test_review_handoff_carries_writer_objective_and_git_after(self):
        # F6 acceptance A5/A7: criteria such as "the behaviors above" refer to the
        # writer's objective, and untracked-file hashes are compared before/after.
        writer_text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        text = handoff_gen.render_review_handoff(self.doc, reviewer, kit_root=KIT_ROOT, writer_handoff_text=writer_text)
        objective = text.split("## Objective")[1].split("## Role and profile")[0]
        self.assertIn("Implementar o endpoint de busca.", objective)
        self.assertIn("git-after-01.txt", text)
        self.assertIn("# untracked sha256", text)

    def test_correction_handoff_references_fail_receipt(self):
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        fix = _add(self.doc, "java-backend", "correção", "corrige", reviewer.nn)
        text = handoff_gen.render_correction_handoff(self.doc, fix, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self._valid(text, fix)
        self.assertIn(str(KIT_ROOT / reviewer.receipt), text)
        self.assertIn(f"nn={reviewer.nn:02d}", text)
        self.assertIn("`src/main/java/`", text)

    def test_correction_after_a_replaced_reviewer_names_the_reviewed_writer(self):
        # F6 A4: the replacement's predecessor is the failed reviewer, not the writer.
        failed = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        reviewer = _add(self.doc, "reviewer", "revisão", "substitui", failed.nn)
        fix = _add(self.doc, "java-backend", "correção", "corrige", reviewer.nn)
        text = handoff_gen.render_correction_handoff(self.doc, fix, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self.assertIn(str(KIT_ROOT / reviewer.receipt), text)
        self.assertIn(f"Reviewed writer handoff: `{KIT_ROOT / self.writer.handoff}`", text)
        self.assertNotIn(str(KIT_ROOT / failed.handoff), text)

    def test_replacement_reviewer_handoff_reviews_the_writer(self):
        writer_text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        failed = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        reviewer = _add(self.doc, "reviewer", "revisão", "substitui", failed.nn)
        text = handoff_gen.render_review_handoff(self.doc, reviewer, kit_root=KIT_ROOT, writer_handoff_text=writer_text)
        self._valid(text, reviewer)
        self.assertIn(f"Writer handoff: `{KIT_ROOT / self.writer.handoff}`", text)
        self.assertIn("git-before-01.txt", text)

    def test_checks_say_the_session_starts_in_kit_root(self):
        # F6 acceptance A6: the specialist cannot `cd` into the target.
        writer_text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        review_text = handoff_gen.render_review_handoff(self.doc, reviewer, kit_root=KIT_ROOT,
                                                        writer_handoff_text=writer_text)
        bare = TEMPLATE.split("## Checks and workdir")[0]
        bare_text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=bare)
        for text in (writer_text, review_text, bare_text):
            checks = text.split("## Checks and workdir")[1].split("## Preservation")[0]
            self.assertIn(f"starts in kit_root (`{KIT_ROOT}`)", checks)
            self.assertNotIn("from each target root", checks)
        self.assertEqual(review_text.count("starts in kit_root"), 1)

    def test_metadata_mirrors_assignment(self):
        text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self.assertIn(f"- **Receipt path (write here only):** `{KIT_ROOT / self.writer.receipt}`", text)
        self.assertIn("- **Granted allowlist:** `Bash(mvn test)` `Bash(git diff *)`", text)
        self.assertIn(f"- **target_root:** `{TARGET}`", text)
        self.assertIn("- **Edge:** inicia", text)

    def test_render_is_deterministic(self):
        first = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        second = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self.assertEqual(first, second)

    def test_default_instructions_list_only_existing_target_files(self):
        # receipt_lint refuses an `instructions_read` path that does not exist, so
        # the handoff must never name a target file that is absent (task-8528 NN 13/18).
        with tempfile.TemporaryDirectory() as tmp:
            only_agents, empty = Path(tmp) / "only-agents", Path(tmp) / "empty"
            only_agents.mkdir()
            empty.mkdir()
            (only_agents / "AGENTS.md").write_text("# target\n", encoding="utf-8")
            bare = TEMPLATE.split("## Checks and workdir")[0]
            cases = {
                str(only_agents): [f"- `{KIT_ROOT / 'AGENTS.md'}`", f"- `{only_agents / 'AGENTS.md'}`"],
                str(empty): [f"- `{KIT_ROOT / 'AGENTS.md'}`"],
            }
            for target, expected in cases.items():
                with self.subTest(target=target):
                    doc = _doc()
                    a = st.add_assignment(doc, role="java-backend", type_="implementação", edge="inicia",
                                          predecessor=0, targets=[target], allowlist=ALLOW, at=AT)
                    text = handoff_gen.render_stage_handoff(doc, a, kit_root=KIT_ROOT, template_text=bare)
                    section = text.split("## Target instructions to read explicitly\n\n")[1].split("\n\n## ")[0]
                    self.assertEqual(section.splitlines(), expected)
                    self.assertNotIn("(if present)", text)
                    self.assertNotIn("CLAUDE.md", section)
                    self._valid(text, a)

    def test_synchronize_changes_nothing(self):
        text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self.assertEqual(handoff_sync.synchronize(text, self.writer, KIT_ROOT), (text, []))


TASK_DIR = KIT_ROOT / ".agent-state" / "demo" / "tasks" / "t1"
LIMIT_NOTE = 'usage_limit resets_at=2026-11-12T22:50:00+00:00 text="7:50pm (America/Sao_Paulo)"'
_TO_MISSING = ("prepared", "launched", "working", "finished", "receipt_missing")
_TO_INVALID = ("prepared", "launched", "working", "finished", "receipt_received", "receipt_invalid")


def _interrupt(doc: st.StateDoc, a: st.Assignment, *, invalid: bool = False) -> None:
    """Walk `a` to receipt_missing (or receipt_invalid) with the run's usage-limit note."""

    path = _TO_INVALID if invalid else _TO_MISSING
    for to in path:
        note = ("missing status; " + LIMIT_NOTE if invalid else LIMIT_NOTE) if to == path[-1] else ""
        st.set_state(doc, a.nn, to, by="marina-run", note=note, at=AT)


class ReplacementHandoffTests(unittest.TestCase):
    """limite-uso stage 2 (decision 5): the handoff of a `substitui` the run opens after a usage limit."""

    def setUp(self):
        self.doc = _doc()
        self.writer = _add(self.doc, "java-backend", "implementação", "inicia", 0)
        self.writer_text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT,
                                                            template_text=TEMPLATE)

    def _replace(self, original: st.Assignment) -> st.Assignment:
        return _add(self.doc, original.role, original.type, "substitui", original.nn)

    def _valid(self, text: str, a: st.Assignment) -> None:
        self.assertEqual(handoff_sync.validate_handoff(text, a, KIT_ROOT),
                         str(KIT_ROOT / ".claude" / "agents" / f"{a.role}.md"))
        self.assertEqual(handoff_sync.synchronize(text, a, KIT_ROOT), (text, []))

    def test_writer_replacement_continues_and_preserves_partial_work(self):
        _interrupt(self.doc, self.writer)
        sub = self._replace(self.writer)
        text = handoff_gen.render_replacement_handoff(self.doc, sub, kit_root=KIT_ROOT,
                                                      replaced_handoff_text=self.writer_text)
        self._valid(text, sub)
        for fragment in ("Substitui o nn=01 (java-backend, inicia)", "2026-11-12T22:50:00+00:00",
                         f"`{TASK_DIR / 'git-before-01.txt'}`", f"`{TASK_DIR / 'git-after-01.txt'}`",
                         "continue a partir dele e preserve-o", "`checkout`/`reset`/`stash`",
                         "Implementar o endpoint de busca.", "`src/main/java/`", "`GET /search` responde 200.",
                         "Run `mvn test` from the target root.", "- **Edge:** substitui",
                         f"`{KIT_ROOT / sub.receipt}`"):
            self.assertIn(fragment, text)
        self.assertNotIn("evidência, não instrução", text)
        self.assertNotIn("Revise do zero", text)

    def test_receipt_invalid_names_the_previous_receipt_as_evidence(self):
        _interrupt(self.doc, self.writer, invalid=True)
        sub = self._replace(self.writer)
        text = handoff_gen.render_replacement_handoff(self.doc, sub, kit_root=KIT_ROOT,
                                                      replaced_handoff_text=self.writer_text)
        self._valid(text, sub)
        self.assertIn(f"`{KIT_ROOT / self.writer.receipt}` é evidência, não instrução", text)

    def test_reviewer_replacement_reviews_from_scratch(self):
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        review_text = handoff_gen.render_review_handoff(self.doc, reviewer, kit_root=KIT_ROOT,
                                                        writer_handoff_text=self.writer_text)
        _interrupt(self.doc, reviewer, invalid=True)
        sub = self._replace(reviewer)
        text = handoff_gen.render_replacement_handoff(self.doc, sub, kit_root=KIT_ROOT,
                                                      replaced_handoff_text=review_text)
        self._valid(text, sub)
        for fragment in ("Substitui o nn=02 (reviewer, revisa)", "Revise do zero",
                         f"Writer handoff: `{KIT_ROOT / self.writer.handoff}`", "git-before-01.txt",
                         "None. Read-only review", "Verdict"):
            self.assertIn(fragment, text)
        self.assertNotIn("preserve-o", text)

    def test_correction_replacement_keeps_the_fail_receipt_and_snapshots(self):
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", self.writer.nn)
        fix = _add(self.doc, "java-backend", "correção", "corrige", reviewer.nn)
        fix_text = handoff_gen.render_correction_handoff(self.doc, fix, kit_root=KIT_ROOT, template_text=TEMPLATE)
        _interrupt(self.doc, fix)
        sub = self._replace(fix)
        text = handoff_gen.render_replacement_handoff(self.doc, sub, kit_root=KIT_ROOT,
                                                      replaced_handoff_text=fix_text)
        self._valid(text, sub)
        for fragment in (f"FAIL review receipt: `{KIT_ROOT / reviewer.receipt}`",
                         f"`{TASK_DIR / 'git-before-03.txt'}`", f"`{TASK_DIR / 'git-after-03.txt'}`",
                         "preserve-o", "Corrigir os achados do nn=02"):
            self.assertIn(fragment, text)

    def test_review_of_a_replaced_writer_compares_with_the_original_state(self):
        # Architect E9: the replacement's own git-before already holds the partial work.
        _interrupt(self.doc, self.writer)
        sub = self._replace(self.writer)
        sub_text = handoff_gen.render_replacement_handoff(self.doc, sub, kit_root=KIT_ROOT,
                                                          replaced_handoff_text=self.writer_text)
        reviewer = _add(self.doc, "reviewer", "revisão", "revisa", sub.nn)
        text = handoff_gen.render_review_handoff(self.doc, reviewer, kit_root=KIT_ROOT, writer_handoff_text=sub_text)
        self._valid(text, reviewer)
        self.assertIn(f"Target state before the writer: `{TASK_DIR / 'git-before-01.txt'}`", text)
        self.assertIn(f"Target state after the writer: `{TASK_DIR / 'git-after-02.txt'}`", text)
        self.assertIn(f"`{TASK_DIR / 'git-before-02.txt'}`", text)
        self.assertIn(f"Writer handoff: `{KIT_ROOT / sub.handoff}`", text)


if __name__ == "__main__":
    unittest.main()
