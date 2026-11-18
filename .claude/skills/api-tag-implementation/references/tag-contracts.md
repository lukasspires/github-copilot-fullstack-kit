# Contratos e validação de TAG

Ler antes de alterar controllers, DTOs ou handlers. A fonte do mapeamento é o contrato confirmado do alvo. Identificadores RN/GAB e resumos históricos, isoladamente, não provam uma norma vigente.

## Matriz por operação

Registrar rota e método atual/novo, campos de entrada, JSON serializado de saída, desfechos, status atual, tipo/gabarito/corpo novo, autorização, service/eventos, fonte e check. O inventário deve explicar rotas ausentes e versões substituídas; uma contagem total pode esconder uma troca de rota.

| Situação | Decisão a fixar com evidência | Prova comportamental |
|---|---|---|
| Chave de registro ou id de pai ausente | Validação de chave; não confundir com filtro de lista | Ramo específico e ausência de chamada indevida ao service |
| Todos os filtros ausentes | Considerar os filtros realmente usados pelo service; distinguir null, vazio e espaços conforme contrato | Matriz de entradas; não criar recusa onde o atual permite consulta sem decisão |
| Lista vazia com sucesso versus exceção 404 | Desfechos distintos; aplicar a conversão TAG de cada um | Exercitar ambos, preservando a semântica e a coleção quando prevista |
| Save/update com objeto versus retorno void/null | Não fabricar objeto resultante; decidir resposta só com tag quando permitida | Campos reais e conteúdo dos detalhes; erro omite dados se assim contratado |
| Dois nomes de entrada | Alias é mudança aditiva que requer escopo; política de conflito deve ser confirmada | Cada nome isolado, ambos iguais/diferentes e nas duas ordens |
| Corpo ausente ou JSON inválido | Tratamento antes do método, entidade derivada do handler e mensagem estável | Requisição HTTP ao novo e ao antigo; resposta e logs sem valor sentinela |

**Exemplo condicionado:** nas decisões da #8527, 404 tornou-se ERRO GAB-06, 409 tornou-se GAB-11 e 412/422 tornou-se GAB-07 nos endpoints novos; lista vazia anteriormente bem-sucedida manteve coleção vazia com INFORMAÇÃO GAB-13. GAB-03 ficou reservado ao filtro integralmente ausente cuja recusa estava prevista, não à chave ausente. Esse exemplo orienta a comparação; não fornece defaults para outra API. Status fora da tabela, incluindo erros inesperados, exigem regra confirmada, sem inferir HTTP 200 ou 500 de uma referência genérica.

## Forma do JSON

Quando o contrato adotado exige corpo plano, usar campos no primeiro nível e `tag`, com coleção no nome confirmado, sem introduzir `data`/`resposta` por conveniência. Reutilizar o catálogo/factory confirmados e suas regras de objeto resultante e detalhes vazios.

Comparar saída Jackson real dos DTOs atual e novo: nomes, aninhados, datas, inclusão de nulos e `false`. Um campo `boolean isHabilitado` pode gerar tanto `isHabilitado` quanto `habilitado`; não remover uma chave como “limpeza”. Em corpos de erro só com tag, primitivos podem introduzir falsos valores padrão: conferir o JSON, usando tipos opcionais quando exigido.

Nomear DTOs pela linhagem existente, sem duplicar sufixo ou colidir com versão já publicada. A regra histórica “retorno atual + próxima versão” só se aplica quando confirmada. Alias de request não renomeia response nem documentação automaticamente. Preservar o comportamento atual de duas chaves até haver decisão específica; não inserir rejeição ou escolher precedência silenciosamente.

Separar Front–BFF, BFF–Gateway e Gateway–API: `detalhe`/`detalhes`, tag objeto/array e envelope são contratos independentes. Remover `resposta` pode quebrar consumidor que faz parse desse campo. Não migrar consumidores sem escopo e estratégia aprovados.

## Handler, dados e efeitos

Restringir o advice aos controllers novos; provar que os antigos conservam status e JSON. Conferir resolução de entidade, recurso reconhecido pela factory e exceções antes do método. Não adicionar `catch (Exception)` por padrão quando o contrato centraliza tratamento no handler.

Detalhes de validação identificam campo/motivo sem reproduzir valores. Evitar mensagem bruta de exceção e stack trace de parsing que ecoem payload. Confirmar política de objetos resultantes, dados pessoais e binários nos detalhes; decisões históricas de incluir base64 não se tornam prática geral, nem autorizam criar um sanitizador incompatível com o componente.

Preservar autorização real, CORS e efeitos transacionais. Para eventos, comparar tabela, operação e JSON com a operação atual, normalizando apenas campos comprovadamente variáveis; testar também que os beans necessários existem e que a escrita efetivamente gera o evento.

## Evidência de conclusão

Usar fixtures sintéticas e comparar o novo com o atual, não com uma cópia da implementação do próprio teste. Cobrir sucesso, erros, serialização, handler e eventos; verificar rotas e schemas gerados. MockMvc isolado, OpenAPI construído em teste e startup real são evidências diferentes.

Executar os comandos descobertos no alvo. Build sem testes não prova comportamento; registrar contagem e checks não executados. Se o alvo explicitamente não versiona testes, respeitar a decisão e propor verificação comportamental permitida, sem alegar cobertura nem recriar suíte automaticamente. Autorização, receipt do writer, revisão independente e observação do estado final permanecem evidências distintas.

## Procedência

Síntese sanitizada das revisões #8526 (setembro/2026), #8527 receipt 07 (06/10/2026), #8528 consolidação e impl4 receipts 17/19/23 (novembro/2026), e #8522-corpo-v2 receipt 02 (04/11/2026). Este último registrou build com zero testes e comportamento HTTP ainda não exercitado; a omissão posterior de testes na #8522 não invalida nem generaliza a política de outros alvos. As referências documentam lições, não certificação de conformidade atual.
