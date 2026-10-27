# F5 — Servidor MCP da Marina: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` em sessão visível (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Dar à Marina interativa um servidor MCP stdio (`marina mcp`) que mostre o estado da tarefa, o envelope, as sessões e a decisão atual sem montar comandos, e que exponha as poucas ações (rascunho de envelope, reserva de nó, launch avulso, iniciar e parar o runner). Nenhuma ferramenta aprova envelope.

**Architecture:**
- **Servidor:** `scripts/marina/mcp_server.py` implementa JSON-RPC 2.0 sobre linhas de stdin/stdout: `initialize`, `notifications/initialized`, `ping`, `tools/list` e `tools/call`. Cada ferramenta é uma função pequena sobre as bibliotecas que já existem (`state`, `envelope`, `decide`, `runner`, `gate`, `handoff_sync`, `launch_claude`, `status_claude`).
- **Decisão sem efeitos:** o runner ganha `preview_decision`, que monta as mesmas observações do laço mas não grava nada.
- **Registro:** `.mcp.json` registra o servidor.
- **Perfil e permissões:** o perfil `marina.md` lista as ferramentas, e o `.claude/settings.json` do kit pré-aprova só as de leitura.

**Tech Stack:** Python ≥ 3.11 stdlib (`json`, `subprocess`, `dataclasses`, `unittest`); protocolo MCP, versões `2025-06-18`, `2025-03-26` e `2024-11-05`.

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md): seções 3.1 (`mcp_server.py`, `cli.py`), 3.2 ("Invalidação": `envelope_draft` apaga a aprovação), 3.4 (tabela de ferramentas e permissões) e 3.7 (testes de `mcp_server`), e a linha F5 da seção 4. Base: [docs/plano-f4-runner-e-juiza-2026-10.md](plano-f4-runner-e-juiza-2026-10.md).

## Global Constraints

- Python ≥ 3.11, só stdlib, sem dependência nova.
- O servidor escreve no stdout só mensagens JSON-RPC, uma por linha. Diagnóstico vai para o stderr.
- O servidor nunca expõe ferramenta de aprovação. A raiz do kit é sempre a do próprio servidor, nunca um parâmetro de ferramenta. `project` e `task` passam por `fullmatch(^[a-z0-9-]+$)`.
- Testes nunca chamam o CLI real, o manager real nem o `.agent-state/` real. O launch, o manager, o processo destacado e as dependências do runner são injetados.
- Nenhuma ferramenta escreve fora de `.agent-state/<projeto>/tasks/<tarefa>/`. As que escrevem (`envelope_draft`, `state_reserve`, `launch_node`, `run_start`, `run_stop`) recusam quando um `marina run` detém a trava da tarefa. A exceção é `run_stop`, que só existe com a trava.
- Continuam valendo todas as proibições da F4: nada de `bypassPermissions`, `--permission-prompts none`, `--resume`/`--continue`/`--fork-session`, nem resposta a aprovação nativa.
- `scripts/gate.py` e `tests/test_gate.py` têm mudanças locais de outra tarefa e não são tocados. O hash dessas mudanças sem números de linha continua `539ee3ee92d5bf11531c32336c321b205c0908ed426ce0647e4bbede74fdfcd0`.
- Branch de trabalho: `feat/f5-servidor-mcp`, criado a partir de `main` (`8c9fb83`).

## Decisões deste plano

1. **O perfil lista as 12 ferramentas; as permissões ficam no settings do kit.** A spec diz que o `marina.md` recebe em `tools` só as de leitura e que as de escrita e ação "ficam sujeitas ao prompt". Mas, quando um agente tem lista `tools`, ferramenta fora da lista não existe para ele, e a Marina não conseguiria usar nenhuma ação. Por isso:
   - o `marina.md` lista as 12 ferramentas `mcp__marina__*`;
   - a pré-aprovação das sete de leitura vai para um `.claude/settings.json` novo do kit, em `permissions.allow`;
   - as cinco de escrita e ação continuam pedindo permissão a cada uso.

   O `.claude/settings.json` é do projeto, versionado; nenhuma configuração do usuário é tocada.
