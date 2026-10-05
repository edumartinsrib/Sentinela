# API

Base: `/api/v1`. Documentação interativa em `/api/v1/docs` (Swagger) e o esquema em
`/api/v1/openapi.json`.

Autenticação do console: `Authorization: Bearer <token OIDC>` (ou, no modo dev,
`X-Sentinela-User: <usuário>`). Runners: `Authorization: Bearer snt_rn_…`.

Erros seguem `{"detail": "mensagem"}`. Rotas de time (`/teams/{time}/…`) checam o papel da
pessoa naquele time; administradores globais podem tudo.

## Console

### Sessão e administração

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `/config` | público: modo de autenticação, OIDC, versão |
| GET | `/me` | usuário, times e papéis |
| GET, POST | `/teams` | listar; criar (admin global) |
| PATCH | `/teams/{time}` | admin do time |
| GET, POST | `/users`; PATCH `/users/{id}` | admin do time lista; admin global cria e vincula logins do GitHub/GitLab |
| GET, POST | `/teams/{time}/roles`; DELETE `/teams/{time}/roles/{id}` | admin do time |
| GET, POST | `/roles`; DELETE `/roles/{id}` | papéis em todos os times (admin global) |
| GET | `/teams/{time}/audit`, `/audit` | auditoria do time (tech lead) e global (admin global) |

### IA e integrações (admin global)

| Método | Rota | O que faz |
| --- | --- | --- |
| GET, POST | `/ai/engines`; PATCH, DELETE `/ai/engines/{id}` | Motores (Claude Code, Copilot CLI, simulador): turnos, tempo, orçamento, argumentos extras |
| PUT | `/ai/engines/{id}/secrets` | Variáveis secretas entregues ao runner (chaves de IA) |
| GET, POST | `/ai/models`; PATCH, DELETE `/ai/models/{id}` | Modelos de cada motor |
| PUT | `/ai/default` | Modelo padrão global |
| GET, POST | `/integrations`; PATCH, DELETE `/integrations/{id}` | GitHub/GitLab: endereço, token, segredo de webhook |
| POST | `/integrations/{id}/check` | Testa o token |
| GET | `/integrations/{id}/webhook-secret` | Mostra o segredo (auditado) |
| GET | `/integrations/{id}/remote-repositories` | Repositórios que o token enxerga |
| GET | `/integrations/{id}/deliveries` | Últimas 50 entregas de webhook |

### Padrões

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `/library` | biblioteca de regras e modelos |
| POST | `/teams/{time}/pattern-test` | testa uma regex num trecho (tech lead) |
| GET, POST | `/teams/{time}/profiles` | listar; criar vazio ou a partir de modelo (tech lead) |
| GET, PATCH, DELETE | `/teams/{time}/profiles/{id}` | tech lead para escrever |
| GET | `/teams/{time}/profiles/{id}/export` | YAML |
| POST | `/teams/{time}/profiles/import` | YAML (cria ou substitui) |
| POST | `/teams/{time}/profiles/{id}/library` | adiciona regras da biblioteca |
| POST | `/teams/{time}/profiles/{id}/rules`; PATCH, DELETE `…/rules/{rule_id}` | regras |

### Repositórios (tech lead)

| Método | Rota | O que faz |
| --- | --- | --- |
| GET, POST | `/teams/{time}/repositories` | listar; cadastrar (confere no provedor) |
| GET, PATCH, DELETE | `/teams/{time}/repositories/{id}` | perfis, branches, modo do gate, política, modelo (admin global), observação e endereço de clone (admin global) |
| POST | `/teams/{time}/repositories/{id}/sync` | busca os PRs abertos e alinha |
| POST | `/teams/{time}/repositories/{id}/webhook` | cria o webhook no provedor |
| GET | `/teams/{time}/repositories/{id}/protection` | diagnóstico da proteção da branch |

