# Segurança

Um gate de merge só vale se for difícil de contornar. Esta página lista o que o Sentinela
protege, contra quem, e como.

## Quem pode tentar contornar

| Quem | O que tentaria |
| --- | --- |
| Autor do PR | Aprovar o próprio código, apagar uma reprovação, fazer a IA "não ver" o problema, publicar um status verde |
| Pessoa de outro time | Mexer no gate de um repositório que não é dela |
| Conteúdo do PR | Injeção de instrução na IA, ataques ao parser de diff, regex lenta, exfiltração de credenciais |
| Runner comprometido ou falso | Enviar resultado de revisão que não é dele |
| Rede | Webhook forjado ou reenviado |

## Garantias

**Autor nunca decide sobre o próprio PR.** Aprovar, reprovar, aceitar exceção e marcar
falso positivo exigem:

- autor do PR identificado (um webhook sem autor nunca apaga o autor já conhecido);
- login do decisor **vinculado** ao provedor (GitHub ou GitLab) em **Acesso**. Só o
  administrador global vincula logins. Sem vínculo, não há como provar que a pessoa não é o
  autor, e a decisão fica bloqueada;
- o login vinculado (ou o usuário, ou o e-mail) diferente do autor.

**Reexecutar não "lava" um commit.**

- Reprovações valem para o commit inteiro; só quem reprovou muda o voto.
- Se alguma revisão do commit teve apontamento, o commit continua exigindo humano mesmo que
  uma nova rodada da IA venha limpa.
- A política do gate é congelada no commit: afrouxar a política do repositório vale só
  para os próximos commits.
- Colocar o repositório em **observação** (que publica sucesso) e cadastrar sem conferir no
  provedor são ações só do administrador global.

**Bloqueante sai só com o tech lead.** Exceção e falso positivo em apontamentos que
bloqueiam o merge exigem o papel de tech lead (ou admin do time). Uma exceção reaberta não
volta a ser herdada nos commits seguintes.

**Repositório tem um dono só.** O nome é único por integração sem diferenciar maiúsculas
(`Org/Repo` = `org/repo`), e o cadastro confere o repositório no provedor.

**Credencial da integração não sai do host do repositório.**

- O endereço de clone só pode ser trocado pelo administrador global e precisa usar o mesmo
  host da integração (sem usuário/senha embutidos).
- No runner, o cabeçalho de autenticação do git é amarrado à origem do repositório
  (`http.<origem>.extraHeader`), vai por variável de ambiente (não aparece em `ps`) e é
  mascarado nos logs.
- O token só é entregue ao runner que reivindicou a revisão.

**A IA só lê.**

- Claude Code: `--tools Read,Grep,Glob`, `--permission-mode dontAsk`, `--restricted`
  (sem ferramentas que executam código, sem configurações do repositório), `--safe-mode`
  quando disponível (sem CLAUDE.md, skills, plugins, hooks), `--strict-mcp-config`,
  `--disable-slash-commands`, sem persistência de sessão.
- Copilot CLI: `--allow-tool read`, `--deny-tool shell`, `--deny-tool write`,
  `--disable-builtin-mcps`, `--no-custom-instructions`, `--no-ask-user`.
- Arquivos de instrução de agentes (`CLAUDE.md`, `AGENTS.md`, `.claude/`,
  `.github/copilot-instructions.md`, `.github/instructions/`, `.mcp.json`) são removidos do
  checkout antes da IA rodar; o conteúdo deles continua no diff, como dado.
- O prompt diz que o conteúdo do PR é dado a revisar, nunca instrução.
- As variáveis de ambiente passadas à CLI são uma lista fechada (credenciais da IA, proxy,
  certificados).

**A IA não aprova por omissão.**

- A resposta precisa trazer a lista `findings`; um JSON qualquer (ou um JSON citado do PR
  antes da resposta) não vale como "nenhum apontamento". Fora do formato, a revisão falha
  (e o gate fica em erro, não aprovado).
- Arquivos que nenhum perfil cobre viram apontamento informativo: alguém precisa olhar.
- Severidade e categoria vêm da regra; achados fora das regras ficam limitados a média.

**Diff e regex resistentes a conteúdo hostil.**

- O diff é lido só por `\n` e respeita as contagens de cada hunk: um `\r` no meio de uma
  linha não cria arquivos falsos nem esconde linhas adicionadas.
- As regex das regras rodam com tempo limite por linha e por arquivo (módulo `regex`), em
  outra thread no runner e na API. O teste de regex no console exige papel de quem edita
  padrões.

**Segredos não se espalham.** O trecho de evidência, a descrição e a sugestão dos achados
passam por um mascaramento (atribuições a `password`/`token`/`api_key`…, credenciais em
URL, `Bearer`, chaves privadas, tokens conhecidos do GitHub, GitLab, AWS, Slack, Anthropic,
JWT): o segredo encontrado não vai para o banco, para o console nem para o comentário do PR.

**Webhooks autenticados.** GitHub: HMAC-SHA256 do corpo bruto (`X-Hub-Signature-256`).
GitLab: `X-Gitlab-Token`. Comparação em tempo constante. Cada integração tem o próprio
segredo, e as entregas (aceitas, ignoradas, recusadas) ficam visíveis. Um webhook atrasado
ou reenviado que tente voltar o PR para um commit já substituído é conferido no provedor e
ignorado se o head atual for outro.

**Concorrência.** Decisões, ações em apontamentos, conclusão de revisão e merge travam a
linha do gate (`SELECT … FOR UPDATE`) e releem o estado antes de gravar. Webhooks do mesmo
PR são tratados um de cada vez. O merge pela plataforma envia o SHA do gate ao provedor.

**Status adulterado é corrigido.** O reconciliador confere periodicamente o status
`sentinela/gate` no commit; se outro publicador mudou o valor, o Sentinela republica o dele
e registra `gate.status_tampered`. No GitHub, fixe a origem do status (veja
[gate de merge](gate-de-merge.md)).

**Runners com identidade própria.** Token de registro (com validade, revogável) só no
primeiro boot; depois, token próprio do runner (só o hash fica no banco, arquivo local com
permissão 0600). Um nome de runner ativo não pode ser registrado de novo; um runner
desabilitado não reivindica nem envia resultados.

**Autenticação.** OIDC por padrão (Entra ID, Keycloak…), com validação de emissor,
audiência obrigatória e expiração. O modo de desenvolvimento (usuário no cabeçalho, sem
senha) precisa ser ligado explicitamente com `SENTINELA_AUTH_MODE=dev`; a API recusa subir
em OIDC sem `SENTINELA_OIDC_AUTHORITY` e audiência.

**Auditoria.** Toda escrita registra quem, quando, antes e depois: aprovações, reprovações,
exceções, falsos positivos, liberações emergenciais, merges (inclusive sem gate), mudanças
de padrão, repositório, papéis, motores e modelos, e leituras do segredo de webhook.

## Recomendações de implantação

- Coloque a API atrás de TLS e restrinja `/api/v1/runner/*` à rede dos runners se possível.
- Use o cofre (Vault) ou, no mínimo, `SENTINELA_SECRET_KEY` próprio e rotacionável (várias
  chaves `id:base64` separadas por vírgula; a primeira cifra, todas decifram).
- Rode os runners como usuário sem privilégios, com disco efêmero, e sem acesso de rede além
  da API, do git e do endpoint da IA.
- Dê ao token da integração o mínimo de permissões (veja [gate de merge](gate-de-merge.md)).
- Monitore `pull_request.merged_without_gate`, `gate.override` e `gate.status_tampered`.
