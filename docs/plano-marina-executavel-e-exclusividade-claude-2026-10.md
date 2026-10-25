# Plano: Marina executável e exclusividade Claude — 2026-10-25

**Status:** design aprovado por seções em 2026-10-25; nada implementado. Base de análise: [analise-marina-executavel-e-exclusividade-claude-2026-10.md](analise-marina-executavel-e-exclusividade-claude-2026-10.md).

**Escopo.** Dois sub-projetos, executados em ordem:

1. **Exclusividade Claude** (fase F0) — remover o lado Codex do kit.
2. **Executável da Marina** (fases F1–F6) — um pacote Python `marina` que impõe por código a metade mecânica da coordenação e roda cadeias de atribuições sem supervisão dentro de um envelope aprovado por humano.

## 1. Entendimento acordado

**Objetivos (do usuário):**

- O procedimento deixa de depender da disciplina da Marina-LLM: gates, preflight, checkpoint e comando de launch são impostos por código.
- A Marina-LLM gasta contexto em decisões, não em montar comandos, ler JSON do manager ou reler estado.
- Uma cadeia implementação → revisão → correção → revisão pode avançar sem o usuário presente, **dentro de um envelope pré-aprovado**.

**Decisões tomadas:**

| Tema | Decisão |
|---|---|
| Autonomia | Envelope pré-aprovado: o usuário aprova antes estágios, alvos, allowlist e limites; o runner avança só dentro dele |
| Julgamento | Híbrido: regras mecânicas decidem os casos claros; uma Marina-juíza headless decide só os ambíguos, antes de parar |
| Interface | CLI (`marina run/status/approve/stop`) + servidor MCP (`marina mcp`) para a Marina interativa |
| Linguagem | Meio, não requisito: evoluir o Python stdlib atual (abordagem A), reaproveitando scripts e testes |
| Hooks de enforcement | No sub-projeto 2 (fase F2), porque `launch_claude` monta o `--settings` |

**Restrições que permanecem:** nada de `bypassPermissions` ou `--permission-prompts none`; aprovações nativas esperam o humano via `claude attach`; sessões visíveis via `claude --bg`, sem fork/resume/continue; writers sequenciais; sessões nunca arquivadas automaticamente; segredos nunca no estado.

**Abordagens descartadas:** Go incremental chamando os scripts Python (duas linguagens escrevendo o mesmo `state.toml` por muito tempo); reescrita total em Go (maior custo e risco de regressão sobre 281 testes, sem objetivo que dependa da linguagem). Portar para Go continua possível depois, com a interface MCP e o schema v1 já definidos.

## 2. Sub-projeto 1 — exclusividade Claude (F0)

### Remoções

- `.codex/` (12 perfis + `config.toml`).
- `.agents/skills/` (cópias das skills + 6 `agents/openai.yaml`).

### Tooling

- `scripts/kit_lint.py`: remover `check_agent_profile_parity`, `check_instructions_parity`, `check_skills_identity` e `_PATH_SUBSTITUTIONS`. Adicionar `check_no_foreign_runtime`, que falha se `.codex/` ou `.agents/` existirem.
- `scripts/state/model.py`: `NATIVE_PLATFORMS = {"claude", "unavailable"}`.
- `scripts/state_lint.py`: remover a parte "codex com `id` exige `host`" da invariante 6; manter "unavailable exige `reason`".
- `scripts/state/__main__.py`: remover `codex` de `--platform` e o argumento `--host`.
- `scripts/handoff_sync.py:95`: aceitar só o perfil `.claude/agents/<role>.md`.
- Testes: ajustar `tests/test_kit_lint.py` aos checks novos; remover `test_6_codex_with_id_without_host`; testar `check_no_foreign_runtime`.
- `tests/fixtures/visible-sessions/state.toml`: sem mudança de dados (o nn=4 é um fallback `unavailable` real); comentário do nn=4 marca o contexto como histórico.

Nenhum `state.toml` real usa `platform = "codex"` (verificado em `.agent-state/` em 2026-10-25), portanto não há migração.

### Instruções e documentos

