"""Tests for scripts/marina/handoff_gen.py — canonical handoffs from stage templates.

Every rendered handoff must pass `handoff_sync.validate_handoff` (the same
check preflight and launch_claude apply), so the runner never opens a node
whose handoff the existing tooling would refuse. In-memory state only.
"""

from __future__ import annotations

import datetime
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

    def test_synchronize_changes_nothing(self):
        text = handoff_gen.render_stage_handoff(self.doc, self.writer, kit_root=KIT_ROOT, template_text=TEMPLATE)
        self.assertEqual(handoff_sync.synchronize(text, self.writer, KIT_ROOT), (text, []))


if __name__ == "__main__":
    unittest.main()
