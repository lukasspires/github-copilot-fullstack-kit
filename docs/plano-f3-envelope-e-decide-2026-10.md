# F3 — Envelope, `marina approve` e `decide`: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` em sessão visível (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Dar ao `state.toml` um envelope aprovado por humano e uma função pura que, a partir do estado, do envelope e de observações, diz qual é o próximo passo da cadeia. A F4 usa as duas peças para montar o runner.

**Architecture:**
- O `state.toml` passa a preservar uma tabela opaca `[envelope]` em toda leitura e escrita.
- `scripts/marina/envelope.py` interpreta e valida essa tabela, calcula o hash e implementa `marina approve`.
- `scripts/marina/decide.py` é uma função pura, sem I/O: recebe estado, envelope e observações e devolve uma decisão.
- O `gate` passa a expor a razão de sobreposição dos riscos e uma faixa cinzenta entre dois limiares.

**Tech Stack:** Python ≥ 3.11 stdlib (`tomllib`, `hashlib`, `json`, `dataclasses`, `unittest`).

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md): seções 3.1, 3.2, 3.3 (tabela de decisão, faixa cinzenta, segundo FAIL) e 3.7, e a linha F3 da seção 4.

## Global Constraints

- Python ≥ 3.11, só stdlib, sem dependência nova.
- Testes nunca chamam o CLI real nem leem ou escrevem o `.agent-state/` real. Tudo roda em diretórios temporários, e TTY, relógio e stdin são injetados.
- `decide.py` não faz I/O nenhum: não abre arquivo, não chama subprocesso, não lê relógio nem ambiente. Toda informação externa chega em `Observations`.
- Um `state.toml` sem `[envelope]` continua válido, e nenhuma ferramenta existente muda de comportamento com ele.
- Só `marina approve` grava `[envelope.approval]`, e só com TTY e com o slug da tarefa digitado.
- Permanece proibido: `bypassPermissions`, `--permission-prompts none`, criar papel, aresta ou alvo fora da expansão do envelope (spec 3.2), e responder aprovações nativas.
- `scripts/gate.py` e `tests/test_gate.py` têm mudanças locais, sem commit, de outra tarefa. Elas precisam ser preservadas e nunca entram num commit desta fase; a Task 2 diz como fazer isso. Dois hashes identificam essas mudanças:
  - `git diff scripts/gate.py tests/test_gate.py | sha256sum` = `0c013412a5a0ee655171d7fd21d919aa37af5f3667a2800b53ac00e00f1d79e6`;
  - a mesma saída sem os números de linha, `git diff scripts/gate.py tests/test_gate.py | grep -v -e '^@@' -e '^index ' | sha256sum` = `539ee3ee92d5bf11531c32336c321b205c0908ed426ce0647e4bbede74fdfcd0`. Este é o que vale depois do commit da Task 2, porque os hunks novos ficam acima dos preexistentes e mudam os números de linha.
- Branch de trabalho: `feat/f3-envelope-decide`, criado a partir de `main` (`39fa083`) antes da Task 1.

## Decisões deste plano

Pontos que a spec deixa em aberto ou em que ela diverge do código.

1. **Ninguém consome a faixa cinzenta na v1.**
   - **O problema:** com `max_corrections ∈ {0, 1}`, uma cadeia só chega a dois FAIL consecutivos no segundo FAIL, e a spec manda parar nesse caso "independentemente da juíza". Então a linha "`ask_judge` se a sobreposição cai na faixa cinzenta" da tabela 3.3 nunca é alcançável.
   - **O que este plano faz:** a F3 entrega a faixa cinzenta no `gate`, com a razão e a faixa nas mensagens de `P_progresso`, para a Marina interativa usar ao decidir um `--user-decided`. O `decide` não consulta a faixa, e o plano registra por quê.
   - **Quando muda:** se um dia `max_corrections` aceitar 2 ou mais, a regra do segundo FAIL muda junto (spec 3.3), e então o `decide` passa a usar a faixa.
2. **"Schema v1" é a versão do envelope, não do `state.toml`.** O `state.toml` já declara `schema = 1` (`SUPPORTED_SCHEMA`). O envelope entra como tabela opcional nesse mesmo schema, sem trocar o número.
3. **O estado guarda o envelope como dicionário opaco.** `StateDoc.envelope` é um `dict | None` preservado como veio, e a interpretação fica em `scripts/marina/envelope.py`. Assim `scripts/state` não passa a depender de `scripts/marina`.
4. **Chaves desconhecidas no `[envelope]` são recusadas.** O hash cobre só as chaves conhecidas, então uma chave extra seria conteúdo aprovado sem estar no hash.
5. **Pontos que a spec não fixa:**
   - todo alvo do envelope precisa estar em `task.targets` e ter entrada em `branches`;
   - o papel do `revisa` é sempre `reviewer`;
   - um estágio só pode usar um papel writer com perfil em `.claude/agents/`, e nunca `marina`.
