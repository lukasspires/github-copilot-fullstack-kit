# Componente integrado por subtree

Ler somente quando o guia ou a decisão vigente do alvo adotar subtree. Registrar revisão exata e prefixo antes da integração. `git subtree add` produz commits: a autorização para editar código não concede automaticamente autorização para esses commits.

## Preparação e integração

1. Comparar o guia com a revisão escolhida: escopo do handler, flags, dependências, versão Java, resources, autoconfiguração e persistência. Escolher uma revisão compatível com os contratos; se só existir advice global incompatível, resolver a revisão ou adaptação externa com o architect antes de integrar. Não editar o prefixo importado nem usar `@Order` como substituto de escopo.
2. Conferir o build efetivo do host. Código incorporado por source root é compilado pelo projeto hospedeiro; o pom interno não garante dependências, plugins ou versão Java. Conferir o artefato produzido e registrar eventual requisito de runtime para promoção.
3. Comparar recursos e configuração. Importar apenas os recursos necessários; `application*.properties` do componente pode sobrescrever configuração do host. Mesclar registros de autoconfiguração preservando entradas existentes, e conferir colisões no artefato final.
4. Inventariar beans e rotas duplicados antes de substituir componente local. Remoção de código local e ativação do compartilhado precisam formar uma etapa verificável, com escopo autorizado. Não remover biblioteca legada enquanto houver consumidores sem substituto comprovado.
5. Confrontar entidades e repositories escaneados com o schema real. Um guia que adiciona entidade não prova a existência da tabela. Separar conversão de objetos de persistência opcional; não ativar auditoria, criar migrations ou registrar entidades por associação de pacote sem necessidade confirmada.
6. Conferir flags e dependências de eventos. Beans opcionais podem transformar erro de configuração em perda silenciosa. Provar registro de service/repository e efeito efetivo de cada escrita, preservando nomes, capitalização, operação e JSON dos eventos.

## Checks

- Conferir revisão/trailer do subtree e ausência de edições no prefixo.
- Build limpo, teste de contexto, regressão do legado e testes de paridade dos eventos. Mesmo método de service não prova que o componente persistiu o evento.
- Conferir contratos de health, métricas e logs quando a integração os afetar; compilar não prova startup, acesso ou ausência de dados sensíveis em logs.
- Se runtime/banco for necessário, seguir as instruções do alvo e do kit para `dev`, sem copiar conexão ou credenciais para evidências. Não exigir Docker por padrão.

## Procedência e limites

Síntese da #8528: análise do architect de 11/11/2026, consolidação e revisões até 17/11/2026. Foram identificados advice global em uma revisão, dependências ausentes no guia, registros JPA incompatíveis com tabelas disponíveis, recursos conflitantes e eventos que poderiam falhar silenciosamente.

A manutenção inicial de `tag-library` foi substituída por decisão explícita de remoção em 17/11. O receipt 25 registrou revisão `PASS_WITH_RISKS` da substituição legada e 918 testes; a execução anterior à troca foi evidência do writer, não repetida pelo reviewer. Isso demonstra a necessidade de revalidar decisões e testar compatibilidade, não uma regra de remover a biblioteca em outras APIs.
