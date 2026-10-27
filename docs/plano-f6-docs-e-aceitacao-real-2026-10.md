# F6 — Documentação e aceitação real: plano

> **Natureza:** fase final do executável da Marina. A primeira metade é documentação, feita pela Marina. A segunda é a aceitação real da spec 3.7 com o CLI de verdade, num repositório descartável. O resultado são evidências no checkpoint, e não código novo. Um defeito encontrado na aceitação vira uma atribuição de correção própria, com plano curto, e não um ajuste silencioso.

**Goal:**
- Deixar README e `docs/agent-workflow.md` descrevendo o kit como ele é agora, com as ferramentas de `scripts/`, `bin/marina`, envelope, `marina run` e `marina mcp`.
- Provar com sessões reais o que até aqui só foi testado com dublês:
  - uma cadeia sob envelope aprovado;
  - um comando fora da allowlist negado e registrado no receipt;
  - interrupção e retomada sem duplicação;
  - o servidor MCP usado por uma sessão Marina.

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md), 3.6, 3.7 ("Aceitação real") e a linha F6 da seção 4. Também `docs/agent-workflow.md`, "Visible-session acceptance scenarios" e "Approved envelopes (`marina run`)".

## Global Constraints

- Nada é testado contra repositório de verdade: o alvo é um repositório Git descartável no scratchpad da sessão, fora do kit.
- O kit só muda nos documentos da Task 1 e em `.agent-state/<projeto-de-aceitação>/`. `scripts/gate.py` e `tests/test_gate.py` (mudanças locais de outra tarefa) não são tocados, e o hash sem números de linha continua `539ee3ee92d5bf11531c32336c321b205c0908ed426ce0647e4bbede74fdfcd0`.
- A Marina nunca responde a diálogos nativos nem aprova o envelope. `marina approve` e a primeira aprovação do servidor MCP numa sessão interativa são passos do usuário.
- Não se inventa defeito para forçar uma correção (`agent-workflow.md`). Se o reviewer real aprovar de primeira, o ramo `corrige` fica registrado como coberto só pelos testes unitários, ou seja, pendente na aceitação real.
- Toda sessão real usa o caminho normal do kit: `launch_claude` com `dontAsk`, `--strict-mcp-config` e o Stop hook. Toda chamada `claude` própria da Marina roda com stdin fechado e `--max-budget-usd`.
- **Custo:** de 3 a 6 sessões de especialista com o modelo configurado pelo usuário, mais uma sonda `-p` com teto de US$ 0,50. O custo real é registrado quando o CLI o informar.
- Branch de trabalho: `feat/f6-docs-aceitacao`, criado a partir de `main` (`b522413`).

## Decisões deste plano

1. **O alvo é um ETL pequeno em Python, e o papel é `python-etl`.** O repositório descartável `marina-acc` tem `transform.py`, com uma função `normalize_rows` incompleta, e `tests/test_transform.py`. Isso cabe no papel `python-etl` e roda só com `python3 -m unittest`. Uma mudança local preexistente e não commitada (`NOTES.md`) precisa sobreviver à cadeia (`agent-workflow.md`: "preserve a preexisting change").
2. **A negação fora da allowlist é pedida explicitamente.**
   - A allowlist do envelope é `Bash(python3 -m unittest *)`, `Bash(git status --short)` e `Bash(git diff *)`.
   - A seção `Checks and workdir` do template pede que o writer também tente `git log -1 --oneline` uma vez e registre o resultado.
   - É um comando legítimo e de leitura. Ele só serve para exercitar a negação real do `dontAsk`, e o receipt deve citá-lo como check pulado e negado.
3. **Interrupção com SIGINT e queda com SIGKILL, em nós diferentes.**
   - **SIGINT:** enquanto o primeiro writer trabalha, a Marina manda `SIGINT` ao `marina run`. O esperado é `stop(interrupted)` no checkpoint e a trava solta. A Marina então roda `marina run` de novo, e a cadeia continua sem nó duplicado.
   - **SIGKILL:** enquanto o reviewer trabalha, a Marina manda `SIGKILL`. O esperado é uma trava órfã. `marina run --recover` precisa recusar enquanto a sessão está `working` e assumir depois que ela termina.
