"""Conexões com GitHub/GitLab. Token e segredo do webhook ficam no cofre e não voltam pela API
(exceto o segredo do webhook, para o administrador configurá-lo no provedor)."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import Session, State, SuperAdmin, User
from sentinela_api.errors import ApiError, conflict, not_found
from sentinela_api.providers.base import ProviderError
from sentinela_api.services import audit
from sentinela_api.services.secrets import integration_path
from sentinela_api.services.serializers import integration_out, webhook_url
from sentinela_core.enums import Provider

router = APIRouter(prefix="/api/v1/integrations", tags=["integrações"])

DEFAULTS = {
    Provider.GITHUB: ("https://api.github.com", "https://github.com"),
    Provider.GITLAB: ("https://gitlab.com/api/v4", "https://gitlab.com"),
}


def _urls(provider: Provider, api_url: str | None, web_url: str | None) -> tuple[str, str]:
    default_api, default_web = DEFAULTS[provider]
    web = (web_url or "").rstrip("/") or None
    api = (api_url or "").rstrip("/") or None
    if api is None and web and web != default_web:
        api = f"{web}/api/v3" if provider == Provider.GITHUB else f"{web}/api/v4"
    if web is None and api and api != default_api:
        web = api.removesuffix("/api/v3").removesuffix("/api/v4")
    return api or default_api, web or default_web


async def _get(session, integration_id: uuid.UUID) -> m.Integration:
    integration = await session.get(m.Integration, integration_id)
    if integration is None:
        raise not_found("integração")
    return integration


async def _out(session, state, integration: m.Integration) -> s.IntegrationOut:
    secret = await state.secrets.read(integration_path(integration.id))
    count = await session.scalar(
        select(func.count())
        .select_from(m.Repository)
        .where(m.Repository.integration_id == integration.id)
    )
    return integration_out(state.settings, integration, secret, count or 0)


async def _check(state, integration: m.Integration) -> s.IntegrationCheckOut:
    try:
        client = await state.providers.client(integration)
        login = await client.current_user()
        ok, detail = True, f"autenticado como {login}"
    except ProviderError as exc:
        login, ok, detail = None, False, str(exc)
    integration.last_check_at = datetime.now(UTC)
    integration.last_check_ok = ok
    integration.last_check_detail = detail[:1000]
    if login:
        integration.bot_login = login
    return s.IntegrationCheckOut(ok=ok, login=login, detail=detail)


@router.get("", response_model=list[s.IntegrationOut])
async def list_integrations(session: Session, state: State, principal: User):
    rows = (await session.scalars(select(m.Integration).order_by(m.Integration.name))).all()
    return [await _out(session, state, i) for i in rows]


@router.post("", response_model=s.IntegrationOut, status_code=201)
async def create_integration(
    body: s.IntegrationCreate, session: Session, state: State, principal: SuperAdmin
) -> s.IntegrationOut:
    if await session.scalar(select(m.Integration.id).where(m.Integration.name == body.name)):
        raise conflict("já existe uma integração com esse nome")
    api, web = _urls(body.provider, body.api_url, body.web_url)
    integration = m.Integration(
        name=body.name, provider=body.provider.value, api_url=api, web_url=web, enabled=True
    )
    session.add(integration)
    await session.flush()
    await state.secrets.write(
        integration_path(integration.id),
        {"token": body.token, "webhook_secret": body.webhook_secret or secrets.token_urlsafe(32)},
    )
    await _check(state, integration)
    audit.record(
        session,
        actor=principal.username,
        action="integration.create",
        resource_type="integration",
        resource_id=integration.id,
        after=audit.snapshot(integration),
    )
    await session.commit()
    return await _out(session, state, integration)


@router.patch("/{integration_id}", response_model=s.IntegrationOut)
async def update_integration(
    integration_id: uuid.UUID,
    body: s.IntegrationUpdate,
    session: Session,
    state: State,
    principal: SuperAdmin,
) -> s.IntegrationOut:
    integration = await _get(session, integration_id)
    before = audit.snapshot(integration)
    if body.name is not None:
        integration.name = body.name
    if body.api_url is not None or body.web_url is not None:
        integration.api_url, integration.web_url = _urls(
            Provider(integration.provider),
            body.api_url if body.api_url is not None else integration.api_url,
            body.web_url if body.web_url is not None else integration.web_url,
        )
    if body.enabled is not None:
        integration.enabled = body.enabled
    secret = await state.secrets.read(integration_path(integration.id)) or {}
    changed = []
    if body.token:
        secret["token"] = body.token
        changed.append("token")
    if body.webhook_secret or body.rotate_webhook_secret:
        secret["webhook_secret"] = body.webhook_secret or secrets.token_urlsafe(32)
        changed.append("segredo do webhook")
    if changed:
        await state.secrets.write(integration_path(integration.id), secret)
    if body.token or body.api_url is not None:
        await _check(state, integration)
    audit.record(
        session,
        actor=principal.username,
        action="integration.update",
        resource_type="integration",
        resource_id=integration.id,
        before=before,
        after=audit.snapshot(integration),
        detail=("alterado: " + ", ".join(changed)) if changed else None,
    )
    await session.commit()
    return await _out(session, state, integration)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: uuid.UUID, session: Session, state: State, principal: SuperAdmin
) -> Response:
    integration = await _get(session, integration_id)
    used = await session.scalar(
        select(func.count())
        .select_from(m.Repository)
        .where(m.Repository.integration_id == integration.id)
    )
    if used:
        raise conflict(f"a integração tem {used} repositório(s); remova-os antes")
    audit.record(
        session,
        actor=principal.username,
        action="integration.delete",
        resource_type="integration",
        resource_id=integration.id,
        before=audit.snapshot(integration),
    )
    await session.delete(integration)
    await session.commit()
    await state.secrets.delete(integration_path(integration_id))
    return Response(status_code=204)


@router.post("/{integration_id}/check", response_model=s.IntegrationCheckOut)
async def check_integration(
    integration_id: uuid.UUID, session: Session, state: State, principal: SuperAdmin
) -> s.IntegrationCheckOut:
    integration = await _get(session, integration_id)
    result = await _check(state, integration)
    await session.commit()
    return result


@router.get("/{integration_id}/webhook-secret", response_model=s.IntegrationSecretOut)
async def webhook_secret(
    integration_id: uuid.UUID, session: Session, state: State, principal: SuperAdmin
) -> s.IntegrationSecretOut:
    integration = await _get(session, integration_id)
    secret = await state.providers.webhook_secret(integration)
    if not secret:
        raise ApiError(404, "integração sem segredo de webhook; gere um novo")
    audit.record(
        session,
        actor=principal.username,
        action="integration.webhook_secret.read",
        resource_type="integration",
        resource_id=integration.id,
    )
    await session.commit()
    return s.IntegrationSecretOut(
        webhook_url=webhook_url(state.settings, integration), webhook_secret=secret
    )


@router.get("/{integration_id}/remote-repositories", response_model=list[s.RemoteRepositoryOut])
async def remote_repositories(
    integration_id: uuid.UUID,
    session: Session,
    state: State,
    principal: User,
    search: str | None = None,
) -> list[s.RemoteRepositoryOut]:
    if not principal.is_superadmin and not any(
        r in ("admin", "tech_lead") for _, r in principal.bindings
    ):
        raise ApiError(403, "apenas administradores e tech leads")
    integration = await _get(session, integration_id)
    try:
        client = await state.providers.client(integration)
        repos = await client.list_repositories(search)
    except ProviderError as exc:
        raise ApiError(502, f"não foi possível listar os repositórios: {exc}") from exc
    imported = dict(
        (
            await session.execute(
                select(m.Repository.full_name, m.Team.name)
                .join(m.Team, m.Team.id == m.Repository.team_id)
                .where(m.Repository.integration_id == integration.id)
            )
        ).all()
    )
    return [
        s.RemoteRepositoryOut(
            full_name=r.full_name,
            external_id=r.external_id,
            default_branch=r.default_branch,
            web_url=r.web_url,
            private=r.private,
            imported_in=imported.get(r.full_name),
        )
        for r in repos[:200]
    ]


@router.get("/{integration_id}/deliveries", response_model=list[s.WebhookDeliveryOut])
async def deliveries(
    integration_id: uuid.UUID, session: Session, principal: SuperAdmin
) -> list[s.WebhookDeliveryOut]:
    """Últimas entregas de webhook recebidas (diagnóstico)."""
    await _get(session, integration_id)
    rows = (
        await session.scalars(
            select(m.WebhookDelivery)
            .where(m.WebhookDelivery.integration_id == integration_id)
            .order_by(m.WebhookDelivery.received_at.desc())
            .limit(50)
        )
    ).all()
    return [
        s.WebhookDeliveryOut(
            id=d.id,
            received_at=d.received_at,
            event=d.event,
            action=d.action,
            repository=d.repository,
            number=d.number,
            outcome=d.outcome,
            detail=d.detail,
        )
        for d in rows
    ]
