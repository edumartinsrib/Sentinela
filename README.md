# Sentinela — gate de revisão de pull requests

O Sentinela revisa cada commit de pull request (GitHub) ou merge request (GitLab) contra os
**padrões que o time definiu para aquele tipo de implementação**: API Python, front-end
React, serviço Java, Terraform, Dockerfiles e pipelines. A revisão cobre segurança, estrutura
e padrão de código, arquitetura e testes. As regras de expressão regular rodam direto no
runner; as regras escritas em linguagem natural vão para o **Claude Code** ou para a
**GitHub Copilot CLI**, em modo somente leitura.

O resultado é um **gate por commit**:

- **sem apontamento**, a IA aprova e o merge fica liberado;
- **com apontamento**, alguém que **não seja o autor** precisa aprovar no Sentinela;
- **apontamento bloqueante** (alta ou acima, ajustável) só sai com correção no código ou
  com exceção justificada pelo tech lead.

O merge só passa com o gate liberado. Isso vale pelo status obrigatório `sentinela/gate` no
GitHub/GitLab, pelo merge feito pela própria plataforma, ou pelos dois, conforme o
repositório.

![Painel do time](docs/screenshots/01-painel.png)

## Componentes

| Projeto | O que é |
| --- | --- |
| [sentinela-api](sentinela-api/) | API (FastAPI, Postgres/Alembic, Redis opcional). Webhooks, fila de revisões, gate, publicação de status e merge, auditoria |
| [sentinela-runner](sentinela-runner/) | Agente que pega revisões da fila, baixa o PR, aplica as regras e chama o Claude Code ou a Copilot CLI |
| [sentinela-console](sentinela-console/) | Console React + TypeScript feito com a [broto-ui](sentinela-console/vendor/) (nginx em produção) |
| [sentinela-core](sentinela-core/) | Contratos compartilhados: diff, regras, prompt, leitura da resposta da IA, regra do gate |

```mermaid
flowchart LR
  gh[GitHub / GitLab] -- webhook assinado --> api[sentinela-api]
  api -- status sentinela/gate,<br/>comentário, merge --> gh
  console[sentinela-console] -- /api --> api
  api --> pg[(Postgres<br/>fila, gates, auditoria)]
  api -.-> redis[(Redis<br/>tempo real)]
  runner[sentinela-runner] -- claim / heartbeat / resultado --> api
  runner -- git fetch do PR --> gh
  runner --> ia[Claude Code ou<br/>Copilot CLI<br/>somente leitura]
```

## Como um PR passa pelo gate

1. O webhook do PR (aberto, novo commit, reaberto, retarget) chega assinado. A API cria o
   **gate do commit** e enfileira a revisão no Postgres; o status `sentinela/gate` fica
   *pending* no provedor.
2. Um runner reivindica a revisão (`SELECT … FOR UPDATE SKIP LOCKED`, com lease e heartbeat),
   baixa `refs/pull/N/head` e calcula o diff a partir do merge-base.
3. As regras de **padrão (regex)** rodam nas linhas adicionadas. As regras de **IA** dos
   perfis que cobrem os arquivos alterados viram o prompt, e o Claude Code ou a Copilot CLI
   revisam o diff podendo só ler, buscar e listar arquivos do repositório.
4. Os achados voltam normalizados. A severidade e a categoria vêm sempre da regra
   cadastrada, nunca da IA. Arquivos que nenhum perfil cobre viram um apontamento
   informativo, para que a IA não aprove o que não revisou.
5. O gate é recalculado e publicado no commit e num comentário do PR. Justificativas e
   falsos positivos de commits anteriores do mesmo PR são herdados pela impressão digital
   do achado.
6. Quem tem papel de aprovador (e não é o autor) aprova ou reprova no console. O tech lead
   aceita exceções nos bloqueantes. Um administrador global pode liberar em caráter
   emergencial, com motivo registrado.
7. O merge acontece no provedor (o status obrigatório trava até o gate liberar) ou pelo
   botão **Fazer merge** do Sentinela, que envia o SHA do gate. Um merge feito por fora com
   o gate travado é marcado como **merge sem gate** e vai para a auditoria.