4. **O servidor MCP é verificado de dois jeitos.**
   - **Sonda headless da Marina:** `claude -p --agent marina --mcp-config .mcp.json --strict-mcp-config --allowedTools mcp__marina__task_status …`. Ela prova que o servidor sobe da raiz do kit e que a ferramenta funciona pela lista `tools` do perfil.
   - **Passo interativo do usuário:** abrir `claude --agent marina` na raiz do kit, aprovar o servidor no diálogo de primeiro uso e pedir `task_status`. Só o usuário pode dar essa aprovação. Se ele não fizer esse passo, o item fica pendente.

## Review Focus

1. A documentação não pode prometer comportamento que o código não tem: listar uma ferramenta que não existe, ou dizer que a juíza decide algo além de `PASS_WITH_RISKS`.
2. As evidências da aceitação têm de vir de arquivos, do manager e de campos estruturados, nunca do texto de resposta de um modelo (F1, X4).
3. A mudança preexistente do alvo sobrevive, e nenhum arquivo do kit fora do escopo muda.
4. Cada item da spec 3.7 termina como executado, falho ou pendente, com evidência. Nada é marcado como passou sem ter rodado.
5. Um defeito achado na aceitação é registrado e vira atribuição própria, e não um ajuste fora do grafo.

---

### Task 1: documentação (Marina)

**Files:** `README.md`, `docs/agent-workflow.md`, `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`

- [ ] **Step 1: README, seção "Ferramentas do kit (`scripts/`)".**
  - Reescrever a seção, que ainda diz que `gate`, `launch-claude`, `status-claude` e `watch-claude` "ainda não existem".
  - A tabela nova lista, com o que cada um faz e o que escreve:
    - `kit_lint`, `unittest`, `python3 -m scripts.state init|add|set|next-nn`, `state_lint`;
    - `preflight`, `gate`, `launch_claude`, `status_claude`, `watch_claude`;
    - `receipt_lint`;
    - `bin/marina hook|approve|run|status|stop|mcp`.
  - Manter a frase de que roteamento, mérito de receipt e decisões continuam sendo julgamento da Marina, agora com a ressalva do envelope aprovado.
- [ ] **Step 2: README, seção nova "Cadeias sem supervisão (`marina run`)"**, depois de "Como uma tarefa é executada", com entrada no sumário. Em até ~25 linhas, explica:
  - o envelope, com estágios, templates, alvos com branch, allowlist e limites;
  - `marina approve`, que só funciona com TTY;
  - o que `marina run` faz e quando para;
  - a juíza, que só decide `PASS_WITH_RISKS`;
  - `marina status` e `marina stop`;
  - o servidor `marina mcp`, com as 12 ferramentas, nenhuma de aprovação, as de leitura pré-aprovadas e o `--strict-mcp-config` nas sessões automáticas.

  Linka a seção "Approved envelopes" do `agent-workflow.md`.
- [ ] **Step 3: `docs/agent-workflow.md`.**
  - Na seção "Claude Code", acrescentar uma tabela curta "Kit tools" com os mesmos comandos do README (nome, efeito, o que grava).
  - Em "Visible-session acceptance scenarios", acrescentar o cenário sob envelope (`marina approve` → `marina run` → interrupção/retomada) e a verificação do servidor MCP.
- [ ] **Step 4: spec.** Linha F6 marcada como executada, com link para este plano e para o checkpoint da aceitação.
- [ ] **Step 5: conferir.**
  - `python3 scripts/kit_lint.py` deve dar 6/6.
  - Cada comando citado na tabela deve existir: para cada script, `test -f`; para cada subcomando, `bin/marina --help`.

### Task 2: preparar a aceitação (Marina)

- [ ] **Step 1: repositório descartável** `<scratchpad>/marina-acc`:
  - `git init`, branch `feat/acc`;
  - `transform.py`, com `normalize_rows(rows)` devolvendo as linhas sem tratamento;
  - `tests/test_transform.py`, cobrindo só o caso já implementado;
  - commit inicial;
  - depois do commit, `NOTES.md` não rastreado, que é a mudança preexistente.
- [ ] **Step 2: tarefa** `acc-envelope` no projeto `marina-acc`:
  - `state init`, com alvo `<scratchpad>/marina-acc`;
  - template `stage-1-handoff-template.md`:
    - `Objective`: completar `normalize_rows` (aparar espaços, converter `amount` para inteiro, descartar linhas sem `id`) e cobrir com testes;
    - `Write scope`: `transform.py` e `tests/`;
    - `Acceptance criteria`: os três comportamentos testados e `python3 -m unittest` passando;
    - `Checks and workdir`: o pedido da decisão 2;
  - envelope com:
    - um estágio `python-etl`, `review = "each_stage"`, `max_corrections = 1`;
    - `max_duration = "2h"`, `judge_max_calls = 1`, `on_pass_with_risks = "judge"`;
    - a allowlist da decisão 2 e o branch `feat/acc`.
  - Gravar o envelope com a função `envelope_draft` do servidor, chamada em processo, e conferir com `envelope_show` (`errors: []`).
