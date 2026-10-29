"""Tests for scripts/marina/envelope.py — parse, validation, hash, approve.

Every test builds its task directory (state.toml + handoffs) in a
temporary directory; the real kit root is read only for its
`.claude/agents/` profiles. TTY, stdin and clock are injected; nothing
here touches the real `.agent-state/` or the Claude CLI.
"""

from __future__ import annotations

import copy
import datetime
import io
import os
import tempfile
import unittest
from pathlib import Path

from scripts import state
from scripts.marina import envelope as env_mod
from scripts.marina.envelope import EnvelopeError

KIT_ROOT = Path(__file__).resolve().parent.parent
TZ = datetime.timezone(datetime.timedelta(hours=-3))
NOW = datetime.datetime(2026, 10, 26, 21, 0, 0, tzinfo=TZ)
TARGET = "/abs/api"
HANDOFF = "stage-1-handoff-template.md"
TEMPLATE = "## Objective\n\nDo it.\n\n## Write scope\n\n`src/`\n\n## Acceptance criteria\n\n1. Works.\n"


def raw_envelope(**overrides) -> dict:
    raw = {
        "targets": [TARGET],
        "branches": {TARGET: "feat/x"},
        "allowlist": [f"Bash(mvn -f {TARGET}/pom.xml test)"],
        "review": "each_stage",
        "max_corrections": 1,
        "max_duration": "8h",
        "judge_max_calls": 4,
        "on_pass_with_risks": "judge",
        "stages": [{"role": "java-backend", "handoff": HANDOFF}],
    }
    raw.update(overrides)
    return raw


class TaskFixture:
    """A temporary task directory with state.toml and one handoff."""

    def __init__(self, tmp: str, *, envelope: dict | None = None, slug: str = "t1", targets: list[str] | None = None):
        self.task_dir = Path(tmp) / ".agent-state" / "demo" / "tasks" / slug
        self.task_dir.mkdir(parents=True)
        self.state_path = self.task_dir / "state.toml"
        (self.task_dir / HANDOFF).write_text(TEMPLATE, encoding="utf-8")
        doc = state.init_state(
            self.state_path, project="demo", slug=slug, title="Demo task", kit_root=str(KIT_ROOT),
            targets=targets or [TARGET], at=NOW,
        )
        doc.envelope = envelope
        state.write_state(self.state_path, doc)

    def doc(self) -> state.StateDoc:
        return state.read_state(self.state_path)


