# F2 — `dontAsk`, regras de escrita derivadas e Stop hook: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` em sessão visível (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Fazer cada especialista em background rodar com `--permission-mode dontAsk`, com escrita limitada nativamente aos alvos e ao próprio receipt, e impedido de encerrar sem um receipt válido; alinhar toda a documentação a esse modelo.

**Architecture:** `launch_claude` passa a derivar, da atribuição, as regras `Edit(//…)` de escrita e o `--settings` com um Stop hook; o hook é um subcomando novo do pacote `scripts/marina/` que roda o `receipt_lint`. `status_claude` reconhece o estado de fim de turno que o `dontAsk` produz. As instruções carregadas pelo runtime e os docs trocam "espera `attach`" por "é negado e vai no receipt".

**Tech Stack:** Python ≥ 3.11 stdlib (`json`, `shlex`, `subprocess`, `unittest`); Claude Code CLI 2.1.306.

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md), seção 3.5 (revisada após a F1) e linha F2 da seção 4; evidência em [docs/achados-f1-spike-hooks-e-juiza-2026-10.md](achados-f1-spike-hooks-e-juiza-2026-10.md).

## Global Constraints

- Python ≥ 3.11, só stdlib; nenhuma dependência nova.
- Todo script com `if __name__ == "__main__":` declara `Minimum tested Claude CLI version:` no cabeçalho; os módulos tocados nesta fase declaram `2.1.306`.
- Testes nunca chamam o CLI real nem leem/escrevem o `.agent-state/` real; subprocessos e sessões do manager são injetados.
- `--permission-mode` dos launches é sempre `dontAsk`; continuam proibidos `bypassPermissions`, `--permission-prompts none`, `--resume`, `--continue`, `--fork-session`, `Bash` nu e `Bash(*)`.
- Regras de escrita nunca vêm da allowlist do `state.toml`: são derivadas da atribuição no launch. Forma exata: writer → `Edit(/<alvo-absoluto-normalizado>/**)` por alvo, na ordem de `targets`, seguido de `Edit(/<receipt-absoluto>)`; leitor → só `Edit(/<receipt-absoluto>)`. Como o caminho absoluto começa com `/`, a regra resulta em `Edit(//…)`.
- `--settings` é o JSON compacto (`json.dumps(..., separators=(",", ":"), ensure_ascii=False)`) de `{"worktree":{"bgIsolation":"none"},"hooks":{"Stop":[{"hooks":[{"type":"command","command":<cmd>}]}]}}`, com `<cmd> = shlex.join(["python3", "<kit_root>/scripts/marina/__main__.py", "hook", "require-receipt", "--receipt", <receipt-absoluto>, "--handoff", <handoff-absoluto>])`.
- Todo subprocesso `claude` aberto por script do kit passa `stdin=subprocess.DEVNULL`.
- Mudanças locais preexistentes de outra pessoa em `scripts/gate.py` e `tests/test_gate.py`: preservar, nunca incluir em `git add` desta fase.
- Commits só com autorização do usuário; os passos "Commit" ficam condicionados a ela.

## Review Focus

1. **Alvo com barra final ou componentes `..`** gera regra malformada (`Edit(//t//**)`) que o CLI não casaria — teste `test_target_paths_are_normalized` na Task 3.
2. **Caminho com espaço** na raiz do kit, no receipt ou no handoff quebra o comando do hook — teste `test_hook_command_survives_spaces` na Task 3.
3. **Stdin vazio ou JSON inválido no Stop hook** não pode virar bloqueio infinito: sai com código 1 (não bloqueante), nunca 2 — teste `test_invalid_hook_input_is_non_blocking` na Task 2.
4. **Handoff ausente ou ilegível** durante o hook não pode bloquear para sempre: código 1 com mensagem — teste `test_unreadable_handoff_is_non_blocking` na Task 2.
5. **Regra de escrita contrabandeada na allowlist** (`edit(...)` minúsculo, `Write`, `NotebookEdit`) precisa ser recusada antes do launch — teste `test_refuses_file_write_rules_in_allowlist` na Task 3.

---

### Task 1: `status_claude` reconhece o fim de turno do `dontAsk`