- `AGENTS.md`: remover as menções a Codex nas linhas 10, 25 e 28. O arquivo permanece como entrada neutra importada por `CLAUDE.md`.
- `.claude/skills/task-execution/SKILL.md`: remover "Codex uses unchanged project-local approval controls".
- `.claude/instructions/kit-tooling.md`: remover a menção a `.codex/`.
- `docs/agent-workflow.md`: remover a seção "Codex desktop"; trocar "execute in each platform" por execução no Claude; remover o caso "Native runtime" dual da tabela de avaliação.
- `README.md`: título, pré-requisitos, início rápido, tabela de plataformas e descrição do `kit_lint` sem Codex.
- Documentos históricos em `docs/` (análises e planos anteriores): conteúdo intocado; uma linha no topo: "Contexto histórico: o kit era dual Codex/Claude até 2026-10."

### Fora de escopo

Renomear o repositório (decisão do usuário, no GitHub).

### Verificação

`python3 scripts/kit_lint.py` verde; `python3 -m unittest discover -s tests` verde; `grep -ri codex` sem ocorrências fora dos documentos históricos, da fixture e deste plano.

## 3. Sub-projeto 2 — executável da Marina (F1–F6)

### 3.1 Componentes

Pacote em `scripts/marina/`, invocado por `bin/marina` (`exec python3 -m scripts.marina "$@"`). Os scripts existentes (`preflight`, `gate`, `launch_claude`, `status_claude`, `receipt_lint`, `handoff_sync`, `state`) continuam sendo a base: o pacote importa suas funções e não as reimplementa; suas CLIs continuam funcionando.

| Unidade | Responsabilidade | Depende de |
|---|---|---|
| `envelope.py` | Modelo, validação, hash e registro de aprovação do envelope | `state.model` |
| `decide.py` | Função pura: estado + envelope + observações → `launch(nó)`, `wait`, `ask_judge(pergunta)` ou `stop(motivo)`. Sem I/O | `gate`, `envelope` |
| `handoff_gen.py` | Gera o handoff de sucessores `revisa`, `corrige` e `prossegue` | `handoff_sync`, `receipt_lint` |
| `judge.py` | Adaptador da Marina-juíza headless | subprocess injetável |
| `runner.py` | Laço com trava, observação, reconciliação, decisão, execução e registro | todos acima |
| `mcp_server.py` | Servidor MCP stdio (JSON-RPC: `initialize`, `tools/list`, `tools/call`) | `envelope`, `decide`, `state` |
| `hooks.py` | Comandos de hook `guard-write` e `require-receipt` | `receipt_lint` |
| `cli.py` | `run`, `status`, `approve`, `stop`, `mcp`, `hook` | — |

### 3.2 Envelope e schema v1

Tabela opcional `[envelope]` no `state.toml`. Um `state.toml` sem envelope continua válido; `marina run` recusa rodar nele.

```toml
[envelope]
targets            = ["/abs/api"]
branches           = { "/abs/api" = "feat/x" }
allowlist          = ["Bash(mvn test)"]
review             = "each_stage"    # each_stage | final
max_corrections    = 1               # por estágio; 0 ou 1 (ver "Segundo FAIL consecutivo")
max_duration       = "8h"
judge_max_calls    = 4
on_pass_with_risks = "judge"         # accept | judge | stop

[[envelope.stages]]
role    = "java-backend"
handoff = "01-java-backend-handoff.md"

[[envelope.stages]]
role    = "java-backend"
handoff = "stage-2-handoff-template.md"

[envelope.approval]
at     = 2026-10-25T21:00:00-03:00
sha256 = "<sha256 do envelope sem approval + conteúdo dos handoffs citados>"
```

**Expansão em grafo.** O estágio 1 é `inicia`; cada estágio seguinte é `prossegue`. `review = "each_stage"` insere `revisa` após cada estágio; `"final"` insere um único `revisa` após o último. Um `FAIL` produz `corrige` com o papel do writer revisado, até `max_corrections` por estágio, seguido de novo `revisa`. Com `review = "final"`, a correção conta na cota do último estágio. O runner nunca cria papel, aresta (`analisa`, `continua`, `substitui`, `revisa_direta`) ou alvo fora dessa expansão.

