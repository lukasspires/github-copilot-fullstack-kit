# F4 — Runner, juíza e `marina run/status/stop`: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` em sessão visível (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Rodar sem supervisão uma cadeia implementação → revisão → correção → revisão dentro de um envelope aprovado. O runner observa o manager, chama `decide`, abre nós pelo caminho já existente (gate → `state add` → handoff → preflight → launch), consulta a juíza headless só nos casos ambíguos e para com motivo registrado.

**Architecture:**
- `scripts/marina/handoff_gen.py` gera o handoff canônico de cada nó a partir dos templates de estágio do envelope e dos receipts anteriores.
- `scripts/marina/judge.py` chama `claude -p` com o perfil `marina-judge`, só com `Read`, e lê a decisão de `structured_output`.
- `scripts/marina/runner.py` é o laço: trava, observações, `decide`, execução de uma ação, registro. Todo I/O passa por um `RunnerDeps` injetável.
- `cli.py` ganha `run`, `status` e `stop`.
- `AGENTS.md`, `docs/agent-workflow.md` e `.claude/instructions/kit-tooling.md` passam a permitir abertura automática de nós só dentro de um envelope aprovado, e abrem a exceção da juíza.

**Tech Stack:** Python ≥ 3.11 stdlib (`subprocess`, `json`, `hashlib`, `os`, `shlex`, `traceback`, `unittest`); Claude Code CLI 2.1.306.

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md): seções 3.1, 3.2 ("Proveniência"), 3.3 (laço, "Abertura de nó", "Gate de Git", "Contrato da juíza", "Encerramento"), 3.6 e 3.7, e a linha F4 da seção 4. Evidência da juíza: [docs/achados-f1-spike-hooks-e-juiza-2026-10.md](achados-f1-spike-hooks-e-juiza-2026-10.md), H7–H9, X1 e X5. Base: [docs/plano-f3-envelope-e-decide-2026-10.md](plano-f3-envelope-e-decide-2026-10.md).

## Global Constraints

- Python ≥ 3.11, só stdlib, sem dependência nova.
- Todo `claude` filho roda com `stdin=subprocess.DEVNULL` (F1, X1). Os módulos que chamam o CLI (`judge.py`, `runner.py`) declaram `Minimum tested Claude CLI version: 2.1.306` no docstring.
- Testes nunca chamam o CLI real, o Git real de outro repositório nem o `.agent-state/` real. Manager, subprocessos, Git, relógio, `sleep`, pid e juíza são injetados.
- O runner nunca responde a uma aprovação nativa, nunca usa `bypassPermissions` nem `--permission-prompts none`, nunca usa `--resume`, `--continue` ou `--fork-session`, nunca arquiva nem apaga sessões e nunca cria papel, aresta, alvo ou allowlist fora da expansão do envelope. Nós abertos pelo runner levam `allowlist = envelope.allowlist`, exatamente.
- Uma única ação por iteração. O runner nunca abre um nó sem antes rodar `gate.evaluate_gate` para ele, e nunca abre um writer com outro writer ativo.
- Escrita em tempo de execução só dentro de `.agent-state/<projeto>/tasks/<tarefa>/`: `state.toml`, handoffs gerados, `git-after-NN.txt`, `marina-run.log`, `judge-calls.jsonl`, `.marina-run.lock`, `.marina-run.stop` e a seção gerada no `checkpoint.md`.
- Git é só leitura (`status`, `diff`, `rev-parse`), como pede `.claude/instructions/kit-tooling.md`.
- `scripts/gate.py` e `tests/test_gate.py` têm mudanças locais, sem commit, de outra tarefa. Esta fase não toca nesses arquivos. O hash dessas mudanças sem números de linha (`git diff scripts/gate.py tests/test_gate.py | grep -v -e '^@@' -e '^index ' | sha256sum`) deve continuar `539ee3ee92d5bf11531c32336c321b205c0908ed426ce0647e4bbede74fdfcd0`.
- Branch de trabalho: `feat/f4-runner-juiza`, criado a partir de `main` (`2153499`) antes da Task 1.

## Decisões deste plano

Pontos que a spec deixa em aberto ou em que ela diverge do código.

