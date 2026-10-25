# F0 — Exclusividade Claude: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` em sessão visível (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Remover o lado Codex do kit (perfis, skills duplicadas, plataforma no schema, checks de paridade e documentação), deixando o Claude Code como único runtime, com o kit verde.

**Architecture:** Apagar `.codex/` e `.agents/`; trocar os três checks de paridade do `kit_lint` por um check de perfis Claude e um guarda contra a volta de diretórios de outro runtime; tirar `codex` e `host` do schema de estado tolerando a chave `host = ""` legada; reescrever as menções a Codex nas instruções carregadas pelo runtime e na documentação humana.

**Tech Stack:** Python ≥ 3.11 stdlib (`tomllib`, `unittest`), Markdown.

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md), seção 2.

## Global Constraints

- Python ≥ 3.11, só stdlib; nenhuma dependência nova.
- Todo script executável em `scripts/` mantém a linha `Minimum tested Claude CLI version:` no cabeçalho (checada por `kit_lint`).
- Testes nunca leem nem escrevem o `.agent-state/` real; usam `tempfile` ou `tests/fixtures/`.
- Rodar tudo a partir da raiz do kit: `python3 -m unittest discover -s tests` e `python3 scripts/kit_lint.py`.
- Há mudanças locais de outra pessoa em `scripts/gate.py`, `tests/test_gate.py` e documentos não rastreados em `docs/`: preservar, nunca reverter, nunca incluir em `git add` desta tarefa.
- Commits exigem autorização do usuário (`AGENTS.md`). Os passos "Commit" abaixo só são executados com essa autorização; sem ela, deixar as mudanças no working tree e registrar no receipt.
- `AGENTS.md` continua existindo, importado por `CLAUDE.md`.
- Mensagens de erro novas em inglês, como as existentes em `scripts/`.

## Desvios da spec

- **`check_agent_profiles` é novo.** A spec manda remover os checks de paridade, mas `check_agent_profile_parity` era o único que validava o frontmatter dos perfis Claude. O check novo preserva essa cobertura.
- **As linhas `host = ""` saem das fixtures.** A spec diz "sem mudança de dados" na fixture `visible-sessions`, mas `NativeMeta.to_dict()` deixa de escrever `host` e `test_round_trip_equals_original_parse` compara o arquivo original com o reescrito. Remover só essa chave vazia é o mínimo para o round-trip continuar exato; os dados do nn=4 não mudam.
- **O caso "Native runtime" da tabela de avaliação é reescrito, não removido.** Confirmar descoberta de perfis e acesso aos alvos continua valendo para um só runtime.

## Review Focus

1. Um `state.toml` real em `.agent-state/` com `host = ""` (há três hoje) precisa continuar carregando — teste `test_legacy_empty_host_is_tolerated` na Task 2.
2. Um `state.toml` legado com `platform = "codex"` precisa falhar com `StateError` que nomeia a plataforma, não com traceback genérico — teste `test_codex_platform_rejected` na Task 2.
3. Um `host` não vazio legado precisa falhar com mensagem que nomeia `host` — teste `test_legacy_nonempty_host_rejected` na Task 2.
4. Alguém recriar `.agents/skills/` copiando uma skill de volta precisa derrubar o `kit_lint` com o caminho — teste `test_agents_dir_fails` na Task 1.
5. Um handoff que ainda aponte para `.codex/agents/<role>.toml` precisa falhar no preflight — subteste `codex profile` na Task 2.

---

### Task 1: `kit_lint` sem paridade e remoção de `.codex/` e `.agents/`

**Owner:** `kit-tooling` (revisão: `reviewer`).

**Files:**
- Delete: `.codex/` (inteiro), `.agents/` (inteiro)
- Modify: `scripts/kit_lint.py` (docstring do módulo, `_PATH_SUBSTITUTIONS`, `_normalize_body`, `check_agent_profile_parity`, `check_instructions_parity`, `check_skills_identity`, `run_all`; remover `import tomllib` se ficar sem uso)
- Test: `tests/test_kit_lint.py`