2. **O registro usa `python3 -m scripts.marina mcp`.** O `.mcp.json` registra o servidor com `"command": "python3"` e `"args": ["-m", "scripts.marina", "mcp"]`, como a spec. Isso depende do Claude Code iniciar o servidor de projeto com cwd na raiz do kit, que é onde o `CLAUDE.md` manda abrir a sessão. A aceitação real da F6 confirma.
3. **`decision_preview` não observa o manager.** A versão sem efeitos colaterais monta as observações sem `record_observed_transition` e sem gravar `git-after`. Um nó `uncertain` aparece sem `manager_match`, e o `decide` devolve `wait` nesse caso.
4. **`state_reserve` é só o `state add`.** Ele não roda o `gate`; quem chama usa `gate_check` antes. A tabela da spec diz "equivale a `state add`", e o `gate` não reserva nada.
5. **`run_start` destaca o próprio CLI.** Ele inicia `python3 <kit>/scripts/marina/__main__.py run …` com `start_new_session=True`, stdin fechado, stdout e stderr anexados a `tasks/<t>/marina-run.log` e cwd na raiz do kit. Antes, recusa se não houver aprovação válida: envelope interpretável e válido, aprovação presente e hash igual. O runner continua refazendo essas checagens a cada iteração.
6. **Ferramentas de ação recusam com a trava presente.** `envelope_draft`, `state_reserve`, `launch_node` e `run_start` recusam enquanto existir `.marina-run.lock`, para nada mudar o grafo ou o envelope sob um runner ativo.
7. **Formato das respostas.** O resultado de `tools/call` é `{"content": [{"type": "text", "text": <JSON indentado>}], "isError": <bool>}`. As ferramentas de leitura levam `annotations: {"readOnlyHint": true}`. A versão do protocolo é a pedida pelo cliente, se suportada; senão, `2025-06-18`.

## Review Focus

1. **Caminho fora da tarefa.** `project`/`task` com `..`, `/`, maiúsculas ou `\n`, ou uma tentativa de passar `kit_root`, devem dar `isError` sem tocar disco. Testes: `test_bad_slugs_refused`, `test_kit_root_argument_refused` (Task 2).
2. **Envelope mexido com execução ativa.** `envelope_draft` com a trava presente, com chave `approval` no rascunho ou com forma inválida deve recusar sem gravar. Um rascunho válido sempre apaga a aprovação. Testes: `test_envelope_draft_clears_approval`, `test_envelope_draft_refuses_approval_key`, `test_actions_refused_while_locked` (Task 3).
3. **`run_start` sem aprovação válida.** Sem aprovação, com hash divergente, com envelope inválido ou com a trava presente, não pode iniciar processo nenhum. Teste: `test_run_start_refuses_without_valid_approval` (Task 3).
4. **JSON-RPC malformado.** Linha que não é JSON, método desconhecido, ferramenta desconhecida, parâmetros faltando e notificação devem responder com o erro certo, ou não responder no caso da notificação, e o servidor deve continuar atendendo a linha seguinte. Testes: `test_parse_error_then_continues`, `test_unknown_method_and_tool`, `test_notification_gets_no_response` (Task 2).
5. **Stdout limpo.** Uma exceção dentro de uma ferramenta vira `isError` com a mensagem, nunca um traceback no stdout nem o fim do servidor. Teste: `test_tool_exception_is_error_result` (Task 2).

---

### Task 1: `runner.preview_decision`, a decisão atual sem efeitos

**Files:**
- Modify: `scripts/marina/runner.py`
- Test: `tests/test_marina_runner.py` (classe `PreviewTests`)

**Interfaces:**
- Produces: `preview_decision(state_path: Path, *, kit_root: Path, deps: RunnerDeps) -> Decision`. Lê o state, interpreta o envelope (`EnvelopeError` vira `Decision("stop", reason="envelope_invalid")`) e chama `_Run(...)._observations(doc, env, None)` e `decide`. Nunca chama `_observe`, `_write_git_after` nem a juíza. Um `ask_judge` é devolvido como está.
- Também: `decision_to_dict(d: Decision) -> dict`, com `kind`, `nn`, `to`, `reason`, `notify`, `node` (dict do `NodeSpec` ou `None`) e `question` (dict ou `None`).

