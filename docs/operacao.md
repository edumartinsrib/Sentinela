# Operação

## Implantação

Três imagens, todas configuradas só por variáveis de ambiente:

| Imagem | Build | Porta | Saúde |
| --- | --- | --- | --- |
| `sentinela-api` | `docker build -f sentinela-api/Dockerfile .` | 8000 | `/healthz` (processo), `/readyz` (banco) |
| `sentinela-runner` | `docker build -f sentinela-runner/Dockerfile .` | — | heartbeat na API |
| `sentinela-console` | `docker build sentinela-console` | 8080 | `/healthz` |

- **API**: aplica as migrações ao subir (`alembic upgrade head`). Com várias réplicas,
  rode a migração como job da implantação e suba as réplicas com
  `SENTINELA_SKIP_MIGRATIONS=true`. Use Redis com mais de uma réplica.
- **Console**: nginx com a SPA e proxy de `/api` e `/webhooks` para
  `SENTINELA_API_UPSTREAM`. O GitHub/GitLab entrega os webhooks no endereço público do
  console (ou direto na API, se ela for exposta).
- **Runner**: um volume em `/var/lib/sentinela-runner` guarda a identidade (token próprio)
  e as áreas de trabalho. A imagem traz git, Node 22, Claude Code e Copilot CLI
  (`--build-arg INSTALL_CLAUDE_CODE=false`/`INSTALL_COPILOT_CLI=false` para tirar;
  `CLAUDE_CODE_VERSION`/`COPILOT_CLI_VERSION` para fixar versões).

## API — variáveis

| Variável | Padrão | Para quê |
| --- | --- | --- |
| `SENTINELA_DATABASE_URL` (ou `DATABASE_URL`) | — | Postgres. Alternativa: `SENTINELA_DB_HOST/PORT/USER/PASSWORD/NAME` (ou `PG*`) |
| `SENTINELA_DB_POOL_SIZE` | 10 | Conexões por réplica |
| `SENTINELA_REDIS_URL` (ou `REDIS_URL`) | — | Eventos em tempo real e logs ao vivo entre réplicas. Sem ele, só em memória |
| `SENTINELA_AUTH_MODE` | `oidc` | `oidc` ou `dev` (usuário no cabeçalho `X-Sentinela-User`, **só desenvolvimento**) |
| `SENTINELA_OIDC_AUTHORITY` | — | Emissor OIDC (ex.: `https://login.microsoftonline.com/<tenant>/v2.0`) |
| `SENTINELA_OIDC_CLIENT_ID` | — | Client ID da SPA (o console usa PKCE) |
| `SENTINELA_OIDC_AUDIENCE` | client ID | Audiência exigida no token |
| `SENTINELA_OIDC_SCOPES` | `openid profile email` | Escopos pedidos pelo console |
| `SENTINELA_ADMIN_GROUPS` | — | Grupos do SSO (claim `groups`) que viram administradores globais |
| `SENTINELA_BOOTSTRAP_ADMINS` | `admin` | Usuários que viram administradores globais no primeiro acesso |
| `SENTINELA_SECRET_STORE` | `db` | `db` (AES-GCM no Postgres), `vault` (KV v2) ou `memory` (testes) |
| `SENTINELA_SECRET_KEY` | — | Chaves do cofre `db`: `id:base64(32 bytes)`, várias separadas por vírgula (a primeira cifra). Obrigatória fora do modo dev |
| `VAULT_ADDR`, `VAULT_TOKEN` ou `VAULT_ROLE_ID`/`VAULT_SECRET_ID`, `VAULT_NAMESPACE` | — | Cofre `vault` (AppRole renova o login sozinho) |
| `SENTINELA_VAULT_MOUNT`, `SENTINELA_VAULT_PREFIX` | `secret`, `sentinela` | Onde ficam os segredos no Vault |
| `SENTINELA_PUBLIC_URL` | `http://localhost:8090` | Endereço do console (links nos status e comentários) |
| `SENTINELA_PUBLIC_API_URL` | `http://localhost:8000` | Endereço público para webhooks e para os runners |
| `SENTINELA_CORS_ORIGINS` | — | Origens extras, se o console não estiver no mesmo host |
| `SENTINELA_BOOTSTRAP_RUNNER_TOKEN` | — | Token de registro inicial (`snt_reg_<uuid>.<segredo>`), útil em ambientes automatizados |
| `SENTINELA_ENABLE_FAKE_ENGINE` | `false` | Habilita o motor "Simulador local" (sem IA) para demonstração e testes |
| `SENTINELA_DEFAULT_TEAM` | `plataforma` | Time criado no primeiro boot |
| `SENTINELA_REVIEW_LEASE_S` | 120 | Lease da revisão; renovada pelo heartbeat |
| `SENTINELA_REVIEW_MAX_ATTEMPTS` | 2 | Tentativas antes de marcar erro |
| `SENTINELA_CLAIM_WAIT_S` | 20 | Long-poll do runner |
| `SENTINELA_MAX_DIFF_CHARS` | 200000 | Tamanho do diff enviado à IA (o resto ela lê pelo arquivo) |
| `SENTINELA_RECONCILER_ENABLED`, `SENTINELA_RECONCILE_INTERVAL_S` | `true`, 30 | Leases vencidas, runners offline, republicação de status |
| `SENTINELA_TAMPER_CHECK`, `SENTINELA_TAMPER_CHECK_INTERVAL_S` | `true`, 300 | Confere se o status no provedor foi alterado por outro publicador |
| `SENTINELA_RUNNER_OFFLINE_AFTER_S` | 90 | Sem heartbeat por esse tempo, o runner fica offline |
| `SENTINELA_PROVIDER_TIMEOUT_S` | 20 | Tempo limite das chamadas ao GitHub/GitLab |
| `SENTINELA_LOG_BUFFER_LINES`, `SENTINELA_LOG_BUFFER_TTL_S` | 3000, 14 dias | Buffer dos logs das revisões |
| `SENTINELA_HOST`, `SENTINELA_PORT`, `SENTINELA_LOG_LEVEL` | `0.0.0.0`, 8000, `INFO` | Servidor |
| `SENTINELA_SHUTDOWN_TIMEOUT_S` | 10 | Espera pelas conexões longas (SSE, long-poll) ao desligar |
| `SENTINELA_SKIP_MIGRATIONS` | — | `true` para não migrar ao subir (imagem) |

