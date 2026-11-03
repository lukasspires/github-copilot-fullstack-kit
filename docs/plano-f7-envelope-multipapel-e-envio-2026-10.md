# F7 — Envelope com vários papéis e aprovação no envio (`marina go`): plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Um plano pode encadear writers de papéis diferentes, cada estágio com alvos e allowlist próprios, e rodar `marina go` num TTY aprova o plano inteiro e dispara `marina run`.

**Architecture:**
- `scripts/marina/envelope.py` ganha escopo por estágio (`Stage.targets`, `Stage.allowlist`), `node_scope` e `approve_on_dispatch`.
- `scripts/state/model.py` e `scripts/state_lint.py` ganham a aresta `encadeia`.
- `scripts/marina/decide.py` escolhe `prossegue` ou `encadeia` pelo papel do estágio seguinte e confere o escopo de cada nó.
- `scripts/marina/runner.py` passa a fazer o Git gate sobre todos os alvos do envelope e expõe `run_argv`/`spawn_detached`.
- `scripts/marina/cli.py` ganha `go`.
- `AGENTS.md`, `docs/agent-workflow.md`, `README.md` e `task-execution` registram as duas mudanças de regra.

**Tech Stack:** Python ≥ 3.11 stdlib; Claude Code CLI 2.1.306+.

**Spec:** [docs/plano-marina-perguntas-plano-e-tui-2026-10.md](plano-marina-perguntas-plano-e-tui-2026-10.md), seções 3 e 5.

## Global Constraints

- Python ≥ 3.11, só stdlib, sem dependência nova.
- **Compatibilidade.** Um envelope cujos estágios têm só `role` e `handoff` continua válido e com o mesmo hash. `envelope_to_raw` só emite `targets`/`allowlist` de um estágio quando eles foram declarados.
- **Sem TTY, nada.** `marina go` e `marina approve` recusam sem TTY. Nenhuma ferramenta MCP grava aprovação.
- **Prazo do `go`.** O `go` espera `--grace` segundos (padrão `10`) antes de gravar a aprovação. Um `KeyboardInterrupt` nesse prazo devolve 1 sem escrever nada.
- **Escopo do nó.** Writers (`inicia`, `prossegue`, `encadeia`) recebem `targets`/`allowlist` do estágio. `revisa` e `corrige` recebem os do estágio com `review = "each_stage"` e os do envelope com `review = "final"`.
- **Mais de um papel exige `each_stage`.** Envelope com mais de um papel e `review = "final"` é inválido, com a mensagem contendo `each_stage`.
- **`encadeia`.** Exige predecessor writer `accepted`, `type = implementação` no nó e no predecessor, e papel **diferente** do predecessor. `prossegue` continua exigindo o mesmo papel.
- **Git gate.** `git-after-NN.txt` e o Git gate usam `env.targets`, na ordem do envelope.
- **Testes isolados.** Os testes nunca chamam o CLI real nem o `.agent-state/` real.

## Review Focus

1. Envelope antigo (sem escopo por estágio) com aprovação gravada antes desta fase: o hash não pode mudar, senão toda run em andamento para com `envelope_changed`. Teste: `test_hash_unchanged_for_stage_without_scope`.
2. Estágio cuja allowlist só nomeia alvos de outro estágio: tem de ser recusado, porque a sessão começa em kit_root. Teste: `test_stage_allowlist_must_name_a_stage_target`.
3. `go` rodado duas vezes com uma run viva: não pode abrir uma segunda run. Teste: `test_go_with_live_lock_does_not_spawn`.
4. Ctrl-C durante o prazo do `go`: nada é gravado. Teste: `test_dispatch_interrupt_writes_nothing`.
5. Correção de um estágio do meio num envelope de dois papéis: vai para o papel daquele estágio, com o escopo dele. Teste: `test_multi_role_fail_corrects_with_stage_role_and_scope`.

---

### Task 1: escopo por estágio no envelope

**Files:**
- Modify: `scripts/marina/envelope.py`
- Test: `tests/test_marina_envelope.py`

**Interfaces:**
- Produces:
  - `Stage(role: str, handoff: str, targets: tuple[str, ...] | None = None, allowlist: tuple[str, ...] | None = None)`;
  - `stage_targets(env, stage: int) -> tuple[str, ...]` e `stage_allowlist(env, stage: int) -> tuple[str, ...]` (estágio 1-based, com fallback para o envelope);
  - `node_scope(env, stage: int, edge: str) -> tuple[tuple[str, ...], tuple[str, ...]]`;
  - `WRITER_STAGE_EDGES = ("inicia", "prossegue", "encadeia")`.

