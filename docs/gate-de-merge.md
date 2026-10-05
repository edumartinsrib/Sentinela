# Gate de merge: só passa com o Sentinela liberando

O Sentinela não confia na boa vontade de ninguém: o merge precisa ser **impossível** no
provedor enquanto o gate do commit não estiver liberado. Cada repositório escolhe o modo:

| Modo (`gate_mode`) | Como trava | Quando usar |
| --- | --- | --- |
| `status_check` | O status `sentinela/gate` é obrigatório na branch protegida; o merge continua no GitHub/GitLab | O time quer manter o botão de merge do provedor |
| `platform_merge` | Ninguém faz merge no provedor; só o usuário-robô do Sentinela, pelo botão **Fazer merge** | Controle total, inclusive no GitLab Free |
| `both` (recomendado) | Os dois: status obrigatório **e** merge restrito ao robô | Defesa em profundidade |

O status publicado é sempre do **commit** (head SHA): um commit novo abre um gate novo, com
status *pending*, e a aprovação anterior não vale para ele. O merge pela plataforma envia o
SHA do gate ao provedor, que recusa se o head tiver mudado nesse meio-tempo.

A tela **Repositórios → Bloqueio do merge** consulta o provedor e mostra o que falta
configurar.

## GitHub (github.com ou Enterprise Server)

### Status obrigatório (`status_check`)

1. **Settings → Rules → Rulesets → New branch ruleset** (ou *Branch protection rules*).
2. Alvo: a branch padrão e as que tiverem gate (`main`, `release/*`…).
3. Ative **Require status checks to pass** e adicione `sentinela/gate`.
   - Em **"Expected source"**, escolha o app ou o usuário-robô do Sentinela. Sem isso,
     qualquer um com escrita no repositório pode publicar um status `sentinela/gate` verde
     pela API. O Sentinela também confere periodicamente o status no commit e republica o
     dele, registrando a adulteração na auditoria, mas a origem fixa evita a janela.
4. Ative **Require branches to be up to date** se o time quiser revisar o código que vai
   mesmo para a branch (o Sentinela revisa o diff a partir do merge-base).
5. Em **Bypass list**, deixe vazio (ou só o próprio robô). Em proteção clássica, ative
   **Do not allow bypassing the above settings**: administradores também respeitam.
6. Bloqueie push direto na branch protegida (**Restrict updates** / *Require a pull
   request before merging*).

### Merge só pelo Sentinela (`platform_merge`)

1. Na mesma regra, em **Restrict who can push to matching branches** (ou *Restrict
   updates* no ruleset com bypass só para o robô), deixe apenas o usuário-robô ou o
   GitHub App do Sentinela.
2. O token da integração precisa de **Contents: write** e **Pull requests: write** para
   fazer o merge.

### Token da integração

GitHub App (preferível) ou PAT *fine-grained* do usuário-robô, só nos repositórios do
Sentinela:

| Permissão | Para quê |
| --- | --- |
| Contents: read (write no `platform_merge`) | Clonar o PR; fazer o merge |
| Pull requests: read/write | Ler o PR, comentar, fazer o merge |
| Commit statuses: read/write | Publicar `sentinela/gate` |
| Webhooks: write | Criar o webhook pelo console (opcional) |
| Administration: read | Diagnóstico da proteção (opcional) |

## GitLab (gitlab.com ou self-managed)

### Status obrigatório (`status_check`)

O Sentinela publica um *commit status* externo (`sentinela/gate`) no commit do MR. No
GitLab, um status externo entra no pipeline do commit.

1. **Settings → Merge requests → Merge checks**: ative **Pipelines must succeed**.
2. Desative **Skipped pipelines are considered successful**.
3. **Settings → Repository → Protected branches**: proteja a branch de destino e, em
   **Allowed to push and merge**, deixe *No one* para push.

> Em projetos sem nenhum pipeline de CI, o status externo sozinho cria o pipeline; com CI,
> ele vira mais um job. Nos dois casos, *pending* ou *failed* impede o merge.
> No GitLab Ultimate, também é possível usar **External status checks** apontando para o
> Sentinela; o modo `platform_merge` cobre todas as edições.

### Merge só pelo Sentinela (`platform_merge`)

1. Crie um usuário-robô (ou *project/group access token*) com papel **Maintainer**.
2. Em **Protected branches → Allowed to merge**, deixe **somente** esse usuário. Ninguém
   mais consegue clicar em merge; o botão do Sentinela faz o merge com o SHA aprovado.

### Token da integração

Token de projeto/grupo ou do usuário-robô com escopo `api` (status, notas, merge e
webhook) e `read_repository` (clone). O webhook usa o **Secret token** da integração (veja
em **Integrações → Mostrar segredo do webhook**).

## Webhook

Cada integração tem sua URL (`/webhooks/github/{id}` ou `/webhooks/gitlab/{id}`) e seu
segredo. O botão **Criar webhook** no repositório faz isso pelo token da integração;
manualmente:

- GitHub: *Payload URL* = URL da integração, *Content type* `application/json`, *Secret* =
  segredo, evento **Pull requests**.
- GitLab: *URL* = URL da integração, *Secret token* = segredo, evento **Merge request
  events**.

Sem webhook (ou depois de uma indisponibilidade), **Sincronizar** busca os PRs abertos e
alinha o estado. O reconciliador também republica status que falharam.

## Merge sem gate

Se alguém conseguir fazer merge com o gate travado (bypass de administrador, regra
desligada por engano), o Sentinela marca o PR como **merge sem gate**, mostra no painel e
registra `pull_request.merged_without_gate` na auditoria. Configure um alerta sobre esse
evento.

## Liberação emergencial

Um **administrador global** pode liberar o gate de um commit com motivo obrigatório
(`gate.override`). O status vira sucesso, o comentário do PR registra quem e por quê, e a
auditoria guarda tudo. Os apontamentos continuam abertos e visíveis.
