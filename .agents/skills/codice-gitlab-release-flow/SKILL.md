---
name: codice-gitlab-release-flow
description: Planejar, validar ou executar releases GitLab de projetos governados pelo Códice, com MRs, changelog, tags, branches de release e promoção por ambientes. Não usar para commits cotidianos nem executar push, merge, tag ou deploy sem autorização e aprovações do papel responsável.
---

# Fluxo de release GitLab do Códice

## Preconditions

- Confirmar a governança do Códice, o repositório, a versão, o ambiente-alvo e a autorização do executor.
- Inspecionar branches, tags, `CHANGELOG.md`, pipeline e evidências de aprovação antes de qualquer mutação.
- Planejamento e validação são somente leitura. Push, merge, tag e deploy só podem ocorrer quando solicitados e quando a aprovação exigida estiver comprovada.
- Não enviar comunicações, criar MRs ou promover ambientes por inferência.

## Fluxo obrigatório

1. O desenvolvedor cria a branch da tarefa a partir da `SPRINT` vigente, mantém `[Unreleased]` e abre MR para `Sprint`.
2. O Tech Lead revisa e aprova o MR; merge direto é proibido.
3. O Engenheiro integra `Sprint` em `Developer`.
4. Para QA, o Engenheiro consolida o changelog, cria a próxima tag `v0.0.Z`, cria `release-v0.0.Z` a partir da tag e promove para QA.
5. Após aprovação de QA, o Engenheiro cria a próxima versão estável `v0.Y.0`, cria `release-v0.Y.0` e promove para Stage.
6. Somente após aprovação em Stage a mesma versão estável pode seguir para Preprod ou Produção.
7. Hotfix nasce da release afetada, recebe nova tag e deve ser sincronizado com Produção e `Developer`.

## Invariantes

- Toda tag segue `vX.Y.Z`, é imutável e possui entrada correspondente no changelog.
- Toda branch de release segue `release-v<tag>`.
- Nunca pular QA ou Stage, reutilizar/mover tag, fazer merge direto em `Developer`/release ou publicar código sem tag.
- Correções feitas na release retornam a `Developer`; falha em um ambiente interrompe a promoção.
- Excluir branch de tarefa somente após confirmar merge bem-sucedido e obter autorização explícita para a exclusão local ou remota.

## Changelog e responsabilidades

- Durante a tarefa, o desenvolvedor atualiza `[Unreleased]` na branch de trabalho conforme NOTEC-2601181721552 e NOTEC-26032410441464.
- O corte da versão ocorre em `Developer` e é responsabilidade do Engenheiro/Escritório de Engenharia conforme NOTEC-2511121308520.
- Não alterar versões já publicadas. Calcular a próxima tag a partir das tags reais e abortar em divergência de changelog, configuração ou histórico.

## Handoff

Relatar estado inicial, aprovações observadas, commits/branches/tags envolvidos, checks e pipeline, ambiente alcançado, falhas e próximo responsável. Nunca declarar uma promoção que não tenha sido verificada.

Fontes consultadas em 20/08/2026: ADR-2501060650520, ADR-25020515521188, NOTEC-2506041249520, NOTEC-2506050906520, NOTEC-2506051351520, NOTEC-2511121308520, NOTEC-2601181721552, NOTEC-26032410441464 e NOTEC-26050508222229. O Códice continua sendo a fonte oficial para revisões futuras.
