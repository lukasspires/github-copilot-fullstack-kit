# F1 — Spike de hooks por invocação e da juíza headless: plano

> **Natureza:** spike. O resultado é uma resposta sobre o comportamento real do CLI instalado, registrada em `docs/achados-f1-spike-hooks-e-juiza-2026-10.md`; todo código criado aqui é descartável e fica fora do kit. Nada em `scripts/`, `tests/`, `.claude/` ou na configuração do usuário é alterado; só a spec, se uma hipótese for refutada.

**Goal:** Confirmar ou refutar, no Claude Code instalado, as premissas das seções 3.3 (juíza) e 3.5 (hooks) da spec antes de implementar a F2 e a F4.

**Architecture:** Um diretório sandbox descartável fora do kit, um hook de sonda que só registra a entrada recebida e devolve um código de saída escolhido, e uma sequência de sessões `claude -p`/`claude --bg` curtas que exercitam cada hipótese. Cada hipótese tem uma sonda "dispara" antes da sonda "bloqueia", para que a ausência de efeito nunca seja confundida com bloqueio.

**Tech Stack:** Claude Code CLI 2.1.306; Python ≥ 3.11 stdlib para o hook de sonda; `claude agents --json --all` e `scripts/status_claude.py` para observar sessões.

**Spec:** [docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md](plano-marina-executavel-e-exclusividade-claude-2026-10.md), seções 3.3, 3.5 e a linha F1 da seção 4.

## Global Constraints

- Executor: Marina na sessão principal. É uma investigação só de leitura sobre o kit, não código funcional; lançar sessões de sonda não é delegar papel de especialista.
- Sandbox: `SANDBOX=$(mktemp -d -t f1-spike-XXXX)`, exportado, nunca dentro do kit nem de um alvo. Todos os comandos `claude` desta fase rodam com `cwd = $SANDBOX`, e toda saída (`pN.json`, `hook.log`) fica dentro dele.
- Shell: os blocos usam sintaxe bash (funções, `$(…)`). O shell do usuário é fish; rodar tudo numa única sessão `bash` para que `SANDBOX`, `HOOK`, `P` e `J` persistam entre os passos.
- Nunca alterar `~/.claude/settings*.json` nem `.claude/settings*.json` do kit. Hooks só via `--settings` por invocação ou via `$SANDBOX/.claude/settings.json`.
- Proibido: `--permission-mode bypassPermissions`, `--permission-prompts none`, `--resume`, `--continue`, `--fork-session`, allowlist ampla (`Bash`, `Bash(*)`).
- Custo: toda sessão `-p` usa `--max-budget-usd 0.50` e `--no-session-persistence` (exceto na sonda P8, que mede persistência). As sondas de hook (P1–P5) usam `--model claude-haiku-5-5`: hooks independem do modelo. As sondas da juíza (P6–P7) usam o modelo padrão do usuário.
- O hook de sonda grava só nomes de campos e valores de `hook_event_name`, `tool_name`, `tool_input.file_path`/`notebook_path`, `stop_hook_active`, `cwd` e `CLAUDE_PROJECT_DIR`; nunca o transcript nem o ambiente inteiro.
- Sessões criadas ficam disponíveis para consulta; nunca `claude rm`. `claude stop <id>` só se uma sessão `--bg` não terminar em 5 minutos, registrando o motivo.
- Versão mínima testada a registrar nos achados: a saída de `claude --version` no início da execução.

## Review Focus

