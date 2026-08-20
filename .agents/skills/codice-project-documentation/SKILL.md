---
name: codice-project-documentation
description: Criar ou atualizar README e diagramas arquiteturais de projetos governados pelo Códice da SES/SC, NADS ou DTIG. Não aplicar a projetos externos nem migrar toda a documentação existente sem solicitação explícita.
---

# Documentação de projeto conforme o Códice

## Aplicabilidade

- Confirmar a governança do Códice e inspecionar a documentação e os comandos reais do repositório antes de escrever.
- Não inventar versões, dependências, ambientes, endpoints ou procedimentos de publicação.
- Manter a alteração proporcional ao trabalho; uma atualização pontual não autoriza uma reestruturação completa.

## README.md

Tratar o `README.md` da raiz como principal referência do projeto. Manter, quando aplicável:

- propósito e visão do projeto;
- ADRs relacionadas;
- pré-requisitos e dependências;
- compilação ou build de artefatos;
- configuração por ambiente, sem segredos;
- execução local e verificações;
- publicação ou implantação descoberta no repositório;
- orientações suficientes para onboarding.

Revisar o README ao final da sprint ou quando a mudança tornar uma instrução incorreta. Preservar detalhes ainda válidos e validar comandos antes de documentá-los.

## Diagramas arquiteturais

- Armazenar fontes e exportações em `Arquitetura/Diagramas`.
- Criar a fonte em PlantUML, Mermaid ou DrawIO; escolher a ferramenta já usada no repositório quando houver padrão.
- Exportar cada diagrama em `.png` ou `.svg` e manter a fonte editável correspondente.
- Atualizar fonte e exportação juntas e garantir que nomes indiquem claramente sistema e visão representada.
- Verificar legibilidade, relações, direção dos fluxos e ausência de dados sensíveis antes da entrega.

## Handoff

Informar arquivos atualizados, comandos verificados, ADRs referenciadas, diagramas-fonte/exportações e qualquer informação que permaneça pendente de confirmação.

Fontes consultadas em 20/08/2026: ADR-2410020748520 e ADR-2410221132520. O Códice continua sendo a fonte oficial para revisões futuras.
