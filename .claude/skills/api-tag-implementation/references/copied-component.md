# Componente por cópia e adaptação

Ler quando o contrato do alvo exige copiar uma implementação de referência. Fixar origem e revisão acessíveis; um exemplo de outro projeto não autoriza escolher essa estratégia.

## Comparação e adaptação

- Levantar a lista de arquivos do componente e as adaptações autorizadas. Se houver exigência de paridade textual, comparar o conteúdo e justificar cada diferença: packages/imports, recursos, controllers e literais permitidos. Não transformar essa exigência em simples equivalência funcional.
- Confirmar catálogo, normalização de detalhes nulos e recursos reconhecidos pela factory. Uma entidade desconhecida pode causar uma segunda exceção dentro do handler.
- Verificar o escopo do advice adotado: lista explícita de controllers ou anotação reconhecida pela implementação. Uma lista vazia de `assignableTypes` não restringe o advice. Preservar os handlers atuais fora do escopo TAG.
- Se a referência deriva a entidade por `HandlerMethod`, conferir a assinatura suportada pelo Spring do alvo e o comportamento quando ele não estiver disponível. Usar o fallback confirmado, sem inventar um recurso não aceito pela factory.
- Copiar somente o componente necessário. Preservar CORS e autorização de cada operação; exemplos de outra API não definem esses controles.

## Evidência de aceite

Comparação origem–destino com diferenças explicadas; serialização da tag e dos DTOs; recurso válido por controller; erro em controller novo e legado; corpo ausente/malformado passando pela cadeia HTTP. Comparar também a versão nova com sua operação atual, conforme [contratos](tag-contracts.md).

## Procedência e limites

Síntese sanitizada das tarefas #8522, #8526 e #8527 (setembro–outubro de 2026): os registros adotaram uma revisão da implementação de referência com adaptações enumeradas, handler único e preservação de contratos. A #8522 teve decisões posteriores sobre CORS e remoção de testes; isso não autoriza remover testes em outro alvo. A #8528 posteriormente escolheu subtree para outra API, sem substituir o método das anteriores.

Esses registros são evidência histórica, não documentação oficial atual. Revalidar origem, revisão e adaptações no projeto em execução. Não há dependência dos receipts originais para aplicar este procedimento.