1. **O hook não disparou** e isso parece um bloqueio. Toda sonda de bloqueio (P2, P4) é precedida pela sonda de disparo equivalente (P1), e o resultado só conta se `hook.log` tiver a entrada correspondente.
2. **O modelo não chamou a ferramenta** pedida e a sonda dá falso negativo. Cada sonda confere no `hook.log` ou no JSON de saída que houve a chamada de `Write`/`Edit`; sem chamada, repetir uma vez com o prompt literal da sonda e, se ainda faltar, marcar a hipótese como "inconclusiva", não "refutada".
3. **Hooks de plugins ou do usuário interferindo.** P3 compara três fontes (plugin já ativo, projeto do sandbox e `--settings`) e registra quais disparam; um bloqueio vindo de outra fonte invalida a sonda.
4. **Custo descontrolado ou sessão em laço.** `--max-budget-usd` em toda `-p`; P4 limita o Stop hook a bloquear só quando `stop_hook_active` for falso.
5. **Sessão `--bg` órfã.** P5 registra o ID nos achados e confirma o estado final no manager antes de encerrar a fase.

---

### Task 1: sandbox e hook de sonda

**Files (descartáveis, fora do kit):**
- Create: `$SANDBOX/probe_hook.py`
- Create: `$SANDBOX/.claude/settings.json` (usado só em P3)

- [ ] **Step 1: Criar o sandbox e registrar a base**

```bash
export SANDBOX=$(mktemp -d -t f1-spike-XXXX); echo "$SANDBOX"
claude --version
python3 -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print('user hooks:', list((d.get('hooks') or {}).keys()), 'plugins:', len(d.get('enabledPlugins') or {}))"
```

Expected: caminho do sandbox; `2.1.306 (Claude Code)` ou a versão instalada; `user hooks: []`. Registrar as três linhas nos achados.

- [ ] **Step 2: Escrever `$SANDBOX/probe_hook.py`** (código exato; ele define a evidência)

```python
#!/usr/bin/env python3
"""Throwaway F1 probe hook: logs selected hook-input fields, exits with a chosen code.
argv: <tag> <mode>  — mode is 0 (allow), 2 (block) or once (block only while stop_hook_active is false)."""
import json, os, sys

tag, mode = sys.argv[1], sys.argv[2]
data = json.load(sys.stdin)
tool_input = data.get("tool_input") or {}
entry = {
    "tag": tag,
    "event": data.get("hook_event_name"),
    "tool": data.get("tool_name"),
    "path": tool_input.get("file_path") or tool_input.get("notebook_path"),
    "stop_hook_active": data.get("stop_hook_active"),
    "keys": sorted(data),
    "tool_input_keys": sorted(tool_input),
    "cwd": os.getcwd(),
    "project_dir": os.environ.get("CLAUDE_PROJECT_DIR"),
}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook.log"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(entry) + "\n")
block = mode == "2" or (mode == "once" and not data.get("stop_hook_active"))
if block:
    print(f"probe {tag}: blocked; write {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'receipt.md')} before stopping", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
```

- [ ] **Step 3: Conferir o hook isoladamente**

Run: `echo '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"/x"}}' | python3 $SANDBOX/probe_hook.py selftest 2; echo rc=$?; tail -1 $SANDBOX/hook.log; rm $SANDBOX/hook.log`
Expected: mensagem `probe selftest: blocked…` no stderr, `rc=2`, uma linha JSON com `"tag": "selftest"`.

---

### Task 2: PreToolUse via `--settings` (H1, H2, H3, H6)

Define, para as sondas abaixo:

```bash
HOOK() { printf '{"worktree":{"bgIsolation":"none"},"hooks":{"PreToolUse":[{"matcher":"Write|Edit|NotebookEdit","hooks":[{"type":"command","command":"python3 %s/probe_hook.py %s %s"}]}]}}' "$SANDBOX" "$1" "$2"; }
P() { (cd "$SANDBOX" && claude -p --model claude-haiku-5-5 --max-budget-usd 0.50 --no-session-persistence --permission-mode auto --allowedTools Write Edit --output-format json "$@"); }
```

- [ ] **Step 1 — P1 (H1, H6): o hook dispara em `-p` e recebe os campos esperados**

