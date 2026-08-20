---
name: git-branch-commit-conventions
description: Criar e validar branches, changelog de tarefa e mensagens de commit em projetos governados pelo Códice da SES/SC, NADS ou DTIG. Use para trabalho cotidiano; encaminhe corte de versão, tags e promoção para codice-gitlab-release-flow.
---

# Branches e commits do Códice

Aplicar somente quando o repositório, a tarefa ou a documentação demonstrar governança SES/SC, NADS ou DTIG. Em projetos externos, seguir as convenções locais.

## Antes de alterar o repositório

- Inspecionar o estado, a branch atual, as alterações e as convenções locais do repositório.
- Identificar a branch `SPRINT` vigente sem adivinhá-la. Ao criar uma branch de tarefa, usar essa branch atualizada como base.
- Preservar alterações do usuário e não incluir arquivos fora do escopo solicitado.
- Uma solicitação explícita para criar uma branch ou efetuar um commit autoriza essa mutação Git, mas não autoriza publicar, fazer push, merge, rebase ou abrir merge request.
- Se faltar um dado obrigatório que não possa ser obtido do contexto, pedir somente esse dado. Não inventar número de tarefa, código da empresa/seção nem finalidade da mudança.

## Branches

Usar exatamente:

```text
<label>/<XXXX>-<tarefa>_<ação>_<artefato>_<local>
```

- `label`: `bugfix`, `feature`, `hotfix` ou `improvement`.
- `XXXX`: código da empresa ou seção responsável; normalmente `NADS`, mas confirmar ou derivar de evidência do projeto/tarefa.
- `tarefa`: número da tarefa, sem `#`.
- Os três segmentos finais descrevem, nesta ordem, a ação, o artefato alterado e o local da modificação.
- Normalizar os segmentos descritivos para minúsculas, sem acentos, espaços ou pontuação; separar palavras com `_`.
- Antes de criar, verificar se a branch já existe localmente ou no remoto. Não sobrescrever nem recriar uma branch existente.
- Criar e trocar para a branch somente quando o usuário pedir a criação; se ele pedir apenas um nome, retornar apenas a sugestão validada.
- Depois do merge, excluir a branch local ou remota somente quando o merge estiver comprovado e o usuário autorizar a exclusão.

Exemplo:

```text
feature/NADS-1234_adicionar_endpoint_usuarios_api
```

## Changelog da tarefa

Quando a codificação estiver concluída e a branch estiver pronta para MR:

- Atualizar somente `## [Unreleased]` no `CHANGELOG.md` da raiz, na própria branch da tarefa.
- Usar a categoria `Adicionado`, `Alterado`, `Corrigido`, `Removido` ou `Segurança` e a entrada `- Tarefa #<ID>: <descrição técnica concisa>`.
- Registrar separadamente mudanças de naturezas distintas e preservar entradas concorrentes ao resolver conflitos.
- Não alterar versões publicadas nem criar tags. Se o arquivo não existir, avisar o Líder Técnico e não inventar um template.
- Alterações triviais só podem omitir o registro quando a exceção estiver justificada e aprovada; hotfix crítico pode documentar depois, dentro do prazo institucional.

## Commits

Usar esta estrutura:

```text
<tipo>: <Descrição no infinitivo> (#<tarefa>)

1. <razão ou detalhe>
2. <razão ou detalhe>

#<tarefa>
```

O corpo numerado é opcional para mudanças simples. A referência da tarefa é obrigatória quando a alteração corresponde a uma atividade rastreada no Redmine.

Tipos permitidos:

- `feat`: nova funcionalidade.
- `fix`: correção de bug.
- `refactor`: refatoração sem mudança direta de lógica ou regra de negócio.
- `style`: estilo ou formatação sem impacto lógico.
- `doc`: documentação. Usar `docs` apenas se a validação já configurada no repositório exigir esse tipo.
- `env`: arquivo ou configuração de CI/CD.
- `build`: build ou dependências.
- `test`: adição ou modificação de testes.
- `chore`: manutenção sem impacto direto na lógica.

Regras de escrita:

- Começar o assunto com `<tipo>: ` e uma descrição clara, no infinitivo presente, com inicial maiúscula.
- Limitar o assunto a 50 caracteres sempre que a referência obrigatória permitir; nunca remover a tarefa apenas para caber no limite.
- Não terminar o assunto com pontuação.
- Separar assunto e corpo por uma linha em branco e limitar o corpo a 72 caracteres por linha.
- Explicar o que mudou e, quando útil, por quê; evitar mensagens vagas como “ajustes” ou “atualizações”.
- Revisar ortografia e manter a mensagem compreensível sem depender da leitura do código.

## Efetuar o commit

1. Conferir o diff e identificar arquivos já preparados. Não usar inclusão indiscriminada de arquivos quando o escopo não estiver claro.
2. Relacionar a mensagem somente ao conteúdo que realmente entrará no commit.
3. Rodar as verificações descobertas no repositório e proporcionais à mudança, ou informar claramente as que não puderam ser executadas.
4. Conferir o registro obrigatório em `[Unreleased]` quando a tarefa estiver concluída.
5. Mostrar a mensagem final e efetuar o commit quando isso tiver sido solicitado. Se o usuário pedir apenas para escrever ou sugerir a mensagem, não executar `git commit`.
6. Depois do commit, informar o hash curto, o assunto e os checks executados. Não fazer push automaticamente.

Corte de versão, tags e promoção de ambientes pertencem a `codice-gitlab-release-flow`. Para o trabalho diário, NOTEC-2601181721552 e NOTEC-26032410441464 definem a atualização na branch da tarefa; NOTEC-2511121308520 permanece aplicável ao fechamento de release em `Developer`.

Fontes consultadas em 20/08/2026: ADR-2410141234520, ADR-2410141520520, ADR-2501060650520, NOTEC-2511121308520, NOTEC-2601181721552 e NOTEC-26032410441464.
