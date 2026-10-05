# sentinela-console

Console web do Sentinela: React 19 + TypeScript + Vite, com a
[broto-ui](../../broto-ui) para todos os componentes (mesma identidade visual do
Orquestrador).

## Desenvolvimento

```bash
npm ci
npm run dev          # http://localhost:5173, com proxy de /api e /webhooks para a API
npm run lint         # tsc
npm run build
```

A API vem de `SENTINELA_API_UPSTREAM` (padrão `http://localhost:8000`). No modo dev da API,
a tela de login pede só o nome do usuário; com OIDC, o console faz o fluxo PKCE com a
configuração de `GET /api/v1/config`.

## broto-ui

A lib entra pelo pacote em `vendor/broto-ui-0.1.0.tgz` (`"broto-ui": "file:vendor/..."`),
para o build funcionar no Docker e no CI sem depender da pasta vizinha. Para atualizar:

```bash
(cd ../../broto-ui && npm pack) && cp ../../broto-ui/broto-ui-*.tgz vendor/
npm install
```

Quando a broto-ui estiver publicada, troque por `github:SEU_USUARIO/broto-ui#vX.Y.Z` ou pela
versão do npm.

## Produção

`Dockerfile` gera a imagem nginx com a SPA e o proxy de `/api` e `/webhooks` para
`SENTINELA_API_UPSTREAM`.
