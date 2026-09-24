# Plano unificado: ferramentas de apoio, estado estruturado e memória de projeto

- **Data:** 2026-09-24
- **Branch:** `feat/structured-state-tooling` (HEAD `a01ab93`)
- **Status:** ver [checklist](#11-checklist-do-que-foi-implementado-até-2026-09-24) — Etapas 0–2 do roteiro concluídas e commitadas; Etapa 3 pendente
- **Une:** [`analise-scripts-apoio-coordenacao.md`](analise-scripts-apoio-coordenacao.md), [`plano-memoria-por-projeto.md`](plano-memoria-por-projeto.md) e [`plano-estado-estruturado-e-grafos.md`](plano-estado-estruturado-e-grafos.md)
- **Escopo:** uma única narrativa — problema, decisões, contrato e roteiro — para as três iniciativas que, juntas, formam o apoio mecânico ao fluxo da coordenadora. Os três documentos originais permanecem no repositório como racional histórico (evidência, tabelas de decisão, mermaid) e continuam linkados por commits e receipts anteriores; este documento não os substitui fisicamente, mas é a referência única daqui para frente.

## Sumário

1. [Por que unificar](#1-por-que-unificar)
2. [Contexto e evidência](#2-contexto-e-evidência)
3. [Papéis e ciclo de vida de uma atribuição](#3-papéis-e-ciclo-de-vida-de-uma-atribuição)
4. [Memória de projeto](#4-memória-de-projeto)
5. [Estado estruturado do grafo](#5-estado-estruturado-do-grafo)
6. [Ferramentas (`scripts/`)](#6-ferramentas-scripts)
7. [Requisitos de projeto para os scripts](#7-requisitos-de-projeto-para-os-scripts)
8. [Riscos e mitigações](#8-riscos-e-mitigações)
9. [Decisões confirmadas](#9-decisões-confirmadas)
10. [Roteiro consolidado](#10-roteiro-consolidado)
11. [Checklist do que foi implementado até 2026-09-24](#11-checklist-do-que-foi-implementado-até-2026-09-24)
12. [Fora de escopo / pendências documentais](#12-fora-de-escopo--pendências-documentais)

---

## 1. Por que unificar

Os três documentos nasceram em sequência — análise (2026-09-16) → memória por projeto (2026-09-18) → estado estruturado (2026-09-18, revisado 2026-09-19) — e cada um carrega seu próprio cabeçalho de `Status`, seu próprio roteiro e, em parte, sua própria lista de decisões. Isso já causou uma divergência real: o `Status` de `plano-estado-estruturado-e-grafos.md` ainda diz "Etapas 1–3 (scripts) não iniciadas; nenhum código existe ainda", e a seção "Structured task state" de `docs/agent-workflow.md` ainda diz "Nothing below is implemented yet — no `scripts/`, `state.toml` writer or lint exists in the kit", mas o commit `a01ab93` (2026-09-19) já implementou e testou `scripts/` inteiro (ver [checklist](#11-checklist-do-que-foi-implementado-até-2026-09-24)). Um plano por iniciativa, cada um reescrevendo seu próprio status, é exatamente o tipo de terceira fonte de verdade que a própria análise (§7.1) advertia — só que entre documentos, não entre scripts e docs.

Este documento consolida o que é comum às três iniciativas (evidência, ciclo de vida da atribuição, decisões, riscos, roteiro) em um só lugar, com um único `Status` atualizado a partir do estado real do repositório, e termina com um checklist verificável.

## 2. Contexto e evidência

A base fatual é a análise original: os commits `7b5b5ea`/`d18d37e` isolaram cada atribuição de especialista em sessão visível independente, e o checkpoint real de `visible-sessions` (`.agent-state/visible-sessions.md` e os receipts `02`/`03` do `reviewer`) registrou falhas concretas — todas em etapas **mecânicas**, nunca de julgamento:

| Falha observada | Causa raiz | Ferramenta que cobre |
|---|---|---|
| Atribuição 01 lançada apesar de preparação falha (`node` fora do `PATH`) | Comandos de preparação/lançamento sem fail-fast | `preflight` |
| Atribuição 02 bloqueada ao escrever o receipt | Flag `--settings '{"worktree":{"bgIsolation":"none"}}'` esquecida | `launch-claude` (flags forçadas) |
| Atribuição 03 aguardando aprovação sem detecção automática | Leitura manual do JSON do manager | `status-claude` / `watch-claude` |
| Asserção de paridade `.codex`↔`.claude` falhou duas vezes | Check reescrito ad hoc a cada uso | `kit-lint` |
| Receipts 02/03 em formatos distintos | Sem template nem validador | `receipt-lint` |
| Checkpoint em prosa livre, difícil de reconciliar | Sem formato estruturado | `state.toml` + `state add`/`set` |

Detalhe completo das fontes lidas, da tabela de papéis e do ciclo de vida por atribuição (etapas 1–13): [`analise-scripts-apoio-coordenacao.md` §1–3](analise-scripts-apoio-coordenacao.md#1-contexto-e-fontes-analisadas).

## 3. Papéis e ciclo de vida de uma atribuição

Inalterado pelas duas iniciativas seguintes — `coordinator` faz intake, roteamento e checkpoint; `angular`/`java-backend`/`go-backend`/`go-etl`/`python-etl`/`node-backend`/`data-analyst`/`kit-tooling` escrevem no alvo atribuído; `architect`, `reviewer` e `analista-redmine` são leitores que só escrevem o próprio receipt. As regras invariantes (nenhum `bypassPermissions`, writers sequenciais, `NN` nunca reutilizado, sessões concluídas nunca arquivadas, `.agent-state/` sanitizado) seguem valendo sem exceção e são o pano de fundo de tudo abaixo — ver [análise §2](analise-scripts-apoio-coordenacao.md#2-escopo-atual-do-fluxo-de-tarefas-e-agentes).

## 4. Memória de projeto

Implementada e documentada como contrato em [`docs/agent-workflow.md` §"Project memory"](agent-workflow.md#project-memory). Resumo:

- Tudo que o kit gera vive em `<kit_root>/.agent-state/<projeto>/`, onde `<projeto>` é o slug do repositório-alvo ou do workspace que agrupa vários repositórios de uma tarefa multi-repo.
- Dois níveis: `project/` (memória estável — `repositories.md`, `architecture.md`, `conventions.md`, `integrations.md`; só a coordenadora escreve, por promoção) e `tasks/<tarefa>/` (`checkpoint.md`, handoffs, receipts, `inputs/` para anexos).
- Promoção: o receipt do especialista pode listar `promote_to_project_knowledge`; só a coordenadora decide o que vira memória de projeto e escreve em `project/`. O especialista nunca escreve lá.
- `project/` segue a mesma regra de sanitização de `.agent-state/` e continua fora do Git.

Racional completo, tabela de decisões e a migração local já executada (`task-5233.md` → `agenda/tasks/task-5233/checkpoint.md`, etc.): [`plano-memoria-por-projeto.md`](plano-memoria-por-projeto.md). Este layout é a base de caminhos usada por todo o resto deste documento (`state.toml`, handoffs, receipts).

## 5. Estado estruturado do grafo

Uma tarefa é modelada como um grafo cujos nós são atribuições (`NN`) e cujas arestas são as regras de sequenciamento já escritas em prosa no kit. O contrato vivo — schema v0 do `state.toml`, a máquina de estados de uma atribuição (G2) e o grafo de dependência entre atribuições (G3) — está documentado em [`docs/agent-workflow.md` §"Structured task state (schema v0)"](agent-workflow.md#structured-task-state-schema-v0); **este documento não o duplica**. Resumo dos três grafos:

- **G1 — fases da tarefa** (`intake → discovery → [architecture] → implementation → review ⇄ correction → delivery`, com desvios para `waiting_input`/`blocked`): só em [`plano-estado-estruturado-e-grafos.md` §3](plano-estado-estruturado-e-grafos.md#3-g1--grafo-de-fases-da-tarefa) — ainda não promovido a contrato porque nenhum script lê `task.phase` hoje (ver [checklist](#11-checklist-do-que-foi-implementado-até-2026-09-24)).
- **G2 — estados de uma atribuição** (`reserved → prepared/preparation_failed → launched/uncertain → working → waiting_approval → finished → receipt_received/... → accepted/returned/closed_*`): contrato em `agent-workflow.md`; implementado pelos scripts listados na seção 6.
- **G3 — dependência entre atribuições** (arestas `inicia`, `revisa`, `revisa_direta`, `analisa`, `corrige`, `continua`, `substitui`, cada uma com predicado `P0`/`P_writer`/`P_reader`/`P_progresso`): contrato em `agent-workflow.md`; predicados implementados em `scripts/gate.py`.

Separação de fontes de verdade (regra de não duplicação): `state.toml` é o estado mecânico do grafo (nós, arestas, transições, IDs nativos, resumo de receipt); `checkpoint.md` continua sendo o diário narrativo (objetivo, motivos, autorizações, evidência) e só referencia nós por `NN`. Nenhum dos dois repete campo do outro.

Racional completo — por que grafos, os loops (correção, monitoramento, clarificação, reconciliação) e suas condições de parada, e as oito invariantes verificadas por `state-lint` — está em [`plano-estado-estruturado-e-grafos.md` §1, §6, §5](plano-estado-estruturado-e-grafos.md).

## 6. Ferramentas (`scripts/`)

Mapeamento dos casos de uso da análise para as ferramentas reais, com o estado de implementação atual (script → transição/predicado que cobre):

| Script | Transição/predicado (G2/G3) | Estado |
|---|---|---|
| `python3 -m scripts.state {init,add,set,next-nn}` | Cria/reserva nós; grava julgamento da coordenadora | ✅ implementado, testado |
| `scripts/preflight.py` | `reserved → prepared \| preparation_failed` (checks P0) | ✅ implementado, testado |
| `scripts/gate.py` | Avalia `P_writer`/`P_reader`/`P_progresso` para a aresta proposta; nunca transita, só responde sim/não | ✅ implementado, testado |
| `scripts/launch_claude.py` | `prepared → launched \| uncertain`; monta e valida o comando `claude --bg ...`, encadeia `preflight` | ✅ implementado, testado |
| `scripts/status_claude.py` | Observa `launched → working → waiting_approval → finished`; imprime `claude attach <id>`, nunca responde | ✅ implementado, testado |
| `scripts/watch_claude.py` | Polling limitado em torno de `status_claude`; sai ao observar mudança, nunca a causa | ✅ implementado, testado |
| `scripts/receipt_lint.py` | `receipt_received → receipt_validated \| receipt_invalid`; extrai `risks_digest` | ✅ implementado, testado |
| `scripts/state_lint.py` | As 8 invariantes de G3 sobre um `state.toml` | ✅ implementado, testado |
| `scripts/kit_lint.py` | Paridade `.codex`↔`.claude`, identidade de skills, `git diff --check`, cabeçalhos de versão do CLI, roda `state-lint` + suíte de testes | ✅ implementado, testado (7/7 checks PASS no kit atual) |
| `handoff new` | Scaffold de handoff a partir de um nó `reserved` | ⬜ não implementado (Etapa 3) |
| `reconcile` | `uncertain → launched \| abandoned`; detecta órfãos; ponto fixo | ⬜ não implementado (Etapa 3) |
| Hook `PreToolUse` (enforcement) | Transforma o gate de disciplina em controle do runtime | ⬜ não implementado; decisão adiada (Etapa 3, exige decidir sobre `settings.json` de projeto) |

Todos os scripts implementados são Python 3 stdlib (`tomllib` exige ≥ 3.11), sem dependência externa, neutros de plataforma exceto os três com sufixo `_claude` (adaptadores do manager `claude agents --json --all`; Codex permanece manual via `create_thread`/`wait_threads`, registrando `native.platform = "codex"` manualmente). Nenhum lança sessões automaticamente encadeadas, nenhum responde aprovação nativa, nenhum escreve fora de `.agent-state/<projeto>/tasks/<tarefa>/`. Ver [`analise-scripts-apoio-coordenacao.md` §4](analise-scripts-apoio-coordenacao.md#4-casos-de-uso-para-scripts) para a descrição original caso a caso e [`plano-estado-estruturado-e-grafos.md` §7](plano-estado-estruturado-e-grafos.md#7-scripts-como-transições) para o mapeamento script→transição.

## 7. Requisitos de projeto para os scripts

Confirmados e em vigor para todo `scripts/` existente e futuro — ver a tabela completa em [`analise-scripts-apoio-coordenacao.md` §10`](analise-scripts-apoio-coordenacao.md#10-requisitos-de-projeto-para-os-scripts). Os pontos que mais restringem qualquer extensão futura:

- Localização `scripts/`; Python 3 stdlib; sem dependência obrigatória; shebang explícito (não assume fish).
- Escrita somente em `.agent-state/<projeto>/tasks/<tarefa>/`; nunca em alvos, nunca em `scripts/`/`tests/` em tempo de execução.
- Git somente leitura (`status`, `diff`, `rev-parse`); manager somente `claude agents --json --all`/`claude logs <id>` com limite de linhas; nunca responder aprovações.
- Um lançamento por invocação; flags proibidas recusadas (`bypassPermissions`, `--permission-prompts none`, `--resume`, `--continue`, `--fork-session`, allowlist ampla).
- Qualquer alteração em `scripts/` passa por revisão do `reviewer`.

## 8. Riscos e mitigações

Os onze riscos originais (`analise-scripts-apoio-coordenacao.md` §7) continuam válidos como checklist de revisão; nenhum foi eliminado pela implementação, só mitigado:

| Risco | Mitigação em vigor |
|---|---|
| Terceira fonte de verdade (docs vs. scripts vs. este próprio documento) | Este documento existe justamente para isso; `agent-workflow.md` é o único contrato normativo, os planos são racional |
| Falsa sensação de enforcement | Nenhum script sandboxa; a fronteira de escrita dos papéis read-only continua sendo instrução, nunca alegada como controle |
| Allowlist como caminho privilegiado | Scripts finos, sem rede, sem mutação Git além de leitura/snapshot; revisão obrigatória de qualquer mudança em `scripts/` |
| Assimetria de plataforma | Isolada nos três adaptadores `*_claude`; os demais oito scripts funcionam para Codex sem adaptação |
| Fragilidade à versão do CLI | `status_claude`/`watch_claude` validam o schema do JSON do manager e falham ruidosamente em divergência |
| Manutenção sem testes | 249 casos `unittest` (ver checklist) sobre fixtures versionadas em `tests/fixtures/`, nunca o `.agent-state/` real |
| Mudança de contrato documentado | Tratada como mudança de contrato normal: handoff, sessão visível do `reviewer`, receipt — seguida em todas as tarefas do checklist |
| Sobre-automação / perda do humano-no-loop | `gate` só responde sim/não; `watch` sai ao observar, nunca age; nenhum script encadeia o próximo lançamento |
| Sanitização | Scripts escrevem só campos enumerados; `receipt-lint` tem heurística de segredo |

## 9. Decisões confirmadas

Da iniciativa de estado estruturado (usuário, 2026-09-19) — íntegra em [`plano-estado-estruturado-e-grafos.md` §11`](plano-estado-estruturado-e-grafos.md#11-decisões-confirmadas):

| ID | Decisão | Confirmado |
|---|---|---|
| D1 | Formato do estado mecânico | TOML |
| D2 | Escopo de `P_writer` | Interseção de `targets` entre **todas** as tarefas com `state.toml` no kit |
| D3 | `risks_digest` | Títulos de risco normalizados extraídos por `receipt-lint`; predicado por interseção |
| D4 | Ponto de decisão no segundo `FAIL` | Obrigatório e registrado no diário antes de `corrige` |
| D5 | `prepared` conta como writer ativo | Sim |
| D6 | Estados terminais sem resultado | Terminais; sucessor via `substitui` |
| D7 | Onde documentar G2/G3 | `docs/agent-workflow.md` (contrato); os planos ficam como racional |

Da iniciativa de memória por projeto — íntegra em [`plano-memoria-por-projeto.md` §7`](plano-memoria-por-projeto.md#7-decisões-registradas):

| Decisão | Motivo |
|---|---|
| Slug de projeto para tarefas multi-repo = diretório de workspace agrupador | Preserva o gate sequencial por tarefa entre repositórios |
| Sem subpasta por repositório dentro da tarefa | A unidade é a atribuição; receipts já registram `changed`/`evidence` por caminho |
| `checkpoint.md`, não `TASK.md` | Vocabulário já usado no kit |
| `project/` continua fora do Git | Mesma regra de sanitização de `.agent-state/` |

## 10. Roteiro consolidado

Substitui os dois roteiros separados (análise §9 e plano-estado §9), já que o segundo reordenou e absorveu o primeiro.

- **Etapa 0 — modelo e contrato.** Schema v0 documentado em `agent-workflow.md`, fixture versionada, revisão independente. **Concluída** (2026-09-19).
- **Etapa 1 — estado e gates neutros.** Biblioteca `state`, `preflight`, `kit-lint`/`state-lint`, `receipt-lint`, testes sobre fixture. **Concluída** (commit `a01ab93`).
- **Etapa 2 — adaptadores e predicados.** `gate`, `launch-claude`, `status-claude`, `watch-claude`; cadeia real de dispatch validada contra uso ao vivo da coordenadora. **Concluída** (commit `a01ab93`; ver checklist para a cadeia real que a validou).
- **Etapa 3 — opcionais.** `reconcile`, `handoff new`, hook `PreToolUse` (só após decisão explícita sobre `settings.json` de projeto). **Não iniciada.**

Critério de aceitação da iniciativa (análise + plano-estado, unificado): cadeia real de atribuições em Claude sem lançamento após preparação falha e sem flag esquecida, com `state.toml` passando em `state-lint` a cada transição; `kit-lint` verde no kit atual; `gate` recusa `corrige` sem progresso e aceita com `risks_digest` distinto; receipt do `reviewer` `PASS`/`PASS_WITH_RISKS` sobre o contrato e sobre `scripts/`. Evidência de cumprimento: [checklist](#11-checklist-do-que-foi-implementado-até-2026-09-24).

## 11. Checklist do que foi implementado até 2026-09-24

Verificado contra o estado real do repositório na branch `feat/structured-state-tooling` (HEAD `a01ab93`, working tree limpa) nesta data — não apenas contra o que os documentos afirmam.

### Contrato e documentação

- [x] Schema v0 do `state.toml` documentado como contrato em `docs/agent-workflow.md` §"Structured task state (schema v0)"
- [x] G2 (máquina de estados da atribuição) e G3 (grafo de dependência, 7 arestas incluindo `revisa_direta`) documentados como contrato
- [x] Fixture versionada `tests/fixtures/visible-sessions/state.toml`, derivada e sanitizada do checkpoint real `visible-sessions`
- [x] Layout `<projeto>/{project,tasks}/` documentado em `docs/agent-workflow.md` §"Project memory" e em `AGENTS.md`
- [x] Papel `kit-tooling` criado (`.claude/agents/kit-tooling.md`, `.codex/agents/kit-tooling.toml`, instruções em ambos os lados) e referenciado em `AGENTS.md`
- [x] README ganhou seção "Ferramentas do kit" e pré-requisito de Python ≥ 3.11
- [x] **Corrigido em 2026-09-24:** `docs/agent-workflow.md` linha 58 dizia "Nothing below is implemented yet — no `scripts/`, `state.toml` writer or lint exists in the kit" (falso desde `a01ab93`) — agora lista os scripts implementados e os dois pendentes
- [x] **Corrigido em 2026-09-24:** `docs/plano-estado-estruturado-e-grafos.md` (`Status`) dizia "Etapas 1–3 (scripts) não iniciadas; nenhum código existe ainda" — agora reflete Etapas 0–2 concluídas em `a01ab93`, Etapa 3 pendente
- [x] **Corrigido em 2026-09-24:** a tabela "Ferramentas do kit" do `README.md` listava só `kit_lint`/`unittest`/`state_lint`/`preflight`/`receipt_lint` e dizia que `gate`, `launch-claude`, `status-claude`, `watch-claude` "ainda não existem" — agora lista os dez comandos existentes, com `reconcile`/`handoff new` como únicos pendentes
- [x] **Corrigido em 2026-09-24:** `docs/plano-memoria-por-projeto.md` (`Status`) dizia "executado nesta branch (etapas 1–9 abaixo); sem commit" — agora aponta o commit real `b695062` (2026-09-18)

### Biblioteca e scripts (`scripts/`)

- [x] `scripts/state/` — biblioteca de leitura/escrita/validação de `state.toml` + escritor TOML mínimo (`toml_write.py`) + CLI `python3 -m scripts.state {init,add,set,next-nn}`
- [x] `scripts/preflight.py` — gate `reserved → prepared | preparation_failed`
- [x] `scripts/gate.py` — predicados `P_writer`/`P_reader`/`P_progresso` sobre a aresta G3 proposta
- [x] `scripts/launch_claude.py` — monta e valida o comando `claude --bg ...` (flags forçadas, flags proibidas recusadas), encadeia `preflight`
- [x] `scripts/status_claude.py` — observa o manager, valida schema do JSON, imprime `claude attach <id>` em vez de agir
- [x] `scripts/watch_claude.py` — polling limitado em torno de `status_claude`
- [x] `scripts/receipt_lint.py` — valida forma do receipt e extrai `risks_digest`
- [x] `scripts/state_lint.py` — as 8 invariantes de G3
- [x] `scripts/kit_lint.py` — paridade `.codex`↔`.claude`, identidade de skills, `git diff --check`, cabeçalhos de versão do CLI, roda `state-lint` + suíte de testes
- [ ] `scripts/reconcile.py` — não implementado (Etapa 3)
- [ ] `scripts/handoff_new.py` (scaffold) — não implementado (Etapa 3)
- [ ] Hook `PreToolUse` de enforcement — não implementado; decisão sobre `settings.json` de projeto ainda em aberto (Etapa 3)

### Verificação executada nesta data

- [x] `python3 -m unittest discover -s tests` → **249 testes, OK** (fixtures em `tests/fixtures/`, nunca `.agent-state/` real)
- [x] `python3 scripts/kit_lint.py` → **7/7 checks PASS** (`agent_profile_parity`, `instructions_parity`, `skills_identity`, `git_diff_check`, `cli_version_headers`, `state_lint`, `unittest_suite`)
- [x] `git status` na branch → limpa; nenhuma mudança pendente de commit

### Evidência de uso real (cadeia de dispatch validada)

Sete tarefas em `.agent-state/github-copilot-fullstack-kit/tasks/` (não versionadas, mas com timestamps todos anteriores ao commit `a01ab93`, confirmando que o trabalho está integralmente capturado nele): `structured-state`, `kit-tooling-role`, `state-scripts`, `gate-launch-scripts`, `receipt-lint-format-fix`, `kit-nits-cleanup`, `tooling-gaps-fix` — cada uma com handoff(s), receipt(s) e `git-before-NN.txt` de pelo menos uma revisão independente do `reviewer`. A cadeia real de dispatch (mencionada no commit `a01ab93`) encontrou e corrigiu ao vivo: bootstrap `state init` faltante, `status`/`watch-claude` não persistindo transições G2 observadas, `watch-claude` saindo numa classificação transitória "unknown", regex de heading do `receipt-lint` mais estrita que o formato real usado, e um bug real de correspondência ampla demais em `extract_profile_path` (compartilhado por `preflight` e `launch-claude`).

### Memória de projeto

- [x] Layout `<projeto>/project/` e `<projeto>/tasks/<tarefa>/` em uso real (`.agent-state/github-copilot-fullstack-kit/project/architecture.md` existe; `tasks/` populado pelas sete tarefas acima)
- [x] Regra de promoção (`promote_to_project_knowledge`, só a coordenadora escreve em `project/`) documentada em `agent-workflow.md`
- [ ] `project/repositories.md`, `conventions.md`, `integrations.md` — ainda não criados para este projeto (só `architecture.md` existe); esperado, já que são "criados sob demanda"

## 12. Fora de escopo / pendências documentais

- As quatro pendências stale da seção 11 foram corrigidas em 2026-09-24 (confirmado pelo usuário): `docs/agent-workflow.md`, `docs/plano-estado-estruturado-e-grafos.md`, `docs/plano-memoria-por-projeto.md` e `README.md` agora refletem o estado real do repositório.
- `docs/analise-scripts-apoio-coordenacao.md` não teve conteúdo alterado além da nota de topo apontando para este documento; permanece como racional histórico.
- Nenhum script novo foi escrito; este é um documento de consolidação e verificação, não uma implementação. Etapa 3 (`reconcile`, `handoff new`, hook `PreToolUse`) continua pendente.
