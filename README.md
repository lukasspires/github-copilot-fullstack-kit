# Kit de agentes multi-repositório para Codex e Claude Code

Este repositório é um **kit de coordenação**, não uma aplicação. Ele fornece perfis de agentes, skills e instruções de domínio para que uma sessão principal (a coordenadora **Marina**) receba uma tarefa, identifique o trabalho restante, delegue a especialistas em sessões visíveis independentes e consolide a implementação e a verificação local nos repositórios da aplicação.

> Este README é documentação para pessoas. Os runtimes não o carregam como instrução: Claude Code lê `CLAUDE.md` (que importa `AGENTS.md`), `.claude/agents/` e `.claude/skills/`; Codex lê `AGENTS.md`, `.codex/agents/` e `.agents/skills/`. Por isso ele pode ser escrito em português sem afetar o comportamento dos agentes.

## Sumário

- [O que o kit faz e o que não faz](#o-que-o-kit-faz-e-o-que-não-faz)
- [Pré-requisitos](#pré-requisitos)
- [Início rápido](#início-rápido)
- [Como uma tarefa é executada](#como-uma-tarefa-é-executada)
- [Equipe de agentes](#equipe-de-agentes)
- [Configurações nativas por plataforma](#configurações-nativas-por-plataforma)
- [Skills principais](#skills-principais)
- [Entrega e autorizações](#entrega-e-autorizações)
- [Eficiência e verificação](#eficiência-e-verificação)
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
| Claude Code CLI ≥ 2.1.267 | Verificado em 2026-09-11 com `--bg`, `--name`, `--agent`, `--add-dir`, `--permission-mode`, `--allowedTools`, `claude agents`, `claude attach`, `claude logs`. Confira `claude --help` em outras versões. |
| Codex desktop | Projeto do kit cadastrado com ambiente `local`; tools `list_projects`, `create_thread`, `wait_threads`, `read_thread`, `list_threads`. |
| Repositórios-alvo clonados localmente | Caminhos absolutos; o kit não os descobre sozinho. |
| Ferramentas de build/teste dos alvos no `PATH` | Os checks descobertos precisam resolver no ambiente da sessão em background (ex.: `mvn`, `node`, `go`, `python`). |

## Início rápido

### Claude Code

Inicie **na raiz do kit** e adicione cada repositório-alvo com `--add-dir`. Substitua os caminhos de exemplo pelos seus caminhos absolutos:

```bash
claude --agent marina --add-dir /caminho/absoluto/api --add-dir /caminho/absoluto/bff
```

### Codex

```bash
codex -C /caminho/absoluto/agent-kit --add-dir /caminho/absoluto/api --add-dir /caminho/absoluto/bff
```

### Em um IDE

Selecione o kit como raiz da sessão e conceda acesso às pastas dos outros projetos pelos controles do próprio runtime. Ter as pastas abertas no IDE **não** prova que o runtime carregou o kit ou que tem acesso a cada projeto. Ao iniciar, confirme que os perfis do kit foram descobertos e que cada alvo está acessível. Reinicie a sessão após alterar perfis se o runtime já os tiver em cache.

Claude Code descobre `.claude/skills/` de diretórios adicionados, mas **não** carrega os agentes deles; por isso o kit deve permanecer como raiz da sessão, e as instruções de cada alvo (`AGENTS.md`/`CLAUDE.md`) são lidas explicitamente. Referências: [permissões de diretório do Claude](https://code.claude.com/docs/en/permissions#additional-directories-grant-file-access-not-configuration) e [recursos do Codex](https://learn.chatgpt.com/docs/features).

### Primeira tarefa

Descreva o resultado esperado, os projetos envolvidos, anexe a evidência da tarefa (PDF, link, texto) e informe os critérios de aceitação conhecidos. Exemplo:

```text
Implementar a tarefa #8144 (PDF anexo). Repositórios: /abs/bff (Node) e /abs/front (Angular).
Preservar o contrato atual do endpoint /v1/pacientes. Critério: testes existentes continuam verdes.
```

## Como uma tarefa é executada

1. **Intake** — Marina consolida objetivo, critérios, decisões posteriores e evidência; distingue o que foi pedido, o que foi decidido depois, o que foi relatado como feito e o que foi verificado. Estado, percentual ou link de MR **não** provam conclusão.
2. **Checkpoint** — Para toda tarefa com atribuições, Marina mantém `.agent-state/<tarefa>.md` (ignorado pelo Git), com decisões, autorizações, evidências, checks e a próxima ação.
3. **Roteamento** — Uma correção simples vai para um único especialista. Sofia entra para decisões de arquitetura, contratos compartilhados, migrations e backfills; Clara revisa automaticamente autorização, contratos públicos, integridade de dados, migrations e operações críticas.
4. **Handoff** — Antes de cada atribuição, Marina escreve `.agent-state/<tarefa>/<NN>-<papel>-handoff.md` com objetivo, perfil absoluto, roots, instruções do alvo a ler, escopo de escrita, contratos, evidência, critérios, checks descobertos e allowlist.
5. **Sessão visível** — Cada implementação, revisão, correção ou análise abre uma sessão nova com título `<tarefa> — <papel> — <NN> — <tipo>`. Claude: `claude --bg --agent <papel>` com permissões por atribuição. Codex: `create_thread` no ambiente `local` do projeto. Nunca reutilizar, retomar ou bifurcar sessões concluídas.
6. **Receipt** — O especialista escreve `<NN>-<papel>-receipt.md` com `status`, `changed`, `checks`, `evidence`, `risks`, `next`, mais `profile_read` e `instructions_read` (caminhos absolutos realmente lidos). Clara acrescenta `verdict` (`PASS`, `PASS_WITH_RISKS`, `FAIL`).
7. **Gate entre writers** — O próximo writer só é liberado com o receipt final do anterior, evidência do gerenciador nativo de que ele parou, e `git status/diff` do alvo conferido e registrado. Writers são sequenciais entre repositórios; leitores (Clara, Sofia, analista-redmine) podem sobrepor-se a outros leitores, nunca a um writer no mesmo alvo.
8. **Correção** — Achados voltam ao **mesmo papel** em uma **nova** sessão. Falha repetida sem evidência nova exige novo diagnóstico, não uma alegação arbitrária de conclusão.
9. **Consolidação** — Marina reporta evidência por critério de aceitação, resultado da revisão, riscos remanescentes e checks pulados.

Se a plataforma não conseguir abrir sessões visíveis, a sessão principal assume a especialidade e registra no checkpoint e na resposta: `delegação visível indisponível: <motivo>; especialidade <papel> assumida na sessão principal`. Esse fallback não é revisão independente. Criação com resultado incerto é reconciliada no gerenciador de sessões antes de qualquer nova tentativa.

## Equipe de agentes

| Papel | Especialidade | Escreve em alvos |
|---|---|---|
| **Marina** | Coordenação na sessão principal: intake, roteamento, delegação sequencial, checkpoint, consolidação | Apenas docs/config gerais pequenas e checkpoints |
| **Alice** | Angular: UI, estado, acessibilidade, acesso a dados | Escopo atribuído |
| **Bruno** | Java: APIs, domínio, persistência, segurança, testes | Escopo atribuído |
| **Gustavo** | Go backend: APIs, serviços, persistência | Escopo atribuído |
| **Gabriel** | Go ETL: ingestão, concorrência limitada, I/O confiável | Escopo atribuído |
| **Paula** | Python ETL: ingestão, transformação, carga, recuperação | Escopo atribuído |
| **node-backend** | Node.js/TypeScript: BFFs, APIs, integrações upstream | Escopo atribuído |
| **Diana** | Análise de dados: SQL reproduzível, notebooks, métricas, reconciliação | Escopo atribuído |
| **Sofia** | Arquitetura: decisões materiais, contratos compartilhados, migrations, backfills | Não (só o próprio receipt) |
| **Clara** | Revisão independente por risco: correção, segurança, integridade, compatibilidade, testes | Não (só o próprio receipt) |
| **analista-redmine** | Opcional: histórico complexo de tarefas, requisitos atuais, trabalho restante | Não (só o próprio receipt) |

Regras de roteamento que costumam gerar dúvida:

- Backend TypeScript/BFF é do `node-backend`, não da Alice.
- Migrations SQL da aplicação vão para o dono do módulo, não para a Diana só por causa da extensão. SQL avulso sem dono pode ficar na sessão principal, com Sofia para arquitetura e Clara para revisão.
- Várias tecnologias na mesma tarefa **não** exigem Sofia; um contrato compartilhado ou uma migration, sim. Conte consequências, não linguagens.
- Papéis read-only (Sofia, Clara, analista-redmine) escrevem apenas o próprio receipt. Essa fronteira é de instrução, não de sandbox; as permissões do runtime continuam valendo.

## Configurações nativas por plataforma

| Camada | Codex | Claude Code |
|---|---|---|
| Entrada | `AGENTS.md` | `CLAUDE.md`, que importa `AGENTS.md` |
| Perfis | `.codex/agents/*.toml` | `.claude/agents/*.md` |
| Skills sob demanda | `.agents/skills/` | `.claude/skills/` |
| Instruções de domínio (carga explícita) | `.codex/instructions/` | `.claude/instructions/` |

As cópias fornecem comportamento equivalente com metadados nativos de cada plataforma. **Toda mudança de comportamento compartilhado deve atualizar as duas cópias.** As instruções de domínio são escolhidas por responsabilidade do módulo, não por extensão: backend TypeScript não carrega instruções Angular, e Go ETL não carrega automaticamente as de Go API. Sessões independentes usam o modelo configurado pelo usuário; a criação no Codex não define modelo. Os perfis não desativam controles de permissão do runtime.

## Skills principais

Skills são procedimentos carregados sob demanda. No Claude Code, a Marina e os especialistas carregam a skill relevante automaticamente; você também pode invocá-la por `/nome-da-skill`. No Codex, use `$nome-da-skill` no prompt. Carregue apenas o necessário: uma alteração só em conector não exige a skill de pipeline completo.

### Coordenação e qualidade

#### `task-execution`

- **O que faz:** procedimento operacional da Marina — intake de texto/PDF/link, identificação do trabalho restante, roteamento por evidência, sessões visíveis, checkpoint, handoff/receipt e retomada.
- **Quando usar:** escopo incerto, histórico longo, vários repositórios ou retomada de uma tarefa interrompida. Uma tarefa limitada a um especialista pode ir direto ao papel.
- **Exemplo:**
  ```text
  /task-execution Retomar a tarefa #7976. Checkpoint em .agent-state/redmine-7976.md. Verificar o estado atual dos repositórios antes de qualquer nova sessão.
  ```

#### `quality-gate`

- **O que faz:** revisão por risco de correção, segurança, testes, compatibilidade, integridade de dados e prontidão operacional, com achados acionáveis (severidade, local, evidência, impacto, correção) e veredito separado.
- **Quando usar:** automaticamente pela Clara em mudanças de autorização, contrato público, integridade de dados, migration ou operação crítica; ou em revisão explícita.
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
- **Quando usar:** perguntas analíticas, reconciliação entre fontes, validação de métricas. Análise pura usa a autovalidação da Diana; se alterar comportamento de produção, entra revisão.
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
- Toda tarefa com atribuições mantém um checkpoint sanitizado e ignorado pelo Git em `.agent-state/`, inclusive tarefas curtas. Sessões concluídas ficam disponíveis para consulta; nunca são arquivadas ou apagadas automaticamente.

## Eficiência e verificação

- Carregue só as instruções e skills relevantes; reutilize descobertas e extratos de PDF; roteie de forma estreita e revise por consequência.
- Teste o comportamento alterado proporcionalmente com os comandos descobertos no projeto; reporte resultados exatos e checks pulados. Não adicione testes que apenas repetem mudanças de texto de baixo impacto.
- Meça tokens reais apenas quando o runtime os expõe; menos agentes ou menos bytes não são um percentual de economia.
- O kit não possui um validador permanente de customizações. Avalie mudanças com checks estruturais direcionados (parse de TOML/YAML, paridade `.codex`/`.claude`, `git diff --check`) e simulações realistas de tarefa, reportando honestamente os checks de runtime não executados. Uma proposta de scripts de apoio está em [docs/analise-scripts-apoio-marina.md](docs/analise-scripts-apoio-marina.md).

## Documentação relacionada

| Documento | Conteúdo |
|---|---|
| [AGENTS.md](AGENTS.md) | Guia operacional carregado pelos runtimes: contexto, equipe, sessões independentes, normas e entrega |
| [CLAUDE.md](CLAUDE.md) | Particularidades do runtime Claude Code (importa `AGENTS.md`) |
| [docs/agent-workflow.md](docs/agent-workflow.md) | Papéis, handoffs, procedimento de lançamento/monitoramento por plataforma, aceitação e cenários de avaliação |
| [docs/analise-scripts-apoio-marina.md](docs/analise-scripts-apoio-marina.md) | Análise de scripts auxiliares para o fluxo da Marina: casos de uso, benefícios, riscos e roteiro |
| `.claude/skills/*/SKILL.md` e `.agents/skills/*/SKILL.md` | Texto completo de cada skill, com templates e referências |
| `.claude/instructions/` e `.codex/instructions/` | Instruções de domínio por responsabilidade de módulo |