- [ ] **Step 1: Write the failing tests** (reaproveitam o `World` do arquivo):
  - `test_preview_empty_graph_is_launch_stage_one`.
  - `test_preview_writes_nothing`: os bytes do `state.toml` e a lista de arquivos do diretório da tarefa ficam iguais depois de uma prévia com uma sessão `working` no manager falso, e nenhum `git-after` é criado.
  - `test_preview_returns_ask_judge_without_calling_judge`: o grafo é montado por um `run` com `stages=2` e `PASS_WITH_RISKS`, e a juíza falsa levanta exceção. Depois disso a prévia devolve `ask_judge` e a juíza não é chamada.
  - `test_decision_to_dict_is_json_serializable`: `json.dumps` aceita o resultado para `launch` e para `ask_judge`.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_runner -v`. Esperado: `AttributeError`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** → OK.

### Task 2: núcleo JSON-RPC e ferramentas de leitura

**Files:**
- Create: `scripts/marina/mcp_server.py`
- Test: `tests/test_marina_mcp.py` (novo)

**Interfaces:**
- Consumes: `runner.status_lines`, `preview_decision` e `decision_to_dict`; `envelope.envelope_from_doc`, `validate_envelope`, `compute_hash` e `envelope_to_raw`; `gate.evaluate_gate` e `load_task_docs`; `handoff_sync.validate_location`, `validate_handoff` e `validate_launch_metadata`; `status_claude.find_task_sessions` e `classify_session`; `scripts.state`.
- Produces:
  - `PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")`;
  - `SERVER_INFO = {"name": "marina", "version": "0.5.0"}`;
  - `@dataclass McpDeps(list_sessions, run_launch, spawn: Callable[[list[str], Path, Path], int], runner_deps: Callable[[Path], RunnerDeps])`, em que `spawn(argv, cwd, log_path)` devolve o pid; `default_mcp_deps()` liga cada campo ao real;
  - `class Server(kit_root: Path, deps: McpDeps)`, com `handle(message: dict) -> dict | None` e `tools() -> list[dict]`;
  - `serve(stdin: TextIO, stdout: TextIO, *, kit_root: Path, deps: McpDeps) -> int`, que lê uma mensagem por linha até EOF, escreve cada resposta com `json.dumps(..., ensure_ascii=False)` seguido de `\n` e `flush`, e devolve 0.
- Erros JSON-RPC:
  - `-32700` para linha que não é JSON;
  - `-32600` para mensagem que não é objeto ou sem `method`;
  - `-32601` para método desconhecido;
  - `-32602` para ferramenta desconhecida ou parâmetros inválidos no nível do protocolo.
  - Mensagem sem `id` é notificação e não recebe resposta.
- Ferramentas de leitura. Todas recebem `project` e `task`, e o `inputSchema` tem `additionalProperties: false`:
  - `task_status` → `{"lines": status_lines(...), "nodes": [{nn, role, edge, type, state, predecessor, native_id}], "next_nn"}`.
  - `envelope_show` → `{"envelope": <raw JSON-serializável, datetimes em ISO>, "approved": bool, "approval_matches": bool, "sha256": <hash atual ou null>, "errors": [...]}`.
  - `sessions` → as sessões do manager com título `<slug> —`, cada uma `{id, name, state, status, classification}`. Manager indisponível → `{"available": false, "reason": ...}`.
  - `next_nn` → `{"next_nn": int}`.
  - `gate_check` → recebe também `role`, `type`, `edge`, `predecessor`, `targets` e, opcionais, `git_diff_acknowledged` e `user_decided`; devolve `{"allowed", "reasons", "notes"}`.
  - `decision_preview` → `decision_to_dict(preview_decision(...))`.
  - `handoff_validate` → recebe também `nn`; devolve `{"ok": true, "profile": ...}` ou `{"ok": false, "error": ...}`. Usa as três validações do `handoff_sync`, sem `synchronize` e sem gravar.

- [ ] **Step 1: Write the failing tests** em `tests/test_marina_mcp.py`.
  - **Fixture:** um `kit_root` temporário com perfis copiados e uma tarefa com envelope aprovado (como o `World` da F4); `McpDeps` falsos; o helper `call(server, name, **arguments)`.
  - **Testes:**
    - `test_initialize_negotiates_version`: com `2025-03-26` a resposta repete essa versão; com `1999-01-01` responde `2025-06-18`. A resposta tem `capabilities.tools` e `serverInfo.name == "marina"`.
    - `test_tools_list_is_exact`: o conjunto de nomes é exatamente as 12 ferramentas da spec 3.4, e nenhum nome contém `approv`.
    - `test_read_tools_are_annotated`: as sete de leitura têm `readOnlyHint: true`, e as outras cinco não.
    - `test_task_status_and_next_nn`.
    - `test_envelope_show_reports_approval_match`: um template editado dá `approval_matches: false`.
    - `test_sessions_filters_by_task_and_handles_unavailable_manager`.
    - `test_gate_check_returns_reasons`.
    - `test_decision_preview_writes_nothing`.
    - `test_handoff_validate_ok_and_error`.
    - `test_bad_slugs_refused`.
    - `test_kit_root_argument_refused`: `isError`, porque `additionalProperties` é falso.
    - `test_parse_error_then_continues`: o `serve` com três linhas (lixo, `ping` e `tools/list`) responde `-32700` e depois as duas respostas certas.
    - `test_unknown_method_and_tool`.
    - `test_notification_gets_no_response`.
    - `test_tool_exception_is_error_result`: `list_sessions` levanta `RuntimeError` e a ferramenta `sessions` devolve `isError` com a mensagem.
    - `test_stdout_only_jsonrpc`: toda linha escrita por `serve` é JSON com `"jsonrpc": "2.0"`.
- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_mcp -v`. Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Implement** o núcleo e as sete ferramentas de leitura.
- [ ] **Step 4: Run.** → OK.

### Task 3: ferramentas de escrita e ação

**Files:**
- Modify: `scripts/marina/mcp_server.py`
- Test: `tests/test_marina_mcp.py`

**Interfaces:**
- `envelope_draft(project, task, envelope: object)`:
  - recusa se houver trava, se `envelope` tiver a chave `approval` ou se `parse_envelope` falhar;
  - grava `doc.envelope = envelope_to_raw(parse_envelope(envelope))` sem aprovação, atualiza `updated_at` e escreve com arquivo temporário e `os.replace` no diretório da tarefa;
  - devolve `{"written": true, "approval_cleared": <havia aprovação>, "errors": validate_envelope(...), "sha256": compute_hash(...)}`, em que os erros semânticos são avisos e o rascunho é gravado mesmo assim.
- `state_reserve(project, task, role, type, edge, predecessor, targets, allowlist, platform="claude", reason="", note="")`: recusa com trava; chama `add_assignment(..., by="marina")` e `write_state`; devolve `{"nn", "title", "handoff", "receipt"}`.
- `launch_node(project, task, nn)`: recusa com trava; chama `deps.run_launch(state_path, nn, kit_root=kit_root)` e devolve `{"ok", "session_id", "reasons", "notes"}`. Um `ok` falso vira `isError`.
- `run_start(project, task, interval, max_duration, notify_cmd=None)`:
  - recusa com trava, sem envelope, com envelope inválido, sem aprovação ou com hash divergente;
  - valida `interval > 0` e `parse_duration(max_duration)`;
  - chama `deps.spawn([sys.executable, str(kit_root/"scripts/marina/__main__.py"), "run", project, task, "--interval", str(interval), "--max-duration", max_duration, *(["--notify-cmd", notify_cmd] if notify_cmd else []), "--kit-root", str(kit_root)], kit_root, task_dir/"marina-run.log")`;
  - devolve `{"pid", "log"}`.
- `run_stop(project, task)` → `{"requested": runner.request_stop(state_path)}`; `false` vira `isError`.
- `default_mcp_deps().spawn` usa `subprocess.Popen(argv, cwd=cwd, stdin=DEVNULL, stdout=<log em append>, stderr=STDOUT, start_new_session=True)` e devolve `proc.pid`.

- [ ] **Step 1: Write the failing tests:**
  - `test_envelope_draft_clears_approval`: depois do rascunho, `envelope_show` dá `approved: false`.
  - `test_envelope_draft_refuses_approval_key`.
  - `test_envelope_draft_refuses_malformed`: o state fica byte a byte igual.
  - `test_envelope_draft_writes_with_warnings`: com `max_corrections: 2`, grava e devolve o erro em `errors`.
  - `test_state_reserve_reserves_next_nn`.
  - `test_launch_node_calls_injected_launch`.
  - `test_run_start_spawns_cli`: o argv tem `run`, os slugs, `--interval`, `--max-duration` e `--kit-root`; o cwd é o `kit_root`; o log é `marina-run.log`.
  - `test_run_start_refuses_without_valid_approval`: sem aprovação, com hash divergente, com envelope inválido e com trava, nenhum `spawn`.
  - `test_run_start_bad_limits`.
  - `test_run_stop_with_and_without_lock`.
  - `test_actions_refused_while_locked`: as quatro ações recusam e nada é gravado.
  - `test_default_spawn_detaches`: `Popen` é substituído por um mock e os kwargs têm `start_new_session=True`, `stdin=DEVNULL` e `cwd`.
- [ ] **Step 2: Run.** Esperado: falhas em `-32602`/ferramenta desconhecida.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_mcp tests.test_marina_runner -v` → OK.

### Task 4: `marina mcp`, `.mcp.json`, perfil e permissões

