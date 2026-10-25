# Análise: Marina como executável e exclusividade Claude — 2026-10-25

**Status:** análise; nada implementado. Nenhuma alteração em `scripts/`, nos perfis ou nas skills foi feita para produzir este documento.

**Escopo.** Avalia duas mudanças propostas: (1) transformar a Marina em um executável escrito em Rust ou Go, responsável por gerenciar os loops e a execução das tarefas; (2) remover a compatibilidade com Codex e outros runtimes, adotando exclusividade para o Claude Code. As mudanças são independentes, mas a segunda simplifica a primeira.

**Método.** Leitura de `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/agent-workflow.md`, `docs/analise-scripts-apoio-marina.md`, `docs/analise-melhorias-complementares-2026-10.md`, dos perfis da Marina e do `reviewer` nos dois lados e da skill `task-execution`; busca de referências a Codex em `scripts/` e `tests/`; contagem de `native.platform` nos `state.toml` locais de `.agent-state/`; conferência das ferramentas instaladas.

## Sumário

A exclusividade Claude é barata, de baixo risco e tem ganho imediato. O executável vale a pena como **orquestrador da metade mecânica** da Marina; não como substituto do julgamento. A troca de linguagem é a parte de menor valor: quase todo o ganho vem de centralizar o procedimento mecânico, expô-lo via MCP e usar hooks do Claude — e nada disso depende de Go ou Rust.

## Fatos de base

| Fato | Evidência |
|---|---|
| Codex nunca foi usado na prática | `.agent-state/`: 12 atribuições — 7 `platform = "claude"`, 5 `"unavailable"`, 0 `"codex"` |
| Duplicação `.claude` ↔ `.codex`/`.agents` | 57 arquivos (~87 KB) em `.codex/` e `.agents/`; B16 de `analise-melhorias-complementares-2026-10.md`: 38 arquivos byte-idênticos + 24 duplicatas semânticas |
| Paridade só detectada, não prevenida | `scripts/kit_lint.py` — `check_agent_profile_parity`, `check_instructions_parity`, `check_skills_identity` |
| Restrição read-only só no Claude | B12: os `.codex/agents/*.toml` não têm equivalente de `tools`/`permissionMode` |
| Tooling atual | ~2,9 mil linhas de Python stdlib em `scripts/`, 281 testes `unittest` |
| Decisão vigente contra lançamento automático | `analise-scripts-apoio-marina.md` §5 e §7.9 ("script propõe, Marina lança"); `agent-workflow.md` G2: abrir o próximo nó é "never automatic" |
| Toolchain local | Go 1.27.1 instalado; Rust (`cargo`/`rustc`) ausente; Claude Code 2.1.306 |

A Marina tem hoje duas metades:

- **Mecânica:** máquina de estados G2/G3, `preflight`, `gate`, `launch_claude`, `status_claude`/`watch_claude`, `receipt_lint`, `state_lint`, `state.toml`.
- **Julgamento:** intake, roteamento por consequência, mérito do receipt, escolha entre `corrige`/`analisa`/`needs_input`, consolidação.

## 1. Marina como executável (Go ou Rust)

### Ganhos

1. **Fonte única do procedimento mecânico.** Os scripts viram um binário com subcomandos (`marina gate`, `launch`, `watch`, `next`), com transições atômicas e trava de arquivo no `state.toml`. Elimina o risco 7.1 de `analise-scripts-apoio-marina.md` (terceira fonte de verdade).
2. **Supervisor real.** Um laço orientado a eventos pode vigiar várias sessões ao mesmo tempo, notificar `waiting_approval` imediatamente e checar o `P_writer` entre tarefas continuamente. Hoje `watch_claude` faz polling de uma sessão por vez.
3. **Tipagem forte da máquina de estados.** Estados e arestas como enums; transição inválida vira erro de compilação (exaustivo em Rust, parcial em Go).
4. **Servidor MCP em vez de Bash na allowlist.** O binário pode expor ferramentas tipadas (`mcp__marina__gate`, `mcp__marina__launch`) com permissão por ferramenta. Resolve o risco 7.3 (`Bash(scripts/*)` pré-aprova tudo o que o script faz). É o ganho mais concreto.
5. **Distribuição.** Binário estático elimina a exigência de Python ≥ 3.11 e os problemas de PATH do §7.6.
6. **Menos contexto gasto na Marina-LLM.** Ela chama `marina next` e recebe uma proposta já validada, em vez de montar comandos e interpretar JSON.

### Perdas e riscos