1. **Os handoffs do envelope são templates.** O handoff canônico de um nó (`NN-<papel>-handoff.md`) é sempre gerado pelo `handoff_gen`. Se o template tivesse o mesmo nome do handoff canônico, a geração sobrescreveria um arquivo coberto pelo hash, e a execução pararia com `envelope_changed`. Por isso o `validate_envelope` passa a recusar templates com nome canônico (`^\d{2}-[a-z0-9-]+-(handoff|receipt)\.md$`) e a exigir as seções `Objective`, `Write scope` e `Acceptance criteria`. O exemplo da spec (`01-java-backend-handoff.md`) vira `stage-1-handoff-template.md`, e os testes da F3 que usam o nome antigo mudam junto.
2. **O `gate` roda antes do `state add`.** A spec lista `state add → handoff_gen → preflight → gate → launch`, mas o `gate` avalia um nó *proposto*, que ainda não existe no `state.toml` (contrato do `scripts/gate.py`). A ordem fica: Gate de Git (writers) → `gate.evaluate_gate` → `state add` → `handoff_gen` → `launch_claude.run_launch`, que roda o preflight.
3. **O primeiro writer não tem diff para reconhecer.** O Gate de Git compara o estado atual com o `git-after` do writer anterior. Antes do primeiro writer não existe writer anterior, e a aprovação do envelope com os branches conta como reconhecimento.
4. **O `git-after` é mais forte que o `git-before`.** O `git-before` do preflight guarda `status --short` e `diff --stat`, e um `--stat` igual não prova conteúdo igual. O `git-after` e a comparação do Gate de Git usam `common.git_snapshot`: `git status --porcelain=v1 --untracked-files=all`, o sha256 de `git diff HEAD --binary` e o sha256 do conteúdo de cada arquivo não rastreado.
5. **As decisões da juíza ficam num registro próprio.** Elas não são transições G2, então não cabem como evento. Cada chamada (válida ou falha) vira uma linha JSON em `judge-calls.jsonl`.
   - `judge_calls_used` é o número de linhas desse arquivo, então a cota sobrevive a reinícios.
   - A última resposta válida para a mesma pergunta é reaproveitada como `judge_answer` na retomada.
   - Quando a resposta da juíza abre o próximo nó, o evento `reserved` desse nó usa `by = "marina-judge"`, com a pergunta e a resposta resumidas em `note` (spec 3.2, "Proveniência").
6. **Proveniência dos eventos.** `state add` e `state set` feitos pelo runner usam `by = "marina-run"`. Preflight, launch e observação do manager mantêm os próprios `by` (`preflight`, `launch-claude`, `status`), porque são as ferramentas existentes que gravam esses eventos.
7. **O runner só dorme depois de `wait`.** Uma `transition` ou um `launch` é seguido imediatamente da próxima iteração; dormir depois de cada transição triplicaria o tempo por nó sem ganho.
8. **`marina stop` usa um arquivo, não sinal.** `marina stop` cria `.marina-run.stop`. O runner verifica esse arquivo no começo de cada iteração e para com `stop_requested`. Assim funciona igual para um runner destacado (F5) e para um em primeiro plano.
9. **A allowlist do envelope precisa servir ao reviewer.** Nós `revisa` usam a mesma allowlist do envelope. O runner não acrescenta `git diff`/`git status` por conta própria, porque uma allowlist diferente da aprovada para com `envelope_changed`. O resumo do `marina approve` e o `agent-workflow.md` dizem isso.
10. **`marina-judge` nunca é papel de estágio.** O perfil existe em `.claude/agents/`, e `mode_for_role` o classificaria como writer. O `validate_envelope` passa a recusar `marina` e `marina-judge`.
11. **Orçamento da juíza.** A spec manda passar `--max-budget-usd`, mas não diz o valor. A constante `JUDGE_MAX_BUDGET_USD = "0.50"` repete o valor usado na F1. Com `judge_max_calls = 4`, o pior caso fica perto de US$ 2 por execução (F1, X5).

## Review Focus

1. **Queda no meio da abertura de um nó.** Se o runner cai entre o `state add` e o launch, o nó fica `reserved`/`prepared`. Ao reiniciar, o runner deve parar com `node_not_launched` sem criar um segundo nó. Teste: `test_restart_with_reserved_node_stops_without_new_node` (Task 4).
2. **Trava existente.** O runner recusa quando a trava pertence a um pid vivo. Com `--recover`, ele só assume uma trava de pid morto se o manager não mostrar nenhuma sessão da tarefa em `working`/`waiting_approval`. Testes: `test_live_lock_refuses`, `test_recover_dead_lock_with_working_session_refuses`, `test_recover_dead_lock_takes_over` (Task 4).
3. **Mudança alheia entre writers.** Inclui mudança só no conteúdo de um arquivo não rastreado. O runner deve parar com `foreign_change` antes de abrir o próximo writer. Testes: `test_foreign_change_before_next_writer_stops` e `test_untracked_content_change_is_foreign` (Tasks 2 e 4).
4. **Juíza falhando de qualquer jeito.** Os casos são saída sem `structured_output`, opção não oferecida, timeout, `is_error`/orçamento estourado e cota esgotada contando chamadas de uma execução anterior. Todos devem dar `stop(judge_failed)` sem abrir nó. Testes na Task 3 e `test_judge_quota_counts_previous_runs` (Task 4).
5. **Envelope editado durante a execução.** Inclui editar um template. A iteração seguinte deve parar com `envelope_changed` antes de qualquer launch. Teste: `test_template_edited_mid_run_stops_before_launch` (Task 4).

