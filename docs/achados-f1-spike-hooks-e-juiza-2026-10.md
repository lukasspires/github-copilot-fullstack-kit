# Achados da F1 — spike de hooks por invocação e da juíza headless — 2026-10-25

**Status:** spike executado em 2026-10-25 na sessão principal, conforme [plano-f1-spike-hooks-e-juiza-2026-10.md](plano-f1-spike-hooks-e-juiza-2026-10.md). Todo o código foi descartável e ficou num sandbox `f1-spike-XXXX` fora do kit; nada em `scripts/`, `tests/`, `.claude/` ou na configuração do usuário foi alterado.

**Ambiente:** Claude Code CLI `2.1.306`; usuário sem hooks próprios em `~/.claude/settings.json`, com 2 plugins ativos; sessão-mãe dentro do app desktop (Code tab).

**Custo:** 15 execuções `-p` somaram US$ 1,42; a sessão `--bg` (`d396e413`) não reporta custo no manager. Sondas de hook com `claude-haiku-5-5` custaram ~US$ 0,005 cada; chamadas de juíza com o modelo padrão, US$ 0,03–0,45.

## Hipóteses

| Hipótese | Premissa da spec | Resultado | Evidência |
|---|---|---|---|
| H1 | `hooks` via `--settings` dispara em `-p` | **confirmada** | P1: duas entradas `PreToolUse` (`Write`, `Edit`) no `hook.log`; `a.txt` com `two` |
| H2 | exit 2 no PreToolUse bloqueia e a mensagem chega ao modelo | **confirmada** | P2: `b.txt` ausente; uma entrada `Write`; o modelo recebeu `PreToolUse:Write hook error: [<comando>]: <stderr>`. O bloqueio **não** aparece em `permission_denials` |
| H3 | `--settings` soma com hooks de outras fontes e com `worktree` | **confirmada** (parcial para plugins) | P3c: entradas `project` e `cli` para o mesmo `Write`, com `worktree.bgIsolation` no mesmo JSON. Disparo dos hooks `SessionStart` de plugins não é observável no `--output-format json` |
| H4 | exit 2 no Stop reabre o turno; reentrada traz `stop_hook_active` | **confirmada** | P4: duas entradas `Stop`, `stop_hook_active` `False` → `True`; o modelo escreveu o `receipt.md` pedido na mensagem. A entrada do Stop também traz `last_assistant_message` e `background_tasks` |
| H5 | hooks de `--settings` disparam em `--bg` | **confirmada** | P5: entrada `bg`/`Write` e `d.txt` criado pela sessão `d396e413`. `--bg` exige diretório confiável (ver X3) |
| H6 | `file_path` e `cwd` do hook permitem resolver o caminho contra os alvos | **confirmada** | P1/P5: `tool_input.file_path` é **absoluto**; `cwd` e `CLAUDE_PROJECT_DIR` do hook são o cwd da sessão (a raiz do kit, em produção), não o alvo. Chaves de `tool_input`: `Write` → `content`, `file_path`; `Edit` → `file_path`, `new_string`, `old_string`, `replace_all`. `NotebookEdit` não exercitado |
| H7 | `-p --json-schema --output-format json` entrega objeto validado numa chave estável, com enum respeitado | **refutada como escrita; confirmada com ajuste** | P6/P6a: agente cuja definição tem lista `tools` faz o `--json-schema` ser **ignorado em silêncio** (sem `structured_output`, `result` em prosa, `subtype: success`). P6b/P6c/P6d/P7: sem lista `tools` no agente, o objeto validado vem em `structured_output` (e `result` é o mesmo JSON em texto); P7: enum respeitado, `corrige` recusado |
| H8 | `--tools Read` remove `Write` da sessão | **confirmada** | P7: `note.txt` ausente, `permission_denials` vazio — a ferramenta não existe na sessão |
| H9 | visibilidade de sessões `-p` no manager | **registrada** | P8: nenhuma sessão `-p` (com ou sem persistência) aparece em `claude agents --json --all`; a `--bg` aparece (`d396e413`, `done`) |

## Achados fora das hipóteses

### X1 — `claude -p` lê o stdin herdado e age sobre ele (severidade alta)

As sondas eram executadas com `bash <<'EOF'`. O `claude -p` filho herdou o stdin do bash — o resto do script — e o tratou como entrada adicional ao prompt. Em P2 e P3 a sessão interna descreveu passos posteriores do script externo e, em P3, **executou um deles** (apagou um arquivo do sandbox), relatando inclusive o contrário do que fez. Repetir com ambiente limpo (`env -i`) não mudou nada; fechar o stdin (`< /dev/null`) eliminou o efeito (P3c).

**Impacto no kit.** `scripts/launch_claude.py:293` chama o subprocesso sem `stdin`, herdando o de quem o executa. Qualquer chamada a `claude` feita por script do kit (launch, futura juíza, runner) precisa de `stdin=subprocess.DEVNULL`.

### X2 — `--permission-mode auto` não trata `--allowedTools` como fronteira (severidade alta, decisão do usuário)

P10: em `auto`, com `--allowedTools Write Edit`, um `touch z.txt` via Bash **rodou sem aprovação e sem registro** em `permission_denials`. O classificador do modo `auto` decide sozinho; comandos só ficam pendentes quando ele escala (o que já foi observado em `kit-nits-cleanup` para outro comando). P10b: em `--permission-mode dontAsk`, o mesmo Bash foi **negado** e registrado em `permission_denials`, e o `Write` da allowlist rodou.

