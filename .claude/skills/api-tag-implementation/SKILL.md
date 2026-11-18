---
name: api-tag-implementation
description: Use when implementing or reviewing TAG business responses in Java/Spring APIs, versioned controllers, TagFactory, RespostaComTag or TagExceptionHandler, with component integration by copy or subtree. Not for Git tags or UI labels.
---

# Implementação de TAG em APIs

Implementar o contrato TAG confirmado no alvo, preservando as operações atuais. Usar com [java-rest-api](../java-rest-api/SKILL.md); consultar [codice-api-contracts](../codice-api-contracts/SKILL.md) somente com evidência de governança aplicável. Esta skill não define uma norma corporativa nem depende do histórico local que a originou.

## Preparar a implementação

1. Identificar instruções, ticket, guia, componente e consumidores acessíveis. Registrar **decisão, fonte/data, revisão, escopo e regra substituída**. Uma decisão posterior substitui somente o que declara; distinguir proposta, autorização, implementação relatada e resultado verificado. Um conflito material suspende apenas a decisão dependente.
2. Construir uma matriz por operação: rota/método atual → novo; request; campos JSON reais; desfechos/status → tipo/gabarito/corpo TAG; autorização; service e eventos; fonte e teste. Comparar inventário com código, versões ativas e operações omitidas. Ampliar o inventário somente quando autorizado.
3. Fixar o modo de integração e a revisão. Ler [cópia/adaptação](references/copied-component.md) ou [subtree](references/subtree-component.md), conforme a evidência do alvo. Não transportar o modo de outro projeto.
4. Antes dos controllers, ler [contratos e validação](references/tag-contracts.md). Converter os endpoints novos conforme a matriz; preservar status e corpo dos atuais. Preservação do legado não significa devolver seu HTTP/corpo sem TAG nas rotas novas.

## Implementar e conferir

- Usar a factory, catálogo e DTOs confirmados. Não inventar gabaritos, impor HTTP 200 a toda API ou aplicar um envelope de Gateway à API.
- Comparar JSON serializado, incluindo booleanos, nulos, coleções, datas e nomes. Alias de entrada e política para duas grafias juntas são decisões de contrato; não adicionar rejeição, renomear saída ou impor “última chave vence” por conveniência.
- Restringir o handler aos controllers TAG, com entidade válida no componente. Cobrir erros anteriores ao método, sem ecoar valores recebidos. Ordenação de advice não substitui restrição de escopo.
- Preservar autorização, chamadas de service e efeitos de escrita. Quando integrar componente compartilhado, provar tanto o registro dos beans quanto a emissão dos eventos.
- Testar a matriz e a regressão do legado com os comandos descobertos. Separar compilação, testes automatizados e observação em runtime; `verify` com zero testes prova apenas o build. Respeitar decisões explícitas do alvo sobre versionamento de testes e reportar a lacuna comportamental.
- Entregar inventário coberto, desvios com fonte, checks/resultados, riscos e próximo responsável. Atualizar documentação/OpenAPI afetados. Encaminhar decisões materiais de arquitetura ao architect e revisão de contrato público ao reviewer pelo procedimento do kit; a skill não cria sessões nem concede autorização operacional.

## Erros recorrentes

Copiar uma regra histórica sem seu escopo; usar contagem fixa de rotas como prova de completude; editar subtree para resolver integração; transformar filtro vazio, chave ausente e lista vazia no mesmo resultado; declarar paridade só porque o service é o mesmo; declarar testes verdes quando nenhum executou.
