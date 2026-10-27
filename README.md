```
                           · · ·   architect  · · ·
                  reviewer                          analista-redmine
              · ·          NIHIL · SINE · PROBATIONE         · ·
    java-backend . . . . .                          . . . . . go-backend
        ·    . .                                              . .    ·
      ·    .                                                      .    ·
     ·    .    ███╗   ███╗ █████╗ ██████╗ ██╗███╗   ██╗ █████╗     .    ·
    ·    .     ████╗ ████║██╔══██╗██╔══██╗██║████╗  ██║██╔══██╗     .    ·
 angular .     ██╔████╔██║███████║██████╔╝██║██╔██╗ ██║███████║     . go-etl
    ·    .     ██║╚██╔╝██║██╔══██║██╔══██╗██║██║╚██╗██║██╔══██║     .    ·
    ·    .     ██║ ╚═╝ ██║██║  ██║██║  ██║██║██║ ╚████║██║  ██║     .    ·
     ·    .    ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝    .    ·
      ·    .                                                      .    ·
        ·    . .                                              . .    ·
    node-backend . . . . .                          . . . . . python-etl
              · ·     coordenadora de sessões de agentes     · ·
              data-analyst                          kit-tooling
                           · · · · · ·  · · · · · ·
```

# Kit de agentes multi-repositório para Claude Code

Este repositório é um **kit de coordenação**, não uma aplicação. Ele fornece perfis de agentes, skills e instruções de domínio para que uma sessão principal (a coordenadora **Marina**) receba uma tarefa, identifique o trabalho restante, delegue a especialistas em sessões visíveis independentes e consolide a implementação e a verificação local nos repositórios da aplicação.

> Este README é documentação para pessoas. Os runtimes não o carregam como instrução: Claude Code lê `CLAUDE.md` (que importa `AGENTS.md`), `.claude/agents/` e `.claude/skills/`. Por isso ele pode ser escrito em português sem afetar o comportamento dos agentes.

## Sumário