1. **O julgamento não cabe no binário.** Se o laço decidir roteamento, aceitação ou correção, cristaliza regras rígidas (rotear por extensão, por exemplo) que o kit evita de propósito. O binário acabaria chamando o Claude de qualquer forma — sessão interativa ou `claude -p --json-schema` para decisões estruturadas.
2. **Conflito com o humano-no-loop.** "Gerenciar os loops" contradiz a regra de que o próximo nó nunca abre sozinho. Ou o binário só propõe (supervisor, não executor), ou a decisão precisa ser revogada explicitamente nos documentos e no `AGENTS.md`.
3. **Custo de reescrita.** ~2,9 mil linhas e 281 testes que guardam correções difíceis (B1, formatos de receipt, fail-open do `preflight`). A reescrita traz risco de regressão exatamente nesses casos de borda.
4. **Auditabilidade.** O `reviewer` lê e executa um script Python na hora; um binário exige build, pipeline de release e verificação de que o binário em uso corresponde ao fonte.
5. **Raio de impacto maior.** Um processo de longa duração com autoridade para lançar sessões pode duplicar writers por bug — o que o protocolo inteiro existe para impedir.
6. **A fragilidade do CLI permanece.** O parse de `claude agents --json` e do ID curto do `--bg` (o próprio `extract_short_id` registra que o formato não é estável) continua frágil em qualquer linguagem.
7. **Fim do "zero dependências".** Go e Rust precisam de bibliotecas de TOML e MCP. Pouco grave, mas é mudança de princípio.
8. **Papéis e identidade.** O papel `kit-tooling` ("Python stdlib only") precisa ser redefinido, e "Marina" passa a nomear tanto um binário quanto uma persona.

### Go ou Rust

**Recomendação: Go.** Já está instalado; a equipe já tem `go-backend`/`go-etl` (o mesmo especialista revisa); goroutines servem bem para vigiar várias sessões; há SDK MCP oficial. Rust daria garantias melhores na máquina de estados, mas não está instalado, não há especialista e o ganho não compensa a curva para ~3 mil linhas de orquestração.

**Terceira opção a considerar:** com exclusividade Claude, o Claude Agent SDK (Python ou TypeScript) oferece callbacks de permissão e hooks nativos. **Não verificado:** se sessões criadas pelo SDK aparecem em `claude agents` e aceitam `claude attach`, como o protocolo de sessões visíveis exige.

## 2. Exclusividade Claude

### Ganhos

1. **Menos manutenção.** Saem `.codex/` e `.agents/`, os três checks de paridade do `kit_lint`, o caminho Codex em `scripts/handoff_sync.py:95`, a regra codex/host de `scripts/state_lint.py` e `scripts/state/model.py`, a seção "Codex desktop" de `docs/agent-workflow.md` e metade dos cenários de aceitação ("execute in each platform"). A correção B16 (`--fix`) deixa de ser necessária.
2. **Fim da assimetria B12.** A restrição read-only de `reviewer`/`architect`/`analista-redmine` deixa de existir só de um lado.
3. **Fronteiras de instrução viram enforcement.** Sem exigência de paridade, hooks do Claude podem ser passados por `--settings` em cada invocação (o launch já usa essa flag):
   - **PreToolUse:** recusa Write/Edit fora do caminho do receipt para papéis read-only. Hoje é só instrução: "this profile does not enforce a filesystem sandbox".
   - **Stop:** roda `receipt_lint` antes de a sessão encerrar.
   - **SessionStart:** injeta o handoff.

   Provavelmente o maior ganho de segurança disponível hoje.
4. **Recursos nativos sem equivalente obrigatório:** `--json-schema` para receipts estruturados, `tools`/`permissionMode` por agente.
5. **Executável mais simples:** um único adaptador, sem o lado Codex "manual via MCP".

### Perdas e riscos

1. **Dependência de fornecedor único.** Mudanças de flags, do JSON do manager, de preço ou de política da organização afetam tudo, sem runtime alternativo. Em contexto governado (SES/SC, NADS, DTIG), confirmar que não há exigência de neutralidade de ferramenta.
2. **Perda da revisão entre modelos.** Um revisor de outro fornecedor pega erros diferentes. Nunca usado, mas é uma opção que se perde.
3. **Pessoas que usem Codex ou Copilot** deixam de poder usar o kit.
4. **Nome e posicionamento.** O nome do repositório ("github-copilot-fullstack-kit") e o README ("para Codex e Claude Code") ficam desatualizados.

**Manter:** o `AGENTS.md` como entrada neutra, importado pelo `CLAUDE.md` como hoje — não custa nada e preserva a leitura básica por Copilot e outras ferramentas. A plataforma `unavailable` no schema, porque o fallback na sessão principal continua existindo. Os documentos históricos que citam Codex, como histórico.

## Recomendação e ordem

1. **Exclusividade Claude primeiro.** Remover o lado Codex, simplificar `kit_lint`, schema e documentos; manter o `AGENTS.md`.
2. **Hooks de enforcement**, ainda em Python. Maior ganho de segurança, menor custo.
3. **Executável Go incremental (strangler).** Começar por um servidor MCP com `gate`, `launch` e `watch`, com paridade de testes; remover cada script Python só depois que a versão Go passar nos mesmos casos.
4. **O laço propõe e supervisiona; não lança.** Lançar o próximo writer continua sendo decisão da Marina e do usuário. Automação total exige decisão explícita: revogar a regra "never automatic" em `AGENTS.md` e `docs/agent-workflow.md`, registrando o motivo.

## Pendências de verificação

- Visibilidade de sessões do Claude Agent SDK em `claude agents` e `claude attach`.
- Forma exata de declarar hooks por invocação via `--settings` na versão instalada do CLI, e se perfis de agente aceitam hooks no frontmatter.
- Existência de exigência organizacional de neutralidade de runtime para projetos governados.