6. **`decide` também devolve transições e o fim da cadeia.** A spec lista quatro ações (`launch`, `wait`, `ask_judge`, `stop`), mas a tabela 3.3 também manda registrar estados (`accepted`, `receipt_validated`, `closed_*`). Cada chamada devolve uma única ação, o runner aplica e chama de novo. Os tipos de ação são `launch`, `wait`, `transition`, `ask_judge`, `stop` e `done`.
7. **Tarefa com nó fora da expansão é recusada.** Exemplos: um nó criado à mão pela Marina, uma aresta `analisa` ou um alvo diferente. Nesses casos o `decide` para com `graph_outside_envelope`, em vez de tentar encaixar o nó.
8. **`bin/marina` chama o script pelo caminho absoluto.** A spec sugere `exec python3 -m scripts.marina`, que só funciona com o diretório atual na raiz do kit. O wrapper resolve o caminho de `scripts/marina/__main__.py` a partir da própria localização.
9. **`prossegue` segue a regra G3 que já existe, e isso tem duas consequências.** `state_lint.check_edge_compatibility`, que o `gate` usa, exige que um `prossegue` tenha o mesmo papel e o mesmo tipo do predecessor.
   - **Todos os estágios do envelope usam o mesmo papel.** Um envelope com papéis diferentes entre estágios é recusado na validação. Encadear papéis diferentes exigiria outra aresta, fora deste plano.
   - **O predecessor de um `prossegue` é o writer que abriu o estágio anterior** (`inicia` ou `prossegue`). A spec 3.2 diz "último writer `accepted` do estágio", mas, se esse writer for um `corrige`, o tipo é `correção`, e o G3 recusaria o `prossegue`, que é `implementação`. O writer de abertura também está `accepted`. A revisão `PASS` do estágio é o que fecha a cadeia de correção.
10. **A spec tem trechos desatualizados desde a F2.** A linha de status ainda diz "decisão de permissão pendente". A linha 28 e a seção 3.7 ainda falam em comando que "espera `attach`". A Task 6 corrige os três.

## Review Focus

1. **Um `state set` comum apagaria o `[envelope]`.** Hoje `StateDoc.from_raw` ignora tabelas desconhecidas, então qualquer `state set` ou `watch_claude --state` reescreveria o arquivo sem o envelope. Teste: `test_envelope_survives_set_state` (Task 1).
2. **Chaves de `branches` são caminhos, como `"/abs/api"`.** Escritas sem aspas, viram TOML inválido e o próximo `read_state` quebra. Teste: `test_non_bare_keys_are_quoted` (Task 1).
3. **O hash precisa ser estável e cobrir o conteúdo dos handoffs.** Editar um handoff depois da aprovação deve invalidá-la, e reordenar chaves no arquivo não deve. Testes: `test_hash_changes_when_handoff_content_changes` e `test_hash_ignores_key_order_and_approval` (Task 3).
4. **Um handoff não pode escapar do diretório da tarefa.** Isso vale para `../`, caminho absoluto e symlink. Teste: `test_handoff_outside_task_dir_refused` (Task 3).
5. **`marina approve` sem TTY precisa recusar sem gravar nada.** Isso inclui stdin vazio, slug errado e envelope inválido. Testes: `test_approve_refuses_without_tty_and_writes_nothing` e `test_wrong_slug_writes_nothing` (Task 4).

---

### Task 1: `[envelope]` sobrevive a leitura e escrita do `state.toml`

**Files:**
- Modify: `scripts/state/model.py` (`StateDoc`)
- Modify: `scripts/state/toml_write.py` (formatação de chaves)
- Test: `tests/test_state_envelope.py` (novo)

**Interfaces:**
- Produces:
  - `StateDoc.envelope: dict | None = None`, sem interpretação e preservado como veio;
  - `StateDoc.from_raw` aceita `raw["envelope"]` só se for `dict`; qualquer outro tipo levanta `StateError("[envelope] must be a table")`;
  - `StateDoc.to_raw()` inclui `"envelope"` logo depois de `"task"`, e só quando não é `None`;
  - `toml_write._format_key(key: str) -> str`: deixa a chave nua quando ela casa com `^[A-Za-z0-9_-]+$` e, nos outros casos, devolve a string entre aspas no mesmo formato de `_format_string`. Vale para linhas `chave = valor` e para cada parte dos cabeçalhos `[a.b]` e `[[a.b]]`.

- [ ] **Step 1: Write the failing tests.** Em `tests/test_state_envelope.py`, crie `SPEC_ENVELOPE_TOML`: um `state.toml` mínimo válido (`schema = 1`, `[task]` completo, sem assignments) mais o envelope do exemplo da spec 3.2, com `branches` em tabela inline, dois `[[envelope.stages]]` e `[envelope.approval]` com `at` com fuso e um `sha256` de 64 hex.
  - `test_envelope_table_round_trips`: `tomllib.loads(dumps_state(parse_state_text(SPEC_ENVELOPE_TOML)))["envelope"] == tomllib.loads(SPEC_ENVELOPE_TOML)["envelope"]`.
  - `test_state_without_envelope_has_none_and_writes_no_table`: um doc sem envelope tem `doc.envelope is None` e `"envelope" not in tomllib.loads(dumps_state(doc))`.
  - `test_envelope_survives_set_state`:
    - grava com `write_state`;
    - adiciona uma atribuição com `add_assignment`;
    - aplica `set_state(doc, 1, "prepared")`;
    - grava, relê com `read_state` e compara `doc.envelope` com o original.
  - `test_non_table_envelope_refused`: `envelope = "x"` levanta `StateError`, e a mensagem contém `[envelope] must be a table`.
  - `test_non_bare_keys_are_quoted`: `tomllib.loads(toml_write.dumps({"t": {"/abs/api": "x", "a.b": "y", "ok_key-1": "z"}}))` reproduz o dict, e o texto contém `"/abs/api" = "x"` e `ok_key-1 = "z"`.