**Owner:** `kit-tooling`.

**Files:**
- Modify: `scripts/status_claude.py` (`classify_session`, cabeçalho de versão mínima)
- Test: `tests/test_status_claude.py` (`ClassifySessionTests`)

**Interfaces:**
- Produces: `classify_session(session: dict) -> str` devolve `"finished"` também para `state == "blocked"` com `status == "idle"` e `waitingFor` ausente ou `None`; qualquer outro `blocked` continua `"unknown"`.

- [ ] **Step 1: Escrever os testes que falham**

```python
    def test_blocked_idle_without_waiting_for_is_finished(self):
        # dontAsk background sessions end their turn in this state after denials (F1, Q2).
        session = _session(state="blocked", status="idle", waitingFor=None)
        self.assertEqual(status_claude.classify_session(session), "finished")

    def test_blocked_idle_missing_waiting_for_key_is_finished(self):
        self.assertEqual(status_claude.classify_session(_session(state="blocked", status="idle")), "finished")

    def test_blocked_busy_stays_unknown(self):
        self.assertEqual(status_claude.classify_session(_session(state="blocked", status="busy")), "unknown")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest tests.test_status_claude -v`
Expected: FAIL nos dois primeiros (`'unknown' != 'finished'`); o terceiro passa.

- [ ] **Step 3: Implementar** — em `classify_session`, depois do teste de `waiting_approval` e antes de `working`, a condição `state == "blocked" and session.get("status") == "idle" and not session.get("waitingFor")` devolve `"finished"`. Cabeçalho: `Minimum tested Claude CLI version: 2.1.306`.

- [ ] **Step 4: Rodar e ver passar**

Run: `python3 -m unittest tests.test_status_claude tests.test_watch_claude -v`
Expected: tudo `ok`.

- [ ] **Step 5: Commit (só com autorização)**

```bash
git add scripts/status_claude.py tests/test_status_claude.py
git commit -m "fix(status-claude): treat blocked+idle as end of turn under dontAsk"
```

---

### Task 2: Stop hook `require-receipt`

**Owner:** `kit-tooling`.

**Files:**
- Create: `scripts/marina/__init__.py` (docstring de uma linha: pacote do executável da Marina; na F2 só hooks)
- Create: `scripts/marina/hooks.py`
- Create: `scripts/marina/cli.py`
- Create: `scripts/marina/__main__.py` (cabeçalho com `Minimum tested Claude CLI version: 2.1.306`; insere a raiz do kit em `sys.path` como os outros scripts e chama `cli.main`)
- Test: `tests/test_marina_hooks.py`

**Interfaces:**
- Consumes: `receipt_lint.lint_file(path, *, role=None, handoff=None) -> tuple[list[str], ReceiptSummary]` (existente).
- Produces:
  - `hooks.require_receipt(hook_input: dict, *, receipt: Path, handoff: Path) -> tuple[int, str]` — `(0, "")` libera; `(2, mensagem)` bloqueia; `(1, mensagem)` erro não bloqueante.
  - `cli.main(argv: list[str] | None = None, *, stdin: TextIO = sys.stdin, stderr: TextIO = sys.stderr) -> int` — único subcomando nesta fase: `hook require-receipt --receipt PATH --handoff PATH`; lê o JSON do hook do `stdin`, escreve a mensagem em `stderr`, devolve o código.

Regras de `require_receipt`, nesta ordem:
1. `hook_input.get("stop_hook_active")` verdadeiro → `(0, "")` (F1, H4: evita laço).
2. Receipt inexistente → `(2, f"receipt missing: write {receipt} using the canonical structure in docs/agent-workflow.md before stopping; record any denied command there and use status needs_input or blocked if acceptance depends on it")`.
3. Handoff inexistente ou ilegível (`OSError`) → `(1, f"cannot read handoff {handoff}: <erro>")`.
4. `lint_file(receipt, handoff=handoff)` com erros → `(2, f"receipt {receipt} fails receipt-lint: " + "; ".join(errors[:5]))`.
5. Senão → `(0, "")`.

`cli.main`: JSON inválido ou vazio no stdin → mensagem em `stderr` e `1`; qualquer exceção inesperada → mensagem e `1`. Nunca `2` fora das regras acima.