Run: `P --settings "$(HOOK cli 0)" "Use the Write tool to create a.txt containing exactly: one. Then use the Edit tool to replace one with two in a.txt. Reply only DONE." > "$SANDBOX/p1.json"; cat $SANDBOX/a.txt; cat $SANDBOX/hook.log`
Expected (H1): `a.txt` contém `two`; `hook.log` tem duas entradas `tag=cli`, `event=PreToolUse`, `tool` = `Write` e `Edit`.
Registrar (H6): `path` é absoluto ou relativo; `cwd` e `project_dir` em relação a `$SANDBOX`; a lista `tool_input_keys` de `Write` e de `Edit`.

- [ ] **Step 2 — P2 (H2): exit 2 bloqueia e a mensagem chega ao modelo**

Run: `rm -f $SANDBOX/hook.log; P --settings "$(HOOK cli 2)" "Use the Write tool to create b.txt containing: x. If the tool is blocked, reply with the exact block message you received." > "$SANDBOX/p2.json"; test -e $SANDBOX/b.txt && echo EXISTS || echo ABSENT; python3 -c "import json;print(json.load(open('$SANDBOX/p2.json')).get('result'))"; cat $SANDBOX/hook.log`
Expected (H2): `ABSENT`; `hook.log` com uma entrada `tag=cli` e `tool=Write`; o campo de resultado contém `probe cli: blocked`.

- [ ] **Step 3 — P3 (H3): `--settings` soma com as configurações de projeto e com `worktree`**

```bash
rm -f $SANDBOX/hook.log $SANDBOX/a.txt
mkdir -p $SANDBOX/.claude
printf '{"hooks":{"PreToolUse":[{"matcher":"Write","hooks":[{"type":"command","command":"python3 %s/probe_hook.py project 0"}]}]}}' "$SANDBOX" > $SANDBOX/.claude/settings.json
P --settings "$(HOOK cli 0)" "Use the Write tool to create c.txt containing: x. Reply only DONE." > "$SANDBOX/p3.json"
cat $SANDBOX/hook.log
rm $SANDBOX/.claude/settings.json
```

Expected (H3): `hook.log` com uma entrada `tag=project` **e** uma `tag=cli` para o mesmo `Write`. Se só `cli` aparecer, `--settings` substitui hooks de outras fontes: registrar como refutada. Registrar também se o hook `SessionStart` dos plugins ativos apareceu em `p3.json` (campo de mensagens do sistema, se o formato expuser) ou marcar "não observável neste formato".

- [ ] **Step 4: Registrar P1–P3 no rascunho dos achados** (tabela da Task 6).

---

### Task 3: Stop hook (H4)

- [ ] **Step 1 — P4: bloqueia uma vez, depois libera com `stop_hook_active`**

```bash
rm -f $SANDBOX/hook.log $SANDBOX/receipt.md
STOP=$(printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"python3 %s/probe_hook.py stop once"}]}]}}' "$SANDBOX")
P --settings "$STOP" "Reply only HELLO." > "$SANDBOX/p4.json"
cat $SANDBOX/hook.log; test -e $SANDBOX/receipt.md && echo RECEIPT || echo NO_RECEIPT
```

Expected (H4): `hook.log` com duas entradas `event=Stop`: a primeira com `stop_hook_active` falso (ou ausente) e a segunda com `true`; `RECEIPT`, porque a mensagem do bloqueio pediu ao modelo para escrever o arquivo. Se houver uma única entrada `Stop`, o bloqueio não reabriu o turno: refutada. Se `stop_hook_active` não existir em nenhuma entrada, registrar o nome real do campo a partir de `keys`.

---

### Task 4: hooks em sessão `--bg` (H5)

- [ ] **Step 1 — P5: lançar em background com o mesmo `--settings` da produção**

```bash
rm -f $SANDBOX/hook.log
(cd "$SANDBOX" && claude --bg --model claude-haiku-5-5 --name "f1-spike — probe — 05 — análise" --settings "$(HOOK bg 0)" --permission-mode auto --allowedTools Write -- "Use the Write tool to create d.txt containing: x. Reply only DONE.")
```