- [O que o kit faz e o que não faz](#o-que-o-kit-faz-e-o-que-não-faz)
- [Pré-requisitos](#pré-requisitos)
- [Início rápido](#início-rápido)
- [Como uma tarefa é executada](#como-uma-tarefa-é-executada)
- [Cadeias sem supervisão (`marina run`)](#cadeias-sem-supervisão-marina-run)
- [Equipe de agentes](#equipe-de-agentes)
- [Configuração nativa](#configuração-nativa)
- [Skills principais](#skills-principais)
- [Entrega e autorizações](#entrega-e-autorizações)
- [Eficiência e verificação](#eficiência-e-verificação)
- [Ferramentas do kit (`scripts/`)](#ferramentas-do-kit-scripts)
- [Documentação relacionada](#documentação-relacionada)

## O que o kit faz e o que não faz

**Faz**

- Coordena uma tarefa (texto, PDF ou link) a partir de uma sessão principal com acesso explícito a cada repositório-alvo.
- Roteia o trabalho por consequência e risco para especialistas de Angular, Java, Go, Node.js, Python, dados e revisão.
- Executa cada atribuição de especialista em uma **sessão visível independente**, com handoff, receipt e checkpoint próprios.
- Preserva contratos públicos e alterações locais já existentes; exige evidência para qualquer alegação de teste ou conformidade.

**Não faz**

- Não contém repositórios de aplicação nem os clona automaticamente.
- Não varre a máquina em busca de projetos; só usa os caminhos explicitamente informados.
- Não faz commit, push, MR, escrita no Redmine, deploy ou operação com dados reais sem autorização correspondente.
- Não contorna controles de permissão dos runtimes (`bypassPermissions`, `--permission-prompts none`).

## Pré-requisitos

| Item | Observação |
|---|---|
| Claude Code CLI ≥ 2.1.306 | Verificado em 2026-10-25 com `--bg`, `--name`, `--agent`, `--add-dir`, `--settings` com hooks, `--permission-mode`, `--allowedTools`, `claude agents`, `claude attach`, `claude logs`. Confira `claude --help` em outras versões. |
| Repositórios-alvo clonados localmente | Caminhos absolutos; o kit não os descobre sozinho. |
| Ferramentas de build/teste dos alvos no `PATH` | Os checks descobertos precisam resolver no ambiente da sessão em background (ex.: `mvn`, `node`, `go`, `python`). |
| Python ≥ 3.11 | Só para rodar as ferramentas do próprio kit em `scripts/` (`tomllib` é stdlib a partir dessa versão); não é exigido para delegar tarefas aos especialistas. |

## Início rápido

### Claude Code

Inicie **na raiz do kit** e adicione cada repositório-alvo com `--add-dir`. Substitua os caminhos de exemplo pelos seus caminhos absolutos:

```bash
claude --agent marina --add-dir /caminho/absoluto/api --add-dir /caminho/absoluto/bff
```

### Em um IDE

Selecione o kit como raiz da sessão e conceda acesso às pastas dos outros projetos pelos controles do próprio runtime. Ter as pastas abertas no IDE **não** prova que o runtime carregou o kit ou que tem acesso a cada projeto. Ao iniciar, confirme que os perfis do kit foram descobertos e que cada alvo está acessível. Reinicie a sessão após alterar perfis se o runtime já os tiver em cache.

Claude Code descobre `.claude/skills/` de diretórios adicionados, mas **não** carrega os agentes deles; por isso o kit deve permanecer como raiz da sessão, e as instruções de cada alvo (`AGENTS.md`/`CLAUDE.md`) são lidas explicitamente. Referências: [permissões de diretório do Claude](https://code.claude.com/docs/en/permissions#additional-directories-grant-file-access-not-configuration).

### Primeira tarefa

Descreva o resultado esperado, os projetos envolvidos, anexe a evidência da tarefa (PDF, link, texto) e informe os critérios de aceitação conhecidos. Exemplo:

```text
Implementar a tarefa #8144 (PDF anexo). Repositórios: /abs/bff (Node) e /abs/front (Angular).
Preservar o contrato atual do endpoint /v1/pacientes. Critério: testes existentes continuam verdes.
```

## Como uma tarefa é executada

1. **Intake** — Marina consolida objetivo, critérios, decisões posteriores e evidência; distingue o que foi pedido, o que foi decidido depois, o que foi relatado como feito e o que foi verificado. Estado, percentual ou link de MR **não** provam conclusão.
2. **Checkpoint** — Para toda tarefa com atribuições, Marina mantém `.agent-state/<projeto>/tasks/<tarefa>/checkpoint.md` (ignorado pelo Git), com decisões, autorizações, evidências, checks e a próxima ação. `<projeto>` é o slug do repositório-alvo ou, em tarefas com vários repositórios, do diretório de workspace que os agrupa; assim o estado de projetos diferentes nunca se mistura. Antes de redescobrir, Marina lê a memória estável em `.agent-state/<projeto>/project/` (repositórios, arquitetura, convenções, integrações), que só ela escreve. Anexos e PDFs da tarefa ficam em `tasks/<tarefa>/inputs/`.
3. **Roteamento** — Uma correção simples vai para um único especialista. O `architect` entra para decisões de arquitetura, contratos compartilhados, migrations e backfills; o `reviewer` revisa automaticamente autorização, contratos públicos, integridade de dados, migrations e operações críticas.
4. **Handoff** — Antes de cada atribuição, Marina escreve `.agent-state/<projeto>/tasks/<tarefa>/<NN>-<papel>-handoff.md` com objetivo, perfil absoluto, roots, instruções do alvo a ler, escopo de escrita, contratos, evidência (inclusive o que já está em `project/`), critérios, checks descobertos e allowlist.
5. **Sessão visível** — Cada implementação, revisão, correção ou análise abre uma sessão nova com título `<tarefa> — <papel> — <NN> — <tipo>`. Claude: `claude --bg --agent <papel>` com permissões por atribuição. Nunca reutilizar, retomar ou bifurcar sessões concluídas.
6. **Receipt** — O especialista escreve `<NN>-<papel>-receipt.md` com `status`, `changed`, `checks`, `evidence`, `risks`, `next`, mais `profile_read` e `instructions_read` (caminhos absolutos realmente lidos). O `reviewer` acrescenta `verdict` (`PASS`, `PASS_WITH_RISKS`, `FAIL`). Qualquer papel pode listar `promote_to_project_knowledge` — fatos curtos e sanitizados que valem para o projeto, não só para a tarefa; Marina decide o que promover para `project/`, e nenhum especialista escreve lá.
7. **Gate entre writers** — O próximo writer só é liberado com o receipt final do anterior, evidência do gerenciador nativo de que ele parou, e `git status/diff` do alvo conferido e registrado. Writers são sequenciais entre repositórios; leitores (`reviewer`, `architect`, analista-redmine) podem sobrepor-se a outros leitores, nunca a um writer no mesmo alvo.
8. **Correção** — Achados voltam ao **mesmo papel** em uma **nova** sessão. Falha repetida sem evidência nova exige novo diagnóstico, não uma alegação arbitrária de conclusão.
9. **Consolidação** — Marina reporta evidência por critério de aceitação, resultado da revisão, riscos remanescentes e checks pulados.

Se a plataforma não conseguir abrir sessões visíveis, a sessão principal assume a especialidade e registra no checkpoint e na resposta: `delegação visível indisponível: <motivo>; especialidade <papel> assumida na sessão principal`. Esse fallback não é revisão independente. Criação com resultado incerto é reconciliada no gerenciador de sessões antes de qualquer nova tentativa.

## Cadeias sem supervisão (`marina run`)

Uma cadeia implementação → revisão → correção → revisão pode avançar sem você presente, mas só dentro de um **envelope** que você aprovou antes. O envelope é a tabela opcional `[envelope]` do `state.toml` da tarefa e contém:

- os estágios (um papel writer, o mesmo em todos, cada um com um template `stage-<n>-handoff-template.md` contendo `Objective`, `Write scope` e `Acceptance criteria`);
- os alvos com o branch esperado de cada um;
- a allowlist, que vale também para reviewers e correções;
- o modo de revisão (`each_stage` ou `final`), `max_corrections` (0 ou 1), `max_duration`, `judge_max_calls` e o que fazer com `PASS_WITH_RISKS` (`accept`, `judge` ou `stop`).

| Comando | O que faz |
|---|---|
| `bin/marina approve <projeto> <tarefa>` | Mostra o envelope e grava a aprovação depois que você digita o slug da tarefa; só funciona num terminal interativo. O hash cobre o envelope e os templates: editar qualquer um invalida a aprovação. |
| `bin/marina run <projeto> <tarefa> --interval 30 --max-duration 2h` | Abre, um nó por vez, só os nós da expansão do envelope, pelo caminho de sempre (Git Gate entre writers, `gate`, `state add`, handoff gerado, preflight, `launch_claude`). Para com o motivo numa seção gerada do checkpoint: envelope ou branch alterado, mudança alheia entre writers, segundo `FAIL` seguido, falha da juíza, receipt ausente ou inválido, limite de tempo, erro, Ctrl-C ou `marina stop`. |
| `bin/marina status <projeto> <tarefa>` | Trava, aprovação do envelope e nós da tarefa. |
| `bin/marina stop <projeto> <tarefa>` | Pede ao `run` que pare na próxima iteração. |

A única decisão ambígua delegada é `PASS_WITH_RISKS` com `on_pass_with_risks = "judge"`: a juíza `marina-judge`, só de leitura, escolhe entre as opções oferecidas, até `judge_max_calls` vezes, e cada chamada fica em `judge-calls.jsonl`. O runner nunca responde a aprovação nativa, nunca relança um launch incerto e escreve só no diretório da tarefa. Um processo morto à força deixa a trava órfã, que `marina run --recover` assume só quando nenhuma sessão da tarefa está trabalhando.

Para a Marina interativa, `.mcp.json` registra o servidor `marina mcp`, com 12 ferramentas `mcp__marina__*` e nenhuma de aprovação. As sete de leitura (`task_status`, `envelope_show`, `sessions`, `next_nn`, `gate_check`, `decision_preview`, `handoff_validate`) são pré-aprovadas em `.claude/settings.json`; as de escrita e ação (`envelope_draft`, `state_reserve`, `launch_node`, `run_start`, `run_stop`) pedem permissão; as quatro primeiras recusam enquanto um `run` estiver ativo, e o `run_stop` é justamente o jeito de pedir a parada desse `run`. O Claude Code pede para aprovar o servidor no primeiro uso, num diálogo que já vem com "Continue without using this MCP server" selecionado: escolha "Use this MCP server", porque um Enter direto recusa o servidor e ele some do `/mcp`. Depois de uma recusa, `claude mcp reset-project-choices` na raiz do kit traz o diálogo de volta. As sessões automáticas (`launch_claude` e a juíza) rodam com `--strict-mcp-config`, porque o `.mcp.json` do projeto pararia cada uma num diálogo interativo. Detalhes em [docs/agent-workflow.md](docs/agent-workflow.md#approved-envelopes-marina-run).

## Equipe de agentes

| Papel | Especialidade | Escreve em alvos |
|---|---|---|
| **Marina** | Coordenação na sessão principal: intake, roteamento, delegação sequencial, checkpoint, consolidação | Apenas docs/config gerais pequenas e checkpoints |
| `angular` | Angular: UI, estado, acessibilidade, acesso a dados | Escopo atribuído |
| `java-backend` | Java: APIs, domínio, persistência, segurança, testes | Escopo atribuído |
| `go-backend` | Go backend: APIs, serviços, persistência | Escopo atribuído |
| `go-etl` | Go ETL: ingestão, concorrência limitada, I/O confiável | Escopo atribuído |
| `python-etl` | Python ETL: ingestão, transformação, carga, recuperação | Escopo atribuído |
| **node-backend** | Node.js/TypeScript: BFFs, APIs, integrações upstream | Escopo atribuído |
| `data-analyst` | Análise de dados: SQL reproduzível, notebooks, métricas, reconciliação | Escopo atribuído |
| `kit-tooling` | Ferramentas do próprio kit em `scripts/` (Python stdlib) — nunca código de aplicação-alvo | `scripts/`, `tests/`, nunca um alvo |
| `architect` | Arquitetura: decisões materiais, contratos compartilhados, migrations, backfills | Não (só o próprio receipt) |
| `reviewer` | Revisão independente por risco: correção, segurança, integridade, compatibilidade, testes | Não (só o próprio receipt) |
| **analista-redmine** | Opcional: histórico complexo de tarefas, requisitos atuais, trabalho restante | Não (só o próprio receipt) |

Regras de roteamento que costumam gerar dúvida:

- Backend TypeScript/BFF é do `node-backend`, não do `angular`.
- Migrations SQL da aplicação vão para o dono do módulo, não para o `data-analyst` só por causa da extensão. SQL avulso sem dono pode ficar na sessão principal, com `architect` para arquitetura e `reviewer` para revisão.
- Várias tecnologias na mesma tarefa **não** exigem o `architect`; um contrato compartilhado ou uma migration, sim. Conte consequências, não linguagens.
- Papéis read-only (`architect`, `reviewer`, analista-redmine) escrevem apenas o próprio receipt. Essa fronteira é de instrução, não de sandbox; as permissões do runtime continuam valendo.

## Configuração nativa

| Camada | Claude Code |
|---|---|
| Entrada | `CLAUDE.md`, que importa `AGENTS.md` |
| Perfis | `.claude/agents/*.md` |
| Skills sob demanda | `.claude/skills/` |
| Instruções de domínio (carga explícita) | `.claude/instructions/` |

As instruções de domínio são escolhidas por responsabilidade do módulo, não por extensão: backend TypeScript não carrega instruções Angular, e Go ETL não carrega automaticamente as de Go API. Sessões independentes usam o modelo configurado pelo usuário. Os perfis não desativam controles de permissão do runtime. Até 2026-10 o kit também mantinha cópias para Codex; elas foram removidas (ver `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`).

## Skills principais

Skills são procedimentos carregados sob demanda. No Claude Code, Marina e os especialistas carregam a skill relevante automaticamente; você também pode invocá-la por `/nome-da-skill`. Carregue apenas o necessário: uma alteração só em conector não exige a skill de pipeline completo.

### Coordenação e qualidade

#### `task-execution`

- **O que faz:** procedimento operacional da Marina — intake de texto/PDF/link, identificação do trabalho restante, roteamento por evidência, sessões visíveis, checkpoint, handoff/receipt e retomada.
- **Quando usar:** escopo incerto, histórico longo, vários repositórios ou retomada de uma tarefa interrompida. Uma tarefa limitada a um especialista pode ir direto ao papel.
- **Exemplo:**
  ```text
  /task-execution Retomar a tarefa #7976. Checkpoint em .agent-state/agenda/tasks/redmine-7976/checkpoint.md. Verificar o estado atual dos repositórios antes de qualquer nova sessão.
  ```

#### `quality-gate`

- **O que faz:** revisão por risco de correção, segurança, testes, compatibilidade, integridade de dados e prontidão operacional, com achados acionáveis (severidade, local, evidência, impacto, correção) e veredito separado.
- **Quando usar:** automaticamente pelo `reviewer` em mudanças de autorização, contrato público, integridade de dados, migration ou operação crítica; ou em revisão explícita.
- **Exemplo:**
  ```text
  Revisar o diff atual de /abs/api contra os critérios do handoff 03. Só checks não mutantes. Receipt com verdict.
  ```

### Implementação por tecnologia

#### `angular-feature`

- **O que faz:** implementa funcionalidades Angular com os padrões existentes de rotas, formulários, estado, UI e testes; preserva o contrato consumido (endpoint, envelope, erros); cobre validação, permissão, estados visuais e acessibilidade.
- **Quando usar:** responsabilidade Angular, não TypeScript em geral.
- **Exemplo:**
  ```text
  Adicionar filtro por período na listagem de atendimentos, reutilizando o componente de data existente e sem alterar o contrato do endpoint. Testes ao lado dos existentes.
  ```

#### `java-rest-api`

- **O que faz:** implementa APIs Java com contratos estáveis, validação, autorização, persistência, migrations, observabilidade e testes, seguindo o framework e os padrões já usados no projeto.
- **Quando usar:** alteração de endpoints ou comportamento de API Java.
- **Exemplo:**
  ```text
  Expor GET /v1/unidades/{id}/leitos com paginação. Manter o envelope de resposta atual e as regras de autorização do módulo.
  ```

### Dados e ETL

#### `etl-pipeline`

- **O que faz:** projeta ou altera ETLs multiestágio com contratos, idempotência, checkpoints, replay, validação e observabilidade.
- **Quando usar:** mudanças em vários estágios ou em recuperação de falha. **Não** para alterações só de conector.
- **Exemplo:**
  ```text
  Tornar o pipeline de cargas SIM/SINASC reexecutável por competência sem duplicar registros; adicionar checkpoint por lote.
  ```

#### `api-ingestion`

- **O que faz:** constrói ingestão de APIs com autenticação, paginação, limites de taxa, retries limitados, checkpoints, validação e testes de contrato.
- **Quando usar:** conector que consome uma API externa; ajuste pontual não exige redesenhar o pipeline.
- **Exemplo:**
  ```text
  Corrigir a paginação por cursor do conector CNES: respeitar o header Retry-After e não repetir erros 4xx de validação.
  ```

#### `file-ingestion`

- **O que faz:** ingestão de arquivos com streaming, validação de schema, deduplicação, proteção contra arquivos comprimidos maliciosos, quarentena e processamento incremental.
- **Quando usar:** entrada por CSV/planilha/arquivo em lote.
- **Exemplo:**
  ```text
  Processar os CSVs diários do diretório de entrada sem carregar tudo em memória; mover arquivos inválidos para quarentena com motivo.
  ```

#### `web-scraping`

- **O que faz:** scrapers autorizados com limites de taxa, testes de parser offline, checkpoints, extração estável e detecção de mudança na fonte.
- **Quando usar:** coleta de páginas com autorização explícita da fonte.
- **Exemplo:**
  ```text
  Extrair a tabela de vigência do portal X (autorizado). Salvar amostras HTML para testes offline e alertar se a estrutura mudar.
  ```

#### `data-analysis`

- **O que faz:** análise reproduzível de dados do repositório com profiling, validação de métricas, reconciliação e conclusões apoiadas em evidência.
- **Quando usar:** perguntas analíticas, reconciliação entre fontes, validação de métricas. Análise pura usa a autovalidação do `data-analyst`; se alterar comportamento de produção, entra revisão.
- **Exemplo:**
  ```text
  Reconciliar o total de internações do relatório mensal com a tabela fato; explicar divergências por unidade com SQL reproduzível.
  ```

### Governança do Códice (condicional)

Estas skills aplicam-se **apenas** a projetos com evidência de governança da SES/SC, NADS ou DTIG. Não as imponha a projetos externos. Os resumos históricos incluídos têm atualidade não verificada: identificadores sozinhos não provam conformidade oficial, e contratos legados não são alterados silenciosamente.

#### `codice-api-contracts`

- **O que faz:** implementa ou revisa contratos de APIs e Gateways (métodos HTTP, URIs, payloads, tags, health checks) conforme o Códice.
- **Quando usar:** API nova ou revisão de contrato em projeto governado.
- **Exemplo:**
  ```text
  $codice-api-contracts Revisar o contrato de /v1/pacientes contra o Códice; apontar divergências sem alterar o contrato legado.
  ```

#### `codice-go-echo-api`

- **O que faz:** cria APIs Go novas com Echo, arquitetura em camadas e middleware corporativo.
- **Quando usar:** API Go nova em projeto governado; não para ETLs nem migração silenciosa de APIs legadas.
- **Exemplo:**
  ```text
  Criar o serviço de consulta de leitos em Go/Echo seguindo a estrutura de camadas do Códice.
  ```

#### `git-branch-commit-conventions`

- **O que faz:** cria e valida branches, changelog de tarefa e mensagens de commit no padrão do Códice.
- **Quando usar:** trabalho cotidiano em projeto governado; corte de versão e tags vão para `codice-gitlab-release-flow`.
- **Exemplo:**
  ```text
  Sugerir nome de branch e mensagem de commit para a tarefa #5231 conforme a convenção; não executar o commit.
  ```

#### `codice-gitlab-release-flow`

- **O que faz:** planeja, valida ou executa releases GitLab com MRs, changelog, tags, branches de release e promoção por ambiente.
- **Quando usar:** corte de versão em projeto governado, com autorização do Engineer/Tech Lead responsável. Nunca para push, merge, tag ou deploy sem aprovação.
- **Exemplo:**
  ```text
  Planejar a release 2.4.0: listar MRs pendentes, changelog e passos de promoção; não executar nada.
  ```

#### `codice-postgres-governance`

- **O que faz:** planeja ou valida criação, configuração e restauração PostgreSQL sob governança.
- **Quando usar:** provisionamento/restore com DBA/Infra e alvo confirmado. Não para migrations comuns da aplicação.
- **Exemplo:**
  ```text
  Validar o plano de restore do banco de homologação contra a norma; apontar o que exige DBA.
  ```

#### `codice-project-documentation`

- **O que faz:** cria ou atualiza README e diagramas arquiteturais no padrão do Códice.
- **Quando usar:** documentação de projeto governado, sob solicitação explícita.
- **Exemplo:**
  ```text
  Atualizar o README do serviço de agendamento com o diagrama de contexto no padrão do Códice.
  ```

## Entrega e autorizações

- A entrega local é **código e checks relevantes** nos repositórios-alvo. Commits, MRs publicados, alterações no Redmine, deploy e operações com dados reais exigem autorização correspondente; autorização já concedida é reutilizada no seu escopo.
- Uma solicitação de desenvolvimento autoriza implementação e checks locais; não autoriza publicação.
- Releases governadas vão para Engineer/Tech Lead autorizados; provisionamento/restore PostgreSQL vai para DBA/Infraestrutura.
- Normas oficiais podem ser fornecidas por projeto. Registre fonte e versão quando houver; norma ausente ou conflitante bloqueia apenas a decisão material que depende dela, não o restante do trabalho.
- Nunca copie segredos, inventários de hosts ou mapas de infraestrutura interna para o kit.
- Toda tarefa com atribuições mantém um checkpoint sanitizado e ignorado pelo Git em `.agent-state/<projeto>/tasks/<tarefa>/`, inclusive tarefas curtas; a memória de projeto em `.agent-state/<projeto>/project/` segue a mesma sanitização. Sessões concluídas ficam disponíveis para consulta; nunca são arquivadas ou apagadas automaticamente.

## Eficiência e verificação

- Carregue só as instruções e skills relevantes; reutilize descobertas e extratos de PDF; roteie de forma estreita e revise por consequência.
- Teste o comportamento alterado proporcionalmente com os comandos descobertos no projeto; reporte resultados exatos e checks pulados. Não adicione testes que apenas repetem mudanças de texto de baixo impacto.
- Meça tokens reais apenas quando o runtime os expõe; menos agentes ou menos bytes não são um percentual de economia.
- O kit tem um validador estrutural em `scripts/kit_lint.py` (Python 3 stdlib, ver [Ferramentas do kit](#ferramentas-do-kit-scripts)) que checa os perfis em `.claude/agents`, a ausência de diretórios de outro runtime, `git diff --check` e roda a suíte de testes — mas ele não substitui uma simulação realista de tarefa nem prova comportamento de runtime; reporte honestamente o que não foi exercitado. O racional completo e o roteiro de scripts ainda pendentes estão em [docs/analise-scripts-apoio-marina.md](docs/analise-scripts-apoio-marina.md) e [docs/plano-estado-estruturado-e-grafos.md](docs/plano-estado-estruturado-e-grafos.md).

## Ferramentas do kit (`scripts/`)

Scripts neutros de plataforma, Python 3 stdlib (`tomllib` exige ≥ 3.11), sem dependência externa. Rode todos a partir da raiz do kit.

| Comando | O que faz | O que grava |
|---|---|---|
| `python3 scripts/kit_lint.py` | Perfis `.claude/agents`, ausência de `.codex/`/`.agents/`, `git diff --check`, cabeçalhos de versão mínima do CLI, `state-lint` na fixture e a suíte `unittest` | nada |
| `python3 -m unittest discover -s tests` | Suíte de testes isolada (fixtures em `tests/fixtures/`, nunca o `.agent-state/` real) | nada |
| `python3 -m scripts.state init\|add\|set\|next-nn` | Cria o `state.toml` da tarefa, reserva nós, registra transições G2 | o `state.toml` da tarefa |
| `python3 scripts/state_lint.py [state.toml]` | As 8 invariantes do estado estruturado; usa a fixture versionada sem caminho | nada |
| `python3 scripts/gate.py --state … --role … --edge … --predecessor … --target …` | Avalia um nó proposto (P0, P_writer, P_reader, P_progresso) e responde ALLOW ou os motivos | nada |
| `python3 scripts/preflight.py --state … --nn … --kit-root …` | Gate de preparação `reserved → prepared \| preparation_failed`; grava `git-before-NN.txt` | `state.toml`, handoff sincronizado, `git-before-NN.txt` |
| `python3 scripts/launch_claude.py --state … --nn … --kit-root …` | Monta e lança o `claude --bg` do nó (`dontAsk`, regras de escrita derivadas, Stop hook, `--strict-mcp-config`) | `state.toml` |
| `python3 scripts/status_claude.py …` / `python3 scripts/watch_claude.py …` | Observa o manager nativo e, com `--state`/`--nn`, registra a transição observada | `state.toml` (só com `--state`) |
| `python3 scripts/receipt_lint.py <receipt> --handoff <handoff>` | Valida a forma de um receipt e extrai `risks_digest` | nada |
| `bin/marina approve\|run\|status\|stop\|mcp` | Envelope aprovado, `marina run` e o servidor MCP (ver [Cadeias sem supervisão](#cadeias-sem-supervisão-marina-run)) | só o diretório da tarefa |
| `bin/marina hook require-receipt` | Stop hook das sessões em background: impede o encerramento sem receipt válido | nada |

Estes scripts formalizam checks mecânicos. Roteamento, mérito de receipt e decisões de correção continuam sendo julgamento da Marina, exceto dentro de um envelope que você aprovou, onde o `marina run` segue a expansão do envelope e para em tudo que fuja dela. Nenhum script responde aprovações nativas.

## Documentação relacionada

| Documento | Conteúdo |
|---|---|
| [AGENTS.md](AGENTS.md) | Guia operacional carregado pelos runtimes: contexto, equipe, sessões independentes, normas e entrega |
| [CLAUDE.md](CLAUDE.md) | Particularidades do runtime Claude Code (importa `AGENTS.md`) |
| [docs/agent-workflow.md](docs/agent-workflow.md) | Papéis, handoffs, procedimento de lançamento/monitoramento por plataforma, aceitação e cenários de avaliação |
| [docs/analise-scripts-apoio-marina.md](docs/analise-scripts-apoio-marina.md) | Análise de scripts auxiliares para o fluxo da Marina: casos de uso, benefícios, riscos e roteiro |
| [docs/plano-estado-estruturado-e-grafos.md](docs/plano-estado-estruturado-e-grafos.md) | Schema v0 do estado estruturado (`state.toml`), grafos G1/G2/G3, decisões confirmadas e roteiro por etapas — Etapas 0 e 1 implementadas em `scripts/` |
| [docs/analise-marina-executavel-e-exclusividade-claude-2026-10.md](docs/analise-marina-executavel-e-exclusividade-claude-2026-10.md) | Análise de ganhos e perdas: Marina como executável e exclusividade Claude |
| [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md) | Design aprovado: remoção do Codex (F0) e executável da Marina com envelope pré-aprovado (F1–F6) |
| `.claude/skills/*/SKILL.md` | Texto completo de cada skill, com templates e referências |
| `.claude/instructions/` | Instruções de domínio por responsabilidade de módulo |