- [ ] **Step 2: Run.** `python3 -m unittest tests.test_state_envelope -v`. Esperado:
  - o round-trip e o set_state falham, porque `envelope` some;
  - o teste de chaves falha com `TOMLDecodeError`;
  - o teste de envelope não-tabela falha porque nada é levantado.

- [ ] **Step 3: Implement.** Implemente `StateDoc.envelope`, `from_raw` e `to_raw` em `model.py` e `_format_key` em `toml_write.py`. Atualize os docstrings dos dois módulos:
  - `model.py`: o `[envelope]` opcional é preservado sem interpretação; ver `scripts/marina/envelope.py`.
  - `toml_write.py`: chaves que não são nuas saem entre aspas.

- [ ] **Step 4: Run.** `python3 -m unittest tests.test_state_envelope tests.test_toml_write tests.test_state_model tests.test_state_cli -v` → OK.

### Task 2: faixa cinzenta no `gate`

**Files:**
- Modify: `scripts/gate.py`: a constante e as duas funções novas junto de `RISKS_OVERLAP_THRESHOLD` e de `risks_overlap_substantially`, e as mensagens de `evaluate_p_progresso`. Nenhuma linha de `evaluate_gate` nem de `main`, que são as regiões com mudanças locais.
- Test: `tests/test_gate_overlap.py` (novo; `tests/test_gate.py` não é tocado)

**Interfaces:**
- Produces:
  - `RISKS_OVERLAP_LOWER_THRESHOLD = 0.25`;
  - `risks_overlap_ratio(previous: list[str], new: list[str]) -> float | None`: interseção sobre união dos conjuntos, e `None` se algum dos dois estiver vazio;
  - `classify_overlap(ratio: float | None) -> str`, que devolve `"no_progress"` quando `ratio ≥ 0.5`, `"gray"` quando `0.25 ≤ ratio < 0.5`, e `"progress"` quando `ratio < 0.25` ou `None`;
  - `risks_overlap_substantially(previous, new)` mantém a assinatura e o resultado de hoje, igual a `classify_overlap(risks_overlap_ratio(...)) == "no_progress"`.
- Mensagens de `evaluate_p_progresso`:
  - no ramo "no progress", o texto atual ganha ` (overlap ratio 0.67)`;
  - no ramo "second consecutive FAIL", o texto atual ganha `; overlap ratio 0.33 is in the gray zone [0.25, 0.5)` ou `; overlap ratio 0.10 indicates progress`, conforme a faixa;
  - o ratio sai com duas casas decimais, e `None` vira `n/a`;
  - `allowed` não muda em nenhum caso.

- [ ] **Step 1: Write the failing tests** em `tests/test_gate_overlap.py`:
  - `test_ratio_values`: `risks_overlap_ratio(["a","b"], ["b","c"]) == 1/3`, e `None` para `([], ["a"])`.
  - `test_band_boundaries`: `classify_overlap` dá `no_progress` para 0.5, `gray` para 0.25 e 0.49, `progress` para 0.24 e para `None`.
  - `test_lower_threshold_constant`: `gate.RISKS_OVERLAP_LOWER_THRESHOLD == 0.25 < gate.RISKS_OVERLAP_THRESHOLD`.
  - `test_substantially_unchanged`: os mesmos casos de hoje, com `["a","b"]`/`["a","b"]` → True e `["a"]`/`["b"]` → False.
  - `test_second_fail_reason_names_gray_zone`:
    - monte, em memória, um `StateDoc` com a cadeia writer → reviewer FAIL → corrige → reviewer FAIL;
    - use `risks_digest` `["a","b","c"]` e `["c","d","e"]` (ratio 0.2), e depois `["a","b"]` e `["b","c","d"]` (ratio 0.25);
    - em cada caso, `evaluate_p_progresso(..., user_decided=False)` recusa, e as razões contêm `indicates progress` e `in the gray zone`, respectivamente.

- [ ] **Step 2: Run.** `python3 -m unittest tests.test_gate_overlap -v`. Esperado: `AttributeError`/`ImportError` nas funções novas.

- [ ] **Step 3: Implement** as funções e mensagens em `scripts/gate.py`, nas regiões listadas acima.

- [ ] **Step 4: Run.** `python3 -m unittest tests.test_gate_overlap tests.test_gate -v` → OK.

