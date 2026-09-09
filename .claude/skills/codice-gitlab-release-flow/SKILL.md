---
name: codice-gitlab-release-flow
description: Planejar, validar ou executar releases GitLab de projetos governados pelo Códice, com MRs, changelog, tags, branches de release e promoção por ambientes. Não usar para commits cotidianos nem executar push, merge, tag ou deploy sem autorização e aprovações do papel responsável.
---

# Planejamento e execução de releases governadas

## Uso e evidência

Aplicar somente com evidência de governança SES/SC, NADS ou DTIG. Requisitos explícitos da tarefa, instruções aplicáveis do projeto e contratos publicados orientam a execução. Documentos oficiais são opcionais por projeto: quando disponíveis, registrar fonte, versão/data e trecho aplicável; quando ausentes, continuar com a evidência local.

O resumo histórico vinculado abaixo tem atualidade **não verificada**. Seus identificadores permitem rastreabilidade, não comprovam conformidade oficial. Adotar uma convenção do resumo somente quando confirmada pelo projeto ou por fonte aplicável fornecida. Uma divergência material bloqueia apenas a decisão dependente, preservando o restante do trabalho e os contratos existentes.

## Autoridade e preparação

- Confirmar repositório, versão, ambiente-alvo, pipeline e fluxo adotado. Identificar branches/tags/changelog reais; não impor SPRINT, Developer ou numeração histórica.
- Preparar e validar planos em leitura. Push, MR, merge, tag, deploy e exclusões exigem autorização correspondente e aprovações aplicáveis do Engineer/Tech Lead; reutilizar autorizações já dadas e não assumir esse papel.
- Não enviar mensagens ou abrir MRs por inferência; preparar handoff ao responsável quando faltar autoridade.
- Derivar próxima versão e branch do esquema confirmado e tags existentes. No exemplo histórico, a tag `vX.Y.Z` corresponde à branch `release-vX.Y.Z` (não `release-vvX.Y.Z`).
- Preservar tags publicadas e histórico. Confirmar gates, versão do artefato e evidências de ambiente antes de promover; falha no gate aplicável interrompe a promoção dependente.
- Planejar retorno de correções/hotfix às branches afetadas e recuperação conforme o projeto. Não deletar branches sem escopo autorizado e merge comprovado.
- Entregar estado inicial/final observado, aprovações, commits/tags, checks/pipeline, riscos e próximo responsável. Nunca declarar promoção não verificada.

Ler [referência histórica](references/historical-summary.md) somente para comparar o fluxo corporativo anterior com evidência atual do projeto.
