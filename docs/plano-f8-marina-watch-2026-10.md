# F8 — `marina watch`: TUI de acompanhamento da execução: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, código em `scripts/`/`tests/` é do papel `kit-tooling` (`AGENTS.md`); ver "Execução" no fim.

**Goal:** Um visor de terminal, só de leitura, que mostra para uma tarefa:
- as etapas planejadas da rodada;
- a etapa e o agente atuais, com a última ação;
- a percentagem, o tempo decorrido e a duração estimada;
- as entradas e saídas esperadas de cada etapa.

O `marina go` abre esse visor depois de disparar a run.

**Architecture:**
- `scripts/marina/progress.py` é puro: estado, envelope, templates, histórico e manager entram, e sai um `View`.
  - `render(view, width)` desenha as linhas.
  - `last_activity` lê o transcript da sessão, sem quebrar se ele faltar.
- `scripts/marina/watch.py` é o laço `curses`: relógio a cada 1 s, manager a cada `--manager-interval` s, teclas `q` e `s`. `--once`, ou a falta de TTY, imprime um retrato.
- `cli.py` ganha `watch`, e o `go` chama o watch depois do disparo (com `--no-watch` para não chamar).

**Tech Stack:** Python ≥ 3.11 stdlib (`curses`, `json`, `statistics`); Claude Code CLI 2.1.311.

**Spec:** [docs/plano-marina-perguntas-plano-e-tui-2026-10.md](plano-marina-perguntas-plano-e-tui-2026-10.md), seções 6 e 6.1.

## Spike (G0), feito em 2026-10-28 com CLI 2.1.311

- `claude agents --json --all` devolve `id, cwd, kind, name, pid, sessionId, startedAt, state, status`, além de `waitingFor` quando a sessão espera.
- O transcript de uma sessão em background existe em `~/.claude/projects/<slug do cwd>/<sessionId>.jsonl`. As linhas `type = "assistant"` trazem `message.content[].type = "tool_use"` com `name`/`input` e `timestamp`.
  - O formato **não é documentado**. A TUI o usa só para a "última ação" e degrada para "atividade indisponível".
- O histórico local tem 28 pares `launched` (by `launch-claude`) → `finished` (by `status`). São esses pares que alimentam a estimativa. Eventos gravados à mão (by `marina`) ficam de fora, porque carregam o atraso de quem registrou.

## Global Constraints

- Python ≥ 3.11, só stdlib, sem dependência nova.
- **Só leitura.** `progress.py` não escreve nada. O watch só escreve por `runner.request_stop`, na tecla `s`.
- **Testes isolados.** Os testes nunca chamam o CLI real, nunca abrem `curses` e nunca leem o `.agent-state/` ou o `~/.claude` reais.
- **Amostra mínima.** Estimativas usam p50/p80 por `(papel, tipo)` com pelo menos `MIN_SAMPLES = 5` amostras. Abaixo disso, mostra "sem base".
- **Percentagem.** É `concluídos/N_min` e `concluídos/N_max`. Os nós condicionais (correção e re-revisão) só entram em N_min quando são disparados (FAIL) ou preenchidos.
- **Sem precisão inventada.** Nenhuma percentagem dentro de um nó e nenhuma estimativa negativa. Um nó acima do p80 aparece como "acima do típico".

## Review Focus

1. Tarefa sem envelope, ou com envelope inválido: o watch mostra os nós existentes e o motivo, sem quebrar. Teste: `test_view_without_envelope`.
2. Transcript ausente, corrompido ou sem `tool_use`: devolve `None`. Teste: `test_last_activity_degrades`.
3. Manager indisponível: o `View` marca o manager como indisponível, e o `render` o mostra. Teste: `test_render_manager_unavailable`.
4. Terminal estreito (< 60 colunas): nenhuma linha passa da largura. Teste: `test_render_respects_width`.
5. Nó substituído (`substitui`): ocupa a vaga do nó original, sem contar duas vezes. Teste: `test_replacement_fills_the_original_slot`.

---

### Task 1: modelo de progresso

**Files:**
- Create: `scripts/marina/progress.py`
- Test: `tests/test_marina_progress.py`