- [ ] **Step 5: Preservar as mudanças locais.** Rode `git diff -U0 scripts/gate.py` e confira:
  - os hunks novos estão só nas regiões da constante, de `risks_overlap_*`, de `classify_overlap` e de `evaluate_p_progresso`;
  - os hunks preexistentes, em `evaluate_gate` e `main`, continuam idênticos, linha por linha, aos do `git-before-01.txt` da tarefa da F3.

  Para o commit, monte a versão do índice com só as mudanças desta task:
  1. aplique as mesmas edições a uma cópia de `git show HEAD:scripts/gate.py`;
  2. grave essa cópia com `git hash-object -w`;
  3. registre-a no índice com `git update-index --cacheinfo 100755,<blob>,scripts/gate.py`.

  Depois confira:
  - `git diff --cached scripts/gate.py` mostra só os hunks desta task;
  - `git diff scripts/gate.py`, que compara o índice com o working tree, mostra só os hunks preexistentes;
  - `tests/test_gate.py` não aparece em `git diff --cached`.

### Task 3: `envelope.py`, que interpreta, valida e calcula o hash do envelope

**Files:**
- Create: `scripts/marina/envelope.py`
- Test: `tests/test_marina_envelope.py` (novo)

**Interfaces:**
- Consumes:
  - `StateDoc.envelope` (Task 1);
  - `scripts.launch_claude._check_forbidden_allowlist` e `LaunchRefused`;
  - `scripts.state.model.mode_for_role`.
- Produces:
  - `class EnvelopeError(StateError)`;
  - `REVIEW_MODES = ("each_stage", "final")` e `PASS_WITH_RISKS_POLICIES = ("accept", "judge", "stop")`;
  - os dataclasses congelados:
    - `Stage(role: str, handoff: str)`;
    - `Approval(at: datetime, sha256: str)`;
    - `Envelope(targets: tuple[str, ...], branches: dict[str, str], allowlist: tuple[str, ...], review: str, max_corrections: int, max_duration: str, judge_max_calls: int, on_pass_with_risks: str, stages: tuple[Stage, ...], approval: Approval | None)`.
  - Funções:
    - `parse_envelope(raw: dict) -> Envelope`: checa forma e tipos e levanta `EnvelopeError`:
      - exige as dez chaves `targets`, `branches`, `allowlist`, `review`, `max_corrections`, `max_duration`, `judge_max_calls`, `on_pass_with_risks` e `stages`, mais `approval` opcional;
      - chave desconhecida é recusada;
      - `bool` não vale como `int`;
      - `approval.at` precisa ser datetime com fuso;
      - `approval.sha256` precisa casar com `^[0-9a-f]{64}$`.
    - `envelope_to_raw(env: Envelope) -> dict`: o inverso, com `approval` só quando presente; `parse_envelope(envelope_to_raw(e)) == e`.
    - `parse_duration(text: str) -> int`: segundos, a partir de `^([1-9][0-9]*)([smh])$`; levanta `EnvelopeError` nos outros casos.
    - `validate_envelope(env: Envelope, *, doc: StateDoc, kit_root: Path, task_dir: Path) -> list[str]`: devolve a lista de erros, vazia se o envelope é válido. Checa, nesta ordem:
      1. pelo menos um estágio;
      2. papel de cada estágio:
         - tem `kit_root/.claude/agents/<role>.md`;
         - `mode_for_role(role) == "writer"`;
         - não é `marina`;
         - é o mesmo papel em todos os estágios (decisão 9).
      3. cada `handoff` é relativo e, depois de `resolve()`, aponta para um arquivo dentro de `task_dir.resolve()`;
      4. cada alvo é absoluto e normalizado (`os.path.normpath(t) == t`), sem duplicatas, e está em `doc.task.targets`;
      5. `set(branches) == set(targets)` e nenhum branch vazio;
      6. a allowlist passa em `_check_forbidden_allowlist`, e o texto do `LaunchRefused` vira o erro;
      7. `max_corrections ∈ {0, 1}`;
      8. `judge_max_calls ≥ 0`;
      9. `parse_duration(max_duration)` funciona;
      10. `review` e `on_pass_with_risks` estão nos enums.
    - `compute_hash(env: Envelope, *, task_dir: Path) -> str`: o algoritmo está fixado abaixo.
    - `envelope_from_doc(doc: StateDoc) -> Envelope | None`: `None` quando o doc não tem envelope; nos outros casos, `parse_envelope(doc.envelope)`.

Algoritmo do hash (fixo, porque a aprovação depende dele):

```python
body = envelope_to_raw(dataclasses.replace(env, approval=None))
h = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
for stage in env.stages:
    h.update(b"\0" + stage.handoff.encode("utf-8") + b"\0" + (task_dir / stage.handoff).read_bytes())
return h.hexdigest()
```

