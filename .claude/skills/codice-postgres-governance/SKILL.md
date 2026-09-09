---
name: codice-postgres-governance
description: Planejar ou validar criação, configuração e restauração PostgreSQL sob governança do Códice da SES/SC, NADS ou DTIG. Não usar para migrations comuns da aplicação nem executar operações reais sem DBA/Infra, alvo confirmado e autorização explícita.
---

# Provisionamento e restauração PostgreSQL

## Uso e evidência

Aplicar somente com evidência de governança SES/SC, NADS ou DTIG. Requisitos explícitos da tarefa, instruções aplicáveis do projeto e contratos publicados orientam a execução. Documentos oficiais são opcionais por projeto: quando disponíveis, registrar fonte, versão/data e trecho aplicável; quando ausentes, continuar com a evidência local.

O resumo histórico vinculado abaixo tem atualidade **não verificada**. Seus identificadores permitem rastreabilidade, não comprovam conformidade oficial. Adotar uma convenção do resumo somente quando confirmada pelo projeto ou por fonte aplicável fornecida. Uma divergência material bloqueia apenas a decisão dependente, preservando o restante do trabalho e os contratos existentes.

## Preparação e autoridade

- Aplicar a provisionamento, configuração operacional ou restore; migrations comuns da aplicação seguem o fluxo de desenvolvimento e revisão por risco.
- Inspecionar evidências fornecidas sobre alvo, versão, backup, extensões, locale, permissões e política de recuperação. Sem acesso ao Códice, preparar o diagnóstico com fontes locais; não inventar infraestrutura nem exigir documentos para toda preparação.
- Operações reais exigem alvo confirmado, autorização correspondente e atuação/aprovação de DBA/Infra. Reutilizar autorização já dada, sem assumir o papel operacional. Sem ela, entregar comandos propostos e pendências específicas.
- Antes de um restore, confirmar origem/destino, integridade e data do backup, impacto, janela e reversão; verificar compatibilidade, espaço e backup recuperável antes de sobrescrever destino.
- Escolher versão, owner, mecanismo de segredos e privilégios conforme evidência operacional confirmada. Não atualizar para PostgreSQL 15 por este resumo. Usar menor privilégio adequado ao procedimento autorizado.
- Validar estrutura, contagens críticas, permissões e conectividade após operação autorizada; para base nova, verificar a cobertura de backup/recuperação exigida pelo projeto. Relatar o que não foi executado.
- Não copiar credenciais, mapas de hosts ou inventários internos para o kit ou logs.

Ler [referência histórica](references/historical-summary.md) apenas ao comparar uma configuração ou procedimento corporativo anterior.
