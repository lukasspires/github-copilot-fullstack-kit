---
name: codice-postgres-governance
description: Planejar ou validar criação, configuração e restauração PostgreSQL sob governança do Códice da SES/SC, NADS ou DTIG. Não usar para migrations comuns da aplicação nem executar operações reais sem DBA/Infra, alvo confirmado e autorização explícita.
---

# Governança PostgreSQL do Códice

## Limites e fonte atual

- Confirmar que a demanda envolve provisionamento, restore ou governança de uma base, e não apenas uma migration versionada da aplicação.
- Consultar o Códice no momento da operação para obter versões, ambientes e procedimentos atuais. Não copiar para a skill mapas de IP, caminhos de credenciais, senhas ou inventários internos sujeitos a mudança.
- Exigir atuação ou aprovação de DBA/Infra para operações reais. Sem essa autoridade, produzir diagnóstico, checklist e comandos propostos sem executá-los.
- Nunca revelar, registrar em logs, commitar ou transmitir credenciais. Usar o fluxo institucional de segredos.

## Criação

- Usar PostgreSQL 15 para projeto novo. Versão legada só é válida para clonagem/compatibilidade estrita documentada e aprovada.
- Criar owner exclusivo por sistema; aplicações e restores nunca usam o superusuário `postgres`.
- Gerar a credencial no mecanismo institucional, com o mínimo exigido pelo Códice para o ambiente, sem mostrá-la na saída.
- Validar `locale -a` antes de escolher encoding/collation e aplicar apenas extensões suportadas e necessárias.
- Conceder ao owner somente os privilégios necessários e preservar as políticas existentes do schema.

## Restore

- Confirmar por escrito origem, backup, checksum/timestamp, banco e ambiente de destino, janela, impacto e plano de reversão.
- Verificar compatibilidade de versão, locale, extensões, owner e espaço antes de restaurar.
- Usar o owner da base, nunca `postgres`, e não sobrescrever um destino existente sem autorização específica e backup recuperável.
- Após o restore, validar estrutura, contagens críticas, permissões, conectividade e logs antes de liberar o ambiente.

## Backup e governança

- Configurar e testar backup automatizado antes do handoff de uma base nova.
- Registrar o ativo, owner, ambiente e cobertura de backup no repositório institucional indicado pela versão atual do Códice, sem duplicar segredos no projeto.
- Entregar evidência de criação/restore, validações, backup testado, riscos residuais e responsável operacional.

Fontes consultadas em 20/08/2026: ADR-2410110901520 e NOTEC-26043009342229. O Códice continua sendo a fonte oficial para mapas de infraestrutura e revisões futuras.