**Predecessores, conforme G3.** `revisa` tem como predecessor o último writer `accepted` do estágio (o writer original ou o último `corrige`). `corrige` tem como predecessor o reviewer `accepted` com `verdict = FAIL`. `prossegue` tem como predecessor o último writer `accepted` do estágio anterior, e só é aberto depois que a revisão desse estágio terminou em `PASS` (ou `PASS_WITH_RISKS` aceito); com `review = "final"`, logo após o writer ser aceito.

**Validação.** Cada estágio usa um papel writer existente em `.claude/agents/`; cada handoff citado existe dentro do diretório da tarefa; `targets` são caminhos absolutos; `allowlist` passa pelas mesmas recusas de `launch_claude` (`_check_forbidden_allowlist`); `max_corrections ∈ {0, 1}`; `judge_max_calls ≥ 0`.

**Aprovação.** Só `marina approve <projeto> <tarefa>` grava `[envelope.approval]`. Exige TTY: imprime um resumo (estágios, papéis, alvos, branches, allowlist, limites, política de juíza) e pede que o usuário digite o slug da tarefa. Sem TTY, recusa com código de saída não zero.

**Invalidação.** O runner para com `stop(envelope_changed)` quando o hash recalculado diverge, quando o branch atual de um alvo difere de `branches`, ou quando a allowlist de um nó difere da do envelope. `envelope_draft` (MCP) apaga `[envelope.approval]` a cada escrita.

**Proveniência.** Eventos criados pelo runner usam `by = "marina-run"`; decisões da juíza, `by = "marina-judge"`, com pergunta e resposta resumidas em `note`. A Marina interativa continua com `by = "marina"`.

### 3.3 Laço e tabela de decisão

Cada iteração de `marina run <projeto> <tarefa> --interval <s> --max-duration <d>` (ambos obrigatórios, efetivo = mínimo entre `--max-duration` e `envelope.max_duration`):

1. Adquire `tasks/<tarefa>/.marina-run.lock` (pid e início). Trava existente → recusa.
2. Revalida o envelope (hash, branches, allowlist).
3. Observa o nó ativo via `status_claude` e registra a transição observada.
4. Chama `decide`.
5. Executa a ação; dorme até `--interval`.

| Estado do nó atual | Decisão |
|---|---|
| `launched`, `working` | `wait` |
| `waiting_approval` | executa `--notify-cmd` (se informado) uma vez por entrada nesse estado; `wait`. Nunca responde à aprovação |
| `uncertain` | reconcilia pelo manager (título, cwd, horário, ID). Encontrou → `launched`. Ausência confirmada → `abandoned` e `stop` |
| `finished` sem receipt | `receipt_missing` e `stop` |
| `receipt_received` | `receipt_lint`: PASS → `receipt_validated`; FAIL → `receipt_invalid` e `stop` |
| writer validado, `status: done` | `accepted`; próximo: `revisa` (each_stage) ou `prossegue`/`revisa` final |
| writer validado, `pending`/`needs_input`/`blocked` | `closed_*` correspondente e `stop` |
| reviewer `PASS` | `accepted`; próximo estágio ou fim `done` |
| reviewer `PASS_WITH_RISKS` | `accepted`; depois, conforme `on_pass_with_risks`: seguir como PASS, `ask_judge` ou `stop` |
| reviewer `FAIL` | `accepted` (a revisão em si é válida); depois `corrige` se P_progresso passa, há cota em `max_corrections` e não é o 2º FAIL consecutivo da cadeia; `ask_judge` se a sobreposição do `risks_digest` cai na faixa cinzenta; senão `stop` |
| `preparation_failed` | `stop` |

**Faixa cinzenta.** `gate.risks_overlap_substantially` passa a expor a razão de sobreposição. Acima do limiar atual → sem progresso (`stop`); abaixo de um limiar inferior novo → progresso (`corrige`); entre os dois → `ask_judge`. O limiar inferior é uma constante em `gate.py` com teste.

