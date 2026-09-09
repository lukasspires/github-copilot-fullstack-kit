---
name: git-branch-commit-conventions
description: Criar e validar branches, changelog de tarefa e mensagens de commit em projetos governados pelo Códice da SES/SC, NADS ou DTIG. Use para trabalho cotidiano; encaminhe corte de versão, tags e promoção para codice-gitlab-release-flow.
---

# Branches, changelog e commits governados

## Uso e evidência

Aplicar somente com evidência de governança SES/SC, NADS ou DTIG. Requisitos explícitos da tarefa, instruções aplicáveis do projeto e contratos publicados orientam a execução. Documentos oficiais são opcionais por projeto: quando disponíveis, registrar fonte, versão/data e trecho aplicável; quando ausentes, continuar com a evidência local.

O resumo histórico vinculado abaixo tem atualidade **não verificada**. Seus identificadores permitem rastreabilidade, não comprovam conformidade oficial. Adotar uma convenção do resumo somente quando confirmada pelo projeto ou por fonte aplicável fornecida. Uma divergência material bloqueia apenas a decisão dependente, preservando o restante do trabalho e os contratos existentes.

## Execução proporcional

- Inspecionar raiz Git, branch, diff, arquivos preparados e convenções do alvo. Derivar a base da tarefa/projeto e das branches reais, por exemplo `developer`; nunca presumir `SPRINT`.
- Criação de branch e commit seguem a autorização correspondente. Pedido de sugestão de nome/mensagem não autoriza execução. Reutilizar autorização já fornecida; commit não implica push, MR, merge ou exclusão de branch.
- Preservar alterações concorrentes e selecionar arquivos do escopo. Não inventar identificador Redmine ou código de seção para satisfazer um template.
- Usar nomenclatura, mensagem e changelog confirmados no projeto. Atualizar `[Unreleased]` quando aplicável, preservando versões publicadas; ausência de changelog não exige criá-lo ou parar toda a tarefa com base no resumo.
- Se uma regra confirmada requer ação de Tech Lead, preparar a pendência/handoff; não enviar mensagem sem autorização.
- Executar checks descobertos e proporcionais, conferir conteúdo preparado e mensagem antes do commit autorizado; informar hash e resultados. Não publicar automaticamente.
- Para corte de versão, tags e ambientes, usar `codice-gitlab-release-flow` com autoridade operacional correspondente.

Ler [referência histórica](references/historical-summary.md) somente ao elaborar nomes, mensagens ou entradas para um projeto que confirme essas convenções.