- [ ] **Step 3: passo do usuário.** `bin/marina approve marina-acc acc-envelope`, num terminal. Depois a Marina confere que `envelope_show` mostra `approved: true` e `approval_matches: true`.

### Task 3: executar e interromper (Marina, com sessões reais)

- [ ] **Step 1: iniciar.** Na raiz do kit, rodar em background `bin/marina run marina-acc acc-envelope --interval 20 --max-duration 2h`. Registrar o pid e o horário.
- [ ] **Step 2: SIGINT.** Quando `marina status` mostrar o nn=01 em `working`, mandar `kill -INT <pid>`. Esperado:
  - o processo sai com 1;
  - o checkpoint ganha uma seção com `stop(interrupted)`;
  - `.marina-run.lock` deixa de existir;
  - a sessão nativa do nn=01 continua trabalhando.
- [ ] **Step 3: retomar.** Rodar `bin/marina run …` de novo, em background. O runner observa o nn=01, sem criar nó, e segue a cadeia.
- [ ] **Step 4: SIGKILL.** Quando o reviewer estiver `working`, mandar `kill -9 <pid>`. Esperado:
  - a trava fica órfã;
  - `marina status` mostra "not running (orphan lock)";
  - `bin/marina run … --recover` recusa enquanto a sessão do reviewer estiver `working`.

  Depois que o manager mostrar o reviewer terminado, `--recover` assume a trava e a cadeia continua.
- [ ] **Step 5: deixar terminar** em `done` ou num `stop` com motivo. Registrar o caminho real:
  - houve ou não `corrige`;
  - a juíza foi chamada ou não;
  - cada id nativo, a duração e o custo, quando houver.

### Task 4: servidor MCP real

- [ ] **Step 1: sonda headless (Marina).** Na raiz do kit, com stdin fechado, rodar:

  `claude -p --agent marina --mcp-config .mcp.json --strict-mcp-config --allowedTools mcp__marina__task_status --output-format json --max-budget-usd 0.50 --no-session-persistence -- "Call mcp__marina__task_status with project marina-acc and task acc-envelope, then reply with the next_nn value only."`

  Evidência:
  - `subtype: success`;
  - `permission_denials` vazio;
  - `next_nn` igual ao do `state.toml`, conferido no arquivo e não no texto da resposta.
- [ ] **Step 2: passo interativo (usuário).** Abrir `claude --agent marina` na raiz do kit, aprovar o servidor `marina` no diálogo de primeiro uso e pedir o `task_status` da tarefa `acc-envelope`. A Marina registra o relato do usuário. Sem esse passo, o item fica pendente.

### Task 5: consolidar e revisar

- [ ] **Step 1: matriz de aceitação no checkpoint.** Para cada item da spec 3.7 e dos "Visible-session acceptance scenarios", registrar o resultado (executado, falho ou pendente) e a evidência (arquivo, campo, id nativo):
  - quatro ids nativos distintos, ou o que a cadeia real produziu;
  - receipts escritos pelos especialistas;
  - Gate de Git entre writers;
  - `NOTES.md` preservado;
  - negação registrada;
  - SIGINT e SIGKILL com retomada sem duplicação;
  - servidor MCP.
- [ ] **Step 2: `kit_lint` e suíte.** `kit_lint` 6/6 e suíte completa; hash alheio inalterado.
- [ ] **Step 3: reviewer em sessão visível** sobre a Task 1 e a matriz de evidências da Task 5. É só leitura, inclusive do repositório descartável.
- [ ] **Step 4: promover fatos** para `project/facts.md` e fechar o checkpoint. Os defeitos encontrados viram atribuições próprias, propostas ao usuário.

## Execução

- **Tasks 1, 2 e 5:** a Marina executa na sessão principal. É documentação e preparação, e não há código de `scripts/`.
- **Tasks 3 e 4:** sessões reais lançadas pelo próprio `marina run`.
- **Passos do usuário:** dois, o `marina approve` (Task 2, Step 3) e a aprovação interativa do servidor MCP (Task 4, Step 2). A Marina para e pede cada um.
- **Commits:** só com autorização explícita. O repositório descartável nunca é commitado no kit.