- [ ] **Step 1: Write the failing tests** em `tests/test_marina_envelope.py`.
  - **Fixture de cada teste:** um diretório temporário com `task_dir/state.toml` (via `init_state`, com `targets=["/abs/api"]`) e um handoff `01-java-backend-handoff.md`. Use `kit_root = KIT_ROOT` (o real, só para ler `.claude/agents/`) e o envelope do exemplo da spec, adaptado para um estágio.
  - **Casos:**
    - `test_parse_round_trip`: `parse_envelope(envelope_to_raw(env)) == env`.
    - `test_unknown_key_refused`: a mensagem cita a chave.
    - `test_missing_key_refused`.
    - `test_bool_is_not_int`: `max_corrections = true` é recusado.
    - `test_parse_duration`:
      - `"8h"` → 28800, `"90m"` → 5400 e `"30s"` → 30;
      - `"0h"`, `"8"`, `"1d"` e `"h"` levantam `EnvelopeError`.
    - `test_valid_envelope_has_no_errors`: `validate_envelope(...) == []`.
    - `test_reader_or_unknown_or_marina_role_refused`: os papéis `reviewer`, `nope` e `marina` geram um erro cada.
    - `test_stages_with_different_roles_refused`: estágios `java-backend` e `angular` geram um erro que cita o G3 `prossegue`.
    - `test_handoff_outside_task_dir_refused`: `../x.md`, um caminho absoluto e um symlink dentro de `task_dir` apontando para fora geram um erro cada.
    - `test_target_rules`:
      - um alvo relativo, um alvo com `/` final e um alvo fora de `task.targets` geram erro cada;
      - `branches` sem o alvo também gera erro.
    - `test_allowlist_refusals_reused`: `["Bash"]`, `["Edit(//x/**)"]` e `[]` geram erro, e o texto contém o de `LaunchRefused`.
    - `test_max_corrections_two_refused`.
    - `test_hash_is_stable`: dois cálculos seguidos dão o mesmo valor, de 64 hex.
    - `test_hash_ignores_key_order_and_approval`:
      - o mesmo envelope, com as chaves em outra ordem no dict cru, dá o mesmo hash;
      - com ou sem `approval`, o hash é o mesmo.
    - `test_hash_changes_when_handoff_content_changes`: o hash muda depois de acrescentar um byte ao handoff.
    - `test_hash_changes_when_allowlist_changes`.

- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_envelope -v`. Esperado: `ModuleNotFoundError: scripts.marina.envelope`.

- [ ] **Step 3: Implement** `scripts/marina/envelope.py`. O docstring do módulo cita a spec 3.2 e as decisões 2 a 5 deste plano.

- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_envelope -v` → OK.

### Task 4: `marina approve`, a CLI e `bin/marina`

**Files:**
- Modify: `scripts/marina/envelope.py` (`approve`, `format_summary`)
- Modify: `scripts/marina/cli.py` (subcomando `approve`)
- Modify: `scripts/marina/__main__.py` (docstring: deixa de ser só leitura)
- Create: `bin/marina` (executável)
- Test: `tests/test_marina_envelope.py` (classe `ApproveTests`), `tests/test_marina_cli.py` (novo)

**Interfaces:**
- Consumes: tudo da Task 3, mais `read_state` e `write_state`.
- Produces:
  - `format_summary(env: Envelope, doc: StateDoc, sha256: str) -> str`. Uma linha para cada item, na ordem:
    - tarefa (`slug — title`);
    - cada estágio (`N. role — handoff`);
    - cada alvo com seu branch;
    - cada entrada da allowlist;
    - `review`, `max_corrections`, `max_duration`, `judge_max_calls`, `on_pass_with_risks`;
    - `sha256`.
  - `approve(state_path: Path, *, kit_root: Path, stdin: TextIO, stdout: TextIO, stderr: TextIO, isatty: Callable[[], bool], now: Callable[[], datetime]) -> int`. Executa, nesta ordem:
    1. sem TTY (`not isatty()`): imprime `marina approve: requires an interactive terminal` no stderr e devolve 1;
    2. sem envelope, com erro de interpretação ou com erro de validação: imprime cada erro no stderr e devolve 1;
    3. imprime `format_summary` no stdout, seguido do prompt `Type the task slug (<slug>) to approve: `;
    4. lê uma linha do stdin; se ela, sem os espaços das pontas, não for igual ao slug, imprime `not approved` no stderr e devolve 1;
    5. grava `[envelope.approval]` com `at=now()` e o `sha256` calculado, atualiza `task.updated_at`, salva com `write_state`, imprime `approved <slug> sha256=<hash>` no stdout e devolve 0.
    - Se já existe uma aprovação, ela é substituída e o hash anterior entra na linha de resumo `previous approval: <sha256>`.
  - `cli.main(argv=None, *, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, isatty=None) -> int`:
    - **Subcomando novo:** `approve <project> <task> [--kit-root PATH]`.
      - `--kit-root` tem como padrão `Path(__file__).resolve().parents[2]`.
      - `project` e `task` precisam casar com `^[a-z0-9-]+$`; caso contrário a saída é 1.
      - O state é lido de `<kit_root>/.agent-state/<project>/tasks/<task>/state.toml`; se o arquivo não existe, a saída é 1.
      - `isatty` tem como padrão `lambda: stdin.isatty() and stdout.isatty()`.
    - **Inalterado:** o subcomando `hook require-receipt` funciona como hoje e só ele lê o stdin como JSON. Argumentos inválidos continuam saindo com 1 e `--help`, com 0.
  - `bin/marina`, modo 755:

    ```sh
    #!/bin/sh
    exec python3 "$(dirname "$(readlink -f "$0")")/../scripts/marina/__main__.py" "$@"
    ```