---

### Task 1: templates de estágio e `handoff_gen.py`

**Files:**
- Create: `scripts/marina/handoff_gen.py`
- Modify: `scripts/marina/envelope.py` (`validate_envelope`: decisões 1 e 10)
- Modify: `tests/test_marina_envelope.py`, `tests/test_marina_cli.py` (nome e conteúdo do template)
- Test: `tests/test_marina_handoff_gen.py` (novo)

**Interfaces:**
- Consumes:
  - `scripts.handoff_sync._section`, `validate_handoff` e `write_atomic`;
  - `StateDoc` e `Assignment`.
- Produces:
  - `TEMPLATE_REQUIRED = ("Objective", "Write scope", "Acceptance criteria")` e `TEMPLATE_OPTIONAL = ("Target instructions to read explicitly", "Checks and workdir", "Preservation")`;
  - `CANONICAL_NAME_RE = re.compile(r"^\d{2}-[a-z0-9-]+-(handoff|receipt)\.md$")`;
  - `template_errors(text: str) -> list[str]`: uma mensagem para cada seção obrigatória ausente ou vazia;
  - `render_stage_handoff(doc, a, *, kit_root: Path, template_text: str) -> str`, para `inicia` e `prossegue`;
  - `render_review_handoff(doc, a, *, kit_root: Path, writer_handoff_text: str) -> str`, para `revisa`;
  - `render_correction_handoff(doc, a, *, kit_root: Path, template_text: str) -> str`, para `corrige`.
- O texto gerado por qualquer `render_*` passa em `handoff_sync.validate_handoff(text, a, kit_root)`. A ordem das seções é:
  1. `# <title>`;
  2. `## Objective`;
  3. `## Role and profile`, com `- **Role:** <role>` e `- **Absolute profile (read explicitly):** \`<kit_root>/.claude/agents/<role>.md\``;
  4. `## Roots`, com `kit_root` e um `target_root` por alvo;
  5. `## Target instructions to read explicitly`, `## Context`, `## Write scope`, `## Acceptance criteria`, `## Checks and workdir`, `## Preservation`;
  6. `## Assignment metadata`, com Task, nn, Predecessor, Edge, Type, `Receipt path (write here only)` absoluto e `Granted allowlist`;
  7. a linha final "Never continue, fork, or resume this assignment…", igual à dos handoffs atuais.
- Conteúdo por tipo:
  - **Revisão:**
    - `Objective`: "Revisão independente do nn=<W> (<role>, <edge>) do estágio <s>".
    - `Context`: os caminhos absolutos do handoff e do receipt do writer, e `git-before-<W>.txt`.
    - `Write scope`: `None. Read-only review; write only the receipt below.`
    - `Acceptance criteria`: os critérios copiados do handoff do writer, mais "Verdict `PASS`, `PASS_WITH_RISKS` ou `FAIL`, com achados (severidade, local, evidência, impacto, correção)".
  - **Correção:**
    - `Objective`: "Corrigir os achados do nn=<R> (FAIL)".
    - `Context`: o receipt absoluto do reviewer `R` e o handoff e o receipt do writer revisado.
    - `Write scope` e `Acceptance criteria`: os do template do estágio, mais "cada achado do receipt nn=<R> corrigido ou justificado no receipt".
- No `validate_envelope`:
  - recusa `stages[i] handoff '<x>' uses a canonical assignment file name; name templates like stage-<n>-handoff-template.md`;
  - inclui cada erro de `template_errors` prefixado com `stages[i] handoff '<x>': `;
  - recusa o papel `marina-judge` com a mesma mensagem de `marina`;
  - em `format_summary`, logo depois da lista da allowlist, acrescenta a linha `  (reviewer and correction nodes use this same allowlist)` (decisão 9).