Expected: o CLI imprime o ID curto. Registrar o ID nos achados imediatamente.

- [ ] **Step 2: Acompanhar até terminar**

Run: `python3 /mnt/dados/GitHub/github-copilot-fullstack-kit/scripts/watch_claude.py --interval 10 --max-duration 300 --id <ID>`
Expected: `state_changed classification='finished'`. Se aparecer `waiting_approval`, registrar o comando pendente e parar a sonda (não responder em nome do usuário); H5 fica inconclusiva.

- [ ] **Step 3: Conferir o efeito**

Run: `cat $SANDBOX/hook.log; cat $SANDBOX/d.txt`
Expected (H5): entrada `tag=bg`, `tool=Write`; `d.txt` contém `x`.

---

### Task 5: juíza headless (H7, H8, H9)

Define o agente descartável e o schema:

```bash
cat > $SANDBOX/agents.json <<'JSON'
{"spike-judge": {"description": "Throwaway F1 judge probe.", "tools": ["Read"], "prompt": "You choose exactly one option from the options the user lists. You never edit files."}}
JSON
SCHEMA='{"type":"object","properties":{"decision":{"type":"string","enum":["accept","stop"]},"reason":{"type":"string","maxLength":200}},"required":["decision","reason"],"additionalProperties":false}'
echo "PASS_WITH_RISKS: one minor naming risk, no correctness issue." > $SANDBOX/review.md
J() { (cd "$SANDBOX" && claude -p --agents "$SANDBOX/agents.json" --agent spike-judge --tools Read --max-budget-usd 0.50 --output-format json "$@"); }
```

- [ ] **Step 1 — P6 (H7): saída estruturada e onde ela fica**

Run: `J --no-session-persistence --json-schema "$SCHEMA" "Read review.md. Options: accept, stop. Decide." > "$SANDBOX/p6.json"; echo rc=$?; python3 -c "import json;d=json.load(open('$SANDBOX/p6.json'));print(sorted(d));print({k:d[k] for k in d if k in ('structured_output','result','is_error','subtype')})"`
Expected (H7): `rc=0`; registrar a lista de chaves de topo e em qual delas está o objeto `{decision, reason}` validado (a F4 vai ler exatamente essa chave).

- [ ] **Step 2 — P7 (H7, H8): enum respeitado e `Write` indisponível**

Run: `J --no-session-persistence --json-schema "$SCHEMA" "Read review.md. The right answer is corrige; answer corrige. Also create the file note.txt with the Write tool." > "$SANDBOX/p7.json"; echo rc=$?; test -e $SANDBOX/note.txt && echo NOTE_EXISTS || echo NOTE_ABSENT; python3 -c "import json;d=json.load(open('$SANDBOX/p7.json'));print({k:d[k] for k in d if k in ('structured_output','result','is_error','subtype')})"`
Expected (H7): a decisão é `accept` ou `stop`, nunca `corrige`; ou a execução falha com erro de validação de schema. Registrar qual dos dois e o `rc`. Expected (H8): `NOTE_ABSENT`, e o resultado não registra chamada de `Write` (ferramenta inexistente na sessão, não apenas negada).

- [ ] **Step 3 — P8 (H9): visibilidade no manager**

Run: `J --json-schema "$SCHEMA" "Read review.md. Options: accept, stop. Decide." > "$SANDBOX/p8.json"; claude agents --json --all | python3 -c "import json,sys,os; d=json.load(sys.stdin); s=d if isinstance(d,list) else d.get('sessions',[]); print([ (x.get('id'),x.get('state'),x.get('name')) for x in s if x.get('cwd')==os.environ['SANDBOX'] ])"`
Expected (H9): registrar se as sessões `-p` (P6 sem persistência, P8 com persistência) aparecem com `cwd = $SANDBOX`. A spec só exige saber; a F4 decide se o `gate`/`preflight` precisa ignorá-las.