- [ ] **Step 1: Write the failing tests.**
  - Em `ApproveTests`, com a fixture da Task 3, `now` fixo e `isatty` injetado:
    - `test_approve_writes_approval_with_hash`:
      - stdin com `"<slug>\n"`, saída 0;
      - ao reler, `envelope_from_doc(read_state(p)).approval.sha256 == compute_hash(...)`;
      - `approval.at == now()`.
    - `test_approve_refuses_without_tty_and_writes_nothing`: saída 1 e os bytes do `state.toml` iguais aos de antes.
    - `test_wrong_slug_writes_nothing`: com stdin `"outro\n"` e com stdin vazio, saída 1 e o arquivo inalterado.
    - `test_invalid_envelope_refused`: com `max_corrections = 2`, saída 1, e o stderr cita `max_corrections`.
    - `test_no_envelope_refused`.
    - `test_summary_lists_every_field`: o stdout contém o papel, o handoff, o alvo, o branch, cada entrada da allowlist, `each_stage` e `8h`.
    - `test_reapprove_reports_previous_hash`.
  - Em `tests/test_marina_cli.py`, com um diretório temporário como `kit_root` (`.claude/agents/java-backend.md` copiado do real) e a tarefa em `.agent-state/demo/tasks/t1/`:
    - `test_approve_via_cli`: `cli.main(["approve", "demo", "t1", "--kit-root", tmp], stdin=io.StringIO("t1\n"), stdout=..., stderr=..., isatty=lambda: True)` sai com 0.
    - `test_bad_slug_args_exit_1`: `["approve", "../x", "t1", ...]` e `["approve", "demo", "T1", ...]` saem com 1.
    - `test_missing_state_exit_1`.
    - `test_hook_still_works`: `["hook", "require-receipt", "--receipt", "/r", "--handoff", "/h"]` com stdin `'{"stop_hook_active": true}'` sai com 0.
    - `test_bin_wrapper_help`:
      - `subprocess.run([KIT_ROOT/"bin"/"marina", "--help"], cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)` sai com 0 e a saída contém `approve`;
      - `os.access(bin, os.X_OK)` é verdadeiro.
    - `test_bin_wrapper_refuses_without_tty`: `bin/marina approve demo t1 --kit-root tmp` com stdin `DEVNULL` sai com 1, e o `state.toml` fica inalterado.

- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_envelope tests.test_marina_cli -v`. Esperado: falha porque `approve` não existe e `bin/marina` não existe.

- [ ] **Step 3: Implement** `approve`, `format_summary`, o subcomando na `cli` e `bin/marina` (`chmod 755`). Atualize os docstrings de `cli.py` e de `__main__.py`, dizendo que `approve` escreve só o `state.toml` da tarefa indicada.

- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_envelope tests.test_marina_cli tests.test_marina_hooks -v` → OK.

### Task 5: `decide.py`, a tabela de decisão como função pura

**Files:**
- Create: `scripts/marina/decide.py`
- Test: `tests/test_marina_decide.py` (novo)

**Interfaces:**
- Consumes:
  - `Envelope` e `Stage` (Task 3);
  - `scripts.gate.find_fail_review_chain`;
  - `StateDoc`, `Assignment` e `ReceiptSummary`.
- Produces:
  - `class MissingObservation(ValueError)`.
  - `EDGE_TYPE = {"inicia": "implementação", "prossegue": "implementação", "revisa": "revisão", "corrige": "correção"}`.
  - Dataclasses congelados:
    - `NodeSpec(role: str, type: str, edge: str, predecessor: int, targets: tuple[str, ...], allowlist: tuple[str, ...], stage: int)`, com `stage` contado a partir de 1;
    - `Question(kind: str, nn: int, options: tuple[str, ...])`, em que `options` sempre inclui `"stop"`;
    - `Observations(envelope_sha256: str, branches: dict[str, str], envelope_errors: tuple[str, ...] = (), receipt_exists: bool | None = None, receipt_lint: tuple[tuple[str, ...], ReceiptSummary] | None = None, manager_match: str | None = None, notified: bool = False, judge_calls_used: int = 0, judge_answer: tuple[Question, str] | None = None)`, com `manager_match ∈ {"found", "absent", None}`;
    - `Decision(kind: str, node: NodeSpec | None = None, nn: int | None = None, to: str | None = None, reason: str = "", notify: bool = False, question: Question | None = None, receipt_summary: ReceiptSummary | None = None)`, com `kind ∈ {"launch", "wait", "transition", "ask_judge", "stop", "done"}`.
  - `stage_of(doc: StateDoc, nn: int) -> int`: `inicia` → 1; `prossegue` → `stage_of(pred) + 1`; `revisa` e `corrige` → `stage_of(pred)`.
  - `graph_errors(doc: StateDoc, env: Envelope) -> list[str]`. Um nó gera erro quando:
    - a aresta está fora de `{inicia, prossegue, revisa, corrige}`;
    - o primeiro nó não é `inicia` com predecessor 0, ou existe mais de um `inicia`;
    - os `targets` diferem de `env.targets`;
    - o estágio passa de `len(env.stages)`;
    - um writer (`inicia`, `prossegue` ou `corrige`) tem papel diferente do papel do estágio;
    - um `revisa` não tem papel `reviewer`.
  - `decide(doc: StateDoc, env: Envelope | None, obs: Observations) -> Decision`.