- [ ] **Step 1: Write the failing tests.**
  - Em `tests/test_marina_handoff_gen.py`, o fixture monta um `StateDoc` em memória com `kit_root = KIT_ROOT` e alvo `/abs/api`, mais um template com as três seções e `Checks and workdir`.
  - **Testes:**
    - `test_template_errors`: ausência de cada seção obrigatória e seção vazia geram um erro cada; o template completo gera `[]`.
    - `test_stage_handoff_passes_validate_handoff`: para `inicia` e para `prossegue`.
    - `test_stage_handoff_copies_template_sections`: o texto do template aparece em `Objective`, `Write scope`, `Acceptance criteria` e `Checks and workdir`.
    - `test_review_handoff_passes_validate_handoff_and_references_writer`: contém os caminhos absolutos do handoff e do receipt do writer, `git-before-01.txt`, os critérios do writer e `Verdict`.
    - `test_correction_handoff_references_fail_receipt`.
    - `test_metadata_mirrors_assignment`: o `Receipt path` é `<kit_root>/<receipt>`, e o `Granted allowlist` lista cada entrada entre crases.
    - `test_render_is_deterministic`: duas chamadas devolvem textos iguais.
  - Em `tests/test_marina_envelope.py`:
    - troque `HANDOFF` por `stage-1-handoff-template.md`, com as três seções;
    - acrescente `test_canonical_template_name_refused` (`01-java-backend-handoff.md`);
    - acrescente `test_template_without_sections_refused`;
    - acrescente `marina-judge` em `test_reader_or_unknown_or_marina_role_refused`;
    - em `test_summary_lists_every_field`, exija `same allowlist`.
  - Em `tests/test_marina_cli.py`, mesma troca de nome e conteúdo.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_handoff_gen tests.test_marina_envelope -v`. Esperado: `ModuleNotFoundError` em `handoff_gen`, e os novos testes de envelope falhando.
- [ ] **Step 3: Implement** `handoff_gen.py` e as mudanças no `validate_envelope`.
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_handoff_gen tests.test_marina_envelope tests.test_marina_cli tests.test_marina_decide -v` → OK.

### Task 2: retrato forte do Git e branch atual

**Files:**
- Modify: `scripts/common.py`
- Test: `tests/test_common.py` (classe nova `GitSnapshotTests`)

**Interfaces:**
- Produces:
  - `git_snapshot(target: str, *, timeout: int = 15, runner: Callable[..., str] = _run_git, read_bytes: Callable[[Path], bytes] = Path.read_bytes) -> str`. O texto tem três blocos:
    1. `# git status --porcelain=v1 --untracked-files=all` e a saída;
    2. `# git diff HEAD --binary sha256` e o hash;
    3. `# untracked sha256` e uma linha `<sha256>  <path>` por arquivo `??`, em ordem de caminho.
  - `git_current_branch(target: str, *, timeout: int = 15, runner=_run_git) -> str`: saída de `rev-parse --abbrev-ref HEAD`, sem espaços nas pontas.

- [ ] **Step 1: Write the failing tests**, com um `runner` falso que responde por argumento e um `read_bytes` falso:
  - `test_snapshot_changes_with_diff_content`: o mesmo `--stat` com conteúdo de diff diferente gera retratos diferentes;
  - `test_untracked_content_change_is_foreign`: o mesmo `status` com bytes diferentes num arquivo `??` gera retratos diferentes;
  - `test_snapshot_is_stable`;
  - `test_current_branch_strips`;
  - `test_git_calls_are_read_only`: todos os `args` recebidos pelo `runner` começam com `status`, `diff` ou `rev-parse`.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_common -v`. Esperado: `AttributeError`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_common -v` → OK.

### Task 3: `judge.py` e o perfil `marina-judge`

**Files:**
- Create: `scripts/marina/judge.py`
- Create: `.claude/agents/marina-judge.md`
- Test: `tests/test_marina_judge.py` (novo)

**Interfaces:**
- Consumes: `Question` (`scripts.marina.decide`).
- Produces:
  - `JUDGE_MAX_BUDGET_USD = "0.50"` e `JUDGE_TIMEOUT_S = 180`;
  - `class JudgeFailed(RuntimeError)`;
  - `@dataclass(frozen=True) JudgeAnswer(decision: str, reason: str)`;
  - `build_schema(options: tuple[str, ...]) -> dict`, que devolve `{"type": "object", "properties": {"decision": {"type": "string", "enum": [...options]}, "reason": {"type": "string", "maxLength": 200}}, "required": ["decision", "reason"], "additionalProperties": False}`;
  - `build_prompt(question: Question, paths: list[str]) -> str`, com o tipo da pergunta, o nn, as opções, uma linha por caminho absoluto e a instrução de escolher exatamente uma opção, sem editar, lançar nem coordenar;
  - `build_argv(question, paths, *, cli: str = "claude") -> list[str]`, que devolve `[cli, "-p", "--agent", "marina-judge", "--tools", "Read", "--permission-mode", "dontAsk", "--json-schema", <schema JSON compacto>, "--output-format", "json", "--max-budget-usd", JUDGE_MAX_BUDGET_USD, "--no-session-persistence", "--", <prompt>]`;
  - `ask(question: Question, paths: list[str], *, run_subprocess=subprocess.run, timeout: int = JUDGE_TIMEOUT_S) -> JudgeAnswer`:
    - chama `run_subprocess(argv, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)`;
    - levanta `JudgeFailed` em: timeout (`subprocess.TimeoutExpired`), código diferente de zero, stdout que não é JSON-objeto, `is_error` verdadeiro, `subtype` diferente de `"success"`, `structured_output` ausente ou que não seja objeto, `decision` fora de `question.options`, `reason` que não seja string ou passe de 200 caracteres.