class ParseTests(unittest.TestCase):
    def test_parse_round_trip(self):
        raw = raw_envelope(approval={"at": NOW, "sha256": "a" * 64})
        env = env_mod.parse_envelope(raw)
        self.assertEqual(env_mod.parse_envelope(env_mod.envelope_to_raw(env)), env)
        self.assertEqual(env_mod.envelope_to_raw(env), raw)

    def test_parse_without_approval(self):
        env = env_mod.parse_envelope(raw_envelope())
        self.assertIsNone(env.approval)
        self.assertNotIn("approval", env_mod.envelope_to_raw(env))

    def test_unknown_key_refused(self):
        with self.assertRaisesRegex(EnvelopeError, "surprise"):
            env_mod.parse_envelope(raw_envelope(surprise=1))

    def test_missing_key_refused(self):
        raw = raw_envelope()
        del raw["review"]
        with self.assertRaisesRegex(EnvelopeError, "review"):
            env_mod.parse_envelope(raw)

    def test_bool_is_not_int(self):
        with self.assertRaisesRegex(EnvelopeError, "max_corrections"):
            env_mod.parse_envelope(raw_envelope(max_corrections=True))

    def test_wrong_types_refused(self):
        for key, value in (("targets", "/abs/api"), ("branches", ["x"]), ("allowlist", "Bash(x)"),
                           ("stages", {"role": "x"}), ("max_duration", 8)):
            with self.subTest(key=key), self.assertRaisesRegex(EnvelopeError, key):
                env_mod.parse_envelope(raw_envelope(**{key: value}))

    def test_bad_stage_refused(self):
        with self.assertRaisesRegex(EnvelopeError, "stages"):
            env_mod.parse_envelope(raw_envelope(stages=[{"role": "java-backend"}]))

    def test_bad_approval_refused(self):
        naive = NOW.replace(tzinfo=None)
        for approval in ({"at": naive, "sha256": "a" * 64}, {"at": NOW, "sha256": "xyz"}, {"at": NOW},
                         {"at": NOW, "sha256": "a" * 64 + "\n"}):
            with self.subTest(approval=approval), self.assertRaisesRegex(EnvelopeError, "approval"):
                env_mod.parse_envelope(raw_envelope(approval=approval))

    def test_parse_duration(self):
        self.assertEqual(env_mod.parse_duration("8h"), 28800)
        self.assertEqual(env_mod.parse_duration("90m"), 5400)
        self.assertEqual(env_mod.parse_duration("30s"), 30)
        for bad in ("0h", "8", "1d", "h", "", "08h", " 8h", "8h\n"):
            with self.subTest(bad=bad), self.assertRaises(EnvelopeError):
                env_mod.parse_duration(bad)

    def test_envelope_from_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(env_mod.envelope_from_doc(TaskFixture(tmp).doc()))
        with tempfile.TemporaryDirectory() as tmp:
            env = env_mod.envelope_from_doc(TaskFixture(tmp, envelope=raw_envelope()).doc())
            self.assertEqual(env.stages[0].role, "java-backend")


