---
name: codice-api-contracts
description: Implementar ou revisar contratos de APIs e Gateways governados pelo Códice da SES/SC, NADS ou DTIG, incluindo métodos HTTP, URIs, payloads, tags e health checks. Não aplicar a projetos externos nem alterar contratos legados incompatíveis sem aprovação explícita.
---

# Contratos de API do Códice

## Uso e evidência

Aplicar somente com evidência de governança SES/SC, NADS ou DTIG. Requisitos explícitos da tarefa, instruções aplicáveis do projeto e contratos publicados orientam a execução. Documentos oficiais são opcionais por projeto: quando disponíveis, registrar fonte, versão/data e trecho aplicável; quando ausentes, continuar com a evidência local.

O resumo histórico vinculado abaixo tem atualidade **não verificada**. Seus identificadores permitem rastreabilidade, não comprovam conformidade oficial. Adotar uma convenção do resumo somente quando confirmada pelo projeto ou por fonte aplicável fornecida. Uma divergência material bloqueia apenas a decisão dependente, preservando o restante do trabalho e os contratos existentes.

## Aplicação

- Identificar separadamente Front–BFF, BFF–Gateway e Gateway–API: método, URI, campos, envelope, mensagens, autenticação e status de cada fronteira. Não uniformizar contratos diferentes por conveniência.
- Validar filtros e campos obrigatórios conforme contrato real, inclusive a semântica de todos os filtros vazios. Não supor que vazio significa consulta irrestrita ou rejeição em toda API.
- `usuario` e `sistema`, quando existentes, são contexto da requisição, não prova de identidade ou autorização. Preservar a autenticação e as verificações de permissão reais.
- Preservar biblioteca de mensagens e health check existentes; mudanças incompatíveis exigem aprovação e estratégia para consumidores. Não criar `/healthz` por uma correção de negócio sem esse escopo.
- Testar comportamento alterado, erros, autorização e compatibilidade; atualizar OpenAPI e consumidores somente quando afetados. Sanitizar respostas e logs.

Consultar [referência histórica](references/historical-summary.md) somente ao avaliar uma convenção corporativa de HTTP, tags ou health check. Não aplicar seus valores como defaults universais.
