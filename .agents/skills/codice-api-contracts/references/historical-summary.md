# Resumo histórico — atualidade não verificada

Este conteúdo resume o registro anterior do kit, que declarava consulta em **20/08/2026**. A data e os IDs foram preservados como proveniência histórica; os documentos não foram disponibilizados nem verificados nesta atualização. Não usar este resumo isoladamente para impor regras ou declarar conformidade.

### Convenções registradas anteriormente

O resumo anterior associava endpoints de negócio a POST com corpo JSON, URIs minúsculas em kebab-case e contexto `usuario`/`sistema`. Também descrevia rejeição de filtros todos ausentes. Confirmar cada regra no contrato do alvo antes de adotá-la.

Para APIs, registrava `tag` com `mensagem`, `tipo`, `detalhes`; para Gateways, uma coleção de mensagens prevista no contrato. Os tipos listados eram `AVISO`, `ERRO`, `INFORMAÇÃO`, `CONFIRMAÇÃO`, com gabaritos corporativos e aprovação arquitetural para novos gabaritos. Isso não autoriza converter envelopes ou grafias já publicados.

O registro descrevia `200` para resultados de negócio e `500` para falhas internas inesperadas. Para health check, descrevia `GET /healthz` sem autenticação, query ou corpo, sem cache, checks leves de dependências críticas, `200/503`, `status: healthy/unhealthy`, timestamp e `dependencies`. Confirmar o contrato e os controles do projeto; não substituir seus códigos HTTP nem remover autenticação com base neste resumo.

Identificadores registrados anteriormente: ADR-2411221420520, ADR-2411250747520, ADR-2501130955520, ADR-2502280633520, ADR-2505200718520, ADR-2505201216520, ADR-2506231135520, ADR-2511041103520 e NOTEC-26042713212229. O Códice continua sendo a fonte oficial para revisões futuras.