class ValidateTests(unittest.TestCase):
    def _errors(self, tmp: str, **overrides) -> list[str]:
        fx = TaskFixture(tmp)
        env = env_mod.parse_envelope(raw_envelope(**overrides))
        return env_mod.validate_envelope(env, doc=fx.doc(), kit_root=KIT_ROOT, task_dir=fx.task_dir)

    def test_valid_envelope_has_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._errors(tmp), [])

    def test_no_stages_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(self._errors(tmp, stages=[])), 1)

    def test_reader_or_unknown_or_marina_role_refused(self):
        for role in ("reviewer", "nope", "marina", "marina-judge"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                errors = self._errors(tmp, stages=[{"role": role, "handoff": HANDOFF}])
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(role, errors[0])

    def test_stages_with_different_roles_accepted_with_each_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            stages = [{"role": "java-backend", "handoff": HANDOFF}, {"role": "angular", "handoff": HANDOFF}]
            self.assertEqual(self._errors(tmp, stages=stages), [])

    def test_multi_role_with_final_review_refused(self):
        # A final FAIL could not tell which role corrects (spec 3.2, decision 2).
        with tempfile.TemporaryDirectory() as tmp:
            stages = [{"role": "java-backend", "handoff": HANDOFF}, {"role": "angular", "handoff": HANDOFF}]
            errors = self._errors(tmp, stages=stages, review="final")
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("each_stage", errors[0])

    def test_canonical_template_name_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            (fx.task_dir / "01-java-backend-handoff.md").write_text(TEMPLATE, encoding="utf-8")
            env = env_mod.parse_envelope(
                raw_envelope(stages=[{"role": "java-backend", "handoff": "01-java-backend-handoff.md"}])
            )
            errors = env_mod.validate_envelope(env, doc=fx.doc(), kit_root=KIT_ROOT, task_dir=fx.task_dir)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("canonical assignment file name", errors[0])

    def test_template_without_sections_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            (fx.task_dir / HANDOFF).write_text("# just a title\n", encoding="utf-8")
            env = env_mod.parse_envelope(raw_envelope())
            errors = env_mod.validate_envelope(env, doc=fx.doc(), kit_root=KIT_ROOT, task_dir=fx.task_dir)
            self.assertEqual(len(errors), 3, errors)
            self.assertTrue(all(HANDOFF in e for e in errors), errors)

    def test_handoff_outside_task_dir_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.md"
            outside.write_text(TEMPLATE, encoding="utf-8")
            fx = TaskFixture(tmp)
            (fx.task_dir / "link.md").symlink_to(outside)
            for handoff in ("../outside.md", str(outside), "link.md", "missing.md"):
                with self.subTest(handoff=handoff):
                    env = env_mod.parse_envelope(raw_envelope(stages=[{"role": "java-backend", "handoff": handoff}]))
                    errors = env_mod.validate_envelope(env, doc=fx.doc(), kit_root=KIT_ROOT, task_dir=fx.task_dir)
                    self.assertEqual(len(errors), 1, errors)
                    self.assertIn(handoff, errors[0])

    def test_target_rules(self):
        cases = (
            {"targets": ["abs/api"], "branches": {"abs/api": "feat/x"}},
            {"targets": ["/abs/api/"], "branches": {"/abs/api/": "feat/x"}},
            {"targets": ["/other"], "branches": {"/other": "feat/x"}},
            {"targets": [TARGET, TARGET], "branches": {TARGET: "feat/x"}},
            {"targets": [], "branches": {}},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                self.assertTrue(self._errors(tmp, **overrides))

    def test_branch_rules(self):
        for branches in ({}, {TARGET: ""}, {TARGET: "feat/x", "/extra": "y"}):
            with self.subTest(branches=branches), tempfile.TemporaryDirectory() as tmp:
                errors = self._errors(tmp, branches=branches)
                self.assertTrue(errors)
                self.assertTrue(any("branch" in e for e in errors), errors)

    def test_allowlist_refusals_reused(self):
        for allowlist, fragment in ((["Bash"], "bare/wildcard"), (["Edit(//x/**)"], "file-write rules"),
                                    ([], "empty")):
            with self.subTest(allowlist=allowlist), tempfile.TemporaryDirectory() as tmp:
                errors = self._errors(tmp, allowlist=allowlist)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(fragment, errors[0])

    def test_allowlist_rules_must_name_a_target(self):
        # F6 acceptance A6: background sessions start in kit_root, so a rule such
        # as `git status --short` inspects the kit, never the target.
        with tempfile.TemporaryDirectory() as tmp:
            errors = self._errors(tmp, allowlist=["Bash(git status --short)", f"Bash(git -C {TARGET} diff *)"])
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'Bash(git status --short)'", errors[0])
        self.assertIn("kit_root", errors[0])

    def test_target_named_only_as_a_whole_path(self):
        errors = env_mod.allowlist_target_errors([f"Bash(git -C {TARGET}2 status --short)"], (TARGET,), KIT_ROOT)
        self.assertEqual(len(errors), 1, errors)
        for rule in (f"Bash(git -C {TARGET} status --short)", f"Bash(python3 -m unittest discover -s {TARGET}/tests *)",
                     f"Bash(mvn -f {TARGET}/pom.xml test)"):
            with self.subTest(rule=rule):
                self.assertEqual(env_mod.allowlist_target_errors([rule], (TARGET,), KIT_ROOT), [])

    def test_relative_rules_allowed_when_the_kit_is_a_target(self):
        rules = ["Bash(git status --short)", "Bash(python3 -m unittest *)"]
        self.assertEqual(env_mod.allowlist_target_errors(rules, (f"{KIT_ROOT}/",), KIT_ROOT), [])

    def test_limits_and_enums(self):
        for overrides in ({"max_corrections": 2}, {"max_corrections": -1}, {"judge_max_calls": -1},
                          {"max_duration": "1d"}, {"review": "never"}, {"on_pass_with_risks": "maybe"}):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                errors = self._errors(tmp, **overrides)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(next(iter(overrides)), errors[0])


FRONT = "/abs/front"
TWO_TARGETS = {"targets": [TARGET, FRONT], "branches": {TARGET: "feat/x", FRONT: "feat/x"}}


def two_stage_raw(**overrides) -> dict:
    raw = raw_envelope(
        **TWO_TARGETS,
        allowlist=[f"Bash(git -C {TARGET} diff *)", f"Bash(git -C {FRONT} diff *)"],
        stages=[
            {"role": "java-backend", "handoff": HANDOFF, "targets": [TARGET],
             "allowlist": [f"Bash(mvn -f {TARGET}/pom.xml test)"]},
            {"role": "angular", "handoff": HANDOFF, "targets": [FRONT],
             "allowlist": [f"Bash(npm --prefix {FRONT} test)"]},
        ],
    )
    raw.update(overrides)
    return raw


class StageScopeTests(unittest.TestCase):
    def _errors(self, tmp: str, raw: dict) -> list[str]:
        fx = TaskFixture(tmp, targets=[TARGET, FRONT])
        env = env_mod.parse_envelope(raw)
        return env_mod.validate_envelope(env, doc=fx.doc(), kit_root=KIT_ROOT, task_dir=fx.task_dir)

    def _with_stage(self, index: int, **stage_overrides) -> dict:
        raw = two_stage_raw()
        raw["stages"][index].update(stage_overrides)
        return raw

    def test_stage_scope_round_trip(self):
        raw = two_stage_raw()
        env = env_mod.parse_envelope(raw)
        self.assertEqual(env.stages[1].targets, (FRONT,))
        self.assertEqual(env_mod.envelope_to_raw(env), raw)

    def test_hash_unchanged_for_stage_without_scope(self):
        # Envelopes approved before F7 must keep their hash.
        env = env_mod.parse_envelope(raw_envelope())
        self.assertEqual(set(env_mod.envelope_to_raw(env)["stages"][0]), {"role", "handoff"})

    def test_bad_stage_scope_refused(self):
        for stage in ({"role": "java-backend", "handoff": HANDOFF, "targets": TARGET},
                      {"role": "java-backend", "handoff": HANDOFF, "allowlist": [1]},
                      {"role": "java-backend", "handoff": HANDOFF, "surprise": []}):
            with self.subTest(stage=stage), self.assertRaisesRegex(EnvelopeError, "stages"):
                env_mod.parse_envelope(raw_envelope(stages=[stage]))

    def test_valid_two_stage_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._errors(tmp, two_stage_raw()), [])

    def test_stage_targets_must_be_envelope_targets(self):
        for targets, fragment in ((["/abs/elsewhere"], "not one of the envelope's targets"), ([], "at least one"),
                                  ([TARGET, TARGET], "duplicates")):
            with self.subTest(targets=targets), tempfile.TemporaryDirectory() as tmp:
                errors = self._errors(tmp, self._with_stage(0, targets=targets))
                self.assertTrue(any(fragment in e for e in errors), errors)

    def test_stage_allowlist_must_name_a_stage_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = self._errors(tmp, self._with_stage(0, allowlist=[f"Bash(npm --prefix {FRONT} test)"]))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("stages[0]", errors[0])
        self.assertIn("names no target", errors[0])

    def test_stage_allowlist_forbidden_rules_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = self._errors(tmp, self._with_stage(1, allowlist=[f"Edit(/{FRONT}/**)"]))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("stages[1]", errors[0])

    def test_stage_scope_and_node_scope(self):
        env = env_mod.parse_envelope(two_stage_raw())
        self.assertEqual(env_mod.stage_targets(env, 2), (FRONT,))
        self.assertEqual(env_mod.stage_allowlist(env, 1), (f"Bash(mvn -f {TARGET}/pom.xml test)",))
        stage2 = ((FRONT,), (f"Bash(npm --prefix {FRONT} test)",))
        for edge in ("inicia", "prossegue", "encadeia", "revisa", "corrige"):
            with self.subTest(edge=edge):
                self.assertEqual(env_mod.node_scope(env, 2, edge), stage2)
        final = env_mod.parse_envelope(raw_envelope())
        whole = ((TARGET,), (f"Bash(mvn -f {TARGET}/pom.xml test)",))
        self.assertEqual(env_mod.node_scope(final, 1, "inicia"), whole)

    def test_final_review_uses_the_envelope_scope(self):
        raw = two_stage_raw(review="final")
        for stage in raw["stages"]:
            stage["role"] = "java-backend"
        env = env_mod.parse_envelope(raw)
        whole = ((TARGET, FRONT), tuple(raw["allowlist"]))
        self.assertEqual(env_mod.node_scope(env, 2, "revisa"), whole)
        self.assertEqual(env_mod.node_scope(env, 2, "corrige"), whole)
        self.assertEqual(env_mod.node_scope(env, 2, "prossegue")[0], (FRONT,))

    def test_summary_lists_stage_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, targets=[TARGET, FRONT])
            env = env_mod.parse_envelope(two_stage_raw())
            text = env_mod.format_summary(env, fx.doc(), "c" * 64)
        self.assertIn(f"targets: {FRONT}", text)
        self.assertIn(f"Bash(npm --prefix {FRONT} test)", text)


