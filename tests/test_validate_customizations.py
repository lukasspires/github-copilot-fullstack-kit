"""Behavior tests for the dependency-free customization validator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "validate_customizations.py"
SPEC = importlib.util.spec_from_file_location("validate_customizations", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import bootstrap guard
    raise RuntimeError(f"cannot load validator from {SCRIPT_PATH}")
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def agent_document(
    name: str,
    *,
    tools: str = '["read"]',
    extra: str = "",
    body: str = "Agent instructions.",
) -> str:
    fields = [
        "---",
        f"name: {name}",
        f"description: Agent {name} description.",
        f"tools: {tools}",
    ]
    if extra:
        fields.extend(extra.splitlines())
    fields.extend(["---", "", body, ""])
    return "\n".join(fields)


def prompt_document(name: str, *, agent: str = "") -> str:
    fields = [
        "---",
        f"name: {name}",
        f"description: Prompt {name} description.",
    ]
    if agent:
        fields.append(f"agent: {agent}")
    fields.extend(["---", "", "Prompt instructions.", ""])
    return "\n".join(fields)


def skill_document(name: str, *, description: str = "Skill description.", body: str = "# Steps") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}\n"
    )


def codex_agent_document(name: str, *, sandbox: str) -> str:
    return (
        f'name = "{name}"\n'
        f'description = "Agent {name}."\n'
        f'sandbox_mode = "{sandbox}"\n'
        'developer_instructions = """\n'
        "Never modify files when configured read-only. Follow the task contract.\n"
        '"""\n'
    )


def claude_agent_document(name: str, *, writer: bool) -> str:
    tools = '["Read", "Glob", "Grep", "Edit", "Write"]' if writer else '["Read", "Glob", "Grep"]'
    return agent_document(
        name,
        tools=tools,
        extra="model: inherit\npermissionMode: plan",
    )


class ValidatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / ".github" / "agents").mkdir(parents=True)
        self.write(
            ".github/agents/writer.agent.md",
            agent_document("writer"),
        )
        self.write("AGENTS.md", "# Repository map\n\nAll paths configured.\n")

    def write(self, relative_path: str, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def diagnostics(self, **options: bool) -> list[object]:
        return validator.validate(self.root, **options)

    def codes(self, **options: bool) -> list[str]:
        return [item.code for item in self.diagnostics(**options)]

    def test_valid_repository_has_no_diagnostics(self) -> None:
        self.write(
            ".github/agents/coordinator.agent.md",
            agent_document(
                "coordinator",
                tools='["read", "agent"]',
                extra='agents: ["writer"]',
            ),
        )
        self.write(
            ".github/prompts/run.prompt.md",
            prompt_document("run", agent="writer"),
        )
        self.write(
            ".github/skills/analysis/SKILL.md",
            skill_document("analysis", body="Use [the template](./template.md)."),
        )
        self.write(".github/skills/analysis/template.md", "# Template\n")

        self.assertEqual([], self.diagnostics())

    def test_frontmatter_rejects_duplicate_nested_and_non_scalar_array_forms(self) -> None:
        self.write(
            ".github/agents/invalid.agent.md",
            "---\n"
            "name: invalid\n"
            "name: repeated\n"
            "description: Invalid metadata.\n"
            "tools:\n"
            "  - read\n"
            "agents: [[\"writer\"]]\n"
            "---\n\nInstructions.\n",
        )

        codes = self.codes()

        self.assertIn("FM003", codes)
        self.assertIn("FM004", codes)
        self.assertIn("FM005", codes)
        self.assertIn("FM007", codes)

    def test_frontmatter_requires_delimiters_and_valid_inline_json(self) -> None:
        self.write(
            ".github/prompts/missing-opening.prompt.md",
            "name: missing-opening\ndescription: No delimiter.\n",
        )
        self.write(
            ".github/prompts/missing-closing.prompt.md",
            "---\nname: missing-closing\ndescription: No closing delimiter.\n",
        )
        self.write(
            ".github/agents/invalid-json.agent.md",
            agent_document("invalid-json", tools='["read",]'),
        )
        self.write(
            ".github/prompts/mapping.prompt.md",
            "---\n"
            "name: mapping\n"
            "description: Mapping value.\n"
            "tools: {\"read\": true}\n"
            "---\n\nPrompt.\n",
        )

        codes = self.codes()

        self.assertIn("FM001", codes)
        self.assertIn("FM002", codes)
        self.assertIn("FM006", codes)
        self.assertIn("FM009", codes)

    def test_agent_identifiers_are_unique_case_insensitively(self) -> None:
        self.write(
            ".github/agents/duplicate.agent.md",
            agent_document("WRITER"),
        )

        duplicate = [item for item in self.diagnostics() if item.code == "ID001"]

        self.assertEqual(1, len(duplicate))
        self.assertIn("case", duplicate[0].message.lower())

    def test_plain_markdown_agent_is_discovered_and_resolves_prompt_reference(self) -> None:
        self.write(
            ".github/agents/plain.md",
            agent_document("plain"),
        )
        self.write(
            ".github/prompts/plain.prompt.md",
            prompt_document("plain-prompt", agent="plain"),
        )

        self.assertEqual([], self.diagnostics())

    def test_agent_markdown_files_are_each_parsed_once(self) -> None:
        self.write(".github/agents/plain.md", "Invalid plain agent.\n")
        self.write(".github/agents/traditional.agent.md", "Invalid traditional agent.\n")

        missing_frontmatter = [
            item for item in self.diagnostics() if item.code == "FM001"
        ]

        self.assertEqual(2, len(missing_frontmatter))
        self.assertEqual(
            [
                ".github/agents/plain.md",
                ".github/agents/traditional.agent.md",
            ],
            [item.path for item in missing_frontmatter],
        )

    def test_prompt_and_whitelist_references_require_known_exact_casing(self) -> None:
        self.write(
            ".github/agents/coordinator.agent.md",
            agent_document(
                "coordinator",
                tools='["read", "agent"]',
                extra='agents: ["WRITER", "missing", "writer"]',
            ),
        )
        self.write(
            ".github/prompts/case.prompt.md",
            prompt_document("case", agent="WRITER"),
        )
        self.write(
            ".github/prompts/missing.prompt.md",
            prompt_document("missing", agent="absent"),
        )

        codes = self.codes()

        self.assertGreaterEqual(codes.count("REF001"), 2)
        self.assertGreaterEqual(codes.count("REF002"), 2)
        self.assertIn("REF003", codes)

    def test_prompt_accepts_documented_builtin_agents(self) -> None:
        for builtin in ("ask", "agent", "plan"):
            self.write(
                f".github/prompts/{builtin}.prompt.md",
                prompt_document(f"builtin-{builtin}", agent=builtin),
            )

        references = [
            item for item in self.diagnostics() if item.code.startswith("REF")
        ]

        self.assertEqual([], references)

    def test_whitelist_requires_agent_tool(self) -> None:
        self.write(
            ".github/agents/coordinator.agent.md",
            agent_document(
                "coordinator",
                tools='["read"]',
                extra='agents: ["writer"]',
            ),
        )

        result = next(item for item in self.diagnostics() if item.code == "POL002")

        self.assertEqual(validator.Severity.ERROR, result.severity)

    def test_task_coordinator_requires_delegation_contract(self) -> None:
        self.write(
            ".github/agents/task-coordinator.agent.md",
            agent_document("Renamed coordinator", tools='["read", "search"]'),
        )

        codes = self.codes()

        self.assertIn("POL004", codes)
        self.assertIn("POL005", codes)
        self.assertIn("POL006", codes)

    def test_task_coordinator_requires_compact_receipt_fields(self) -> None:
        receipt = "\n".join(validator.COORDINATOR_RECEIPT_FIELDS)
        self.write(
            ".github/agents/task-coordinator.agent.md",
            agent_document(
                "Renamed coordinator",
                tools='["read", "agent"]',
                extra='agents: ["writer"]',
                body=receipt,
            ),
        )

        policy_codes = [
            item.code for item in self.diagnostics() if item.code.startswith("POL")
        ]

        self.assertNotIn("POL006", policy_codes)

    def test_estimated_tokens_uses_rounded_up_utf8_bytes(self) -> None:
        self.assertEqual(1, validator._estimated_tokens("abcd"))
        self.assertEqual(2, validator._estimated_tokens("abcde"))
        self.assertEqual(1, validator._estimated_tokens("é"))
        self.assertEqual(2, validator._estimated_tokens("ééé"))

    def test_context_budget_warns_only_above_the_limit(self) -> None:
        budget = validator.TOKEN_BUDGET_OVERRIDES["AGENTS.md"]
        self.write("AGENTS.md", "x" * (budget * 4))

        self.assertNotIn("TOK001", self.codes())

        self.write("AGENTS.md", "x" * (budget * 4 + 1))
        warning = next(item for item in self.diagnostics() if item.code == "TOK001")
        strict = next(
            item for item in self.diagnostics(strict=True) if item.code == "TOK001"
        )

        self.assertEqual(validator.Severity.WARNING, warning.severity)
        self.assertEqual(validator.Severity.ERROR, strict.severity)
        self.assertIn(str(budget + 1), warning.message)

    def test_context_budget_applies_to_new_agents(self) -> None:
        budget = validator.TOKEN_BUDGETS["agent"]
        self.write(
            ".github/agents/large.agent.md",
            agent_document("large", body="x" * (budget * 4)),
        )

        warning = next(item for item in self.diagnostics() if item.code == "TOK001")

        self.assertEqual(".github/agents/large.agent.md", warning.path)

    def test_context_budget_excludes_docs_and_skill_resources(self) -> None:
        large = "x" * 5000
        self.write("README.md", large)
        self.write("docs/guide.md", large)
        self.write(".github/skills/example/templates/large.md", large)
        self.write(".github/skills/example/references/large.md", large)

        self.assertNotIn("TOK001", self.codes())

    def test_strict_cli_rejects_context_budget_warning(self) -> None:
        budget = validator.TOKEN_BUDGET_OVERRIDES["AGENTS.md"]
        self.write("AGENTS.md", "x" * (budget * 4 + 1))
        normal = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        strict = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--root",
                str(self.root),
                "--strict",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, normal.returncode)
        self.assertIn("TOK001 WARNING AGENTS.md:1", normal.stdout)
        self.assertEqual(1, strict.returncode)
        self.assertIn("TOK001 ERROR AGENTS.md:1", strict.stdout)

    def test_strict_promotes_delegation_policy_warning(self) -> None:
        self.write(
            ".github/agents/open-delegator.agent.md",
            agent_document("open-delegator", tools='["read", "agent"]'),
        )

        warning = next(item for item in self.diagnostics() if item.code == "POL003")
        strict = next(
            item for item in self.diagnostics(strict=True) if item.code == "POL003"
        )

        self.assertEqual(validator.Severity.WARNING, warning.severity)
        self.assertEqual(validator.Severity.ERROR, strict.severity)

    def test_prompt_skill_collision_is_case_insensitive_policy_warning(self) -> None:
        self.write(
            ".github/prompts/shared.prompt.md",
            prompt_document("SHARED"),
        )
        self.write(
            ".github/skills/shared/SKILL.md",
            skill_document("shared"),
        )

        result = next(item for item in self.diagnostics() if item.code == "POL001")
        strict = next(
            item for item in self.diagnostics(strict=True) if item.code == "POL001"
        )

        self.assertEqual(validator.Severity.WARNING, result.severity)
        self.assertEqual(validator.Severity.ERROR, strict.severity)

    def test_skill_name_description_and_body_constraints(self) -> None:
        long_name = "s" * 65
        self.write(
            ".github/skills/short/SKILL.md",
            skill_document(long_name, description="d" * 1025, body="   "),
        )

        codes = self.codes()

        self.assertIn("SKILL001", codes)
        self.assertIn("SKILL002", codes)
        self.assertIn("SKILL003", codes)
        self.assertIn("SKILL004", codes)

    def test_local_links_detect_escape_missing_target_and_case_difference(self) -> None:
        self.write("docs/Guide.md", "# Guide\n")
        self.write(
            "README.md",
            "[valid](docs/Guide.md)\n"
            "[wrong case](docs/guide.md)\n"
            "[missing](docs/missing.md)\n"
            "[escape](../outside.md)\n"
            "[external](https://example.com/docs)\n",
        )

        diagnostics = self.diagnostics()
        links = [item for item in diagnostics if item.code.startswith("LINK")]

        self.assertEqual(["LINK003", "LINK002", "LINK001"], [item.code for item in links])
        self.assertEqual([2, 3, 4], [item.line for item in links])

    def test_local_link_scanner_handles_parentheses_angles_and_fenced_code(self) -> None:
        self.write("docs/escaped(parens).md", "# Escaped parentheses\n")
        self.write("docs/Angle File (v1).md", "# Angle destination\n")
        self.write(
            "README.md",
            "[escaped](docs/escaped\\(parens\\).md)\n"
            "[angle](<docs/Angle File (v1).md>)\n"
            "```markdown\n"
            "[ignored backticks](docs/not-present.md)\n"
            "```\n"
            "~~~markdown\n"
            "[ignored tildes](docs/also-not-present.md)\n"
            "~~~\n"
            "[missing](docs/really-not-present.md)\n",
        )

        links = [
            item for item in self.diagnostics() if item.code.startswith("LINK")
        ]

        self.assertEqual(1, len(links))
        self.assertEqual("LINK002", links[0].code)
        self.assertEqual(9, links[0].line)

    def test_installed_mode_rejects_agents_project_map_placeholders(self) -> None:
        self.write(
            "AGENTS.md",
            "# Project map\n\n- Python ETLs: `[path or N/A]`\n",
        )

        self.assertNotIn("INST002", self.codes())
        installed = [
            item for item in self.diagnostics(installed=True) if item.code == "INST002"
        ]

        self.assertEqual(1, len(installed))
        self.assertEqual(3, installed[0].line)

    def test_cli_returns_zero_one_and_two(self) -> None:
        success = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.write(
            ".github/prompts/broken.prompt.md",
            prompt_document("broken", agent="unknown"),
        )
        configuration_error = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        usage_error = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--root",
                str(self.root / "not-a-directory"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, success.returncode, success.stdout + success.stderr)
        self.assertEqual(1, configuration_error.returncode)
        self.assertIn("REF001 ERROR .github/prompts/broken.prompt.md:4", configuration_error.stdout)
        self.assertEqual(2, usage_error.returncode)
        self.assertIn("CLI001 ERROR", usage_error.stderr)

    def test_argparse_usage_errors_have_stable_diagnostics(self) -> None:
        unknown_flag = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--not-a-real-flag"],
            check=False,
            capture_output=True,
            text=True,
        )
        missing_root_value = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(2, unknown_flag.returncode)
        self.assertEqual(
            "CLI003 ERROR <arguments>:1: invalid arguments: "
            "unrecognized arguments: --not-a-real-flag",
            unknown_flag.stderr.strip(),
        )
        self.assertEqual(2, missing_root_value.returncode)
        self.assertEqual(
            "CLI003 ERROR <arguments>:1: invalid arguments: "
            "argument --root: expected one argument",
            missing_root_value.stderr.strip(),
        )

    def test_cli_installed_and_strict_flags_apply_additional_policy(self) -> None:
        self.write(
            ".github/agents/open-delegator.agent.md",
            agent_document("open-delegator", tools='["read", "agent"]'),
        )
        warning_only = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        strict = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--root",
                str(self.root),
                "--strict",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.write("AGENTS.md", "- Python ETLs: `[path or N/A]`\n")
        installed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--root",
                str(self.root),
                "--installed",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, warning_only.returncode)
        self.assertIn("POL003 WARNING", warning_only.stdout)
        self.assertEqual(1, strict.returncode)
        self.assertIn("POL003 ERROR", strict.stdout)
        self.assertEqual(1, installed.returncode)
        self.assertIn("INST002 ERROR AGENTS.md:1", installed.stdout)

    def test_diagnostics_are_deterministic_and_render_code_severity_path_line(self) -> None:
        self.write(
            ".github/prompts/z.prompt.md",
            prompt_document("z", agent="missing"),
        )
        self.write(
            ".github/prompts/a.prompt.md",
            prompt_document("a", agent="missing"),
        )

        first = self.diagnostics()
        second = self.diagnostics()

        self.assertEqual(first, second)
        self.assertEqual(
            sorted(item.path.casefold() for item in first),
            [item.path.casefold() for item in first],
        )
        self.assertRegex(first[0].render(), r"^[A-Z]+\d{3} ERROR .+\.md:\d+: .+")


    def test_valid_codex_and_claude_sets_pass_platform_validation(self) -> None:
        for name in validator.EXPECTED_AGENTS:
            read_only = name in validator.READ_ONLY_AGENTS
            self.write(
                f".codex/agents/{name}.toml",
                codex_agent_document(
                    name, sandbox="read-only" if read_only else "workspace-write"
                ),
            )
            self.write(
                f".claude/agents/{name}.md",
                claude_agent_document(name, writer=not read_only),
            )
        for name in validator.EXPECTED_SKILLS:
            self.write(f".agents/skills/{name}/SKILL.md", skill_document(name))
            self.write(f".claude/skills/{name}/SKILL.md", skill_document(name))

        platform_codes = {
            item.code
            for item in self.diagnostics()
            if item.code.startswith(("CODEX", "CLAUDE", "TOML"))
        }

        self.assertEqual(set(), platform_codes)

    def test_codex_rejects_fixed_model_and_wrong_sandbox(self) -> None:
        for name in validator.EXPECTED_AGENTS:
            content = codex_agent_document(name, sandbox="workspace-write")
            if name == "alice":
                content += 'model = "fixed-model"\n'
            self.write(f".codex/agents/{name}.toml", content)
        for name in validator.EXPECTED_SKILLS:
            self.write(f".agents/skills/{name}/SKILL.md", skill_document(name))

        codes = self.codes()

        self.assertIn("CODEX002", codes)
        self.assertIn("CODEX003", codes)

    def test_claude_rejects_writer_without_write_tools_and_unknown_skill(self) -> None:
        for name in validator.EXPECTED_AGENTS:
            writer = name not in validator.READ_ONLY_AGENTS
            content = claude_agent_document(name, writer=writer)
            if name == "alice":
                content = agent_document(
                    name,
                    tools='["Read"]',
                    extra='model: inherit\npermissionMode: plan\nskills: ["missing"]',
                )
            self.write(f".claude/agents/{name}.md", content)
        for name in validator.EXPECTED_SKILLS:
            self.write(f".claude/skills/{name}/SKILL.md", skill_document(name))

        codes = self.codes()

        self.assertIn("CLAUDE004", codes)
        self.assertIn("CLAUDE005", codes)


if __name__ == "__main__":
    unittest.main()
