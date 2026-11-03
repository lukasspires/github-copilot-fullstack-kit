# F9 — Skills `marina-intake` e `marina-plan`: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste kit**, skills e documentação são da Marina; código em `scripts/`/`tests/` é do papel `kit-tooling` (`AGENTS.md`).

**Goal:** Fazer a Marina abrir toda tarefa nova com a rodada de perguntas e montar o plano e o envelope a partir do brief confirmado.

**Architecture:**
- **Skills do kit:** adaptadas do brainstorming e do writing-plans do Superpowers 7.0.0, sem dependência do plugin em tempo de execução.
  - `.claude/skills/marina-intake/` traz a skill e o template `brief-template.md`.
  - `.claude/skills/marina-plan/` traz a skill e o template `plan-template.md`.
- **Pontos de carga:** `task-execution` e o perfil `marina.md` apontam para as duas skills.
- **Handoffs:** `handoff_gen` passa as seções `Contracts`, `Expected inputs` e `Expected outputs` do template para o `Context` do handoff gerado.

**Spec:** [docs/plano-marina-perguntas-plano-e-tui-2026-10.md](plano-marina-perguntas-plano-e-tui-2026-10.md), seções 2, 2.1, 2.2 e 4.

## Global Constraints

- **Skills em inglês**, como as demais do kit. A conversa com o usuário segue o idioma dele.
- **Sem conflito de regras.** As skills não mudam nenhuma regra do `AGENTS.md`: commits só com autorização, sessões visíveis, writers sequenciais, nenhuma ferramenta aprova envelope.
- **Gate do brief.** Nada é reservado, entregue em handoff, rascunhado ou lançado antes de o usuário confirmar o brief (ou pular as perguntas).

## Review Focus

1. **Seções descartadas.** Um template com seções que o `handoff_gen` não conhece perderia contratos no handoff. Teste: `test_stage_and_correction_handoffs_carry_contracts_and_expected_io`.
2. **Compatibilidade.** Um template sem as seções novas produz o handoff de antes. Teste: `test_stage_handoff_without_extra_sections_is_unchanged`.
3. **Retomadas e tarefas limitadas.** Elas não podem ser forçadas a passar pela rodada de perguntas; o `task-execution` diz isso.

### Task 1: skills e templates (Marina)

- [x] `marina-intake/SKILL.md` e `templates/brief-template.md`.
- [x] `marina-plan/SKILL.md` e `templates/plan-template.md`.
- [x] `task-execution`, `marina.md` e README apontam para elas. O runtime as descobriu na sessão (listagem de skills após a criação).

### Task 2: seções de contexto no handoff (kit-tooling)

- [x] Testes em `tests/test_marina_handoff_gen.py` falham primeiro e depois passam.
- [x] `TEMPLATE_CONTEXT` e `_with_template_context` em `scripts/marina/handoff_gen.py`, usados nos handoffs de estágio e de correção.
- [x] `python3 -m unittest discover -s tests` → OK; `python3 scripts/kit_lint.py` → todos PASS.

## Execução

Igual à F7 e à F8: na sessão principal, com o fallback declarado no checkpoint da tarefa, e revisão independente em sessão visível no fim da série.
