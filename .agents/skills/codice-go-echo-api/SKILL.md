---
name: codice-go-echo-api
description: Implementar APIs Go novas governadas pelo Códice da SES/SC, NADS ou DTIG com Echo, arquitetura em camadas e middleware corporativo. Não usar para ETLs, projetos externos ou migração silenciosa de APIs legadas.
---

# APIs Go governadas

## Uso e evidência

Aplicar somente com evidência de governança SES/SC, NADS ou DTIG. Requisitos explícitos da tarefa, instruções aplicáveis do projeto e contratos publicados orientam a execução. Documentos oficiais são opcionais por projeto: quando disponíveis, registrar fonte, versão/data e trecho aplicável; quando ausentes, continuar com a evidência local.

O resumo histórico vinculado abaixo tem atualidade **não verificada**. Seus identificadores permitem rastreabilidade, não comprovam conformidade oficial. Adotar uma convenção do resumo somente quando confirmada pelo projeto ou por fonte aplicável fornecida. Uma divergência material bloqueia apenas a decisão dependente, preservando o restante do trabalho e os contratos existentes.

## Aplicação

- Identificar API Go e confirmar framework, versão e layout em manifests e implementações exemplares; não aplicar a ETLs ou CLIs.
- Preservar framework existente. Em API nova, usar o padrão confirmado pelo projeto; se a escolha não tiver evidência e for material, encaminhar ao `architect`. Não impor Echo ou uma versão com base no resumo.
- Manter handlers focados, contexto/cancelamento no I/O, dependências testáveis e recursos fechados. Reutilizar middleware existente; configurar CORS apenas quando necessário, respeitando origens e credenciais dos consumidores reais.
- Usar `codice-api-contracts` quando a tarefa afetar contratos governados. Testar as camadas afetadas e executar formatação/checks descobertos no alvo, sem reorganizar pastas não relacionadas.

Ler [referência histórica](references/historical-summary.md) somente se a tarefa precisar comparar a arquitetura/middleware com o modelo corporativo anterior.