Ordem das verificações de `decide`, onde "nó atual" é o de maior `nn`. Os motivos de `stop` são estes literais:

1. `env is None` → `stop("no_envelope")`. `env.approval is None` → `stop("not_approved")`. `obs.envelope_errors` não vazio → `stop("envelope_invalid")`.
2. `obs.envelope_sha256 != env.approval.sha256`, ou algum `obs.branches.get(t) != env.branches[t]`, ou nó atual com `tuple(allowlist) != env.allowlist` → `stop("envelope_changed")`.
3. `graph_errors` não vazio → `stop("graph_outside_envelope")`, com o primeiro erro em `reason`.
4. Sem nós → `launch` do estágio 1: `inicia`, predecessor 0, papel `stages[0].role`.
5. Nó atual, conforme o estado:

| Estado | Decisão |
|---|---|
| `reserved`, `prepared` | `stop("node_not_launched")` |
| `launched`, `working` | `wait` |
| `waiting_approval` | `wait`, com `notify = not obs.notified` |
| `uncertain` | `manager_match`: `"found"` → `transition` para `launched`; `"absent"` → `transition` para `abandoned`; `None` → `wait` |
| `finished` | `receipt_exists`: `False` → `transition` para `receipt_missing`; `True` → `transition` para `receipt_received`; `None` → `MissingObservation` |
| `receipt_received` | `receipt_lint`: com erros → `transition` para `receipt_invalid`, com o primeiro erro em `reason`; sem erros → `transition` para `receipt_validated`, levando o `receipt_summary`; `None` → `MissingObservation` |
| `receipt_validated` | `receipt_summary.status`: `done` → `accepted`; `pending`, `needs_input`, `blocked` → `closed_pending`, `closed_needs_input`, `closed_blocked`; sem `receipt_summary` → `stop("receipt_summary_missing")` |
| `accepted`, writer | `corrige` → `launch` de `revisa`, com pred = o nó. `each_stage` → `revisa`. `final`: no último estágio → `revisa`; antes dele → `prossegue` do estágio seguinte, com pred = o nó |
| `accepted`, reviewer, `PASS` | `each_stage` com estágio seguinte → `prossegue`, com pred = o writer que abriu o estágio do reviewer (`inicia` ou `prossegue`; decisão 9); nos outros casos → `done` |
| `accepted`, reviewer, `PASS_WITH_RISKS` | `accept` → igual a `PASS`; `stop` → `stop("pass_with_risks")`; `judge` → ver o bloco abaixo |
| `accepted`, reviewer, `FAIL` | `len(find_fail_review_chain(doc, nn)) ≥ 2` → `stop("second_fail")`; já há `corrige` no estágio em quantidade `≥ max_corrections` → `stop("max_corrections")`; nos outros casos → `launch` de `corrige`, com o papel do writer revisado e pred = o reviewer |
| `accepted`, reviewer, verdict vazio | `stop("verdict_missing")` |
| qualquer outro terminal | `stop(<nome do estado>)`, por exemplo `stop("receipt_missing")` |

Política `judge` para `PASS_WITH_RISKS`:
- A pergunta é `Question("pass_with_risks", nn, ("continue", "stop"))`.
- Se `obs.judge_answer` responde a essa mesma pergunta:
  - `"continue"` → igual a `PASS`;
  - `"stop"` → `stop("judge_stop")`;
  - qualquer outra resposta → `stop("judge_failed")`.
- Sem resposta:
  - `obs.judge_calls_used ≥ env.judge_max_calls` → `stop("judge_failed")`;
  - nos outros casos → `ask_judge(question)`.

Todo `launch` carrega `targets = env.targets`, `allowlist = env.allowlist` e `type = EDGE_TYPE[edge]`. O `revisa` tem sempre papel `reviewer`. A faixa cinzenta não é consultada (decisão 1).