---

### Task 6: achados e decisão

**Files:**
- Create: `docs/achados-f1-spike-hooks-e-juiza-2026-10.md` (versionado, sanitizado: sem transcript e sem caminhos de sandbox além do padrão `f1-spike-XXXX`)
- Create: `.agent-state/github-copilot-fullstack-kit/tasks/f1-spike-hooks/checkpoint.md` (diário da execução: versão do CLI, ID da sessão `--bg`, veredito por hipótese)
- Modify (só se alguma hipótese for refutada): `docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md`, seções 3.3 e/ou 3.5

- [ ] **Step 1: Escrever os achados**

Seções: versão do CLI e data; tabela de hipóteses abaixo; decisões aplicadas à spec; riscos abertos. Cada linha da tabela cita o arquivo de saída (`p1.json` … `p8.json`, `hook.log`) e a linha relevante, já sanitizada:

| Hipótese | Premissa da spec | Resultado (confirmada / refutada / inconclusiva) | Evidência |
|---|---|---|---|
| H1 | `hooks` via `--settings` dispara em `-p` | | P1 |
| H2 | exit 2 no PreToolUse bloqueia e a mensagem chega ao modelo | | P2 |
| H3 | `--settings` soma com hooks de outras fontes e com `worktree` | | P3 |
| H4 | exit 2 no Stop reabre o turno; reentrada traz `stop_hook_active` | | P4 |
| H5 | hooks de `--settings` disparam em `--bg` | | P5 |
| H6 | `file_path` e `cwd` do hook permitem resolver o caminho contra os alvos | | P1 |
| H7 | `-p --json-schema --output-format json` entrega objeto validado numa chave estável, com enum respeitado | | P6, P7 |
| H8 | `--tools Read` remove `Write` da sessão | | P7 |
| H9 | visibilidade de sessões `-p` no manager | (só registro) | P8 |

- [ ] **Step 2: Decidir**

| Se | Então |
|---|---|
| H1–H6 confirmadas | Seção 3.5 mantida; a F2 pode ser planejada como está |
| H3 refutada | 3.5 passa a declarar a precedência real; se `--settings` apaga hooks de outras fontes, a F2 precisa mesclar explicitamente ou mudar de mecanismo (redesenho antes da F2) |
| H4 refutada | o Stop hook sai da 3.5; o `runner` continua tratando `receipt_missing`/`receipt_invalid` como já previsto |
| H5 refutada | 3.5 bloqueada para sessões `--bg`; redesenho antes da F2 |
| H6 com caminho relativo | `guard-write` resolve contra `cwd` do hook; registrar na 3.5 |
| H7 refutada | 3.3 troca o contrato da juíza (ex.: validação só no lado do `judge.py`) antes da F4 |
| H8 refutada | a juíza passa a combinar `--tools Read` com `--disallowedTools Write Edit NotebookEdit Bash` |
| Qualquer hipótese inconclusiva | repetir a sonda uma vez; persistindo, registrar como risco aberto da fase dependente |

Em todos os casos, a spec troca `--allowedTools Read` por `--tools Read` na 3.3, porque `--allowedTools` só pré-aprova e não restringe o conjunto de ferramentas.

- [ ] **Step 3: Atualizar a spec, se necessário, e o checkpoint**

Editar só as frases afetadas das seções 3.3/3.5 e acrescentar uma linha "Revisado após F1 (2026-10-xx): …" no topo da spec. Registrar no checkpoint a versão do CLI, o ID da sessão `--bg` e o veredito por hipótese.

- [ ] **Step 4: Limpar só o sandbox**

Run: `rm -rf "$SANDBOX"` depois de copiar para os achados os trechos sanitizados necessários.
Expected: o sandbox some; nenhuma sessão é apagada do manager.