**Interfaces:**
- Consumes: `_parse_frontmatter(md_path: Path) -> tuple[dict, str]` e `CheckResult` (existentes, mantidos).
- Produces: `check_agent_profiles(kit_root: Path) -> CheckResult` com `name="agent_profiles"`; `check_no_foreign_runtime(kit_root: Path) -> CheckResult` com `name="no_foreign_runtime"`; constante `FOREIGN_RUNTIME_DIRS = (".codex", ".agents")`. `run_all` passa a devolver, nesta ordem: `agent_profiles`, `no_foreign_runtime`, `git_diff_check`, `cli_version_headers`, `state_lint`, `unittest_suite`.

- [ ] **Step 1: Substituir os testes de paridade pelos testes novos**

Em `tests/test_kit_lint.py`: apagar `_write_profile_pair`, `DeliberateParityBreakTests`, `InstructionsAndSkillsBreakTests` e os três testes de paridade de `RealKitPositiveTests`. Acrescentar:

```python
class RealKitPositiveTests(unittest.TestCase):  # manter os testes existentes de git/state/cli
    def test_agent_profiles_pass_on_real_kit(self):
        result = kit_lint.check_agent_profiles(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_no_foreign_runtime_passes_on_real_kit(self):
        result = kit_lint.check_no_foreign_runtime(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)


def _write_profile(root: Path, filename: str, text: str) -> None:
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "agents" / filename).write_text(text, encoding="utf-8")


class AgentProfilesTests(unittest.TestCase):
    def test_valid_profile_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", '---\nname: demo\ndescription: "Demo."\n---\n\nBody.\n')
            self.assertTrue(kit_lint.check_agent_profiles(Path(tmp)).ok)

    def test_no_profiles_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("no *.md profiles" in d for d in result.details))

    def test_name_differs_from_filename_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", '---\nname: other\ndescription: "Demo."\n---\n\nBody.\n')
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("demo" in d and "name" in d for d in result.details))

    def test_missing_description_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", "---\nname: demo\n---\n\nBody.\n")
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("description" in d for d in result.details))

    def test_empty_body_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", '---\nname: demo\ndescription: "Demo."\n---\n\n')
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("body" in d for d in result.details))

    def test_missing_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", "Body only.\n")
            self.assertFalse(kit_lint.check_agent_profiles(Path(tmp)).ok)


class NoForeignRuntimeTests(unittest.TestCase):
    def test_clean_root_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(kit_lint.check_no_foreign_runtime(Path(tmp)).ok)

    def test_codex_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".codex" / "agents").mkdir(parents=True)
            result = kit_lint.check_no_foreign_runtime(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any(".codex" in d for d in result.details))

    def test_agents_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".agents" / "skills" / "demo").mkdir(parents=True)
            (Path(tmp) / ".agents" / "skills" / "demo" / "SKILL.md").write_text("x\n", encoding="utf-8")
            result = kit_lint.check_no_foreign_runtime(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any(".agents" in d for d in result.details))

    def test_run_all_order(self):
        # Patch the suite runner so run_all never re-invokes the test suite recursively.
        fake = lambda kit_root, **_: kit_lint.CheckResult("unittest_suite", True, [])
        with unittest.mock.patch.object(kit_lint, "check_unittests", fake):
            results = kit_lint.run_all(REAL_KIT_ROOT)
        self.assertEqual(
            [r.name for r in results],
            ["agent_profiles", "no_foreign_runtime", "git_diff_check", "cli_version_headers", "state_lint", "unittest_suite"],
        )
```