- [ ] **Step 1: Testes.**
  - `test_stage_scope_round_trip`: um estágio com `targets`/`allowlist` passa por `parse_envelope` → `envelope_to_raw` sem perda.
  - `test_hash_unchanged_for_stage_without_scope`: `envelope_to_raw` de um estágio sem escopo tem exatamente as chaves `role` e `handoff`.
  - `test_bad_stage_scope_refused`: `targets` não-lista e chave desconhecida levantam `EnvelopeError`.
  - `test_stage_targets_must_be_envelope_targets`: alvo fora do envelope, lista vazia ou duplicada são recusados.
  - `test_stage_allowlist_must_name_a_stage_target`: com dois alvos, uma regra que só nomeia o alvo B, num estágio cujo alvo é A, é recusada.
  - `test_stage_allowlist_forbidden_rules_refused`: `Edit(...)` na allowlist de um estágio é recusado.
  - `test_stages_with_different_roles_accepted_with_each_stage`: substitui o atual `test_stages_with_different_roles_refused`.
  - `test_multi_role_with_final_review_refused`: a mensagem contém `each_stage`.
  - `test_node_scope`: sem escopo declarado, devolve os do envelope. Com escopo, writers usam o do estágio, e `revisa`/`corrige` usam o do estágio com `each_stage` e o do envelope com `final`.
- [ ] **Step 2: Rodar** `python3 -m unittest tests.test_marina_envelope`. Esperado: falhas.
- [ ] **Step 3: Implementar.**
  - `_parse_stages` aceita as chaves `role` e `handoff` (obrigatórias) e `targets` e `allowlist` (opcionais, arrays de strings).
  - `_role_errors` troca o erro de papel único por: mais de um papel exige `review == "each_stage"`.
  - `_stage_scope_errors` valida os alvos de cada estágio e reaplica `_check_forbidden_allowlist` e `allowlist_target_errors` à allowlist de cada estágio, com os alvos dele.
  - `format_summary` lista os alvos e a allowlist de cada estágio que os declara.
- [ ] **Step 4: Rodar** `python3 -m unittest tests.test_marina_envelope` → OK.

### Task 2: aresta `encadeia` e escopo no `decide`

**Files:**
- Modify: `scripts/state/model.py`, `scripts/state_lint.py`, `scripts/marina/decide.py`, `scripts/marina/handoff_gen.py` (docstring)
- Test: `tests/test_state_lint.py`, `tests/test_marina_decide.py`

**Interfaces:**
- Consumes: `node_scope`, `WRITER_STAGE_EDGES` (Task 1).
- Produces: `"encadeia"` em `EDGES`; `decide.EDGE_TYPE["encadeia"] == "implementação"`; `decide.expected_scope(doc, env, a) -> tuple[tuple[str, ...], tuple[str, ...]]`.

- [ ] **Step 1: Testes.**
  - **state_lint:**
    - `test_encadeia_requires_accepted_writer_of_another_role`;
    - `test_encadeia_same_role_refused`;
    - `test_encadeia_requires_implementacao`.
  - **decide**, com o envelope de dois estágios (`java-backend` em `/abs/api`, `angular` em `/abs/front`):
    - `test_multi_role_pass_opens_encadeia_with_next_stage_scope`;
    - `test_same_role_still_opens_prossegue`;
    - `test_multi_role_review_uses_stage_scope`;
    - `test_multi_role_fail_corrects_with_stage_role_and_scope`;
    - `test_encadeia_node_with_wrong_targets_is_graph_outside_envelope`;
    - `test_stage_allowlist_mismatch_is_envelope_changed`;
    - `test_replacement_of_encadeia_follows_its_stage`.
- [ ] **Step 2: Rodar** `python3 -m unittest tests.test_state_lint tests.test_marina_decide`. Esperado: falhas.
- [ ] **Step 3: Implementar.**
  - `encadeia` entra em `EDGES`. No `state_lint`, o mesmo bloco de `prossegue`, mas com papel diferente.
  - **No `decide`:**
    - `stage_of` trata `encadeia` como `prossegue`;
    - `_PREDECESSOR_EDGES` passa a ser `prossegue`/`encadeia` → `("inicia", "prossegue", "encadeia")`;
    - `_WRITER_EDGES` inclui `encadeia`;
    - `_stage_opener` considera `inicia`/`prossegue`/`encadeia`;
    - `_launch` usa `node_scope`;
    - o próximo estágio usa `encadeia` quando o papel muda;
    - `graph_errors` compara `targets` com `expected_scope`;
    - a checagem `envelope_changed` compara a allowlist do nó atual com `expected_scope`; se `stage_of` falhar, a decisão fica para `graph_errors`;
    - a allowlist de `substitui` é comparada com o escopo do nó substituído.
- [ ] **Step 4: Rodar** `python3 -m unittest tests.test_state_lint tests.test_marina_decide tests.test_gate tests.test_state_model` → OK.

### Task 3: Git gate sobre todos os alvos, `run_argv`, `spawn_detached`

**Files:**
- Modify: `scripts/marina/runner.py`, `scripts/marina/mcp_server.py`
- Test: `tests/test_marina_runner.py`, `tests/test_marina_mcp.py`

