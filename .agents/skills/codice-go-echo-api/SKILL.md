---
name: codice-go-echo-api
description: Implementar APIs Go novas governadas pelo Códice da SES/SC, NADS ou DTIG com Echo, arquitetura em camadas e middleware corporativo. Não usar para ETLs, projetos externos ou migração silenciosa de APIs legadas.
---

# APIs Go com Echo conforme o Códice

## Aplicabilidade

- Confirmar a governança do Códice e que o trabalho é uma API Go, não um ETL ou ferramenta de linha de comando.
- Para uma API nova, usar Echo v4 e a versão Go definida pelo repositório. Para uma API existente, preservar framework e layout atuais até que uma migração seja explicitamente aprovada.
- Aplicar também `codice-api-contracts` aos contratos HTTP.

## Arquitetura

Manter fluxo unidirecional e dependências das bordas para o domínio:

- `cmd/<aplicacao>.go`: composição e entrada da aplicação.
- `cmd/servidor/`: servidor, rotas e ciclo de vida HTTP.
- `cmd/bancodados/`: configuração de conexão.
- `cmd/manipuladores/`: validação HTTP e mapeamento de respostas.
- `cmd/servico/`: regras e orquestração de negócio.
- `cmd/armazenamento/`: persistência e queries.
- `cmd/dominio/`: entidades.
- `cmd/solicitacoes/` e `cmd/respostas/`: DTOs de entrada e saída.

Seguir variações já consolidadas em um repositório existente quando preservarem essa separação; não reorganizar mecanicamente apenas para igualar nomes de pastas.

## Echo e middlewares

- Usar middlewares oficiais do Echo. Não criar implementação paralela sem necessidade demonstrada.
- Aplicar CORS em todas as APIs Echo.
- Preferir a configuração padrão somente quando segura para o ambiente. Em produção, configurar allowlist mínima e nunca usar `AllowOrigins: ["*"]`.
- Manter origens por ambiente em configuração externa e testar origens permitidas e rejeitadas.
- Documentar e justificar customizações aprovadas; não expor `Authorization` ou outros headers sensíveis sem necessidade.

## Qualidade

- Manter manipuladores finos, contexto e cancelamento em todo I/O, dependências injetáveis e recursos fechados.
- Testar cada camada isoladamente e adicionar integração para rotas, middleware, persistência e health check.
- Executar `gofmt` e os checks descobertos no repositório.

Fontes consultadas em 20/08/2026: ADR-2507021258520, ADR-2507100930520 e NOTEC-2507021347520. O Códice continua sendo a fonte oficial para revisões futuras.