- `.claude/agents/marina-judge.md`:
  - o frontmatter tem `name: marina-judge`, `description` e `model: inherit`, **sem** `tools` (F1, H7);
  - o corpo diz que a juíza só lê os caminhos dados, escolhe uma das opções e explica em até 200 caracteres, e que nunca edita, lança, coordena nem delega.

- [ ] **Step 1: Write the failing tests:**
  - `test_argv_shape`:
    - `--tools` seguido de `Read`;
    - `--agent marina-judge`;
    - `--no-session-persistence` presente;
    - o prompt depois de `--`;
    - `--allowedTools` e `bypassPermissions` ausentes.
  - `test_schema_enum_is_options`.
  - `test_valid_answer`: o stdout `{"type": "result", "subtype": "success", "is_error": false, "structured_output": {"decision": "continue", "reason": "ok"}}` dá `JudgeAnswer("continue", "ok")`; o subprocesso falso recebe `stdin=subprocess.DEVNULL`.
  - `test_missing_structured_output_fails`: o caso F1 H7, com `result` em prosa.
  - `test_option_not_offered_fails`, `test_timeout_fails`, `test_nonzero_exit_fails`.
  - `test_is_error_or_budget_subtype_fails`: `subtype: "error_max_budget_usd"`.
  - `test_invalid_json_fails`, `test_long_reason_fails`.
  - `test_profile_has_no_tools_list`: o frontmatter de `.claude/agents/marina-judge.md` não tem a chave `tools`.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_judge -v`. Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Implement** `judge.py` e o perfil.
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_judge tests.test_kit_lint -v` → OK. O `check_agent_profiles` do `kit_lint` precisa aceitar o perfil novo.

### Task 4: `runner.py`, o laço

**Files:**
- Create: `scripts/marina/runner.py`
- Test: `tests/test_marina_runner.py` (novo)

**Interfaces:**
- Consumes:
  - `decide`, `Observations`, `Decision`, `Question` e `NodeSpec` (F3);
  - `envelope.envelope_from_doc`, `validate_envelope` e `compute_hash` (F3 e Task 1);
  - `handoff_gen.render_*` e `handoff_sync.write_atomic` (Task 1);
  - `common.git_snapshot` e `git_current_branch` (Task 2);
  - `judge.ask`, `JudgeFailed` e `JudgeAnswer` (Task 3);
  - `gate.evaluate_gate` e `load_task_docs`;
  - `launch_claude.run_launch`, `preflight.run_preflight` e `status_claude.find_task_sessions`, `classify_session` e `record_observed_transition`;
  - `receipt_lint.lint_file`;
  - `scripts.state` (`read_state`, `write_state`, `add_assignment`, `append_event`).
- Produces:
  - `LOCK_NAME = ".marina-run.lock"`, `STOP_NAME = ".marina-run.stop"`, `LOG_NAME = "marina-run.log"`, `JUDGE_LEDGER = "judge-calls.jsonl"`;
  - `class RunRefused(RuntimeError)`;
  - `@dataclass RunnerDeps`, com os campos:
    - `list_sessions`, `run_subprocess` (para o launch), `run_preflight`;
    - `git_snapshot`, `git_branch`;
    - `judge: Callable[[Question, list[str]], JudgeAnswer]`, `notify: Callable[[str], None]`;
    - `sleep`, `monotonic`, `now: Callable[[], datetime]`;
    - `pid_alive: Callable[[int], bool]`, `getpid`.
    - `default_deps()` liga cada campo ao real (`os.kill(pid, 0)` para `pid_alive`).
  - `@dataclass RunResult(outcome: str, reason: str, created: list[int], judge_decisions: list[str])`, com `outcome ∈ {"done", "stop"}`.
  - `run(state_path: Path, *, kit_root: Path, interval: float, max_duration: float, notify_cmd: str | None = None, recover: bool = False, deps: RunnerDeps) -> RunResult`.
  - `request_stop(state_path: Path) -> bool`: cria `.marina-run.stop`; devolve `False` se não há trava.
  - `status_lines(state_path: Path, *, pid_alive) -> list[str]`: tarefa, trava (pid e se está vivo), aprovação do envelope e uma linha por nó (`nn role edge state`), seguidas das últimas 5 linhas do log.