### Pull requests, gates e apontamentos

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `/teams/{time}/pull-requests?state=open\|merged\|closed\|all&gate=…&repository=…&q=…` | leitura |
| GET | `/teams/{time}/pull-requests/{id}` | detalhe: gate, revisão, apontamentos, decisões, histórico, permissões |
| POST | `/teams/{time}/pull-requests/{id}/reviews` | reexecuta (dev; modelo diferente só admin global) |
| POST | `/teams/{time}/pull-requests/{id}/approve` | revisor/tech lead que não seja o autor, com login vinculado |
| POST | `/teams/{time}/pull-requests/{id}/reject` | idem; `comment` obrigatório |
| POST | `/teams/{time}/pull-requests/{id}/override` | admin global; `reason` obrigatório |
| POST | `/teams/{time}/pull-requests/{id}/merge` | dev ou acima; gate liberado e modo com merge pela plataforma |
| POST | `/teams/{time}/findings/{id}/{ação}` | `waive` (tech lead), `dismiss` (revisor; tech lead se bloqueante), `dispute` (dev), `reopen`, `comment`; corpo `{"reason": "…"}` |
| GET | `/teams/{time}/reviews/{id}`; `…/logs?tail=` | revisão e log |
| GET | `/teams/{time}/reviews/{id}/stream` | SSE do log e das fases |
| POST | `/teams/{time}/reviews/{id}/cancel` | cancela (dev) |
| GET | `/teams/{time}/events` | SSE do time (`pull_request`, `review`, `gate`, `finding`) |
| GET | `/teams/{time}/dashboard` | indicadores do painel |

### Runners (admin global)

| Método | Rota | O que faz |
| --- | --- | --- |
| GET | `/runners` | runners, ferramentas, ocupação (qualquer usuário) |
| PATCH, DELETE | `/runners/{id}` | drenar, habilitar, remover |
| GET, POST | `/runner-tokens`; DELETE `/runner-tokens/{id}` | tokens de registro (validade, revogação) |

## Runner

| Método | Rota | O que faz |
| --- | --- | --- |
| POST | `/runner/register` | token de registro → `runner_id`, `runner_token`, configuração |
| GET | `/runner/config` | configuração (habilitado, drenando, long-poll) |
| POST | `/runner/heartbeat` | `{running, engines, slots}` → revisões a abandonar |
| POST | `/runner/claim` | `{engines, wait_s}` → `{"review": …}` ou 204 |
| POST | `/runner/reviews/{id}/phase` | `cloning`, `diff`, `patterns`, `ai`, `reporting` |
| POST | `/runner/reviews/{id}/logs` | linhas de log (já mascaradas) |
| POST | `/runner/reviews/{id}/result` | `{summary, findings, stats}` |
| POST | `/runner/reviews/{id}/fail` | `{error, retryable}` |

Formato de um achado enviado pelo runner:

```json
{
  "rule_code": "SEC-005",
  "profile": "API Python (FastAPI)",
  "source": "ai",
  "category": "security",
  "severity": "high",
  "file": "app/routers/pedidos.py",
  "line": 12,
  "title": "Consulta SQL montada com interpolação",
  "description": "…",
  "suggestion": "…",
  "evidence": "return session.execute(text(f\"SELECT …\"))",
  "confidence": "high",
  "in_diff": true,
  "fingerprint": "3f1c…"
}
```

## Webhooks

| Rota | Autenticação | Eventos |
| --- | --- | --- |
| POST `/webhooks/github/{integração}` | `X-Hub-Signature-256` (HMAC-SHA256 do corpo) | `pull_request`: opened, reopened, synchronize, edited, ready_for_review, converted_to_draft, closed |
| POST `/webhooks/gitlab/{integração}` | `X-Gitlab-Token` | `merge_request`: open, reopen, update, close, merge |

Respostas: `200 processed`, `202 ignored` (evento ou repositório fora do Sentinela),
`401 rejected` (assinatura), `404` (integração).
