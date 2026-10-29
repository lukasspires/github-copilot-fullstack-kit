# Marina com perguntas, plano e execução acompanhada: spec

> **Natureza:** spec da evolução que combina o funcionamento da Marina com o ciclo do Superpowers (perguntas → plano → execução), dispara a execução aprovada num terminal separado e a acompanha numa TUI. Os planos de implementação de cada fase (F7 em diante) argumentam a partir deste documento.
>
> **Origem:** design discutido com o usuário em 2026-10-28. As decisões do usuário estão marcadas como **decisão do usuário**. As decisões tomadas pela Marina, que o usuário pode rever, estão marcadas como **decisão da Marina**.

## 1. Estado de partida (verificado)

- **Intake:** a Marina consolida objetivo, critérios, decisões e evidências, e lê `project/` antes de redescobrir ([task-execution](../.claude/skills/task-execution/SKILL.md)). Ela pergunta, mas sem um procedimento estruturado de perguntas.
- **Plano executável:** é a tabela `[envelope]` do `state.toml` ([agent-workflow.md](agent-workflow.md#approved-envelopes-marina-run)).
  - Cada estágio tem um template com `Objective`, `Write scope` e `Acceptance criteria`.
  - Hoje **todos os estágios usam o mesmo papel writer**: o `validate_envelope` recusa papéis diferentes, porque o G3 `prossegue` exige o papel do predecessor.
- **Aprovação:** `marina approve`, só num TTY, com o slug digitado. O hash cobre o envelope e os templates.
- **Execução:** `marina run`, sem interface, um nó por vez. O `run_start` do MCP o dispara destacado.
- **Estado observável:** `state.toml` (eventos G2 com horário), `marina-run.log`, `judge-calls.jsonl`, `.marina-run.lock`, `git-after-NN.txt`, receipts e `claude agents --json --all`.
- **Superpowers 7.0.0** (instalado em escopo de usuário):
  - brainstorming: uma pergunta por vez, opt-out, resumos parciais;
  - writing-plans: tarefas TDD com `Global Constraints` e `Review Focus`;
  - subagent-driven-development: Agent tool, ledger, implementador retomado, worktree, commits por tarefa.
  - O perfil da Marina não tem a ferramenta `Skill`.
- **Ambiente do usuário:**
  - sessão gráfica: Hyprland/Wayland, `TERMINAL=kitty`, alacritty também instalado, sem tmux;
  - fish 4.9.3 (o `$SHELL` da sessão do Claude é zsh) e Python 3.14 com `curses`;
  - Claude Code CLI 2.1.311 (as notas do kit verificaram o 2.1.306).

## 2. Fluxo da tarefa

| # | Transição | Quem age | Artefato |
|---|---|---|---|
| 1 | Intake | Usuário → Marina | `checkpoint.md`, `inputs/` |
| 2 | Perguntas, uma por vez, com resumos parciais e recon só de leitura | Marina ↔ usuário | `brief.md` em construção |
| 3 | Brief fechado e confirmado no chat | Marina → usuário | `brief.md`; linha `brief confirmado <data>` no checkpoint |
| 4 | Plano: estágios com papel, alvos e allowlist próprios; nó `analisa` do architect quando a decisão é material | Marina (architect) | `plan.md`, `stage-N-handoff-template.md`, `[envelope]` |
| 5 | Ajustes do plano no chat; nada é aprovado aqui | Usuário ↔ Marina | Novas versões |
| 6 | **Envio = aprovação:** o usuário roda `marina go <projeto> <tarefa>` num terminal | **Usuário** | `[envelope.approval]`, lock, `marina-run.log` |
| 7 | Execução: um writer por vez; troca de papel por `encadeia` | `marina run`, especialistas | Handoffs, receipts, `git-after-NN.txt` |
| 8 | Encerramento: a Marina consolida por critério e separa lições; o usuário decide commit e MR | runner → Marina → usuário | Checkpoint final, `project/facts.md` |

### 2.1 Fim da rodada de perguntas

A rodada termina quando todos os campos obrigatórios do brief têm um valor marcado como "do usuário", "decisão da Marina" ou "pendente, não bloqueia". Os campos são:
- objetivo e o porquê;
- critérios de aceite;
- não-objetivos;
- alvos e branches;
- contratos a preservar;
- autorizações (commit, MR, dados reais);
- normas aplicáveis;
- papel ou papéis;
- checks descobertos.

Ela também termina quando o usuário diz que a Marina pode seguir. Nesse caso a Marina lista em uma linha cada padrão que assumiu.

Em seguida a Marina lê o brief como o especialista que vai receber o trabalho e faz **uma** rodada só com as perguntas que mudam o que vai ser construído. O usuário confirma o brief no chat.

### 2.2 Do brief ao plano

| Campo do brief | Destino |
|---|---|
| Critérios de aceite | `Acceptance criteria` dos templates e foco do reviewer |
| Contratos | seção de contratos dos handoffs |
| Alvos e branches | `targets`/`branches` do envelope e `targets` dos estágios |
| Checks | regras `Bash(...)` da allowlist do estágio, com o alvo no comando |
| Autorizações | o que pode entrar na allowlist (sem commit, salvo autorização no brief) |
| Não-objetivos | `Write scope` mais estreito |
| Riscos implícitos | `Review Focus` do `plan.md`, repassado ao handoff do reviewer |

## 3. Mudanças de regra (decisões do usuário, 2026-10-28)

1. **Envio é aprovação.**
   - Rodar `marina go <projeto> <tarefa>` num TTY aprova o plano inteiro, sem digitar slug e sem uma aprovação por envelope.
   - O TTY continua obrigatório: a Marina só tem Bash sem terminal, então não consegue disparar a run sozinha.
   - O `go` grava o hash no disparo, e qualquer edição posterior para a run com `envelope_changed`.
   - `marina approve` deixa de ser um passo obrigatório e continua existindo para aprovar sem executar (**decisão da Marina**).
2. **Writers de papéis diferentes num plano só.**
   - A aresta G3 nova é `encadeia`: liga um writer `accepted` ao writer seguinte de **outro** papel, com `type = implementação`.
   - Valem as mesmas pré-condições de `prossegue`: `P_writer`, Git gate e receipt validado.
   - `prossegue` continua exigindo o mesmo papel.

### 3.1 O que não muda

- Só um humano dispara a execução, e nenhuma ferramenta MCP grava aprovação.
- Writers continuam sequenciais, com Git gate e receipt validado entre eles.
- `dontAsk` com allowlist por atribuição.
- Nenhuma resposta a aprovação nativa.
- Commit só com autorização.
- No máximo uma correção por estágio, e o segundo `FAIL` para a run.
- A juíza decide só `PASS_WITH_RISKS`.
- Sessões novas, nunca retomadas.
- Modelo configurado pelo usuário.

### 3.2 Decisões da Marina que acompanham as mudanças

1. **Escopo por estágio.**
   - Cada estágio pode declarar `targets` (subconjunto não vazio dos `targets` do envelope) e `allowlist`. Sem eles, o estágio herda os do envelope, então os envelopes atuais continuam válidos e se comportam como hoje.
   - Writers (`inicia`, `prossegue`, `encadeia`) usam o escopo do estágio.
   - Revisão e correção usam o escopo do estágio quando `review = "each_stage"` e o do envelope quando `review = "final"`.
2. **Plano com mais de um papel exige `review = "each_stage"`.** Com uma revisão só no fim, um `FAIL` não diria qual papel corrige. A opção `each_stage_and_final` fica fora (YAGNI).
3. **O Git gate compara todos os alvos do envelope.**
   - `git-after-NN.txt` e a comparação antes do próximo writer usam os `targets` do envelope, não os do nó.
   - Assim, uma mudança alheia num alvo de outro estágio também é detectada.
   - Um writer não consegue alterar um alvo fora do seu estágio, porque o `Edit(//…)` é derivado dos alvos do nó.
4. **Prazo de cancelamento no `go`.**
   - O `go` mostra o resumo do plano e espera 10 s antes de gravar a aprovação.
   - Um Ctrl-C nesse intervalo cancela sem escrever nada.
   - Se a aprovação gravada já corresponde ao hash atual, o `go` não espera nem regrava.

## 4. Divisão Marina × Superpowers

| Aspecto | Superpowers | Resultado |
|---|---|---|
| Perguntas | brainstorming | Adotado como a skill do kit `marina-intake`: ritmo, opt-out, resumos e recon, no território da Marina. Sem companion visual. |
| Design | `docs/superpowers/specs/`, com commit | `tasks/<t>/brief.md`, ignorado pelo Git |
| Plano | writing-plans | A skill do kit `marina-plan` produz `plan.md` sem passos de commit. Cada tarefa vira um estágio; `Files` vira `Write scope`. |
| Execução | subagentes, ledger, retomada, até 5 rodadas, worktree, commits | Fica a da Marina (`marina run`) |
| Ledger | `progress.md` | `state.toml`, log e checkpoint. O formato `Ruling:` passa a valer para as decisões da Marina no checkpoint. |

As skills são copiadas e adaptadas no kit, citando Superpowers 7.0.0 como fonte (**decisão do usuário**: mantidas as recomendações). O kit não depende do plugin em tempo de execução.

## 5. Terminal

A Marina entrega o comando `/<kit_root>/bin/marina go <projeto> <tarefa>`, e o usuário o roda em qualquer terminal (**decisão do usuário**).
- `bin/marina` é `#!/bin/sh`, então o comando funciona igual em fish, zsh ou bash, sem nenhum recurso de shell.
- A run nasce do shell do usuário, fora do processo do Claude, e não depende de permissão nova.
- Abrir o kitty pela Marina fica para uma fase opcional (F10).

O `go` faz três coisas:
1. Aprova no envio (seção 3).
2. Dispara `marina run` destacado, com a mesma semântica do `run_start`. Usa `--interval 30` e `--max-duration` igual ao do envelope, salvo opção explícita.
3. Abre a TUI (a partir da F8). Na F7, ele imprime pid, log e o comando `marina status`.

Detalhes:
- Com um lock vivo, o `go` não dispara uma segunda run.
- Fechar o terminal não para a run; para parar, use `marina stop`.

## 6. TUI (`marina watch`)

A TUI não muda nada na execução. A única escrita é a tecla `s`, que equivale a `marina stop`. Usa stdlib `curses`, e `--once` imprime um retrato em texto puro.

- **Etapas planejadas:** os nós existentes, mais os futuros calculados pela mesma expansão do `decide`. Os condicionais aparecem com `?`. Colunas: papel, tipo, estado, entrada, saída, duração e duração típica.
- **Agora:**
  - o nó ativo e o estado no manager;
  - a última ação, lida do transcript `~/.claude/projects/<slug>/<sessionId>.jsonl` (formato não documentado; sem ele, `claude logs`);
  - a decisão do runner;
  - os arquivos alterados nos alvos.
- **Entradas e saídas esperadas da etapa:**
  - entradas: handoff, receipt do predecessor, estado do Git gate e allowlist;
  - saídas: arquivos do `Write scope`, receipt, checks, `git-after` e critérios;
  - fontes: os templates, incluindo as seções opcionais novas `Expected inputs` e `Expected outputs`, que o hash cobre.
- **Leituras de "entrada e saída":** artefatos (a leitura do usuário) e horários de entrada e saída (colunas `entra`/`sai`). Tokens ficam de fora até um spike confirmar a fonte.
- **Atualização:**
  - relógio a cada 1 s;
  - arquivos relidos só quando o mtime muda;
  - manager consultado a cada 10 s; quando falha, a tela mostra o último valor marcado como antigo.

### 6.1 Métricas

- **Percentagem:** nós concluídos sobre nós previstos, mostrada em duas versões: sem correção (N_min) e com o máximo de correções (N_max). Dentro de um nó, a TUI mostra a fase, não uma percentagem.
- **Duração típica:**
  - p50 e p80 por papel e tipo, só com transições gravadas por `marina-run` ou pelo status;
  - usa o projeto primeiro e depois todos os projetos;
  - com menos de 5 amostras, mostra "sem base".
- **Restante:** soma de p50 a p80 dos nós obrigatórios que faltam. Os condicionais aparecem à parte.
- **Nó acima do típico:** a tela diz "acima do típico", nunca uma estimativa negativa.
- **Número certo:** o limite `max_duration`.

## 7. Fases

| Fase | Entrega | Plano |
|---|---|---|
| **F7** | Escopo por estágio, aresta `encadeia`, `marina go` (aprovação no envio) e regras do kit atualizadas | [plano-f7-envelope-multipapel-e-envio-2026-10.md](plano-f7-envelope-multipapel-e-envio-2026-10.md) |
| **F8** | `marina watch`: modelo de progresso puro, `--once`, `curses`, atividade atual; o `go` abre o visor | [plano-f8-marina-watch-2026-10.md](plano-f8-marina-watch-2026-10.md) |
| **F9** | Skills `marina-intake` e `marina-plan`, templates de `brief.md` e `plan.md`, `task-execution` apontando para elas | [plano-f9-skills-perguntas-e-plano-2026-10.md](plano-f9-skills-perguntas-e-plano-2026-10.md) |
| **F10** | Opcional: `marina open-terminal` (kitty ou alacritty via `$TERMINAL`) | só se o usuário pedir |
| **F11** | Aceitação real no repositório descartável `marina-acc`, com fluxo completo e dois papéis | a escrever |

## 8. Riscos

- **Transcript e campos do manager não documentados.** O CLI mudou de 2.1.306 para 2.1.311. A F8 começa revalidando esses campos e degrada sem quebrar.
- **Disparo por engano.** Rodar o `go` por engano dispara a implementação. O prazo de 10 s atenua.
- **Plugin nas sessões em background.** Não se sabe se o SessionStart do Superpowers dispara nelas. Os especialistas não têm `Skill`, o que atenua.
- **Estimativas fracas no começo:** pouca amostra significa "sem base" com frequência.