Acrescente `import unittest.mock` aos imports do arquivo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest tests.test_kit_lint -v`
Expected: FAIL/ERROR com `AttributeError: module 'scripts.kit_lint' has no attribute 'check_agent_profiles'`.

- [ ] **Step 3: Implementar `check_agent_profiles` e `check_no_foreign_runtime`; remover os checks de paridade**

`check_agent_profiles`: para cada `.claude/agents/*.md` (ordenado), `_parse_frontmatter`; exigir `name` igual ao `stem`, `description` não vazio (após `strip('"')`) e corpo com algum caractere não branco. Sem arquivos → `f"no *.md profiles found under {dir}"`. Mensagens: `f"{stem}: frontmatter name {name!r} differs from filename"`, `f"{stem}: missing description"`, `f"{stem}: empty body"`.

`check_no_foreign_runtime`: para cada nome em `FOREIGN_RUNTIME_DIRS`, se `(kit_root / nome).exists()` → `f"foreign runtime directory present: {kit_root / nome}"`.

Apagar `_PATH_SUBSTITUTIONS`, `_normalize_body`, `check_agent_profile_parity`, `check_instructions_parity`, `check_skills_identity`; atualizar `run_all` e a docstring do módulo ("Checks: `.claude/agents/*.md` frontmatter and body; no `.codex/`/`.agents/` directory; `git diff --check`; …").

- [ ] **Step 4: Apagar os diretórios do outro runtime**

Run: `git rm -r -q .codex .agents`
Expected: sem saída; `test -e .codex || test -e .agents; echo $?` imprime `1`.

- [ ] **Step 5: Rodar e ver passar**

Run: `python3 -m unittest tests.test_kit_lint -v`
Expected: todos `ok`.

- [ ] **Step 6: Commit (só com autorização)**

```bash
git add scripts/kit_lint.py tests/test_kit_lint.py
git commit -m "refactor(kit-lint): drop Codex parity, guard against foreign runtime dirs"
```

(`git rm` da Step 4 já deixou a remoção no índice.)

---

### Task 2: schema de estado e handoff sem Codex

**Owner:** `kit-tooling` (revisão: `reviewer` — muda o contrato do `state.toml`).

**Files:**
- Modify: `scripts/state/model.py` (`NATIVE_PLATFORMS`, `NativeMeta`), `scripts/state/__init__.py` (`add_assignment`), `scripts/state/__main__.py` (`cmd_add`, parser `add`), `scripts/state_lint.py` (`check_native_metadata`), `scripts/handoff_sync.py:93-96` (`expected_profiles`)
- Modify (fixtures): remover as linhas `host = ""` / `host         = ""` de `tests/fixtures/gate-tasks/task-a/state.toml`, `tests/fixtures/gate-tasks/task-c/state.toml`, `tests/fixtures/visible-sessions/state.toml`; no comentário do nn=4 da fixture visible-sessions, acrescentar a linha `# (histórico: o kit era dual Codex/Claude até 2026-10)`
- Test: `tests/test_state_model.py`, `tests/test_state_lint.py`, `tests/test_state_cli.py`, `tests/test_preflight.py`

**Interfaces:**
- Consumes: nada das outras tasks.
- Produces: `NATIVE_PLATFORMS == frozenset({"claude", "unavailable"})`; `NativeMeta(platform, id="", reason="", last_seen="", last_seen_at=None)` sem `host`; `NativeMeta.to_dict()` sem chave `host`; `add_assignment(..., platform="claude", reason="", ...)` sem `host`; `state add` sem `--host` e com `--platform` em `("claude", "unavailable")`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_state_model.py` (nova classe, usando `scripts.state.model`):

```python
class NativeMetaClaudeOnlyTests(unittest.TestCase):
    def test_platforms(self):
        self.assertEqual(model.NATIVE_PLATFORMS, frozenset({"claude", "unavailable"}))

    def test_codex_platform_rejected(self):
        with self.assertRaises(model.StateError) as ctx:
            model.NativeMeta.from_dict({"platform": "codex", "id": "t-1"})
        self.assertIn("codex", str(ctx.exception))

    def test_legacy_empty_host_is_tolerated(self):
        meta = model.NativeMeta.from_dict({"platform": "claude", "id": "abc", "host": ""})
        self.assertEqual(meta.id, "abc")
        self.assertNotIn("host", meta.to_dict())

    def test_legacy_nonempty_host_rejected(self):
        with self.assertRaises(model.StateError) as ctx:
            model.NativeMeta.from_dict({"platform": "claude", "host": "h-1"})
        self.assertIn("host", str(ctx.exception))
```

Em `tests/test_state_lint.py`: apagar `test_6_codex_with_id_without_host`.

Em `tests/test_state_cli.py` (nova classe; o arquivo já importa `from scripts.state import __main__ as state_cli`). O argparse encerra com `SystemExit` antes de ler o arquivo; antes da mudança, os dois comandos passam do parser e falham de outro jeito, então os testes falham:

```python
class AddArgsClaudeOnlyTests(unittest.TestCase):
    BASE = ["add", "--state", "x.toml", "--role", "reviewer", "--type", "revisão",
            "--edge", "inicia", "--predecessor", "0", "--target", "/tmp/x"]

    def test_platform_codex_rejected_by_parser(self):
        with self.assertRaises(SystemExit):
            state_cli.main(self.BASE + ["--platform", "codex"])

    def test_host_flag_removed(self):
        with self.assertRaises(SystemExit):
            state_cli.main(self.BASE + ["--host", "h"])
```

Em `tests/test_preflight.py`, `test_identity_mismatches_fail_preparation`: acrescentar ao dicionário `replacements` a entrada

```python
"codex profile": ("/.claude/agents/node-backend.md", "/.codex/agents/node-backend.toml"),
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python3 -m unittest tests.test_state_model tests.test_state_cli tests.test_preflight -v`
Expected: FAIL em `test_platforms`, `test_codex_platform_rejected`, `test_legacy_empty_host_is_tolerated` (to_dict ainda tem `host`), `test_legacy_nonempty_host_rejected`, nos dois testes do parser e no subteste `codex profile`.

- [ ] **Step 3: Implementar**

- `model.py`: `NATIVE_PLATFORMS = frozenset({"claude", "unavailable"})`; remover o campo `host` de `NativeMeta`; em `from_dict`, se `d.get("host", "")` for não vazio → `StateError("[assignments.native] 'host' was Codex-only and is no longer supported")`; vazio é ignorado; `to_dict` sem `host`. A mensagem de plataforma desconhecida já inclui o valor (`unknown platform: 'codex'`).
- `state/__init__.py`: remover o parâmetro `host` de `add_assignment` e de `NativeMeta(...)`.
- `state/__main__.py`: remover `host=args.host` de `cmd_add`, o argumento `--host` e trocar `choices` de `--platform` para `("claude", "unavailable")`.
- `state_lint.py`: `check_native_metadata` mantém só a regra `unavailable` exige `reason`; docstring `"""6. \`platform=unavailable\` requires \`reason\`."""`.
- `handoff_sync.py`: `expected_profiles` vira só `{str(kit_root / ".claude" / "agents" / f"{assignment.role}.md")}`.
- Fixtures: remover as linhas `host` listadas em **Files**.

- [ ] **Step 4: Rodar a suíte inteira**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (a contagem final aparece na última linha; registre-a no receipt).

- [ ] **Step 5: Conferir que os estados reais continuam carregando (só leitura)**

Run: `for f in .agent-state/*/tasks/*/state.toml; do python3 scripts/state_lint.py "$f" >/dev/null || echo "FAIL $f"; done`
Expected: nenhuma linha `FAIL` causada por `host`/`platform` (falhas preexistentes de outras invariantes, se houver, são registradas no receipt como preexistentes, não corrigidas aqui).

- [ ] **Step 6: Commit (só com autorização)**

```bash
git add scripts/state/model.py scripts/state/__init__.py scripts/state/__main__.py scripts/state_lint.py scripts/handoff_sync.py tests/test_state_model.py tests/test_state_lint.py tests/test_state_cli.py tests/test_preflight.py tests/fixtures/gate-tasks/task-a/state.toml tests/fixtures/gate-tasks/task-c/state.toml tests/fixtures/visible-sessions/state.toml
git commit -m "refactor(state): drop codex platform and host from schema"
```

---

### Task 3: instruções carregadas pelo runtime

**Owner:** Marina (configuração/documentação geral pequena).

**Files:**
- Modify: `AGENTS.md:10`, `AGENTS.md:25`, `AGENTS.md:28`
- Modify: `.claude/skills/task-execution/SKILL.md:42`
- Modify: `.claude/instructions/kit-tooling.md:3`

**Interfaces:** nenhuma.

- [ ] **Step 1: Aplicar as substituições exatas**

| Arquivo | Trecho atual | Novo trecho |
|---|---|---|
| `AGENTS.md:10` | `Codex uses \`<kit_root>/.codex/instructions/\` and \`.agents/skills/\`; Claude uses \`<kit_root>/.claude/instructions/\` and \`.claude/skills/\`.` | `Use \`<kit_root>/.claude/instructions/\` and \`.claude/skills/\`.` |
| `AGENTS.md:25` | `Use native visible sessions: Codex desktop \`create_thread\` in the kit project's explicit \`local\` environment; Claude \`claude --bg --agent <role>\` from the kit.` | `Use native visible sessions: \`claude --bg --agent <role>\` from the kit.` |
| `AGENTS.md:28` | ` Codex keeps the project's local approval controls unchanged.` | *(remover a frase)* |
| `task-execution/SKILL.md:42` | ` Codex uses unchanged project-local approval controls.` | *(remover a frase)* |
| `kit-tooling.md:3` | `never inside \`.claude/\` or \`.codex/\`` | `never inside \`.claude/\`` |

- [ ] **Step 2: Verificar**

Run: `grep -n -i "codex\|\.agents/" AGENTS.md CLAUDE.md .claude/`
Expected: nenhuma linha.

Run: `python3 scripts/kit_lint.py`
Expected: todas as linhas `PASS`.

- [ ] **Step 3: Commit (só com autorização)**

```bash
git add AGENTS.md .claude/skills/task-execution/SKILL.md .claude/instructions/kit-tooling.md
git commit -m "docs(agents): Claude Code as the only runtime"
```

---

### Task 4: documentação humana e notas históricas

**Owner:** Marina.

**Files:**
- Modify: `README.md` (linhas 22, 26, 63, 78–82, 88, 105, 137–146, 150, 311, 319, 336–337)
- Modify: `docs/agent-workflow.md` (linhas 112, 114–134, 162, 187, 193, 195)
- Modify (só a linha de nota no topo, logo após o título): `docs/analise-scripts-apoio-marina.md`, `docs/plano-estado-estruturado-e-grafos.md`, `docs/plano-memoria-por-projeto.md`, `docs/analise-melhorias-complementares-2026-10.md`, `docs/plano-melhorias-tooling-2026-10.md`

**Interfaces:** nenhuma.

- [ ] **Step 1: `README.md`**

- L22: `# Kit de agentes multi-repositório para Claude Code`.
- L26: remover `; Codex lê \`AGENTS.md\`, \`.codex/agents/\` e \`.agents/skills/\``.
- L63: remover a linha da tabela `| Codex desktop | … |`.
- L78–82: remover a subseção `### Codex` com seu bloco de código.
- L88: remover ` e [recursos do Codex](https://learn.chatgpt.com/docs/features)`.
- L105: remover ` Codex: \`create_thread\` no ambiente \`local\` do projeto.`
- L137–146: trocar a seção inteira por:

```markdown
## Configuração nativa

| Camada | Claude Code |
|---|---|
| Entrada | `CLAUDE.md`, que importa `AGENTS.md` |
| Perfis | `.claude/agents/*.md` |
| Skills sob demanda | `.claude/skills/` |
| Instruções de domínio (carga explícita) | `.claude/instructions/` |

As instruções de domínio são escolhidas por responsabilidade do módulo, não por extensão: backend TypeScript não carrega instruções Angular, e Go ETL não carrega automaticamente as de Go API. Sessões independentes usam o modelo configurado pelo usuário. Os perfis não desativam controles de permissão do runtime. Até 2026-10 o kit também mantinha cópias para Codex; elas foram removidas (ver `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`).
```

- Sumário (L28–40): trocar o item `[Configurações nativas por plataforma](#configurações-nativas-por-plataforma)` por `[Configuração nativa](#configuração-nativa)`.
- L150: remover ` No Codex, use \`$nome-da-skill\` no prompt.`
- L311: trocar `que checa paridade \`.codex\`/\`.claude\`, identidade de skills,` por `que checa os perfis em \`.claude/agents\`, a ausência de diretórios de outro runtime,`.
- L319: trocar `Paridade de perfis \`.codex\`↔\`.claude\`, identidade de skills,` por `Perfis \`.claude/agents\`, ausência de \`.codex/\`/\`.agents/\`,`.
- L336: `| \`.claude/skills/*/SKILL.md\` | Texto completo de cada skill, com templates e referências |`.
- L337: `| \`.claude/instructions/\` | Instruções de domínio por responsabilidade de módulo |`.
- Tabela "Documentação relacionada": acrescentar as linhas da análise e do plano de 2026-10-25 (`docs/analise-marina-executavel-e-exclusividade-claude-2026-10.md`, `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`).