### OIDC

1. Registre uma aplicação **SPA** no provedor (Entra ID, Keycloak, Okta…) com redirect
   `https://<console>/auth/callback` e logout `https://<console>/`.
2. Configure `SENTINELA_AUTH_MODE=oidc`, `SENTINELA_OIDC_AUTHORITY`,
   `SENTINELA_OIDC_CLIENT_ID` e, se o token de acesso tiver outra audiência,
   `SENTINELA_OIDC_AUDIENCE`.
3. Para papéis por grupo, inclua o claim `groups` no token e dê papéis a grupos em
   **Acesso** (por time ou para todos os times). `SENTINELA_ADMIN_GROUPS` define os
   administradores globais.
4. Em **Acesso → Usuários**, vincule o login do GitHub/GitLab de cada pessoa. **Sem o
   vínculo, a pessoa não aprova nem aceita exceções**: é o vínculo que prova que ela não é a
   autora do PR.

## Runner — variáveis

| Variável | Padrão | Para quê |
| --- | --- | --- |
| `SENTINELA_API_URL` | `http://localhost:8000` | Endereço da API |
| `SENTINELA_REGISTRATION_TOKEN` | — | Token de registro (só no primeiro boot) |
| `SENTINELA_RUNNER_NAME` | hostname | Nome único do runner |
| `SENTINELA_RUNNER_HOME` | `~/.sentinela-runner` | Identidade e áreas de trabalho |
| `SENTINELA_LABELS` | sistema operacional | Rótulos informativos |
| `SENTINELA_SLOTS` | 2 | Revisões em paralelo |
| `SENTINELA_ENGINES` | `auto` | `auto` (detecta `claude` e `copilot` no PATH) ou lista: `claude_code,copilot_cli` |
| `SENTINELA_ENABLE_FAKE_ENGINE` | `false` | Oferece o simulador local |
| `SENTINELA_CLAUDE_PATH`, `SENTINELA_COPILOT_PATH`, `SENTINELA_GIT_PATH` | `claude`, `copilot`, `git` | Executáveis |
| `SENTINELA_CLAUDE_HARDENING` | `restricted` | `restricted` (`--restricted`), `bare` (`--bare`, exige `ANTHROPIC_API_KEY` ou Bedrock/Vertex) ou `settings` (`--setting-sources user`, para versões antigas) |
| `SENTINELA_FETCH_DEPTH` | 200 | Profundidade do fetch raso |
| `SENTINELA_GIT_TIMEOUT_S` | 600 | Tempo limite dos comandos git |
| `SENTINELA_KEEP_WORKSPACES` | `false` | Mantém o checkout depois da revisão (depuração) |
| `SENTINELA_KILL_GRACE_S` | 10 | Espera entre SIGTERM e SIGKILL ao cancelar |

Credenciais da IA (passadas à CLI, nunca ao repositório):

- **Claude Code**: `ANTHROPIC_API_KEY`, ou Bedrock (`CLAUDE_CODE_USE_BEDROCK=1` + `AWS_*`),
  ou Vertex (`CLAUDE_CODE_USE_VERTEX=1` + `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID`,
  `GOOGLE_APPLICATION_CREDENTIALS`).
- **Copilot CLI**: `COPILOT_GITHUB_TOKEN` (token com permissão *Copilot Requests*).

Elas podem ficar no ambiente do runner ou nos **segredos do motor** (IA e modelos →
motor → segredos), que a API entrega ao runner na hora da revisão e mascara nos logs.

## Escala e disponibilidade

- **Runners**: escale pelo número de revisões simultâneas (slots). Revisões de um runner
  que cai voltam à fila quando a lease vence. **Drenar** termina as atuais e para de pegar
  novas, para manutenção.
- **API**: stateless; várias réplicas com Redis. O long-poll dos runners e os SSEs do
  console são conexões longas: ajuste o timeout do balanceador (≥ 60 s).
- **Postgres**: tudo (fila, gates, auditoria) está nele. Backup regular; a tabela
  `audit_log` cresce sempre (arquive por data se precisar).

## Observabilidade

- Logs estruturados no stdout (API e runner).
- Painel do time: gates por dia, tempo até a aprovação humana, regras mais violadas,
  merges sem gate, liberações emergenciais, runners.
- Eventos para alerta na auditoria: `pull_request.merged_without_gate`, `gate.override`,
  `gate.status_tampered`.
- **Integrações → webhooks recebidos** mostra as últimas entregas (processadas, ignoradas,
  recusadas).