class HashTests(unittest.TestCase):
    def _hash(self, fx: TaskFixture, raw: dict) -> str:
        return env_mod.compute_hash(env_mod.parse_envelope(raw), task_dir=fx.task_dir)

    def test_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            first, second = self._hash(fx, raw_envelope()), self._hash(fx, raw_envelope())
            self.assertEqual(first, second)
            self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_hash_ignores_key_order_and_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            raw = raw_envelope()
            reordered = dict(reversed(list(copy.deepcopy(raw).items())))
            approved = raw_envelope(approval={"at": NOW, "sha256": "b" * 64})
            self.assertEqual(self._hash(fx, raw), self._hash(fx, reordered))
            self.assertEqual(self._hash(fx, raw), self._hash(fx, approved))

    def test_hash_changes_when_handoff_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            before = self._hash(fx, raw_envelope())
            with (fx.task_dir / HANDOFF).open("a", encoding="utf-8") as fh:
                fh.write(" ")
            self.assertNotEqual(before, self._hash(fx, raw_envelope()))

    def test_hash_changes_when_allowlist_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            self.assertNotEqual(
                self._hash(fx, raw_envelope()), self._hash(fx, raw_envelope(allowlist=["Bash(mvn verify)"]))
            )


class ApproveTests(unittest.TestCase):
    def _approve(self, fx: TaskFixture, stdin_text: str, *, tty: bool = True) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = env_mod.approve(
            fx.state_path, kit_root=KIT_ROOT, stdin=io.StringIO(stdin_text), stdout=out, stderr=err,
            isatty=lambda: tty, now=lambda: NOW,
        )
        return code, out.getvalue(), err.getvalue()

    def test_approve_writes_approval_with_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            code, out, _ = self._approve(fx, "t1\n")
            self.assertEqual(code, 0)
            env = env_mod.envelope_from_doc(fx.doc())
            self.assertEqual(env.approval.sha256, env_mod.compute_hash(env, task_dir=fx.task_dir))
            self.assertEqual(env.approval.at, NOW)
            self.assertEqual(fx.doc().task.updated_at, NOW)
            self.assertIn(f"approved t1 sha256={env.approval.sha256}", out)

    def test_approve_refuses_without_tty_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            before = fx.state_path.read_bytes()
            code, out, err = self._approve(fx, "t1\n", tty=False)
            self.assertEqual(code, 1)
            self.assertIn("requires an interactive terminal", err)
            self.assertEqual(out, "")
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_wrong_slug_writes_nothing(self):
        for stdin_text in ("outro\n", "", "T1\n"):
            with self.subTest(stdin=stdin_text), tempfile.TemporaryDirectory() as tmp:
                fx = TaskFixture(tmp, envelope=raw_envelope())
                before = fx.state_path.read_bytes()
                code, _, err = self._approve(fx, stdin_text)
                self.assertEqual(code, 1)
                self.assertIn("not approved", err)
                self.assertEqual(fx.state_path.read_bytes(), before)

    def test_slug_with_surrounding_spaces_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            self.assertEqual(self._approve(fx, "  t1  \n")[0], 0)

    def test_invalid_envelope_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope(max_corrections=2))
            before = fx.state_path.read_bytes()
            code, _, err = self._approve(fx, "t1\n")
            self.assertEqual(code, 1)
            self.assertIn("max_corrections", err)
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_malformed_envelope_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope(surprise=1))
            code, _, err = self._approve(fx, "t1\n")
            self.assertEqual(code, 1)
            self.assertIn("surprise", err)

    def test_no_envelope_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp)
            code, _, err = self._approve(fx, "t1\n")
            self.assertEqual(code, 1)
            self.assertIn("no [envelope]", err)

    def test_summary_lists_every_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope(allowlist=[f"Bash(mvn -f {TARGET}/pom.xml test)", f"Bash(mvn -f {TARGET}/pom.xml verify)"]))
            _, out, _ = self._approve(fx, "no\n")
            for fragment in ("t1 — Demo task", f"1. java-backend — {HANDOFF}", "same allowlist", TARGET, "feat/x",
                             f"Bash(mvn -f {TARGET}/pom.xml test)", f"Bash(mvn -f {TARGET}/pom.xml verify)", "each_stage", "max_corrections: 1", "8h",
                             "judge_max_calls: 4", "on_pass_with_risks: judge", "sha256: ",
                             "Type the task slug (t1) to approve: "):
                self.assertIn(fragment, out)

    def test_concurrent_state_change_during_prompt_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())

            class WriterStdin(io.StringIO):
                def readline(self_inner):
                    doc = state.read_state(fx.state_path)
                    state.add_assignment(
                        doc, role="java-backend", type_="implementação", edge="inicia", predecessor=0,
                        targets=[TARGET], at=NOW,
                    )
                    state.write_state(fx.state_path, doc)
                    return "t1\n"

            out, err = io.StringIO(), io.StringIO()
            code = env_mod.approve(fx.state_path, kit_root=KIT_ROOT, stdin=WriterStdin(), stdout=out, stderr=err,
                                   isatty=lambda: True, now=lambda: NOW)
            self.assertEqual(code, 0, err.getvalue())
            doc = fx.doc()
            self.assertEqual([a.nn for a in doc.assignments], [1])
            self.assertIsNotNone(env_mod.envelope_from_doc(doc).approval)

    def test_handoff_changed_during_prompt_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            before = fx.state_path.read_bytes()

            class EditingStdin(io.StringIO):
                def readline(self_inner):
                    (fx.task_dir / HANDOFF).write_text("# edited\n", encoding="utf-8")
                    return "t1\n"

            out, err = io.StringIO(), io.StringIO()
            code = env_mod.approve(fx.state_path, kit_root=KIT_ROOT, stdin=EditingStdin(), stdout=out, stderr=err,
                                   isatty=lambda: True, now=lambda: NOW)
            self.assertEqual(code, 1)
            self.assertIn("changed while waiting", err.getvalue())
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_envelope_changed_during_prompt_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())

            class EnvelopeStdin(io.StringIO):
                def readline(self_inner):
                    doc = state.read_state(fx.state_path)
                    doc.envelope["allowlist"] = ["Bash(mvn verify)"]
                    state.write_state(fx.state_path, doc)
                    return "t1\n"

            err = io.StringIO()
            code = env_mod.approve(fx.state_path, kit_root=KIT_ROOT, stdin=EnvelopeStdin(), stdout=io.StringIO(),
                                   stderr=err, isatty=lambda: True, now=lambda: NOW)
            self.assertEqual(code, 1)
            self.assertIn("changed while waiting", err.getvalue())
            self.assertIsNone(env_mod.envelope_from_doc(fx.doc()).approval)

    def test_approve_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            self.assertEqual(self._approve(fx, "t1\n")[0], 0)
            self.assertEqual(sorted(p.name for p in fx.task_dir.iterdir()), [HANDOFF, "state.toml"])

    def test_reapprove_reports_previous_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope(approval={"at": NOW, "sha256": "c" * 64}))
            code, out, _ = self._approve(fx, "t1\n")
            self.assertEqual(code, 0)
            self.assertIn("previous approval: " + "c" * 64, out)
            self.assertNotEqual(env_mod.envelope_from_doc(fx.doc()).approval.sha256, "c" * 64)