- [ ] **Step 2: `docs/agent-workflow.md`**

- L112: `` `native.platform` is `claude` or `unavailable`; the last requires a non-empty `reason` and is how the disclosed main-session fallback (above) is represented structurally rather than only in prose. ``
- L114–134: remover a seção `## Codex desktop` inteira.
- L162: remover `, and [Codex features](https://learn.chatgpt.com/docs/features)` e a frase `Exact Codex tool names/arguments above come from the installed desktop schemas, not a claim that the public features page documents that API.`
- L187: `| Native runtime | Confirm profile discovery and target access in Claude Code from the kit root. |`
- L193: `Static checks cover profile frontmatter, the absence of other runtimes' directories, native profile paths, no role delegation through Agent, and no conflicting fallback/blanket no-write rules. These do not replace real execution.`
- L195: trocar `execute in each platform an implementation` por `execute in Claude Code an implementation`.

- [ ] **Step 3: Nota histórica**

Em cada um dos cinco documentos listados, inserir, na linha logo abaixo do título `# …`, uma linha em branco seguida de:

```markdown
> Contexto histórico: o kit era dual Codex/Claude até 2026-10; referências a `.codex/`, `.agents/` e `native.platform = "codex"` neste documento descrevem esse período.
```

Os dois últimos documentos da lista não estão rastreados pelo Git: editar só essa linha e não incluí-los no `git add`.