Comportamento de `run`, em ordem:

1. **Trava.** `interval > 0` e `max_duration > 0`, ou `ValueError`.
   - A trava é criada com `os.open(..., O_CREAT | O_EXCL)` e contém o JSON `{"pid", "started_at"}`.
   - Se a trava já existe, `RunRefused`. A exceção é `--recover` com o pid da trava morto e nenhuma sessão do manager com título `<slug> —` em `working`/`waiting_approval`; nesse caso o runner assume a trava.
   - A trava é sempre solta num `finally`.
2. **Duração efetiva.** `min(max_duration, parse_duration(envelope.max_duration))`. Ao passar desse tempo, `stop("max_duration")`. Envelope ausente ou inválido no início segue para o `decide`, que para com o motivo próprio.
3. **Cada iteração:**
   1. `.marina-run.stop` presente → apaga o arquivo e `stop("stop_requested")`.
   2. Relê o `state.toml`.
   3. **Observa o nó atual:**
      - `launched`, `working` ou `waiting_approval` com `native.id`: classifica a sessão do manager por `native_id` e chama `record_observed_transition`. Manager indisponível conta como sem observação.
      - `uncertain`: procura uma sessão com `name == title` e `cwd == kit_root`; encontrou → `manager_match = "found"`; manager disponível e nenhuma sessão → `"absent"`.
   4. **Writer em `finished` sem `git-after-NN.txt`:** grava o arquivo com `git_snapshot` de cada alvo.
   5. **Monta `Observations`:**
      - o hash recalculado (`OSError` vira erro em `envelope_errors`);
      - `envelope_errors = validate_envelope(...)`;
      - `branches` com `git_branch` de cada alvo;
      - `receipt_exists` para `finished`;
      - `receipt_lint = lint_file(receipt, handoff=handoff)` para `receipt_received`, com os erros convertidos em tupla;
      - `notified`: o runner lembra o `(nn, número de eventos waiting_approval)` já notificado;
      - `judge_calls_used` = linhas do registro da juíza;
      - `judge_answer` = última linha válida do registro para a pergunta atual.
   6. **`decide` e a ação:**
      - `wait`: notifica se `notify` e `notify_cmd` (`shlex.split`, sem shell, `stdin=DEVNULL`, timeout 30 s, falha só registrada no log) e depois `sleep(interval)`.
      - `transition`: `append_event(by="marina-run")`; em `receipt_validated`, grava `receipt_summary` antes; depois `write_state`.
      - `launch`: abertura de nó (abaixo).
      - `ask_judge`:
        1. os caminhos passados à juíza são o receipt e o handoff do reviewer e o receipt do writer revisado;
        2. a chamada (`JudgeFailed` vira linha `ok: false`) é registrada no ledger;
        3. em falha, `stop("judge_failed")`; em sucesso, chama `decide` de novo na mesma iteração, com `judge_answer`.
      - `stop` ou `done`: encerra.
   7. Exceção não prevista → `stop("internal_error")`, com o traceback no log.
4. **Abertura de nó:**
   1. Writer: Gate de Git. Se `git_snapshot` de cada alvo difere do `git-after` do último writer `accepted`, `stop("foreign_change")` (decisão 3 para o primeiro writer).
   2. `gate.evaluate_gate(..., git_diff_acknowledged=True, user_decided=False, sibling_docs=load_task_docs(tasks_root, exclude_slug=slug), list_sessions=deps.list_sessions)`; recusado → `stop("gate_refused: <primeira razão>")`.
   3. `add_assignment(..., allowlist=env.allowlist, platform="claude", by="marina-run" ou "marina-judge" (decisão 5))` e `write_state`.
   4. Renderiza o handoff conforme a aresta e grava com `write_atomic`.
   5. `run_launch(state_path, nn, kit_root=kit_root, run_preflight=deps.run_preflight, run_subprocess=deps.run_subprocess)`. O resultado (`launched`, `preparation_failed`, `uncertain`) fica no estado e é tratado pelo `decide` na iteração seguinte.