if __name__ == "__main__":
    unittest.main()


class DispatchTests(unittest.TestCase):
    """F7: running `marina go` on a TTY is the approval of the whole plan."""

    def _dispatch(self, fx: TaskFixture, *, tty: bool = True, sleep=None, grace: float = 10):
        out, err, slept = io.StringIO(), io.StringIO(), []
        code = env_mod.approve_on_dispatch(
            fx.state_path, kit_root=KIT_ROOT, stdout=out, stderr=err, isatty=lambda: tty, now=lambda: NOW,
            sleep=sleep or slept.append, grace=grace,
        )
        return code, out.getvalue(), err.getvalue(), slept

    def test_dispatch_records_approval_after_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            code, out, _, slept = self._dispatch(fx)
            self.assertEqual((code, slept), (0, [10]))
            env = env_mod.envelope_from_doc(fx.doc())
            self.assertEqual(env.approval.sha256, env_mod.compute_hash(env, task_dir=fx.task_dir))
            self.assertEqual(env.approval.at, NOW)
            self.assertIn("stages:", out)
            self.assertIn("Ctrl-C", out)
            self.assertIn(f"approved on dispatch t1 sha256={env.approval.sha256}", out)

    def test_dispatch_refuses_without_tty(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            before = fx.state_path.read_bytes()
            code, out, err, slept = self._dispatch(fx, tty=False)
            self.assertEqual((code, out, slept), (1, "", []))
            self.assertIn("requires an interactive terminal", err)
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_dispatch_interrupt_writes_nothing(self):
        def interrupt(_seconds):
            raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            before = fx.state_path.read_bytes()
            code, _, err, _ = self._dispatch(fx, sleep=interrupt)
            self.assertEqual(code, 1)
            self.assertIn("cancelled", err)
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_dispatch_already_approved_skips_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            self._dispatch(fx)
            before = fx.state_path.read_bytes()
            code, out, _, slept = self._dispatch(fx)
            self.assertEqual((code, slept), (0, []))
            self.assertIn("already approved", out)
            self.assertEqual(fx.state_path.read_bytes(), before)

    def test_dispatch_change_during_grace_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())

            def edit(_seconds):
                (fx.task_dir / HANDOFF).write_text(TEMPLATE + "\nedited\n", encoding="utf-8")

            code, _, err, _ = self._dispatch(fx, sleep=edit)
            self.assertEqual(code, 1)
            self.assertIn("changed while waiting", err)
            self.assertIsNone(env_mod.envelope_from_doc(fx.doc()).approval)

    def test_dispatch_invalid_envelope_refused(self):
        for envelope in (None, raw_envelope(review="never"), {"surprise": 1}):
            with self.subTest(envelope=envelope), tempfile.TemporaryDirectory() as tmp:
                fx = TaskFixture(tmp, envelope=envelope)
                code, _, err, slept = self._dispatch(fx)
                self.assertEqual((code, slept), (1, []))
                self.assertIn("marina go", err)

    def test_dispatch_with_zero_grace_does_not_sleep(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = TaskFixture(tmp, envelope=raw_envelope())
            code, _, _, slept = self._dispatch(fx, grace=0)
            self.assertEqual((code, slept), (0, []))
