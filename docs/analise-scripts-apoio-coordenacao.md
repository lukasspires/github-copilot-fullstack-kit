# Análise: scripts auxiliares de apoio ao fluxo da coordenadora

> Este documento é racional histórico. A narrativa unificada e atualizada (status real, checklist do que está implementado) está em [`plano-unificado.md`](plano-unificado.md).

- **Data:** 2026-09-16
- **Branch analisada:** `feat/independent-visible-sessions` (HEAD `d18d37e`)
- **Status:** proposta de avaliação; nenhum script foi implementado
- **Escopo:** apoio, administração e controle do fluxo de tarefas coordenado pela coordenadora após a introdução de sessões visíveis independentes por atribuição

## Sumário

1. [Contexto e fontes analisadas](#1-contexto-e-fontes-analisadas)
2. [Escopo atual do fluxo de tarefas e agentes](#2-escopo-atual-do-fluxo-de-tarefas-e-agentes)
3. [Evidência de execução real](#3-evidência-de-execução-real)
4. [Casos de uso para scripts](#4-casos-de-uso-para-scripts)
5. [O que deve permanecer fora dos scripts](#5-o-que-deve-permanecer-fora-dos-scripts)
6. [Benefícios](#6-benefícios)
7. [Riscos e problemas](#7-riscos-e-problemas)
8. [Alternativa: hooks nativos como enforcement](#8-alternativa-hooks-nativos-como-enforcement)
9. [Recomendação e roteiro](#9-recomendação-e-roteiro)
10. [Requisitos de projeto para os scripts](#10-requisitos-de-projeto-para-os-scripts)
11. [Impacto documental](#11-impacto-documental)
12. [Perguntas em aberto](#12-perguntas-em-aberto)

---

## 1. Contexto e fontes analisadas

Os commits `7b5b5ea` e `d18d37e` isolaram cada atribuição de especialista em uma sessão visível independente, com handoff, receipt e checkpoint obrigatórios. A coordenadora permanece na sessão principal e executa manualmente todas as etapas mecânicas do protocolo.

Fontes lidas para esta análise:

| Fonte | Papel na análise |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Regras de coordenação, time, sessões independentes |
| `docs/agent-workflow.md` | Procedimento por plataforma (Codex desktop, Claude CLI), gates, cenários de aceitação |
| `.claude/skills/task-execution/SKILL.md` | Procedimento operacional da coordenadora (intake, roteamento, continuidade) |
| `.claude/agents/coordinator.md`, `reviewer.md`, `java-backend.md` | Ferramentas, modo de permissão e fronteiras por papel |
| `README.md` | Posicionamento do kit ("no permanent customization validator") |
| `.agent-state/visible-sessions.md` | Checkpoint real da tarefa que implementou o fluxo |
| `.agent-state/visible-sessions/02-reviewer-*.md`, `03-reviewer-*.md` | Handoffs e receipts reais de duas revisões independentes |
| `.agent-state/visible-sessions/git-before-0N.txt` | Snapshots de gate Git gravados manualmente |
| `claude --version`, `claude agents --json --all` | Estado do runtime instalado (2.1.270) |

A evidência de execução (`.agent-state/`) é a fonte de maior peso: mostra onde o fluxo já falhou na prática, não apenas onde poderia falhar.

---

## 2. Escopo atual do fluxo de tarefas e agentes

### 2.1 Papéis

| Papel | Responsabilidade | Escreve em alvos |
|---|---|---|
| `coordinator` | Intake, roteamento por risco, delegação sequencial, checkpoint, consolidação | Apenas docs/config gerais pequenas e checkpoints |
| `angular`, `java-backend`, `go-backend`, `go-etl`, `python-etl`, node-backend, `data-analyst` | Implementação no escopo atribuído | Sim (write set do handoff) |
| `architect` | Arquitetura, contratos compartilhados, migrations/backfills | Não (só o próprio receipt) |
| `reviewer` | Revisão independente por risco, com `verdict` | Não (só o próprio receipt) |
| analista-redmine | Histórico complexo (opcional) | Não (só o próprio receipt) |

### 2.2 Ciclo de vida por atribuição (`NN`)

Cada atribuição — implementação, revisão, correção ou análise — exige da coordenadora as etapas abaixo. A coluna **Natureza** distingue o que é decisão (julgamento) do que é procedimento repetível (mecânico), que é o candidato natural a script.

| # | Etapa | O que a coordenadora faz hoje | Natureza |
|---|---|---|---|
| 1 | Intake | Consolidar objetivo, critérios, evidência, decisões superadas; escolher papel por consequência | Julgamento |
| 2 | Checkpoint | Manter `.agent-state/<task>.md` em prosa livre, ignorado pelo Git | Mecânico + julgamento |
| 3 | Reserva de NN | Escolher o próximo número sequencial; nunca reutilizar após falha | Mecânico |
| 4 | Handoff | Escrever `.agent-state/<task>/<NN>-<role>-handoff.md` com ~14 campos obrigatórios (objetivo, perfil absoluto, roots, instruções do alvo, write set, contratos, evidência, autorizações, critérios, checks, predecessor, receipt path, allowlist, aviso de preservação) | Mecânico (estrutura) + julgamento (conteúdo) |
| 5 | Gate de preparação | Handoff legível; perfil existe; instruções do alvo existem; diretório de receipt existe; executáveis dos checks resolvem no ambiente; `git status/diff` gravado; nenhum outro writer ativo no manager | **Mecânico** |
| 6 | Lançamento | Claude: `claude --bg --agent --name --add-dir… --settings '{"worktree":{"bgIsolation":"none"}}' --permission-mode acceptEdits --allowedTools … -- "prompt"`. Codex: `create_thread` via MCP com `environment.type=local` | Mecânico |
| 7 | Registro do ID | Capturar o ID curto/threadId e gravar imediatamente no checkpoint | Mecânico |
| 8 | Monitoramento | `claude agents --json --all`, `claude logs <id>`; detectar `status: waiting` + `waitingFor: permission prompt` e reportar `claude attach <id>` ao usuário | Mecânico |
| 9 | Gate de liberação do writer N+1 | Receipt final do predecessor existe; manager indica `done`/`stopped`/`failed`; `git status/diff` conferido contra o snapshot; nenhuma sessão desconhecida no mesmo cwd/alvo | **Mecânico** |
| 10 | Leitura do receipt | Forma: `status`, `changed`, `checks`, `evidence`, `risks`, `next`, `profile_read`, `instructions_read`, `verdict` (`reviewer`). Mérito: aceitar ou devolver | Mecânico (forma) + julgamento (mérito) |
| 11 | Decisão seguinte | Correção → mesmo papel em nova sessão; revisão automática por risco → `reviewer`; `needs_input` → nova atribuição após resposta | Julgamento |
| 12 | Retomada | Reconciliar checkpoint × manager × Git antes de criar qualquer sessão; nunca duplicar writer | Mecânico + julgamento |
| 13 | Checks estáticos do kit | Parse TOML/YAML dos 11 perfis; paridade `.codex`/`.claude` normalizada; cópias `.agents/skills` ≡ `.claude/skills`; `git diff --check` | **Mecânico** (hoje ad hoc em Python) |

### 2.3 Regras invariantes que qualquer script deve respeitar

- A coordenadora nunca é executada em background nem delegada; scripts a apoiam, não a substituem.
- Nenhum `bypassPermissions`, `--permission-prompts none`, ou resposta automática a aprovações nativas.
- Nunca `--resume`, `--continue`, `--fork-session` para nova atribuição.
- Writers são sequenciais entre repositórios; leitores podem sobrepor-se a leitores, nunca a um writer no mesmo alvo.
- Sessões concluídas nunca são arquivadas ou apagadas automaticamente.
- `.agent-state/` é sanitizado: sem segredos, transcrições ou dados sensíveis.
- Fronteira de escrita dos papéis read-only é de instrução, não de sandbox; scripts não devem alegar o contrário.

---

## 3. Evidência de execução real

O checkpoint `.agent-state/visible-sessions.md` e os receipts do `reviewer` registram falhas concretas do fluxo manual. Cada uma mapeia diretamente para um caso de uso de script.

| Ocorrência | Registro | Causa raiz | Caso de uso relacionado |
|---|---|---|---|
| Atribuição 01 lançada apesar de preparação falha | "shell launch followed failed preparation because commands were not fail-fast. Node not on PATH" | Comandos de preparação e lançamento encadeados sem `set -e`; executável do check não resolvido no ambiente | `preflight`, `launch` |
| Atribuição 02 bloqueada sem conseguir escrever o receipt | "Receipt write failed due Claude background worktree isolation guard" | Flag `--settings '{"worktree":{"bgIsolation":"none"}}'` ausente no lançamento | `launch` (flags forçadas) |
| Atribuição 03 aguardando aprovação humana | `waitingFor: permission prompt` para `Read(/tmp/…)` fora do alvo | Comportamento esperado; detecção foi manual | `status`/`watch` |
| Asserção de paridade falhou duas vezes | "First parity assertion failed on paragraph whitespace"; "omitted platform-path normalization; corrected check PASS" | Check reescrito a cada uso, sem normalização consolidada | `kit-lint` |
| Receipts 02 e 03 com formatos distintos | `**Status:** done` inline vs. seções com títulos | Sem template ou validador de receipt | `receipt-lint` |
| Checkpoint em prosa livre | Entradas `NN \| plataforma \| papel \| id \| …` misturadas a parágrafos narrativos | Sem formato estruturado | `checkpoint add`, `reconcile` |
| Recomendação explícita da revisora | Receipt 03, Risco 1: "Create a pre-launch checklist script that verifies preparation gate conditions before dispatching" | Gate depende de disciplina da coordenadora | `preflight` |
| Documentação já admite a solução | `docs/agent-workflow.md`: "use separate successful preparation and launch steps or a fail-fast script" | — | `preflight` + `launch` |
| Versão do CLI já avançou | Documentado 2.1.267; instalado 2.1.270; JSON de sessões interativas sem campo `state` | Formato consumido pelo fluxo varia entre versões | `status` com validação de schema |
| Kit declara não ter validador permanente | README: "The kit contains no permanent customization validator" | Decisão de design a revisar se `kit-lint` for adotado | Impacto documental |

Conclusão da seção: as falhas observadas são todas em etapas **mecânicas** (5, 6, 8, 13). Nenhuma foi de roteamento ou julgamento. Isso delimita com precisão o que scripts podem melhorar.

---

## 4. Casos de uso para scripts

Ordenados por valor esperado, considerando evidência de falha, frequência de uso e neutralidade de plataforma.

### 4.1 `preflight` — gate de preparação

- **Prioridade:** 1 (evidência direta: atribuição 01; recomendação do `reviewer`)
- **Plataforma:** neutra (arquivos + Git)
- **Entradas:** slug da tarefa, `NN`, papel, `kit_root`, lista de `target_root`, lista de checks descobertos
- **Verificações:**
  - slug casa `^[a-z0-9-]+$`; nenhum symlink em `.agent-state/<task>/` escapa do diretório
  - handoff `<NN>-<role>-handoff.md` existe, não vazio, contém as seções obrigatórias
  - perfil absoluto referenciado no handoff existe e é legível
  - `AGENTS.md`/`CLAUDE.md` de cada `target_root` legíveis (quando existirem)
  - diretório `.agent-state/<task>/` existe; receipt `<NN>-<role>-receipt.md` **ainda não existe**
  - `NN` não consta como reservado/lançado no checkpoint
  - cada executável dos checks resolve via `command -v` (captura "Node not on PATH")
  - grava `git-before-<NN>.txt` com `git status --short` + `git diff --stat` de cada alvo
  - lista sessões do manager com o mesmo cwd ou alvo e sinaliza qualquer `working`
- **Saída:** relatório legível + código de saída não-zero em qualquer falha; nada é lançado
- **Escreve:** apenas `git-before-<NN>.txt` e, opcionalmente, uma linha no checkpoint

### 4.2 `gate` — liberação do writer N+1

- **Prioridade:** 2
- **Plataforma:** neutra para arquivos/Git; adaptador Claude para o manager
- **Verificações:**
  - receipt final do predecessor existe e passa em `receipt-lint`
  - `status` do predecessor ∈ {`done`, `pending`, `needs_input`, `blocked`} — e explicita que apenas `done` estabelece aceitação
  - estado do predecessor no manager ∈ {`done`, `stopped`, `failed`}; nunca `working`
  - `git status/diff` atual comparado ao `git-before-<NN>` do predecessor; diferenças listadas
  - nenhuma sessão desconhecida `working` no mesmo cwd/alvo
- **Saída:** "pode liberar writer N+1: sim/não" com motivos; nunca lança nada
- **Dependência:** formato estruturado de checkpoint (4.6)

### 4.3 `launch` — montagem do comando Claude

- **Prioridade:** 3
- **Plataforma:** Claude apenas (Codex é MCP, não shell)
- **Comportamento:**
  - deriva `--agent`, `--name "<task> — <role> — <NN> — <type>"`, `--add-dir` (repetido por alvo), `--allowedTools` e o prompt curto a partir do handoff
  - força `--settings '{"worktree":{"bgIsolation":"none"}}'` e `--permission-mode acceptEdits`
  - **recusa** `bypassPermissions`, `--permission-prompts none`, `--resume`, `--continue`, `--fork-session`
  - recusa padrões amplos de allowlist (`Bash`, `Bash(*)`)
  - executa `preflight` antes; qualquer falha aborta (`set -euo pipefail`)
  - captura o ID curto impresso e anexa ao checkpoint com carimbo de tempo
- **Não faz:** escolher papel, escolher checks, lançar o próximo writer automaticamente

### 4.4 `status` / `watch` — monitoramento bounded

- **Prioridade:** 3
- **Plataforma:** Claude (`claude agents --json --all`); Codex permanece via `wait_threads`
- **Comportamento:**
  - filtra por cwd do kit e por prefixo de título `<task> —`
  - mostra `name`, `state`, `status`, `waitingFor`, existência do receipt correspondente
  - quando `waitingFor: permission prompt`, imprime literalmente `claude attach <id>` para o usuário
  - `watch` faz polling com limite de tempo e intervalo explícitos; nunca responde prompts
  - valida o schema JSON esperado e **falha ruidosamente** se campos previstos faltarem (o JSON de 2.1.270 já omite `state` em sessões interativas)

### 4.5 `receipt-lint` — validação de forma do receipt

- **Prioridade:** 4
- **Plataforma:** neutra
- **Verificações:** campos obrigatórios presentes; `status` no enum; `verdict` presente e no enum quando papel é `reviewer`; `profile_read` igual ao perfil do handoff; `instructions_read` com caminhos absolutos existentes; ausência de conteúdo que pareça segredo (heurística simples)
- **Não faz:** avaliar mérito, riscos ou evidência

### 4.6 `checkpoint add` / `next-nn` — entradas estruturadas

- **Prioridade:** 2 (pré-requisito de 4.2 e 4.9)
- **Plataforma:** neutra
- **Comportamento:** anexa um bloco por atribuição com campos fixos (`nn`, `platform`, `role`, `native_id`, `predecessor`, `type`, `allowlist`, `state`, `handoff`, `receipt`, `git_before`, `result`, `timestamp`); `next-nn` lê o checkpoint e devolve o próximo número livre
- **Implicação:** altera o contrato do checkpoint hoje descrito em prosa; ver seção 11

### 4.7 `kit-lint` — checks estáticos do kit

- **Prioridade:** 1 (mais barato; já executado ad hoc 3+ vezes)
- **Plataforma:** neutra
- **Verificações:**
  - parse dos 11 `.codex/agents/*.toml` (`tomllib`) e 11 `.claude/agents/*.md` (frontmatter YAML)
  - paridade de corpo entre pares com normalização de whitespace de parágrafo e de caminhos nativos (`.codex/instructions` ↔ `.claude/instructions`, `.agents/skills` ↔ `.claude/skills`)
  - `.agents/skills/**` byte-idêntico a `.claude/skills/**` (exceto `agents/openai.yaml`, que só existe no lado Codex)
  - `git diff --check`
  - opcional: links relativos em `docs/` e `README.md` resolvem
- **Uso:** pela coordenadora antes de qualquer edição de kit; pelo `reviewer` em revisões do próprio kit; futuramente em CI

### 4.8 `handoff new` — scaffold do template

- **Prioridade:** 4
- **Plataforma:** neutra
- **Comportamento:** gera `<NN>-<role>-handoff.md` com todas as seções obrigatórias e placeholders; preenche automaticamente perfil absoluto, `kit_root`, receipt path e título; a coordenadora completa o conteúdo de julgamento
- **Benefício:** reduz omissões estruturais; não reduz o esforço de julgamento

### 4.9 `reconcile` — apoio à retomada

- **Prioridade:** 5
- **Plataforma:** Claude para o manager; neutra para arquivos
- **Comportamento:** cruza entradas do checkpoint com o manager; sinaliza `native_id` ausente/"uncertain", sessões no manager com título da tarefa sem entrada no checkpoint, receipts órfãos; sugere reconciliação mas **não cria nem encerra nada**
- **Dependência:** 4.6

### 4.10 Matriz resumo

| Script | Prioridade | Plataforma | Escreve | Cobre falha observada |
|---|---|---|---|---|
| `preflight` | 1 | neutra | `git-before-NN.txt`, checkpoint | 01, recomendação do `reviewer` |
| `kit-lint` | 1 | neutra | nada | paridade ×2 |
| `checkpoint add` / `next-nn` | 2 | neutra | checkpoint | prosa livre |
| `gate` | 2 | neutra + Claude | nada | — (preventivo) |
| `launch` | 3 | Claude | checkpoint | 01, 02 |
| `status` / `watch` | 3 | Claude | nada | 03, schema CLI |
| `receipt-lint` | 4 | neutra | nada | formatos 02/03 |
| `handoff new` | 4 | neutra | handoff | — (preventivo) |
| `reconcile` | 5 | neutra + Claude | nada | — (preventivo) |

---

## 5. O que deve permanecer fora dos scripts

| Atividade | Motivo |
|---|---|
| Roteamento de papel e classificação de risco | Julgamento por consequência, não por extensão/tecnologia |
| Leitura semântica de receipts (aceitar, devolver, escalar) | Mérito, não forma |
| Decisão correção × revisão × `needs_input` | Julgamento |
| Responder aprovações nativas (`attach`) | Proibido pelo protocolo; pertence ao humano |
| Criar threads Codex | Via MCP na sessão, não shell |
| Arquivar/apagar sessões | Proibido pelo protocolo |
| Editar alvos, fazer commit, push, MR, Redmine, deploy | Fora da entrega local; exige autorização própria |
| Lançar automaticamente o writer N+1 após `gate` | Erode o humano-no-loop; script propõe, a coordenadora lança |
| Reescrever `settings.json` do usuário | O kit evita deliberadamente; ver seção 8 |

---

## 6. Benefícios

1. **Disciplina vira código de saída.** Os receipts 02 e 03 apontam três riscos "instruction-level" (gate de preparação, isolamento de worktree, fronteira de escrita). `preflight` e `launch` tornam os dois primeiros verificáveis mecanicamente; a atribuição 01 não teria sido lançada.
2. **Evidência reproduzível.** Snapshots `git-before-NN.txt` e entradas de checkpoint com formato fixo tornam retomada e revisão comparáveis entre tarefas e legíveis pelo `reviewer` sem interpretação.
3. **Menos boilerplate na sessão principal.** O comando de lançamento tem sete flags com semântica de segurança; esquecer uma custou uma sessão inteira (02). Menos contexto da coordenadora gasto em `jq`/`grep` manuais e mais em julgamento.
4. **Fragilidade de plataforma encapsulada.** O consumo de `claude agents --json` fica em um lugar só, com validação de schema, em vez de espalhado em prosa e reexecutado a cada tarefa.
5. **Consolidação de checks já existentes.** `kit-lint` substitui asserções Python reescritas (e erradas) em cada rodada por um único validador testado.
6. **Base para CI futura.** `kit-lint` e `receipt-lint` são executáveis sem runtime de agente, logo podem rodar em pipeline.

---

## 7. Riscos e problemas

### 7.1 Terceira fonte de verdade

O kit já mantém paridade `.codex` ↔ `.claude`. Scripts criam um terceiro lugar onde o procedimento é definido; sem disciplina, docs e scripts divergem.

- **Mitigação:** scripts são a fonte única do procedimento mecânico; `AGENTS.md`, skills e `docs/agent-workflow.md` passam a referenciá-los em vez de repetir a checklist; `kit-lint` inclui testes dos próprios scripts.

### 7.2 Falsa sensação de enforcement

`preflight` verifica arquivos; não sandboxa nada. A fronteira "`reviewer` só escreve o receipt" continua sendo instrução (`reviewer.md`: "this profile does not enforce a filesystem sandbox").

- **Mitigação:** documentação e saída dos scripts nunca usam linguagem de "controle de permissão"; o receipt do `reviewer` continua obrigado a explicitar o limite.

### 7.3 Allowlist como caminho privilegiado

Para a coordenadora rodar `scripts/launch` sem prompt, algo como `Bash(scripts/*)` entra na allowlist; a partir daí, tudo que o script faz está pré-aprovado.

- **Mitigação:** scripts finos e auditáveis — sem rede, sem mutação Git além de leitura/snapshot, sem escrita fora de `.agent-state/`, sem responder aprovações, sem encadear lançamentos. Revisão do `reviewer` obrigatória para qualquer alteração em `scripts/`.

### 7.4 Assimetria de plataforma

`launch` e `status` só existem para Claude; Codex continua manual via MCP.

- **Mitigação:** manter `preflight`, `gate`, `checkpoint`, `receipt-lint`, `handoff new` e `kit-lint` estritamente neutros; isolar Claude em adaptadores nomeados (`launch-claude`, `status-claude`). Documentar explicitamente que Codex usa o mesmo `preflight` + `create_thread` manual.

### 7.5 Fragilidade a versão do CLI

Documentado 2.1.267; instalado 2.1.270; o JSON já omite `state` em sessões interativas.

- **Mitigação:** validação de schema com falha ruidosa; versão mínima testada declarada no cabeçalho do script; `kit-lint` avisa se `claude --version` diverge do documentado.

### 7.6 Ambiente de execução

Shell do usuário é fish; `tomllib` exige Python ≥ 3.11; PyYAML não é stdlib; Node não estava no PATH na sessão background 01.

- **Mitigação:** shebang `#!/usr/bin/env python3` (ou bash), sem dependência de fish; Python stdlib apenas, YAML de frontmatter parseado de forma mínima ou PyYAML como dependência opcional só em `kit-lint`; `preflight` reporta o PATH efetivo dos executáveis — o propósito é **expor** problemas de ambiente, não escondê-los.

### 7.7 Manutenção sem testes

O kit não tem testes; scripts sem testes viram mais um artefato de "currency não verificada".

- **Mitigação:** testes mínimos (`unittest` stdlib) usando a fixture existente em `.agent-state/visible-sessions/fixture/` ou uma fixture versionada em `tests/fixtures/`; `kit-lint` roda os testes.

### 7.8 Mudança de contrato documentado

`checkpoint add` altera o formato do checkpoint descrito em três documentos; `kit-lint` contradiz a frase do README sobre ausência de validador.

- **Mitigação:** tratar como mudança de contrato com revisão do `reviewer`; ver seção 11.

### 7.9 Sobre-automação e perda do humano-no-loop

Um `watch` que lança o próximo writer ao detectar `done` transformaria o fluxo em pipeline autônomo, contrariando o design.

- **Mitigação:** regra fixa — scripts propõem, a coordenadora decide e executa cada lançamento; `watch` termina ao detectar transição, não age.

### 7.10 Sanitização

Scripts que escrevem em `.agent-state/` podem vazar ambiente, transcrições ou caminhos sensíveis.

- **Mitigação:** escrever apenas campos enumerados; nunca `env`, `claude logs` completos ou stdout de checks além de resumo; `receipt-lint` com heurística de segredo.

### 7.11 Balanço

| Dimensão | Sem scripts | Com scripts (recomendação) |
|---|---|---|
| Gate de preparação | disciplina; falhou (01) | código de saída; fail-fast |
| Flags de lançamento | memória; falhou (02) | forçadas e validadas |
| Detecção de prompt pendente | leitura manual de JSON | automática, com `attach` impresso |
| Checks do kit | reescritos a cada uso; falharam ×2 | consolidados e testados |
| Fontes de verdade | 2 (`.codex`, `.claude`) | 3 (+ `scripts/`) — exige lint cruzado |
| Enforcement de permissões | instrução | instrução (inalterado) |
| Cobertura Codex | manual | manual para lançamento; neutro no resto |
| Custo de manutenção | baixo | médio (testes, versão CLI) |

---

## 8. Alternativa: hooks nativos como enforcement

Um hook `PreToolUse` em `<kit_root>/.claude/settings.json` (projeto = raiz da sessão), casando o comando `claude --bg*` no tool `Bash` e executando `preflight`, transformaria o gate em enforcement do runtime: a coordenadora não conseguiria lançar sem o gate passar, independentemente de lembrar de chamá-lo.

**A favor**

- É o único mecanismo disponível que sai de "disciplina" para "controle" para a etapa 5.
- Escopo de projeto: não altera settings do usuário, apenas os do kit versionado.

**Contra**

- O kit hoje evita deliberadamente reescrever settings; um `settings.json` de projeto é uma mudança de postura a decidir explicitamente.
- Um hook com bug bloqueia toda dispatch; precisa de `preflight` estável e testado antes.
- Não existe equivalente no Codex desktop; aumenta a assimetria.
- Hooks executam com a permissão da sessão; o próprio hook vira caminho privilegiado (mesmo risco de 7.3).

**Posição:** considerar como terceira etapa, após `preflight` provado em uso real por pelo menos uma cadeia completa de quatro atribuições.

---

## 9. Recomendação e roteiro

### Etapa 1 — neutros e de maior evidência

- `kit-lint` (consolida checks já executados)
- `preflight` (cobre a falha 01 e a recomendação do `reviewer`)
- formato estruturado de checkpoint + `checkpoint add` / `next-nn` (pré-requisito de `gate`)
- testes mínimos com fixture
- atualização documental (seção 11)
- revisão independente do `reviewer` sobre `scripts/` e o novo contrato de checkpoint

### Etapa 2 — adaptadores Claude

- `gate`
- `launch-claude` (encadeando `preflight`)
- `status-claude` / `watch-claude` com validação de schema
- `receipt-lint`
- validação em uma cadeia real implementação → revisão → correção → revisão usando os scripts; registrar no checkpoint da tarefa

### Etapa 3 — opcionais

- `handoff new`
- `reconcile`
- hook `PreToolUse` (seção 8), somente após Etapa 2 validada

### Critério de aceitação da iniciativa

- Uma cadeia real de quatro atribuições em Claude executada com `preflight`/`gate`/`launch` sem lançamento após preparação falha e sem flag esquecida.
- `kit-lint` verde no kit atual e vermelho em uma quebra de paridade introduzida de propósito (teste).
- Receipt do `reviewer` `PASS` ou `PASS_WITH_RISKS` sobre `scripts/`, com os riscos 7.2 e 7.3 explicitamente avaliados.

---

## 10. Requisitos de projeto para os scripts

| Requisito | Decisão proposta |
|---|---|
| Localização | `<kit_root>/scripts/` (neutro de plataforma; não em `.claude/` nem `.codex/`) |
| Linguagem | Python 3 stdlib (≥ 3.11 para `tomllib`); bash apenas para wrappers triviais |
| Dependências externas | nenhuma obrigatória; PyYAML opcional e declarado |
| Shell do usuário | não assumir fish; shebang explícito |
| Escrita | somente em `.agent-state/<task>/` e no checkpoint; nunca em alvos |
| Rede | nenhuma |
| Git | somente leitura (`status`, `diff`, `rev-parse`); nunca `checkout`, `reset`, `commit` |
| Manager | somente `claude agents --json --all` e `claude logs <id>` com limite de linhas |
| Aprovações | nunca responder; apenas imprimir `claude attach <id>` |
| Lançamento | um por invocação, explícito; nunca encadear N+1 |
| Flags proibidas | `bypassPermissions`, `--permission-prompts none`, `--resume`, `--continue`, `--fork-session`, allowlist ampla |
| Saída | legível para humano e a coordenadora; código de saída significativo; `--json` opcional |
| Schema do manager | validado; falha ruidosa em divergência |
| Versão mínima do CLI | declarada no cabeçalho; checada por `kit-lint` |
| Sanitização | campos enumerados; sem dump de ambiente ou logs completos |
| Testes | `unittest` com fixture; executados por `kit-lint` |
| Revisão | qualquer alteração em `scripts/` passa pelo `reviewer` |

---

## 11. Impacto documental

| Documento | Alteração necessária |
|---|---|
| `README.md` | Revisar "The kit contains no permanent customization validator" se `kit-lint` for adotado; mencionar `scripts/` |
| `AGENTS.md` | Referenciar `preflight`/`gate` como forma canônica dos gates; manter regras invariantes |
| `CLAUDE.md` | Referenciar `launch-claude`/`status-claude` no lugar da lista de flags (mantendo a lista como documentação) |
| `docs/agent-workflow.md` | Substituir a checklist manual do gate pela chamada ao script; documentar o formato estruturado do checkpoint; atualizar versão do CLI |
| `.claude/skills/task-execution/SKILL.md` e `.agents/skills/task-execution/SKILL.md` | Mesmas mudanças, mantendo cópias idênticas |
| `.claude/agents/coordinator.md` e `.codex/agents/coordinator.toml` | Instruir uso dos scripts antes de qualquer lançamento; sem alterar `tools`/`permissionMode` |
| `.gitignore` | Sem mudança (scripts versionados; `.agent-state/` continua ignorado) |

Toda alteração acima é de contrato do kit e deve passar pelo fluxo normal: handoff, sessão visível do `reviewer`, receipt.

---

## 12. Perguntas em aberto

1. O checkpoint deve migrar para um formato totalmente estruturado (YAML/JSON) ou manter prosa com um bloco estruturado por atribuição? A segunda opção preserva legibilidade humana; a primeira simplifica `gate`/`reconcile`.
2. `scripts/` deve cobrir também a verificação de `create_thread`/`wait_threads` do Codex por meio de arquivos intermediários gravados pela coordenadora, ou o lado Codex permanece 100% manual?
3. Há intenção de adotar `settings.json` de projeto no kit (pré-requisito para hooks)? A decisão muda a postura documentada de "não reescrever settings".
4. Qual a política de versão mínima do CLI: pinar e falhar, ou avisar e prosseguir?
5. Os testes dos scripts devem usar a fixture já existente em `.agent-state/` (ignorada pelo Git) ou uma fixture versionada em `tests/`?
