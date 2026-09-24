# Plano: estado e memória por projeto em `.agent-state/`

> Este documento é racional histórico. A narrativa unificada e atualizada (status real, checklist do que está implementado) está em [`plano-unificado.md`](plano-unificado.md). O contrato vivo do layout de memória está em [`docs/agent-workflow.md` §"Project memory"](agent-workflow.md#project-memory).

- **Data:** 2026-09-18
- **Branch:** `feat/independent-visible-sessions` (HEAD `0b72cdf`)
- **Status:** executado e commitado em `b695062` (2026-09-18); etapas 1–9 abaixo concluídas
- **Base:** conversa externa "Estrutura de pastas" (ChatGPT, 2026-09-18) e o checkpoint real da tarefa #5233
- **Escopo:** separar por projeto os arquivos que o kit gera (checkpoints, handoffs, receipts, anexos) e introduzir uma memória estável por projeto, sem alterar o protocolo de sessões visíveis nem a fronteira de escrita dos especialistas

## Sumário

1. [Problema](#1-problema)
2. [O que a conversa externa acrescenta](#2-o-que-a-conversa-externa-acrescenta)
3. [Layout adotado](#3-layout-adotado)
4. [Regras novas](#4-regras-novas)
5. [Etapas](#5-etapas)
6. [Fora de escopo](#6-fora-de-escopo)
7. [Decisões registradas](#7-decisões-registradas)

---

## 1. Problema

O kit é usado com vários projetos, mas gera tudo em um nível só: `.agent-state/<tarefa>.md`, `.agent-state/<tarefa>/<NN>-<papel>-*.md` e `tmp/pdfs/<arquivo>`. A tarefa #5233 mostra o efeito na prática: envolve três repositórios do projeto `Agenda`, mas nada nos caminhos indica o projeto; slugs como `task-1234` ou `redmine-1234` colidem entre projetos, e handoffs/receipts de projetos diferentes se misturam no mesmo diretório.

Há um segundo problema, menos visível: o checkpoint da #5233 contém conhecimento que é do **projeto**, não da tarefa — roots dos três repositórios, branches base, a regra "nunca merge/push em `sprint`", a necessidade da `tag-library` no `~/.m2` para o Maven funcionar. Na próxima tarefa do mesmo projeto, tudo isso seria redescoberto.

## 2. O que a conversa externa acrescenta

| Ideia | Situação no kit | Decisão |
|---|---|---|
| Hierarquia `<projeto>/<task>/…` para o conhecimento dos agentes (não para os repositórios Git) | Tudo plano | **Adotar** |
| Dois níveis de memória: `project/` (estável) e `tasks/` (específico) | Não existe memória de projeto | **Adotar** — é a lacuna real |
| Tarefa nunca escreve na memória global; o especialista registra `promote_to_project_knowledge` e o orquestrador promove | Especialista escreve só o receipt; a coordenadora escreve checkpoint e handoffs | **Adotar** — o campo entra no receipt, a coordenadora promove; a fronteira de escrita fica intacta |
| Subpasta por repositório dentro da tarefa (`context/analysis/changes/decisions.md`) mais `shared/` | A unidade do kit é a **atribuição** (`<NN>-<papel>`), writers sequenciais entre repositórios; `changed`/`evidence`/`risks` já vivem no receipt; decisões cross-repo vivem no checkpoint e nos receipts do `architect` | **Não adotar** — criaria segunda fonte de verdade e exigiria escrita fora do receipt |
| `TASK.md` como conhecimento global da tarefa | É o checkpoint | Manter o conceito como `checkpoint.md` dentro da pasta da tarefa |

A própria conversa conclui que o protocolo de leitura/escrita importa mais que os nomes das pastas. Esse protocolo o kit já tem; faltavam o nível de projeto e a promoção.

## 3. Layout adotado

```text
.agent-state/                                   # continua ignorado pelo Git
└── <projeto>/                                  # slug do repositório-alvo ou do workspace agrupador (ex.: agenda)
    ├── project/                                # memória estável — só a coordenadora escreve, por promoção
    │   ├── repositories.md                     # roots absolutos, branches base, comandos de check, regras operacionais
    │   ├── architecture.md
    │   ├── conventions.md
    │   └── integrations.md                     # fronteiras Front–BFF–Gateway–API e contratos vigentes
    └── tasks/
        └── <tarefa>/
            ├── checkpoint.md                   # antes: .agent-state/<tarefa>.md
            ├── <NN>-<papel>-handoff.md
            ├── <NN>-<papel>-receipt.md
            └── inputs/                         # PDFs/anexos da tarefa (antes: tmp/pdfs/ e Task #*.pdf na raiz)
```

**`<projeto>`**: slug minúsculo (`^[a-z0-9-]+$`) do diretório do repositório-alvo; quando a tarefa envolve vários repositórios, do diretório de workspace que os agrupa (`/home/lukassp/dev/Agenda` → `agenda`). A coordenadora registra o slug e os `target_root` no cabeçalho do checkpoint e em `project/repositories.md`.

Os arquivos de `project/` são opcionais e criados sob demanda; um projeto novo começa só com `repositories.md`.

## 4. Regras novas

- **Leitura antes de redescobrir.** Na intake, a coordenadora lê `project/` (se existir) antes de qualquer discovery e aponta no handoff o que já é conhecido lá. Evidência de `project/` tem a mesma validade de qualquer evidência anterior: é reutilizada onde o estado não mudou e invalidada onde mudou.
- **Promoção.** O receipt ganha o campo opcional `promote_to_project_knowledge`: lista curta de fatos sanitizados que o especialista considera estáveis (ex.: "backend usa `ApiResponse<T>` como envelope padrão"). A coordenadora decide o que promover e escreve em `project/`; o especialista nunca escreve em `project/`.
- **Sanitização.** `project/` segue a regra já existente do kit: sem segredos, inventários de hosts ou mapas de infraestrutura interna. Fica fora do Git como o restante de `.agent-state/`.
- **Anexos.** PDFs e anexos de intake ficam em `tasks/<tarefa>/inputs/`; a extração continua acontecendo uma única vez.

## 5. Etapas

| # | Etapa | Arquivos |
|---|---|---|
| 1 | Perfis de especialista: caminho do receipt → `.agent-state/<project>/tasks/<task>/<NN>-<role>-receipt.md`; campo `promote_to_project_knowledge`; proibição de escrever em `project/` | `.claude/agents/*.md`, `.codex/agents/*.toml` (exceto a coordenadora, que não cita caminhos) |
| 2 | Guia operacional: regra do `<project>`, layout, dois níveis, promoção | `AGENTS.md` |
| 3 | Skill `task-execution`: intake lê `project/`; handoff/checkpoint/receipt nos novos caminhos; campo de promoção; anexos em `inputs/` | `.claude/skills/task-execution/SKILL.md`, `.agents/skills/task-execution/SKILL.md` (cópias idênticas) |
| 4 | Procedimento de plataforma: caminhos, exemplo de prompt de lançamento, parágrafo "Memória de projeto" | `docs/agent-workflow.md` |
| 5 | README: fluxo de execução, exemplo `/task-execution`, normas | `README.md` |
| 6 | `.gitignore`: comentário sobre o layout; entradas `Task #*.pdf` e `tmp/pdfs/*` permanecem como legado | `.gitignore` |
| 7 | Plano de estado estruturado: `state.toml` e caminhos de exemplo passam para `tasks/<tarefa>/` | `docs/plano-estado-estruturado-e-grafos.md` |
| 8 | Migração local (ignorada pelo Git): `task-5233.md` → `agenda/tasks/task-5233/checkpoint.md`; `tmp/pdfs/Task #5233` → `agenda/tasks/task-5233/inputs/`; fatos estáveis do checkpoint extraídos para `agenda/project/repositories.md` | `.agent-state/`, `tmp/pdfs/` |
| 9 | Verificação: `grep` sem ocorrências dos caminhos antigos; `diff` vazio entre as duas cópias da skill; `git diff --stat` conferido | — |

## 6. Fora de escopo

- `docs/analise-scripts-apoio-coordenacao.md` referencia arquivos reais de uma tarefa passada (`.agent-state/visible-sessions.md`) como evidência histórica; não é alterado.
- Versionar `project/` no Git ou compartilhá-lo entre pessoas. Exigiria outro local e revisão de sanitização; fica para decisão futura.
- Scripts de apoio (`state add`, `preflight`, …) do plano de estado estruturado: só os caminhos de exemplo são atualizados.
- Nenhum commit; a branch recebe apenas working tree.

## 7. Decisões registradas

| Decisão | Motivo |
|---|---|
| Slug de projeto para tarefas multi-repo = diretório de workspace agrupador, não uma pasta por repositório | A coordenadora trabalha por tarefa com gate sequencial entre repositórios; um checkpoint único por tarefa preserva esse gate |
| Sem subpasta por repositório dentro da tarefa | A unidade é a atribuição; receipts já registram `changed`/`evidence` por caminho absoluto |
| `checkpoint.md` em vez de `TASK.md` | Vocabulário já usado em todo o kit |
| `tasks/` como subdiretório explícito | Evita mistura entre `project/` e diretórios de tarefa no mesmo nível |
| Anexos dentro da tarefa (`inputs/`) em vez de `tmp/pdfs/<projeto>/` | Tudo de uma tarefa em um só lugar; `tmp/pdfs/` vira legado |
| `project/` continua ignorado pelo Git | Mesma regra de sanitização de `.agent-state/`; versionar é decisão separada |