**Interfaces:**
- Produces:
  - `Slot(stage: int, kind: str, role: str, type: str, conditional: bool, node: Assignment | None, active: bool)`, com `kind` sendo `writer`, `review`, `correction` ou `rereview`;
  - `expansion_slots(env) -> list[Slot]`;
  - `fill_slots(doc, env) -> tuple[list[Slot], list[Assignment]]`;
  - `counts(slots) -> tuple[int, int, int]`, que devolve `(feitos, n_min, n_max)`;
  - `Stats(n: int, p50: float, p80: float)`;
  - `duration_stats(docs) -> dict[tuple[str, str], Stats]`;
  - `node_window(a, now) -> tuple[datetime | None, datetime | None, float | None]`;
  - `estimate(slots, stats, now) -> Estimate`.

- [ ] Testes:
  - `test_expansion_each_stage_two_stages`;
  - `test_expansion_final`;
  - `test_expansion_without_corrections`;
  - `test_fill_and_counts_happy_path`;
  - `test_fail_activates_correction_slots`;
  - `test_replacement_fills_the_original_slot`;
  - `test_duration_stats_uses_observed_pairs_only`;
  - `test_stats_below_min_samples_absent`;
  - `test_estimate_remaining_and_over_typical`;
  - `test_estimate_without_base`.
- [ ] Implementar, depois rodar `python3 -m unittest tests.test_marina_progress` → OK.

### Task 2: entradas e saídas, atividade, `View` e `render`

**Files:** `scripts/marina/progress.py`, `tests/test_marina_progress.py`

**Interfaces:**
- Produces:
  - `stage_io(doc, env, slot, *, kit_root, task_dir) -> tuple[list[str], list[str]]`;
  - `last_activity(session_id, projects_root) -> tuple[str, datetime] | None`;
  - `build_view(state_path, *, kit_root, now, sessions, pid_alive, projects_root, history_docs) -> View`;
  - `render(view, width) -> list[str]`.
- **Origem das entradas e saídas:** com as seções opcionais `## Expected inputs`/`## Expected outputs` no template, elas são usadas tal como estão. Sem elas, as entradas são handoff, receipt do predecessor, Git gate e allowlist, e as saídas são as linhas de `Write scope`, o receipt, os checks e `git-after-NN.txt`.

- [ ] Testes:
  - `test_stage_io_from_template_sections`;
  - `test_stage_io_defaults`;
  - `test_last_activity_reads_last_tool_use`;
  - `test_last_activity_degrades`;
  - `test_view_without_envelope`;
  - `test_render_lists_slots_and_progress`;
  - `test_render_manager_unavailable`;
  - `test_render_respects_width`.
- [ ] Implementar, depois rodar → OK.

### Task 3: laço `curses`, CLI `watch`, `go` abrindo o visor

**Files:** `scripts/marina/watch.py`, `scripts/marina/cli.py`; Test: `tests/test_marina_watch.py`, `tests/test_marina_cli.py`

**Interfaces:**
- Produces:
  - `watch.run_watch(state_path, *, kit_root, once: bool, stdout, isatty, manager_interval: float, deps: WatchDeps) -> int`;
  - CLI `marina watch <p> <t> [--once] [--manager-interval 10]`;
  - `marina go … [--no-watch]`.

- [ ] Testes:
  - `test_once_prints_snapshot_and_writes_nothing` (o mtime de todos os arquivos da tarefa fica igual);
  - `test_no_tty_falls_back_to_once`;
  - `test_manager_unavailable_once`;
  - `test_cli_watch_once`;
  - `test_go_opens_watch` e `test_go_no_watch`;
  - `test_bin_wrapper_help` exige `watch`.
- [ ] Implementar, depois rodar `python3 -m unittest discover -s tests` → OK.

### Task 4: documentação

- [ ] README e `docs/agent-workflow.md`: comando `watch`, o que a tela mostra, de onde vem cada dado e os limites (transcript não documentado, "sem base").
- [ ] `python3 scripts/kit_lint.py` → todos PASS.

## Execução

Igual à F7: implementação na sessão principal via `superpowers:executing-plans` (fallback declarado no checkpoint da tarefa), e revisão independente em sessão visível no fim da série.