**Interfaces:**
- Produces:
  - `runner.run_argv(kit_root: Path, project: str, task: str, *, interval: float, max_duration: str, notify_cmd: str | None) -> list[str]`;
  - `runner.spawn_detached(argv: list[str], cwd: Path, log_path: Path) -> int`;
  - `runner.live_lock_pid(task_dir: Path, *, pid_alive) -> int | None`.

- [ ] **Step 1: Testes.**
  - `test_git_after_covers_every_envelope_target`, num World de dois papéis;
  - `test_foreign_change_in_other_stage_target_stops`;
  - `test_live_lock_pid`;
  - os testes do MCP `run_start` passam a conferir `run_argv`.
- [ ] **Step 2: Rodar** → falhas.
- [ ] **Step 3: Implementar.**
  - `_write_git_after` e `_git_gate` recebem `env` e fazem o snapshot de `env.targets`.
  - O runner usa `WRITER_STAGE_EDGES` + `corrige`.
  - O `_spawn_detached` do MCP vira um alias de `runner.spawn_detached`, e o `_tool_run_start` passa a usar `run_argv`.
- [ ] **Step 4: Rodar** `python3 -m unittest tests.test_marina_runner tests.test_marina_mcp` → OK.

### Task 4: `marina go`

**Files:**
- Modify: `scripts/marina/envelope.py`, `scripts/marina/cli.py`
- Test: `tests/test_marina_envelope.py`, `tests/test_marina_cli.py`

**Interfaces:**
- Produces:
  - `approve_on_dispatch(state_path, *, kit_root, stdout, stderr, isatty, now, sleep, grace: float) -> int`;
  - CLI `marina go <project> <task> [--interval 30] [--max-duration D] [--notify-cmd C] [--grace 10] [--kit-root K]`.

- [ ] **Step 1: Testes.**
  - **envelope:**
    - `test_dispatch_records_approval_after_grace`;
    - `test_dispatch_refuses_without_tty`;
    - `test_dispatch_interrupt_writes_nothing`;
    - `test_dispatch_already_approved_skips_grace` (o `sleep` não é chamado);
    - `test_dispatch_change_during_grace_refused`;
    - `test_dispatch_invalid_envelope_refused`.
  - **cli:**
    - `test_go_spawns_run_with_envelope_duration`;
    - `test_go_with_live_lock_does_not_spawn`;
    - `test_go_refusal_does_not_spawn`;
    - `test_bin_wrapper_help` exige `go`.
- [ ] **Step 2: Rodar** → falhas.
- [ ] **Step 3: Implementar.**
  - `approve` e `approve_on_dispatch` compartilham `_record_approval`, que relê o estado, confere se nada mudou e grava atomicamente.
  - O `go`:
    1. chama `approve_on_dispatch`;
    2. se `live_lock_pid` existir, imprime `marina go: run already in progress (pid N)` e devolve 0;
    3. senão, chama `spawn_detached(run_argv(...))` e imprime pid, log e `marina status <p> <t>`.
  - `main` recebe um parâmetro `spawn` injetável, para os testes.
- [ ] **Step 4: Rodar** `python3 -m unittest tests.test_marina_envelope tests.test_marina_cli` → OK.

### Task 5: regras do kit (Marina)

**Files:** `AGENTS.md`, `docs/agent-workflow.md`, `README.md`, `.claude/skills/task-execution/SKILL.md`, `scripts/marina/mcp_server.py` (mensagens)

- [ ] **AGENTS.md:** o item "Opening the next node…" passa a dizer "outside a human-dispatched envelope (`marina go`, or `marina approve`)", acrescido de: "running `marina go` on a TTY is the approval of the whole plan".
- [ ] **agent-workflow.md:**
  - linha `encadeia` na tabela G3;
  - a seção "Approved envelopes" descreve `go`, o escopo por estágio, a regra multi-papel → `each_stage` e o Git gate sobre todos os alvos.
- [ ] **README** e **task-execution:** `marina go` como o passo do usuário.
- [ ] **MCP:** as mensagens de erro citam `marina go`.
- [ ] **Conferir:** `python3 scripts/kit_lint.py`.

### Task 6: verificação

- [ ] `python3 -m unittest discover -s tests` → OK (562 + novos).
- [ ] `python3 scripts/kit_lint.py` → todos PASS.
- [ ] `bin/marina --help` lista `go`.

## Execução

- **Pedido do usuário (2026-10-28):** executar sem interrupção com o Superpowers e entregar num branch novo no GitHub.
- **Implementação:** subagente de papel é proibido pelo `AGENTS.md`, por isso as Tasks 1–4 rodam na sessão principal via `superpowers:executing-plans`, com TDD. O registro de fallback é: "delegação visível indisponível: execução contínua pedida pelo usuário via Superpowers; especialidade kit-tooling assumida na sessão principal".
- **Revisão independente:** fica com o `reviewer`, em sessão visível lançada pelo `launch_claude`, no fim da série F7–F9.
- **Commits e push:** autorizados pelo usuário para o branch `feat/f7-envelope-multipapel-envio`.