- [ ] **Step 1: Escrever os testes que falham** (`tests/test_marina_hooks.py`, com `tempfile` e uma cópia mínima de receipt válido; reutilize `tests/fixtures/receipts/good-node-backend-receipt.md` e um handoff mínimo escrito no `tmp` cujo perfil absoluto bata com o `profile_read` da fixture, como `tests/test_receipt_lint.py` já faz)

```python
class RequireReceiptTests(unittest.TestCase):
    def test_stop_hook_active_always_releases(self):
        code, _ = hooks.require_receipt({"stop_hook_active": True}, receipt=Path("/nonexistent"), handoff=Path("/nonexistent"))
        self.assertEqual(code, 0)

    def test_missing_receipt_blocks_with_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "01-node-backend-receipt.md"
            code, msg = hooks.require_receipt({"stop_hook_active": False}, receipt=receipt, handoff=Path(tmp) / "h.md")
            self.assertEqual(code, 2)
            self.assertIn(str(receipt), msg)
            self.assertIn("needs_input", msg)

    def test_unreadable_handoff_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "01-node-backend-receipt.md"
            receipt.write_text("x\n", encoding="utf-8")
            code, msg = hooks.require_receipt({}, receipt=receipt, handoff=Path(tmp) / "missing-handoff.md")
            self.assertEqual(code, 1)
            self.assertIn("missing-handoff.md", msg)

    def test_invalid_receipt_blocks_with_lint_errors(self):
        # receipt present, handoff present, receipt lacks a status section
        ...  # write receipt without "## Status"; assert code == 2 and "receipt-lint" in msg and "status" in msg

    def test_valid_receipt_releases(self):
        ...  # fixture receipt + matching handoff; assert code == 0


class CliTests(unittest.TestCase):
    def _run(self, argv, stdin_text):
        err = io.StringIO()
        code = cli.main(argv, stdin=io.StringIO(stdin_text), stderr=err)
        return code, err.getvalue()

    def test_invalid_hook_input_is_non_blocking(self):
        for text in ("", "not json"):
            with self.subTest(text=text):
                code, err = self._run(["hook", "require-receipt", "--receipt", "/r", "--handoff", "/h"], text)
                self.assertEqual(code, 1)
                self.assertTrue(err)

    def test_block_message_goes_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self._run(
                ["hook", "require-receipt", "--receipt", f"{tmp}/r.md", "--handoff", f"{tmp}/h.md"],
                '{"hook_event_name": "Stop", "stop_hook_active": false}',
            )
            self.assertEqual(code, 2)
            self.assertIn("receipt missing", err)

    def test_runs_as_a_script_by_path(self):
        # The Stop hook invokes the file by absolute path from an arbitrary cwd.
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(KIT_ROOT / "scripts" / "marina" / "__main__.py"), "hook", "require-receipt",
                 "--receipt", f"{tmp}/r.md", "--handoff", f"{tmp}/h.md"],
                input='{"stop_hook_active": true}', capture_output=True, text=True, cwd=tmp, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
```