- [ ] **Step 4: Verificar**

Run: `grep -rn -i "codex" README.md docs/agent-workflow.md`
Expected: só a menção histórica da seção "Configuração nativa" do README.

Run: `python3 scripts/kit_lint.py`
Expected: todas as linhas `PASS` (inclui `git_diff_check`).

- [ ] **Step 5: Commit (só com autorização)**

```bash
git add README.md docs/agent-workflow.md docs/analise-scripts-apoio-marina.md docs/plano-estado-estruturado-e-grafos.md docs/plano-memoria-por-projeto.md
git commit -m "docs: Claude Code as the only runtime; mark Codex-era docs as historical"
```

---

### Task 5: verificação final da F0

**Owner:** Marina, com revisão independente do `reviewer` sobre o diff das Tasks 1–4.

- [ ] **Step 1: Suíte e lint**

Run: `python3 scripts/kit_lint.py`
Expected: 6 linhas `PASS` (`agent_profiles`, `no_foreign_runtime`, `git_diff_check`, `cli_version_headers`, `state_lint`, `unittest_suite`).

- [ ] **Step 2: Varredura de Codex**

Run: `git grep -l -i "codex" -- . ':!docs/analise-*' ':!docs/plano-*'`
Expected: exatamente estes arquivos, todos por nota histórica, guarda ou teste de regressão: `README.md`, `scripts/kit_lint.py`, `scripts/state/model.py`, `tests/fixtures/visible-sessions/state.toml`, `tests/test_kit_lint.py`, `tests/test_preflight.py`, `tests/test_state_cli.py`, `tests/test_state_model.py`. Qualquer outro arquivo é resto a remover.