5. **Encerramento.** O runner acrescenta ao `checkpoint.md` a seção `## Execução marina-run <started_at ISO>` com cinco linhas:
   - `- Envelope: sha256 \`<h>\`; intervalo <i>s; duração efetiva <d>s.`
   - `- Nós criados: <nn papel aresta (id)>, … | nenhum.`
   - `- Decisões da juíza: <nn kind → decision: reason>, … | nenhuma.`
   - `- Motivo de parada: done | stop(<reason>).`
   - `- Próxima ação: Marina — revisar o resultado e decidir commit.` em `done`, ou `Marina — decidir sobre <reason>.` em `stop`.

  Depois solta a trava.
- **Log.** Uma linha por iteração em `marina-run.log`: `<ISO> <kind> nn=<n> <to|reason>`, sem conteúdo de receipt.

- [ ] **Step 1: Write the failing tests** em `tests/test_marina_runner.py`.
  - **Fixture:**
    - um `kit_root` temporário com `.claude/agents/node-backend.md` e `reviewer.md` copiados;
    - um repositório-alvo falso, de que só existem os caminhos; `git_snapshot` e `git_branch` são injetados;
    - a tarefa com envelope aprovado (`compute_hash` real), template `stage-1-handoff-template.md` e allowlist `["Bash(true)"]`;
    - `FakeManager`, com uma lista de sessões que o teste avança;
    - `FakeLaunch`, que imprime um id curto e registra o argv;
    - `run_preflight` real com `which`, `list_sessions` e `git_status_diff` falsos;
    - relógio e `sleep` falsos, em que `sleep` avança o relógio e chama um gancho do teste (por exemplo, fazer a sessão terminar e escrever o receipt a partir das fixtures `good-node-backend-receipt.md`/`good-reviewer-receipt.md`, adaptadas ao título e ao `__KIT_ROOT__`).
  - **Cadeia:**
    - `test_happy_chain_writer_review_done`:
      - `RunResult("done", …)` com `created == [1, 2]`;
      - nn=1 `inicia` e nn=2 `revisa`, ambos `accepted`;
      - eventos `by="marina-run"`;
      - `git-after-01.txt` existe;
      - a seção do checkpoint lista os dois nós e `done`;
      - a trava não existe mais.
    - `test_fail_then_correction_then_pass`: a cadeia 1 → FAIL → `corrige` → PASS termina `done` com `created == [1, 2, 3, 4]`; o handoff do nó 3 cita o receipt do nó 2.
    - `test_second_fail_stops`.
  - **Juíza:**
    - `test_pass_with_risks_judge_continue_opens_next_stage`: o evento `reserved` do novo nó é `by="marina-judge"`, e `judge-calls.jsonl` tem uma linha.
    - `test_judge_failure_stops` e `test_judge_quota_counts_previous_runs`: o ledger já tem uma linha, `judge_max_calls = 1`, a juíza não é chamada e o runner para com `judge_failed`.
  - **Proteções:**
    - `test_restart_with_reserved_node_stops_without_new_node`;
    - `test_live_lock_refuses`, `test_recover_dead_lock_with_working_session_refuses`, `test_recover_dead_lock_takes_over`;
    - `test_foreign_change_before_next_writer_stops`: o snapshot muda depois do writer 1 e antes do `corrige`;
    - `test_template_edited_mid_run_stops_before_launch`;
    - `test_branch_changed_stops`;
    - `test_stop_file_stops`;
    - `test_max_duration_stops`;
    - `test_waiting_approval_notifies_once_and_never_answers`: `notify` é chamado uma vez em duas iterações seguidas em `waiting_approval`, e nenhum subprocesso recebe `attach`;
    - `test_internal_error_stops_and_logs_traceback`;
    - `test_children_stdin_closed`: todo `run_subprocess` falso recebe `stdin=subprocess.DEVNULL`.
  - **Funções auxiliares:** `test_request_stop_without_lock_returns_false` e `test_status_lines`.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_runner -v`. Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Implement** `runner.py`. O docstring cita a spec 3.3 e 3.6 e as decisões 2 a 8.
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_runner -v` → OK.

### Task 5: `marina run`, `status` e `stop` na CLI

**Files:**
- Modify: `scripts/marina/cli.py`, `scripts/marina/__main__.py` (docstring)
- Test: `tests/test_marina_cli.py`

