# sentinela-api

API do Sentinela (FastAPI, Postgres/Alembic, Redis opcional).

- Cadastro: times, pessoas e papéis, integrações GitHub/GitLab, repositórios, perfis de
  padrão e regras, motores e modelos de IA, runners. Toda escrita vai para a auditoria.
- Webhooks assinados de pull request (GitHub) e merge request (GitLab): criam o gate do
  commit e enfileiram a revisão.
- Fila de revisões no Postgres para os runners (`/api/v1/runner`), com lease e heartbeat.
- Regra do gate (de `sentinela-core`), publicação do status `sentinela/gate`, comentário
  no PR e merge pela plataforma.
- Tempo real por SSE, distribuído entre réplicas pelo Redis.

Contrato: [../docs/api.md](../docs/api.md). Variáveis: [../docs/operacao.md](../docs/operacao.md).

```bash
docker build -f sentinela-api/Dockerfile -t sentinela-api .
```

Migrações (o container aplica ao subir, salvo com `SENTINELA_SKIP_MIGRATIONS=true`):

```bash
cd sentinela-api && uv run alembic upgrade head
```

Testes (Postgres em `SENTINELA_TEST_DATABASE_URL`):

```bash
uv run pytest sentinela-api/tests
```
