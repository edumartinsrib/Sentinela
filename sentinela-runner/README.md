# sentinela-runner

Agente que executa as revisões. Pega uma revisão da fila da API, baixa o PR, aplica as
regras e chama a IA em modo somente leitura.

1. **Reivindica** a revisão (`POST /api/v1/runner/claim`, long-poll) e recebe os perfis,
   o modelo e uma credencial de leitura do repositório.
2. **Baixa** `refs/pull/N/head` (ou `refs/merge-requests/N/head`) e a branch de destino com
   fetch raso, e calcula o diff a partir do merge-base.
3. Roda as **regras de regex** nas linhas adicionadas, com tempo limite.
4. Remove `CLAUDE.md`, `AGENTS.md` e `.claude/` do checkout e chama o **Claude Code** ou a
   **Copilot CLI** só com leitura (sem shell, sem escrita, sem MCP do repositório).
5. Normaliza a resposta (severidade da regra, segredos mascarados) e envia o resultado.

Heartbeat a cada poucos segundos; o cancelamento (novo push, cancelamento no console)
chega por ele e encerra o grupo de processos.

```bash
SENTINELA_API_URL=https://sentinela.exemplo \
SENTINELA_REGISTRATION_TOKEN=snt_reg_... \
ANTHROPIC_API_KEY=... \
  uv run sentinela-runner
```

A imagem (`docker build -f sentinela-runner/Dockerfile .`) traz git, Node 22, Claude Code
e Copilot CLI. Variáveis e credenciais: [../docs/operacao.md](../docs/operacao.md).
Endurecimento das CLIs: [../docs/seguranca.md](../docs/seguranca.md).

```bash
uv run pytest sentinela-runner/tests
```