**Segundo FAIL consecutivo.** Sempre `stop`, independentemente da juíza: continua exigindo decisão humana registrada no journal. Por isso `max_corrections` aceita só 0 ou 1 no schema v1; a aprovação do envelope não conta como essa decisão antecipada. Aceitar mais correções automáticas exige mudar essa regra explicitamente, fora deste plano.

**Abertura de nó.** `state add` (by `marina-run`) → `handoff_gen` → `preflight` → `gate` → `launch_claude`. Uma falha em qualquer passo registra o terminal correspondente (`preparation_failed`, `uncertain`) e para.

**Gate de Git.** O runner grava `git-before-NN.txt` no launch e `git-after-NN.txt` ao observar `finished` de cada writer. Antes do próximo writer, reconhece o diff automaticamente só se o `git status`/`git diff` atual for idêntico ao `git-after` do writer anterior; qualquer diferença → `stop(foreign_change)`.

**Contrato da juíza.** Perfil novo `.claude/agents/marina-judge.md`, tools só `Read`. Invocação: `claude -p --agent marina-judge --allowedTools Read --json-schema <schema>` com timeout. Entrada: tipo da pergunta, opções permitidas (sempre incluindo `stop`) e caminhos absolutos de receipts e handoffs relevantes. Saída: `{"decision": <opção>, "reason": <≤ 200 caracteres>}`. Timeout, JSON inválido, opção não oferecida ou cota `judge_max_calls` esgotada → `stop(judge_failed)`. A juíza não lança, não edita e não coordena; ela escolhe entre opções que `decide` já validou.

**Encerramento.** Em `done` ou `stop`, o runner acrescenta ao `checkpoint.md` uma seção gerada "Execução marina-run <timestamp>" com nós criados, decisões da juíza, motivo de parada e próxima ação/dono; depois solta a trava.

### 3.4 MCP e permissões

Registro em `.mcp.json` na raiz do kit: `python3 -m scripts.marina mcp`. Servidores de escopo de projeto exigem aprovação do usuário no primeiro uso.

| Ferramenta | Tipo | Comportamento |
|---|---|---|
| `task_status`, `envelope_show`, `sessions`, `next_nn` | leitura | estado da tarefa, envelope, classificação do manager, próximo NN |
| `gate_check` | leitura | avalia `gate` para um nó proposto |
| `decision_preview` | leitura | roda `decide` a seco e devolve a decisão atual |
| `envelope_draft` | escrita restrita | grava `[envelope]` e apaga `[envelope.approval]` |
| `state_reserve` | escrita restrita | equivale a `state add` |
| `handoff_validate` | leitura | equivale à validação de `handoff_sync` |
| `launch_node` | ação | lançamento avulso de um nó `prepared` fora do envelope; sem pré-aprovação no perfil |
| `run_start`, `run_stop` | ação | inicia `marina run` destacado (log em `tasks/<t>/marina-run.log`) ou sinaliza parada; `run_start` recusa sem aprovação válida |

Não existe ferramenta de aprovação. O perfil `marina.md` recebe as ferramentas de leitura `mcp__marina__*` em `tools`; as de escrita e ação ficam sujeitas ao prompt de permissão normal.

### 3.5 Hooks por invocação

`launch_claude` acrescenta `hooks` ao JSON de `--settings` que já carrega `worktree.bgIsolation = "none"`:

- **PreToolUse** com matcher `Write|Edit|NotebookEdit` → `marina hook guard-write --role <papel> --receipt <caminho> --target <alvo>...`. Papéis leitores: permite só o receipt. Writers: permite caminhos dentro dos `targets` e o receipt. Qualquer outro caminho → bloqueio com mensagem.
- **Stop** → `marina hook require-receipt --receipt <caminho> --handoff <caminho>`. Receipt ausente ou reprovado no `receipt_lint` → bloqueia o encerramento e devolve o erro ao modelo. Se a entrada do hook indicar que ele já está ativo, libera; o runner registra `receipt_missing`/`receipt_invalid` normalmente.

**Limite declarado.** Escrita por Bash (`sed -i`, redirecionamento) não é coberta pelo PreToolUse de `Write|Edit`; continua sendo fronteira de instrução e de allowlist. Docs e o perfil do reviewer dizem isso explicitamente.