**Files:**
- Modify: `scripts/marina/cli.py`, `scripts/marina/__main__.py` (docstring)
- Create: `.mcp.json`, `.claude/settings.json`
- Modify: `.claude/agents/marina.md` (frontmatter `tools`)
- Test: `tests/test_marina_cli.py`, `tests/test_kit_lint.py` ou `tests/test_marina_mcp.py` (testes de configuração)

**Interfaces:**
- `marina mcp [--kit-root PATH]` chama `mcp_server.serve(stdin, stdout, kit_root=..., deps=default_mcp_deps())` e devolve 0. O stdin e o stdout são os do `main`.
- `.mcp.json`: `{"mcpServers": {"marina": {"command": "python3", "args": ["-m", "scripts.marina", "mcp"]}}}`.
- `.claude/settings.json`: `{"permissions": {"allow": ["mcp__marina__task_status", "mcp__marina__envelope_show", "mcp__marina__sessions", "mcp__marina__next_nn", "mcp__marina__gate_check", "mcp__marina__decision_preview", "mcp__marina__handoff_validate"]}}`.
- `marina.md` `tools`: a lista atual mais as 12 `mcp__marina__<ferramenta>`, na ordem da tabela 3.4.

- [ ] **Step 1: Write the failing tests:**
  - `test_mcp_subcommand_serves`: `cli.main(["mcp", "--kit-root", tmp], stdin=<initialize + tools/list>, stdout=...)` devolve 0 e responde às duas mensagens.
  - `test_bin_wrapper_help` exige `mcp`.
  - `test_mcp_json_registers_server`: `json.load(.mcp.json)` e o `args` é exatamente `["-m", "scripts.marina", "mcp"]`.
  - `test_settings_preapprove_only_read_tools`: o `allow` é exatamente as sete de leitura, coincide com as anotadas `readOnlyHint` no servidor e não contém nenhuma de escrita ou ação.
  - `test_marina_profile_lists_every_tool`: o frontmatter `tools` do `marina.md` contém `mcp__marina__<n>` para cada nome de `Server.tools()`.
  - `test_module_entry_point`: `python3 -m scripts.marina mcp`, rodado num subprocesso com cwd na raiz do kit e stdin com uma linha `initialize`, sai 0 e responde.
- [ ] **Step 2: Run.** Esperado: falhas.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_cli tests.test_marina_mcp tests.test_kit_lint -v` → OK.

### Task 5: skill `task-execution` e spec (Marina)

**Files:**
- Modify: `.claude/skills/task-execution/SKILL.md`, `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`

- [ ] **Step 1: Na skill**, seção "Route and execute", acrescentar um item:

  "For a chain the user wants to run unattended, draft the envelope with `mcp__marina__envelope_draft` (or by editing `[envelope]`), check it with `envelope_show`, `gate_check` and `decision_preview`, and ask the user to run `marina approve <project> <task>` in a terminal — no tool approves an envelope. Then `run_start` starts `marina run`; follow it with `task_status`/`sessions`, stop it with `run_stop`, and read the generated checkpoint section when it ends. Outside an approved envelope keep the manual procedure; `state_reserve` and `launch_node` are its mechanical steps, after `gate_check`."
- [ ] **Step 2: Na spec 3.4**, acrescentar uma frase com as decisões 1 e 2. Na seção 4, marcar a linha F5 como "Executada em 2026-10", com link para este plano.
- [ ] **Step 3: Conferir.** `python3 scripts/kit_lint.py` → 6/6.

### Task 6: verificação final

- [ ] `python3 -m unittest discover -s tests` → OK, com 490 testes mais os novos.
- [ ] `python3 scripts/kit_lint.py` → 6/6 PASS.
- [ ] O hash das mudanças preexistentes sem números de linha continua `539ee3ee…`.
- [ ] `printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 -m scripts.marina mcp`, rodado da raiz do kit, deve responder às duas mensagens e listar as 12 ferramentas, e nada mais no stdout.

## Execução

Mesmo modelo da F4:
- **Tasks 1 a 4:** código e configuração do `kit-tooling`. Rodam em sessão visível, ou na sessão principal com o aviso de fallback.
- **Task 5:** documentação, feita pela Marina.
- **Reviewer:** em sessão visível no fim, porque a fase muda permissões (perfil e settings do kit).
- **Aprovação do servidor:** a aprovação pelo usuário do servidor de projeto no primeiro uso e a chamada real das ferramentas por uma sessão `claude --agent marina` ficam para a aceitação da F6.
- **Commits:** só com autorização explícita.