- [ ] **Step 1: Write the failing tests** em `tests/test_marina_decide.py`.
  - **Helpers:**
    - um construtor de `StateDoc` em memória: `init_state` num diretório temporário, mais `add_assignment` e `set_state`/`append_event` até o estado desejado, com `receipt_summary` atribuído direto;
    - um envelope válido com dois estágios `java-backend`, `review="each_stage"`, `max_corrections=1`, `judge_max_calls=1` e `on_pass_with_risks="judge"`;
    - `obs_ok()`, com o hash e os branches que casam com o envelope.
  - **Testes, um para cada linha das verificações e da tabela:**
    - `test_no_envelope`, `test_not_approved`, `test_envelope_invalid`;
    - `test_hash_mismatch`, `test_branch_mismatch`, `test_allowlist_mismatch`, todos com `envelope_changed`;
    - `test_graph_outside_envelope_for_analisa_edge`, `test_graph_outside_envelope_for_foreign_target`;
    - `test_empty_graph_launches_stage_one`;
    - `test_reserved_stops`;
    - `test_launched_and_working_wait`;
    - `test_waiting_approval_notifies_once`: `notify` é True com `notified=False` e False com `notified=True`;
    - `test_uncertain_found_absent_unknown`;
    - `test_finished_with_and_without_receipt`, `test_finished_requires_observation` (`MissingObservation`);
    - `test_receipt_lint_pass_and_fail`, `test_receipt_validated_status_mapping` (os quatro status);
    - `test_writer_accepted_each_stage_opens_revisa`;
    - `test_final_review_middle_stage_opens_prossegue`, `test_final_review_last_stage_opens_revisa`;
    - `test_corrige_accepted_opens_revisa`;
    - `test_pass_opens_next_stage_with_writer_as_predecessor`, `test_pass_on_last_stage_is_done`;
    - `test_pass_after_correction_opens_next_stage_from_stage_opener`: na cadeia inicia → FAIL → corrige → PASS, o `prossegue` tem como predecessor o nó `inicia`, não o `corrige`. Além disso, um `StateDoc` com o nó resultante passa em `check_edge_compatibility`;
    - `test_pass_with_risks_accept`, `test_pass_with_risks_stop`;
    - `test_pass_with_risks_judge_asks`, `test_judge_answer_continue`, `test_judge_answer_stop`;
    - `test_judge_answer_invalid_option`, `test_judge_quota_exhausted` (`judge_failed`);
    - `test_fail_opens_corrige_with_writer_role`;
    - `test_fail_with_zero_quota_stops`;
    - `test_second_consecutive_fail_stops_even_with_quota`: com a cota em 1 e já usada, o motivo é `second_fail`, não `max_corrections`;
    - `test_verdict_missing`;
    - `test_terminal_states_stop_with_state_name`: em subTest, para `receipt_missing`, `receipt_invalid`, `abandoned`, `preparation_failed`, `returned` e os três `closed_*`.
  - **Teste extra, `test_decide_has_no_io`:** a fonte de `decide.py` não contém `open(`, `subprocess`, `os.environ`, `datetime.now`, `time.`, `Path(` nem `read_state`.

- [ ] **Step 2: Run.** `python3 -m unittest tests.test_marina_decide -v`. Esperado: `ModuleNotFoundError: scripts.marina.decide`.

- [ ] **Step 3: Implement** `scripts/marina/decide.py`. O docstring do módulo cita a spec 3.3 e as decisões 1, 6, 7 e 9.

- [ ] **Step 4: Run.** `python3 -m unittest tests.test_marina_decide -v` → OK.

### Task 6: spec atualizada (Marina)

**Files:**
- Modify: `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`

- [ ] **Step 1: Edições na spec.**
  - Linha de status: trocar "decisão de permissão pendente" por "permissão decidida (`dontAsk`) e implementada na F2 (PR #8)".
  - Linha 28: trocar "aprovações nativas esperam o humano via `claude attach`" por "comandos fora da allowlist são negados (`dontAsk`) e vão para o receipt; aprovações nativas nunca são respondidas por código".
  - Seção 3.7, aceitação real: trocar "um comando fora da allowlist que espera `attach`" por "um comando fora da allowlist negado e registrado no receipt".
  - Seção 3.3, depois do parágrafo "Faixa cinzenta": acrescentar uma frase com a decisão 1 deste plano.
  - Seção 3.2: acrescentar uma frase com as decisões 4 e 5, e corrigir o predecessor do `prossegue` e a exigência de mesmo papel entre estágios (decisão 9).
- [ ] **Step 2: Conferir.** `git grep -n "espera \`attach\`\|esperam o humano\|permissão pendente" docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md` não encontra nada.

### Task 7: verificação final

- [ ] `python3 -m unittest discover -s tests` → OK, com 314 testes mais os novos.
- [ ] `python3 scripts/kit_lint.py` → 6/6 PASS.
- [ ] Conferir as mudanças preexistentes em `scripts/gate.py` e `tests/test_gate.py`:
  - **Antes do commit:** o diff contra `HEAD` inclui os hunks da Task 2, então nenhum dos dois hashes bate. Confira à mão os hunks com `git diff -U0`.
  - **Depois do commit**, montado como manda a Task 2, Step 5: `git diff scripts/gate.py tests/test_gate.py | grep -v -e '^@@' -e '^index ' | sha256sum` precisa dar `539ee3ee…`.
  - **`tests/test_gate.py`:** não aparece em nenhum commit desta fase.
- [ ] Um `state.toml` real sem envelope (`.agent-state/github-copilot-fullstack-kit/tasks/f2-dontask-stop-hook/state.toml`) passa em `state_lint` e reescreve sem diff, conferido com `parse_state_text`/`dumps_state` em memória, sem gravar nada.

## Execução

Mesmo modelo da F2:
- **Tasks 1 a 5:** código do `kit-tooling`. Rodam em sessão visível, ou na sessão principal com o aviso de fallback, se o usuário preferir.
- **Task 6:** documentação, feita pela Marina.
- **Reviewer:** em sessão visível no fim, lançado pelo `launch_claude`, porque a fase altera o contrato de estado (`[envelope]`) e o `gate`.
- **Commits:** só com autorização explícita. A ordem sugerida é um commit por task, ou um único commit da fase, sempre sem `tests/test_gate.py` e sem as mudanças preexistentes de `scripts/gate.py`.