- [ ] **Step 3: Preservação**

Run: `git status --short`
Expected: `scripts/gate.py` e `tests/test_gate.py` com as mesmas mudanças de antes da F0 (comparar com `git diff --stat` registrado no checkpoint antes da Task 1), e os documentos não rastreados continuam não rastreados.

- [ ] **Step 4: Receipt do reviewer**

O `reviewer` confere o diff das Tasks 1–4 contra a seção 2 da spec e a Review Focus acima, com verdict `PASS`, `PASS_WITH_RISKS` ou `FAIL`.

---

## Execução neste kit

`AGENTS.md` define como o trabalho roda aqui, e isso restringe as opções genéricas da skill:

- Tasks 1 e 2 (código em `scripts/`/`tests/`) vão para o `kit-tooling` em **sessões visíveis** (`claude --bg --agent kit-tooling`), uma por task, em sequência, com handoff/receipt em `.agent-state/github-copilot-fullstack-kit/tasks/f0-exclusividade-claude/` e gate de Git entre elas. Subagentes nativos (`Agent`) não podem assumir papéis de especialista.
- Tasks 3 e 4 ficam com a Marina na sessão principal.
- Task 5 inclui uma sessão visível do `reviewer` (revisão obrigatória por mudança de contrato de estado).
- Se sessões visíveis estiverem indisponíveis, o fallback é a sessão principal com o aviso `delegação visível indisponível: <motivo>; especialidade kit-tooling assumida na sessão principal`; isso não é revisão independente.
