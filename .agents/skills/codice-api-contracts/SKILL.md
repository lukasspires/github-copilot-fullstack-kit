---
name: codice-api-contracts
description: Implementar ou revisar contratos de APIs e Gateways governados pelo Códice da SES/SC, NADS ou DTIG, incluindo métodos HTTP, URIs, payloads, tags e health checks. Não aplicar a projetos externos nem alterar contratos legados incompatíveis sem aprovação explícita.
---

# Contratos de API do Códice

## Aplicabilidade

- Aplicar somente quando o repositório, a tarefa ou a documentação demonstrar governança SES/SC, NADS ou DTIG.
- Se essa vinculação não estiver comprovada, seguir as convenções do próprio repositório e não impor este padrão.
- Preservar contratos publicados. Uma adaptação incompatível exige estratégia de versão, migração de consumidores e aprovação explícita.

## Endpoints de negócio

- Usar exclusivamente `POST`, com os parâmetros no corpo em JSON.
- Escrever URIs em minúsculas e kebab-case; não usar `_`, camelCase nem palavras compostas sem separador.
- Preferir nomes intuitivos que expressem a ação ou o recurso específico.
- Exigir `usuario` e `sistema` em todos os corpos de requisição; validar no servidor e rejeitar valores ausentes, vazios ou nulos.
- Em filtros com múltiplos parâmetros, não processar quando todos estiverem ausentes e nunca retornar o conjunto completo como fallback.

## Respostas

- Para APIs, incluir `tag` com `mensagem`, `tipo` e `detalhes`. Para Gateways, manter a coleção de mensagens prevista pelo contrato existente.
- Usar somente os tipos `AVISO`, `ERRO`, `INFORMAÇÃO` e `CONFIRMAÇÃO` e reutilizar os gabaritos aprovados. Um novo gabarito exige aprovação da Arquitetura e ADR.
- Retornar `200 OK` para respostas de negócio e `500 Internal Server Error` somente para falhas internas inesperadas que interrompam o processamento.
- Nunca expor stack traces, credenciais, consultas, tokens ou detalhes internos. Quando o Códice pedir contexto técnico, fornecer apenas informação sanitizada e manter o diagnóstico completo em logs protegidos.
- Se o projeto já usa a biblioteca corporativa de tags, reutilizá-la. Não adicionar ou trocar dependências sem necessidade comprovada.

## Exceção obrigatória: health check

`/healthz` substitui as regras gerais de método, autenticação e status:

- Expor `GET /healthz`, sem autenticação, query ou corpo, e impedir cache.
- Executar verificações leves e rápidas do processo e das dependências realmente críticas.
- Retornar `200` com `status: healthy` quando tudo estiver operacional e `503` com `status: unhealthy` quando uma dependência crítica falhar.
- Incluir timestamp e `dependencies`, mesmo quando a lista estiver vazia. Informar a dependência com falha sem revelar dados sensíveis.
- Testar sucesso, falha de cada dependência crítica, resposta sem cache e ausência de autenticação.

## Verificação

- Atualizar contrato OpenAPI e consumidores afetados.
- Cobrir campos obrigatórios, filtro vazio, mensagens por tipo, `200/500` de negócio e a exceção `200/503` do health check.
- Tratar segurança e compatibilidade como limites superiores: este padrão não autoriza vazamento de internos nem quebra silenciosa de clientes.

Fontes consultadas em 20/08/2026: ADR-2411221420520, ADR-2411250747520, ADR-2501130955520, ADR-2502280633520, ADR-2505200718520, ADR-2505201216520, ADR-2506231135520, ADR-2511041103520 e NOTEC-26042713212229. O Códice continua sendo a fonte oficial para revisões futuras.