Os dois testes marcados com `...` seguem o mesmo padrão: escrever os arquivos no `tmp` e afirmar exatamente o que o comentário diz.

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest tests.test_marina_hooks -v`
Expected: ERROR `ModuleNotFoundError: No module named 'scripts.marina'`.

- [ ] **Step 3: Implementar `hooks.py`, `cli.py`, `__init__.py`, `__main__.py`** conforme as interfaces e regras acima.

- [ ] **Step 4: Rodar e ver passar**

Run: `python3 -m unittest tests.test_marina_hooks -v && python3 scripts/kit_lint.py`
Expected: testes `ok`; `kit_lint` 6/6 (inclui `cli_version_headers` para o novo `__main__.py`).

- [ ] **Step 5: Commit (só com autorização)**

```bash
git add scripts/marina/ tests/test_marina_hooks.py
git commit -m "feat(marina): Stop hook that requires a lint-clean receipt"
```

---

### Task 3: `launch_claude` em `dontAsk`

**Owner:** `kit-tooling` (revisão: `reviewer` — muda o contrato de permissão).

**Files:**
- Modify: `scripts/launch_claude.py` (docstring do módulo, cabeçalho de versão, `_check_forbidden_allowlist`, `build_argv`, `run_launch`; novas `derive_write_rules`, `build_settings`)
- Modify: `scripts/common.py` (`list_manager_sessions`, `installed_claude_version`: `stdin=subprocess.DEVNULL`)
- Test: `tests/test_launch_claude.py` (`EXPECTED_DOC_ARGV`, `BuildArgvDocumentedExampleTest`, `ForbiddenConstructionTests`, `RunLaunchTests`, nova `WriteRulesAndSettingsTests`), `tests/test_common.py` (nova `ClaudeSubprocessStdinTests`)

**Interfaces:**
- Consumes: `scripts.state.model.mode_for_role(role) -> str`; caminho do hook de Task 2 (`<kit_root>/scripts/marina/__main__.py`).
- Produces:
  - `derive_write_rules(mode: str, targets: list[str], receipt: str) -> list[str]`
  - `build_settings(kit_root: Path, receipt: str, handoff: str) -> str`
  - `build_argv(handoff: HandoffData, *, handoff_path: str, receipt_path: str, kit_root: Path, extra_args: list[str] | None = None, cli: str = "claude") -> list[str]` — ordem: `claude --bg --agent <role> --name <título> --add-dir <alvo>… --settings <build_settings> --permission-mode dontAsk --allowedTools <derive_write_rules…> <allowlist…> [extra] -- <prompt>`.
  - `run_launch` passa `receipt_path=str(kit_root / assignment.receipt)` e `kit_root`, chama o subprocesso com `stdin=subprocess.DEVNULL` e acrescenta à nota do evento `launched` o texto `write_rules=<n>`.

- [ ] **Step 1: Escrever os testes que falham**

```python
class WriteRulesAndSettingsTests(unittest.TestCase):
    def test_writer_rules_cover_each_target_then_receipt(self):
        self.assertEqual(
            launch_claude.derive_write_rules("writer", ["/abs/api", "/abs/bff"], "/kit/.agent-state/p/tasks/t/01-x-receipt.md"),
            ["Edit(//abs/api/**)", "Edit(//abs/bff/**)", "Edit(//kit/.agent-state/p/tasks/t/01-x-receipt.md)"],
        )

    def test_reader_rules_are_receipt_only(self):
        self.assertEqual(
            launch_claude.derive_write_rules("reader", ["/abs/api"], "/kit/r.md"),
            ["Edit(//kit/r.md)"],
        )

    def test_target_paths_are_normalized(self):
        self.assertEqual(
            launch_claude.derive_write_rules("writer", ["/abs/api/", "/abs/x/../bff"], "/kit/r.md")[:2],
            ["Edit(//abs/api/**)", "Edit(//abs/bff/**)"],
        )

    def test_relative_target_refused(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.derive_write_rules("writer", ["rel/api"], "/kit/r.md")

    def test_settings_shape(self):
        settings = json.loads(launch_claude.build_settings(Path("/kit"), "/kit/r.md", "/kit/h.md"))
        self.assertEqual(settings["worktree"], {"bgIsolation": "none"})
        command = settings["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(command["type"], "command")
        self.assertEqual(
            shlex.split(command["command"]),
            ["python3", "/kit/scripts/marina/__main__.py", "hook", "require-receipt", "--receipt", "/kit/r.md", "--handoff", "/kit/h.md"],
        )

    def test_hook_command_survives_spaces(self):
        settings = json.loads(launch_claude.build_settings(Path("/my kit"), "/my kit/r 1.md", "/my kit/h 1.md"))
        argv = shlex.split(settings["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertEqual(argv[1], "/my kit/scripts/marina/__main__.py")
        self.assertEqual(argv[-3:], ["/my kit/r 1.md", "--handoff", "/my kit/h 1.md"])
```

Em `ForbiddenConstructionTests`:

```python
    def test_refuses_file_write_rules_in_allowlist(self):
        for entry in ("Edit", "Edit(//abs/**)", "edit(src/**)", "Write", "NotebookEdit", "MultiEdit"):
            with self.subTest(entry=entry):
                data = self._data(allowlist=["Bash(mvn test)", entry])
                with self.assertRaises(launch_claude.LaunchRefused):
                    launch_claude.build_argv(data, handoff_path="/x", receipt_path="/kit/r.md", kit_root=Path("/kit"))

    def test_permission_mode_is_dont_ask(self):
        argv = launch_claude.build_argv(self._data(), handoff_path="/x", receipt_path="/kit/r.md", kit_root=Path("/kit"))
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("auto", argv)
```

(Atualize `test_default_argv_never_emits_bypass_or_permission_prompts` e os demais chamadores de `build_argv` no arquivo para a nova assinatura; troque a asserção de `"auto"` por `"dontAsk"`. Se o helper `_data` da classe não aceitar `allowlist=`, construa o `HandoffData` diretamente com `dataclasses.replace`.)

Em `RunLaunchTests`: o `_RecordingSubprocess` passa a guardar `kwargs`; novo teste `test_launch_closes_stdin` afirma `recorder.kwargs[0]["stdin"] is subprocess.DEVNULL`; novo teste `test_launched_event_note_counts_write_rules` afirma `"write_rules=2"` na nota do evento `launched` para o fixture writer de um alvo (alvo + receipt).

Em `tests/test_common.py`, com `unittest.mock.patch.object(common.shutil, "which", return_value="/usr/bin/claude")` e `patch.object(common.subprocess, "run", ...)` devolvendo um `CompletedProcess` válido (`stdout="[]"` para o manager, `"2.1.306 (Claude Code)"` para a versão):

```python
class ClaudeSubprocessStdinTests(unittest.TestCase):
    def test_list_manager_sessions_closes_stdin(self):
        ...  # call common.list_manager_sessions(); assert run.call_args.kwargs["stdin"] is subprocess.DEVNULL

    def test_installed_claude_version_closes_stdin(self):
        ...  # call common.installed_claude_version(); assert run.call_args.kwargs["stdin"] is subprocess.DEVNULL
```

`EXPECTED_DOC_ARGV` passa a ser exatamente o exemplo novo de `docs/agent-workflow.md` (Task 4, Step 2), com `receipt_path="/absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-receipt.md"` e `kit_root=Path("/absolute/kit")`:

```python
EXPECTED_DOC_ARGV = [
    "claude", "--bg", "--agent", "java-backend",
    "--name", "redmine-1234 — java-backend — 01 — implementação",
    "--add-dir", "/absolute/api",
    "--settings",
    '{"worktree":{"bgIsolation":"none"},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"python3 /absolute/kit/scripts/marina/__main__.py hook require-receipt --receipt /absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-receipt.md --handoff /absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-handoff.md"}]}]}}',
    "--permission-mode", "dontAsk",
    "--allowedTools",
    "Edit(//absolute/api/**)",
    "Edit(//absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-receipt.md)",
    "Bash(mvn test)",
    "--",
    "Act as java-backend. Read /absolute/kit/.claude/agents/java-backend.md and "
    "/absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-handoff.md, then execute the assignment.",
]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest tests.test_launch_claude tests.test_common -v`
Expected: ERROR/FAIL por `derive_write_rules`/`build_settings` inexistentes, assinatura antiga de `build_argv`, `"auto"` no argv e `stdin` ausente (inclusive nas duas funções de `common`).

- [ ] **Step 3: Implementar**

- `derive_write_rules`: recusa (`LaunchRefused`) alvo ou receipt não absoluto; normaliza com `os.path.normpath`; `f"Edit(/{t}/**)"` por alvo para `mode == "writer"`; `f"Edit(/{receipt})"` sempre por último.
- `build_settings`: exatamente o JSON e o comando definidos em Global Constraints.
- `_check_forbidden_allowlist`: além das recusas atuais, recusa qualquer entrada que case `^(Edit|Write|NotebookEdit|MultiEdit)\b` sem diferenciar maiúsculas, com a mensagem `"file-write rules are derived from the assignment's targets and receipt, never granted through the allowlist: {entry!r}"`.
- `build_argv`: nova assinatura e ordem de Interfaces; `mode_for_role(handoff.role)` decide writer/leitor.
- `common.list_manager_sessions` e `common.installed_claude_version`: acrescentar `stdin=subprocess.DEVNULL` ao `subprocess.run`.
- `run_launch`: `receipt_path=str(kit_root / assignment.receipt)`; `run_subprocess(argv, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)`; nota `launched` com `; write_rules={n}`.
- Docstrings de `build_argv` e do módulo: `dontAsk` no lugar de `auto`, com uma frase sobre as regras derivadas; cabeçalho `Minimum tested Claude CLI version: 2.1.306`.

- [ ] **Step 4: Rodar a suíte inteira**

Run: `python3 -m unittest discover -s tests && python3 scripts/kit_lint.py`
Expected: `OK`; `kit_lint` 6/6.

- [ ] **Step 5: Commit (só com autorização)**

```bash
git add scripts/launch_claude.py scripts/common.py tests/test_launch_claude.py tests/test_common.py
git commit -m "feat(launch-claude): dontAsk with derived write rules and receipt Stop hook"
```

---

### Task 4: instruções e documentação

**Owner:** Marina.

**Files:**
- Modify: `AGENTS.md:28`, `CLAUDE.md:10`, `.claude/skills/task-execution/SKILL.md:42`
- Modify: `docs/agent-workflow.md` (exemplo de launch e parágrafos da seção "Claude Code"; cenário de aceitação da seção "Visible-session acceptance scenarios")
- Modify: `README.md:62` (versão verificada do CLI)

- [ ] **Step 1: Instruções carregadas pelo runtime** — substituições exatas:

| Arquivo | Trecho atual | Novo trecho |
|---|---|---|
| `AGENTS.md:28` | a linha inteira | `- Claude background assignments use per-invocation \`--settings\` (worktree \`bgIsolation: none\` for the authorized shared checkout, plus the kit's Stop hook that requires a lint-clean receipt), \`--permission-mode dontAsk\` and an explicit \`--allowedTools\`: check-derived \`Bash(...)\` rules recorded per assignment, plus file-write rules derived at launch (\`Edit(//<target>/**)\` per target for writers, \`Edit(//<receipt>)\` for every role). Anything outside the allowlist is denied, not queued: the specialist records each denied command in its receipt (as a skipped check with the reason; \`needs_input\` or \`blocked\` when acceptance depends on it), and Marina grants a wider allowlist only through a new assignment. Never use \`bypassPermissions\` or \`--permission-prompts none\`. An allowlist belongs to its assignment and is not copied to the next.` |
| `CLAUDE.md:10` | `` `--permission-mode auto` and a check-derived `--allowedTools` `` | `` `--permission-mode dontAsk` and an `--allowedTools` of check-derived `Bash(...)` rules plus launch-derived `Edit(//…)` write rules `` |
| `CLAUDE.md:10` | `` per-invocation `--settings '{"worktree":{"bgIsolation":"none"}}'` for shared local files `` | `` per-invocation `--settings` for shared local files and the receipt Stop hook `` |
| `task-execution/SKILL.md:42` | a linha inteira | `- Claude launches use per-invocation \`--settings\` (worktree \`bgIsolation: none\` and the receipt Stop hook) without changing persistent settings, \`--permission-mode dontAsk\` and an \`--allowedTools\` of check-derived \`Bash(...)\` rules plus launch-derived \`Edit(//…)\` write rules; record exact rules for each assignment. Never use \`bypassPermissions\` or \`--permission-prompts none\`. A command outside the allowlist is denied and must appear in the receipt; a wider allowlist needs a new assignment.` |

- [ ] **Step 2: `docs/agent-workflow.md`, seção "Claude Code"**

- Frase de versão: `The installed CLI was checked at version 2.1.306 on 2026-10-25 (permission and hook behavior: docs/achados-f1-spike-hooks-e-juiza-2026-10.md)`; manter a lista de flags e acrescentar `--settings` hooks.
- Exemplo `bash`: idêntico, flag por flag, a `EXPECTED_DOC_ARGV` da Task 3 (mesma ordem, mesmos valores, `\` por linha).
- Parágrafo do `bgIsolation`: trocar "preserve the permission mode and scoped allowlist" por "the same `--settings` also carries the receipt Stop hook".
- Parágrafo do JSON `state`: acrescentar "Under `dontAsk`, a background session that ends its turn after denials reports `state: blocked`, `status: idle` with no `waitingFor`; `status-claude` treats it as finished."
- Parágrafo "Background execution has no human terminal…": reescrever para `dontAsk` + regras derivadas, dizendo que o `Read` é livre, que `Edit`/`Write`/Bash fora das regras são negados e registrados em `permission_denials`, e que a allowlist da CLI continua aditiva às permissões gerenciadas/usuário/projeto.
- Parágrafo "For `scripts/launch_claude.py`…": acrescentar que as regras `Edit(//…)` e o Stop hook são derivados no launch e não ficam no `state.toml`; o `state add` não muda, e é o `launch-claude` que recusa regras de escrita vindas da allowlist.
- Parágrafo "Commands outside the allowlist that require approval remain pending…": trocar por "Commands outside the allowlist are denied. The specialist reports each denied command in its receipt; Marina decides whether a new assignment with a wider allowlist is warranted. Never use `bypassPermissions` or `--permission-prompts none`, and never answer a native approval on the user's behalf if one appears."
- Seção "Visible-session acceptance scenarios": trocar "an outside-allowlist command that visibly waits and is resolved by the human through attach without bypass" por "an outside-allowlist command that is denied, recorded in `permission_denials` and reported in the receipt".

- [ ] **Step 3: `README.md:62`** — `Claude Code CLI ≥ 2.1.306 | Verificado em 2026-10-25 com …` (mantendo a lista de flags e acrescentando `--settings` com hooks).

- [ ] **Step 4: Verificar**

Run: `grep -rn "permission-mode auto\|remain pending\|stay pending" AGENTS.md CLAUDE.md .claude/ docs/agent-workflow.md README.md`
Expected: nenhuma linha.

Run: `python3 -m unittest tests.test_launch_claude.BuildArgvDocumentedExampleTest -v && python3 scripts/kit_lint.py`
Expected: `ok`; 6/6.

- [ ] **Step 5: Commit (só com autorização)**

```bash
git add AGENTS.md CLAUDE.md .claude/skills/task-execution/SKILL.md docs/agent-workflow.md README.md
git commit -m "docs: background specialists run under dontAsk with derived write rules"
```

---

### Task 5: verificação final e aceitação real

**Owner:** Marina, com revisão independente do `reviewer`.

- [ ] **Step 1: Suíte e lint**

Run: `python3 scripts/kit_lint.py`
Expected: 6/6 PASS.

- [ ] **Step 2: Preservação**

Run: `git diff scripts/gate.py tests/test_gate.py | sha256sum`
Expected: o mesmo hash registrado no checkpoint antes da Task 1.

- [ ] **Step 3: Aceitação real com o launcher novo** — reservar o `reviewer` desta fase pelo fluxo normal (`state add` → `gate` → `preflight` → `launch_claude`). O próprio lançamento é a prova de ponta a ponta:
  - o argv impresso tem `--permission-mode dontAsk`, só `Edit(//<receipt>)` como regra de escrita e o Stop hook no `--settings`;
  - o reviewer consegue escrever o receipt (regra nativa) e nada mais;
  - `watch_claude` termina com `finished` (inclusive se o manager reportar `blocked`/`idle`);
  - `git status` do kit, fora o receipt em `.agent-state/`, idêntico antes e depois da sessão.
  Registrar o ID e cada item no checkpoint.

- [ ] **Step 4: Receipt do reviewer** — confere o diff das Tasks 1–4 contra a seção 3.5 revisada da spec e a Review Focus acima; verdict `PASS`, `PASS_WITH_RISKS` ou `FAIL`.

---

## Execução neste kit

- Tasks 1–3 (código em `scripts/`/`tests/`) são do `kit-tooling`. Pelo protocolo, cada uma iria a uma sessão visível em sequência, com gate de Git entre elas. Na F0, o usuário escolheu executar na sessão principal com o aviso de fallback; a escolha desta fase é dele.
- Task 4 fica com a Marina.
- Task 5 inclui uma sessão visível do `reviewer`, lançada com o `launch_claude` novo — que é também o teste real do `dontAsk`.