| Situação do commit | Quem libera |
| --- | --- |
| Revisão sem apontamentos | A IA (aprovação automática) |
| Apontamentos abaixo de *alta* | Um aprovador que não seja o autor (revisor, tech lead ou admin do time) |
| Apontamento *alta* ou *bloqueante* | Correção em novo commit, ou exceção do tech lead + aprovação |
| Reprovado | Novo commit, ou a mesma pessoa muda o voto |
| Emergência | Administrador global, com motivo (auditado) |

Cada repositório pode exigir humano sempre, mudar a severidade mínima que exige humano ou
que bloqueia, pedir mais de uma aprovação e rodar em **observação** (revisa e mostra tudo,
mas publica sucesso) durante a adoção.

## Rodando localmente

Pré-requisitos: Docker, [uv](https://docs.astral.sh/uv/) e Node 22.

```bash
docker compose --profile demo up -d --build     # API, runner, console e GitHub simulado
uv run python scripts/demo.py                   # time, perfis, 3 repositórios e 8 PRs
```

- Console: http://localhost:8090. No modo de desenvolvimento, entre como `admin`, `ana`
  (dev), `bia` (revisora) ou `caio` (tech lead).
- API e Swagger: http://localhost:8000/api/v1/docs

Sem chave de IA, o runner usa o **simulador local** (heurísticas, sem IA). Para revisar com
IA de verdade, exporte `ANTHROPIC_API_KEY` e/ou `COPILOT_GITHUB_TOKEN` antes do `up` e
escolha o modelo padrão em **IA e modelos**.

Sem Docker, com um Postgres local:

```bash
uv sync --all-packages
export SENTINELA_DATABASE_URL=postgresql://sentinela:sentinela@localhost:5432/sentinela
(cd sentinela-api && uv run alembic upgrade head)
uv run uvicorn fake_github:app --app-dir scripts --port 9000 &
SENTINELA_AUTH_MODE=dev SENTINELA_ENABLE_FAKE_ENGINE=true \
SENTINELA_BOOTSTRAP_RUNNER_TOKEN=snt_reg_00000000-0000-4000-8000-000000000001.dev \
  uv run sentinela-api &
SENTINELA_REGISTRATION_TOKEN=snt_reg_00000000-0000-4000-8000-000000000001.dev \
SENTINELA_ENABLE_FAKE_ENGINE=true uv run sentinela-runner &
(cd sentinela-console && npm ci && npm run dev) &      # http://localhost:5173
uv run python scripts/demo.py --github-api http://localhost:9000 \
  --github-control http://localhost:9000 --webhook-base http://localhost:8000
```

## Testes

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                                     # core, runner, API e ponta a ponta
(cd sentinela-console && npm run lint && npm run build)
SENTINELA_UI_URL=http://localhost:8090 uv run --group ui pytest tests/ui   # com a demo no ar
```

Os testes de API e o de ponta a ponta usam Postgres (`SENTINELA_TEST_DATABASE_URL` e
`SENTINELA_E2E_DATABASE_URL`). O de ponta a ponta sobe a API, o runner e o GitHub simulado
como processos e passa por webhook assinado, revisão, exceção, aprovação e merge pela
plataforma.

## Documentação

- [Arquitetura](docs/arquitetura.md): componentes, modelo de dados, fila, runner e tempo real
- [Gate de merge](docs/gate-de-merge.md): como travar o merge no GitHub e no GitLab
- [Padrões e regras](docs/padroes.md): perfis, regras de IA e de regex, biblioteca, YAML
- [Segurança](docs/seguranca.md): ameaças consideradas e como o Sentinela se protege
- [Operação](docs/operacao.md): variáveis de ambiente, implantação, OIDC, cofre, runners
- [API](docs/api.md): rotas da API e do runner
- [Funcionalidades e próximos passos](docs/funcionalidades.md): o que existe e o que vale a pena agregar
- [Estado](docs/estado.md): o que foi implementado e testado, e o que falta

Exemplos de perfis prontos para importar estão em [examples/perfis](examples/perfis/).
