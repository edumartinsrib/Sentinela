# Estado da implementação

Situação em 05/10/2026, versão 0.1.0.

## Implementado e testado

| Área | O que existe | Como foi verificado |
| --- | --- | --- |
| Regra do gate | IA aprova o commit sem apontamento; com apontamento, aprovação de quem não é o autor; bloqueante só com exceção do tech lead; reprovação, liberação emergencial, merge sem gate | Testes unitários do `sentinela-core` + testes de API |
| Padrões | Perfis por tipo de implementação e por caminho, regras de IA e de regex, biblioteca com 32 regras e 5 modelos, YAML de importação/exportação, teste de regex | Testes de API; exemplos em `examples/perfis` gerados e relidos pelo próprio parser |
| Fila e runner | Fila no Postgres (`SKIP LOCKED`, lease, heartbeat, reenvio), fetch raso do PR, diff a partir do merge-base, regex com tempo limite, cancelamento, logs ao vivo mascarados | Testes do runner + ponta a ponta com processos reais |
| Claude Code | `claude -p` só leitura com `--json-schema`, `--restricted` e `--safe-mode` | Revisão real com Claude Haiku num PR da demonstração: 34 s, 3 turnos, US$ 0,04, 7 apontamentos ligados às regras do perfil e gate bloqueado como esperado |
| GitHub | Webhook assinado, status `sentinela/gate`, comentário-resumo, merge pela plataforma com SHA, diagnóstico da proteção da branch, detecção de merge sem gate | Ponta a ponta contra o GitHub simulado (`scripts/fake_github.py`, inclusive git por HTTP) |
| GitLab | Webhook com token, status do commit, nota no MR, merge com SHA, diagnóstico | Testes de API com respostas HTTP simuladas |
| Segurança | Correções de uma revisão de código independente (tomada de repositório, escopo do token de clone, autoaprovação, condições de corrida, ReDoS, resposta da IA fora do formato, arquivos de instrução no checkout, entre outros) | `sentinela-api/tests/test_security.py` + testes do core |
| Console | Todas as telas (painel, PRs, gate, apontamentos, revisão ao vivo, padrões, repositórios, IA e modelos, integrações, runners, acesso, auditoria) com a broto-ui | `tsc` + build; 12 testes de interface com Playwright contra a demonstração; prints em `docs/screenshots` |
| Banco | Migração inicial Alembic | `upgrade`, `check` (modelos em sincronia) e `downgrade` |

Números da última execução: core 34, runner 9, API 27, ponta a ponta 1, interface 12, todos
passando.

## Não verificado

- **GitHub e GitLab de verdade.** O GitHub foi exercitado só pelo simulador e o GitLab só
  por respostas HTTP simuladas. Falta um teste com um repositório real, de preferência
  com o GitHub App e um projeto GitLab da empresa.
- **Copilot CLI.** O motor está escrito conforme a documentação de modo programático, mas
  a CLI não estava instalada no ambiente de desenvolvimento.
- **Imagens Docker e o `docker compose`.** Os Dockerfiles e o compose foram escritos, mas
  não havia Docker disponível para construir e subir.
- **OIDC com um provedor real**, **Vault** e **Redis com várias réplicas**: o código existe
  e segue o padrão do Orquestrador, mas só o modo dev e o cofre `db` foram exercitados.
- **Workflow de CI** (`.github/workflows/ci.yml`): não rodou no GitHub Actions.

## Antes de usar em produção

1. Gerar e guardar `SENTINELA_SECRET_KEY` (ou configurar o Vault) e configurar o OIDC
   (`SENTINELA_AUTH_MODE` é `oidc` por padrão e a API não sobe sem a autoridade).
2. Criar a integração (GitHub App ou token; no GitLab, token de projeto ou grupo), cadastrar
   os repositórios e seguir [gate-de-merge.md](gate-de-merge.md) para tornar o status
   obrigatório e, se quiser, limitar o merge ao Sentinela.
3. Vincular os logins do GitHub/GitLab de cada pessoa em **Acesso**. Sem isso, o
   Sentinela não sabe se quem aprova é o autor e recusa a aprovação.
4. Subir pelo menos um runner com Claude Code ou Copilot CLI e a credencial da IA, escolher
   o modelo padrão em **IA e modelos** e rodar uma revisão de teste.
5. Começar os repositórios em **modo observação** (revisa e mostra tudo, mas publica
   sucesso) e ligar o gate depois de calibrar as regras.

## Próximos passos

Estão em [funcionalidades.md](funcionalidades.md), com prioridade. Os primeiros:
comentários na linha do diff, revisão incremental, exceções com prazo, notificações e
aprovação por área (estilo CODEOWNERS).
