# Contribuindo

Obrigado pelo interesse em melhorar o kit. Abra uma issue para discutir mudanças de comportamento ou envie um pull request com escopo pequeno e explicação do problema resolvido.

Antes de enviar:

1. Leia [AGENTS.md](AGENTS.md) para entender os limites de coordenação e de autorização do projeto.
2. Preserve os contratos e exemplos existentes, e mantenha mudanças em `scripts/` acompanhadas de testes pertinentes.
3. Execute `python3 scripts/kit_lint.py` na raiz do repositório e informe no pull request o resultado e os checks que não pôde executar.
4. Confira `git diff --check` e os arquivos preparados para commit. Remova credenciais, dados pessoais, caminhos locais, PDFs de tarefas e arquivos de `.agent-state/`.

As instruções condicionais ligadas à governança da SES/SC, NADS ou DTIG são resumos históricos, não fontes oficiais. Uma contribuição que as altere deve citar a evidência pública ou autorizada que sustenta a mudança e preservar contratos já publicados.

Para falhas de segurança, siga [SECURITY.md](SECURITY.md) em vez de abrir uma issue pública.