**Interfaces:**
- Consumes: `runner.run`, `request_stop`, `status_lines`, `RunRefused` e `default_deps`.
- Produces:
  - `marina run <project> <task> --interval <s> --max-duration <dur> [--notify-cmd CMD] [--recover] [--kit-root PATH]`:
    - `--interval` e `--max-duration` são obrigatórios;
    - `--max-duration` usa o mesmo formato do envelope (`envelope.parse_duration`);
    - a saída é 0 em `done`, 1 em `stop`, em `RunRefused` ou em argumento inválido;
    - imprime uma linha final `marina run: <outcome> <reason>`.
  - `marina status <project> <task> [--kit-root PATH]`: imprime `status_lines`; saída 0, ou 1 sem `state.toml`.
  - `marina stop <project> <task> [--kit-root PATH]`: saída 0 quando criou o pedido, 1 quando não há execução em andamento.
  - A validação de slug e o caminho do state são os mesmos do `approve`. `main` aceita um parâmetro `deps` injetável para os testes.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_requires_interval_and_duration` (saída 1);
  - `test_run_bad_duration` (`"1d"`, saída 1);
  - `test_run_done_exit_0` e `test_run_stop_exit_1`, com `deps` falso;
  - `test_run_refused_when_locked` (saída 1);
  - `test_status_prints_nodes`;
  - `test_stop_without_run_exit_1` e `test_stop_creates_request`;
  - `test_bin_wrapper_help` passa a exigir `run`, `status` e `stop` no `--help`.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_cli -v`. Esperado: falha porque os subcomandos não existem.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_cli tests.test_marina_hooks -v` → OK.

### Task 6: regras do kit (Marina)

**Files:**
- Modify: `AGENTS.md`, `docs/agent-workflow.md`, `.claude/instructions/kit-tooling.md`, `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`

- [ ] **Step 1: Edições nas regras.**
  - **`AGENTS.md:3`:** depois de "never delegate to another coordinator", acrescentar: "the one exception is the read-only `marina-judge`, which `marina run` asks only to choose among options it already validated; it never edits, launches or coordinates".
  - **`AGENTS.md`, seção "Independent visible sessions":** acrescentar o item "Opening the next node is never automatic outside a human-approved envelope (`marina approve`); inside one, `marina run` opens only the nodes of the envelope's expansion, through the same gate, preflight and launch, and stops on anything else."
  - **`docs/agent-workflow.md:70`:** trocar "opening the next node is a separate G3 edge chosen by Marina, never automatic" por "opening the next node is a separate G3 edge chosen by Marina, never automatic outside a human-approved envelope (`marina approve`)".
  - **`docs/agent-workflow.md`, seção nova curta "Approved envelopes (`marina run`)"** depois da tabela G3, cobrindo:
    - os comandos `approve`, `run`, `status` e `stop`;
    - as regras: a allowlist do envelope também serve aos reviewers (decisão 9), os templates de estágio não usam nome canônico, e uma parada sempre deixa o motivo no checkpoint;
    - o que o runner nunca faz.
  - **`.claude/instructions/kit-tooling.md:11`:** trocar por "One launch/dispatch per script invocation; never chain a second writer automatically, except `marina run` inside a human-approved envelope, one node at a time."
  - **`.claude/instructions/kit-tooling.md:9`:** acrescentar a invocação da juíza (`claude -p --agent marina-judge --tools Read …`, stdin fechado) como chamada sancionada.
- [ ] **Step 2: Linha F4 da spec.** Acrescentar à seção 4 a nota "Executada em 2026-10 — ver `docs/plano-f4-runner-e-juiza-2026-10.md`" e, na 3.3, as decisões 1, 2 e 5 numa frase cada.
- [ ] **Step 3: Conferir.** `git grep -n "never automatic\." docs/agent-workflow.md` deve não encontrar nada, e `python3 scripts/kit_lint.py` deve passar.

### Task 7: verificação final

- [ ] `python3 -m unittest discover -s tests` → OK, com 423 testes mais os novos.
- [ ] `python3 scripts/kit_lint.py` → 6/6 PASS.
- [ ] O hash das mudanças preexistentes sem números de linha continua `539ee3ee…`, e `scripts/gate.py` e `tests/test_gate.py` não estão em nenhum diff desta fase.
- [ ] `grep -n "stdin=subprocess.DEVNULL" scripts/marina/judge.py scripts/marina/runner.py` encontra cada chamada a subprocesso.
- [ ] `bin/marina --help` mostra `approve`, `run`, `status` e `stop`.

## Execução

Mesmo modelo da F3:
- **Tasks 1 a 5:** código do `kit-tooling`. Rodam em sessão visível, ou na sessão principal com o aviso de fallback, se o usuário preferir.
- **Task 6:** documentação, feita pela Marina.
- **Reviewer:** em sessão visível no fim, lançado pelo `launch_claude`, porque a fase muda regras de coordenação e permissão.
- **Aceitação real:** com o CLI de verdade (spec 3.7) é da F6. Nesta fase o runner não é executado contra sessões reais.
- **Commits:** só com autorização explícita.