**Impacto no kit.** `AGENTS.md` e `docs/agent-workflow.md` afirmam que comandos fora da allowlist que exigem aprovação ficam pendentes para `claude attach`. Com `auto`, isso só vale quando o classificador escala; a allowlist derivada dos checks não é a fronteira real. As alternativas são:

- manter `auto` e reescrever a documentação para dizer que o classificador pode aprovar fora da allowlist (o `guard-write` da F2 fica ainda mais importante); ou
- passar especialistas em background para `dontAsk`: a allowlist vira fronteira de fato, mas um comando fora dela é negado em vez de esperar `attach`, e o especialista precisa reportá-lo no receipt (`needs_input`/`blocked`).

Esta decisão não está tomada aqui; ela precede a F2.

### X3 — `--bg` exige diretório confiável

`claude --bg` com cwd num diretório nunca aberto recusa: "Workspace not trusted". `-p` pula o diálogo de confiança. Em produção não muda nada (o kit é a raiz confiável e os alvos entram por `--add-dir`); a P5 foi lançada da raiz do kit com `--add-dir` para o sandbox, escrevendo só no caminho absoluto do sandbox (`git status` do kit inalterado antes/depois).

### X4 — o texto de resposta do modelo não é evidência

Em P2/P3 (sob X1) o `result` em prosa afirmou coisas falsas sobre o próprio efeito. Confirma a regra do kit: aceitação vem de arquivos, logs e campos estruturados (`structured_output`, `permission_denials`), nunca do texto da resposta.

### X5 — custo da juíza perto do limite

Com o modelo padrão, duas chamadas de juíza custaram ~US$ 0,45 com `--max-budget-usd 0,50`. Um estouro de orçamento precisa ser tratado pelo `judge.py` como `stop(judge_failed)`; `judge_max_calls = 4` implica até ~US$ 2 por execução no pior caso.

## Decisões aplicadas à spec

- **3.3 (juíza):** perfil `marina-judge` **sem** `tools` no frontmatter; restrição por `--tools Read` na invocação; ler `structured_output` (ausente → `stop(judge_failed)`); `--max-budget-usd` e `--no-session-persistence`; `stdin` fechado. Sessões da juíza não aparecem no manager.
- **3.5 (hooks):** mecanismo confirmado. `guard-write` compara o caminho absoluto de `tool_input.file_path` (ou `notebook_path`) com `targets ∪ {receipt}`, nunca com `CLAUDE_PROJECT_DIR`; o Stop hook usa `stop_hook_active`; `launch_claude` passa a fechar o stdin. A política de permissão (X2) fica como decisão pendente antes da F2.

## Riscos abertos

- X2 sem decisão: a F2 não deve começar antes dela.
- `NotebookEdit` não exercitado: `guard-write` trata `notebook_path` defensivamente e tem teste unitário próprio.
- Disparo de hooks de plugins junto com `--settings` não observado diretamente (só hooks de projeto).
- Comportamento verificado no CLI 2.1.306; o cabeçalho "Minimum tested Claude CLI version" dos módulos da F2/F4 deve citar essa versão.

## Adendo — decisão de permissão e sondas `dontAsk` (2026-10-25)

**Decisão do usuário:** especialistas em background usam `--permission-mode dontAsk`. A allowlist vira fronteira; comandos fora dela são negados e reportados no receipt. `AGENTS.md`, `docs/agent-workflow.md` e `launch_claude` são alinhados na F2.

Sondas complementares (Haiku, stdin fechado, sandbox `f1b-spike-XXXX` fora do kit; custo < US$ 0,05):

| Sonda | Configuração | Resultado |
|---|---|---|
| Q1 | `-p`, `dontAsk`, `--allowedTools "Bash(ls *)"` | `Read` funcionou sem estar listado; `Edit`, `Write` e `touch` via Bash negados e registrados em `permission_denials`; `ls` permitido. `Glob` e `Grep` não existem como ferramentas neste build |
| Q3 | `-p`, `dontAsk`, `Write(//<dir>/**)` | as duas escritas negadas: regra com caminho em `Write(...)` não vale |
| Q3b/Q3c | `-p`, `dontAsk`, `Edit(//<dir>/**)` e `Edit(<dir>/**)` | `Write` dentro de `<dir>` permitido, fora negado: regras `Edit(...)` com caminho cobrem o `Write` |
| Q2 | `--bg` da raiz do kit, `--add-dir <sandbox>`, `dontAsk`, `Edit(//<sandbox>/allowed/**)` e `Bash(ls *)` (sessão `abb1f8a4`) | escrita dentro de `allowed/` feita; escrita fora e `touch` sem efeito; `git status` do kit inalterado. Ao fim do turno o manager reporta `state: blocked`, `status: idle`, `waitingFor: None` — estado que `status_claude.classify_session` classifica como `unknown`, fazendo o `watch_claude` esperar até `--max-duration` |

**Consequências para a F2:**

- Com `dontAsk`, writers precisam de regras de escrita explícitas; a forma nativa é `Edit(//<alvo>/**)` por alvo mais `Edit(//<receipt>)`. Leitores recebem só a regra do receipt. Isso impõe nativamente a fronteira que o `guard-write` (spec 3.5) faria por hook.
- `status_claude` precisa reconhecer `blocked` + `idle` + sem `waitingFor` como fim de turno.
- O cenário de aceitação "comando fora da allowlist espera `attach`" deixa de existir; passa a ser "é negado, aparece no receipt".