### 3.6 Falhas e retomada

- Ao iniciar, o runner reconcilia `state.toml` com o manager antes de qualquer decisão.
- Reserva gravada antes do launch e `uncertain` para launch sem ID confirmado tornam a retomada segura; não há retry automático de launch.
- Trava órfã (pid inexistente): `marina status` informa; `marina run --recover` só assume a trava se o manager confirmar que nenhuma sessão da tarefa está em `working`/`waiting_approval`.
- Exceção não prevista → `stop(internal_error)`, traceback no log, linha no checkpoint.

### 3.7 Testes

`unittest` stdlib; fixtures em `tests/fixtures/`; nunca o CLI real nem o `.agent-state/` real.

- `decide`: uma linha de teste por linha da tabela 3.3, mais invalidação (hash, branch, allowlist), faixa cinzenta e 2º FAIL consecutivo.
- `envelope`: validação, expansão em grafo, hash estável, `approve` com `isatty` injetável (sem TTY recusa).
- `runner`: relógio falso, snapshots falsos do manager, subprocess falso (padrão de `test_watch_claude`); crash e retomada; gate de Git com e sem mudança alheia; trava existente e `--recover`.
- `judge`: saída válida, JSON inválido, opção não oferecida, timeout, cota esgotada.
- `mcp_server`: JSON-RPC por pipes em processo; ausência de ferramenta de aprovação; `envelope_draft` apaga a aprovação; `run_start` recusa sem aprovação.
- `hooks`: JSON no stdin, códigos de saída e mensagem para leitor/writer/receipt e para Stop ativo/inativo.
- **Aceitação real (pendente até executada):** repositório descartável, envelope implementação → revisão → correção → revisão com o CLI real; um comando fora da allowlist que espera `attach`; interrupção do runner e retomada sem duplicação. Evidência registrada no checkpoint.

## 4. Fases

Cada fase é uma atribuição própria ao `kit-tooling` (código em `scripts/`/`tests/`), com revisão do `reviewer` porque altera contrato de estado ou de permissão. Documentação e configuração gerais ficam com a Marina.

| Fase | Entrega | Pré-condição |
|---|---|---|
| F0 | Sub-projeto 1 completo (seção 2) | — |
| F1 | Spike só de leitura no CLI instalado (2.1.306): formato de `hooks` via `--settings`; se soma às configurações do usuário; campo de Stop hook ativo; `claude -p --agent --json-schema --allowedTools` | F0 |
| F2 | `hooks.py` e integração em `launch_claude` (seção 3.5) | F1 confirma o formato; divergência devolve 3.5 para redesenho |
| F3 | `envelope.py`, schema v1, `marina approve`, `decide.py`, faixa cinzenta no `gate` | F0 |
| F4 | `handoff_gen.py`, `judge.py` com perfil `marina-judge`, `runner.py`, `marina run/status/stop`; **no mesmo bloco**, a reescrita da regra em `AGENTS.md` e `docs/agent-workflow.md`: "opening the next node is never automatic outside a human-approved envelope (`marina approve`)", e a exceção da juíza à regra "never delegate to another coordinator" (juíza só leitura, decide entre opções dadas) | F1, F3 |
| F5 | `mcp_server.py`, `.mcp.json`, `tools` do perfil `marina.md`, ajuste da skill `task-execution` | F4 |
| F6 | README, `agent-workflow.md`, tabela de ferramentas; aceitação real (3.7) | F2, F5 |

## 5. Riscos residuais

- **Escrita via Bash** continua fora do enforcement de hooks (3.5).
- **Formato instável do CLI** (`claude agents --json`, ID curto do `--bg`, `claude -p --json-schema`): mitigado por versão mínima testada no cabeçalho de cada módulo e falha ruidosa; não eliminado.
- **Execução sem supervisão pode parar cedo** em aprovação nativa fora da allowlist; é o comportamento correto, não um defeito.
- **Juíza não determinística:** restrita a escolher entre opções validadas, com cota e registro; ainda assim duas execuções podem decidir diferente no mesmo caso cinzento.
- **Dependência de fornecedor único** após F0 (ver a análise de base, seção 2).
