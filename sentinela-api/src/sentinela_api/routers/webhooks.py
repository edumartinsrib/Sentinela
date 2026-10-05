"""Webhooks do GitHub (`pull_request`) e do GitLab (`Merge Request Hook`).

Cada integração tem a própria URL (`/webhooks/<provedor>/<id da integração>`) e o próprio
segredo: assinatura HMAC-SHA256 no GitHub, cabeçalho X-Gitlab-Token no GitLab.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from sentinela_api import models as m
from sentinela_api.deps import Session, State
from sentinela_api.providers.base import ProviderError, PullRequestData
from sentinela_api.providers.github import GitHubClient
from sentinela_api.providers.gitlab import GitLabClient
from sentinela_api.services import pull_requests as pr_svc
from sentinela_core.enums import ReviewTrigger

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)

GITHUB_ACTIONS = {
    "opened",
    "reopened",
    "synchronize",
    "ready_for_review",
    "converted_to_draft",
    "edited",
    "closed",
}
GITLAB_IGNORED = {"approved", "unapproved", "approval", "unapproval"}


def _reply(status: int, outcome: str, detail: str) -> JSONResponse:
    return JSONResponse({"outcome": outcome, "detail": detail}, status_code=status)


async def _record(session, integration: m.Integration | None, provider: str, **kw: Any) -> None:
    session.add(
        m.WebhookDelivery(
            integration_id=integration.id if integration else None, provider=provider, **kw
        )
    )
    await session.commit()


async def _integration(session, integration_id: str, provider: str) -> m.Integration | None:
    try:
        ident = uuid.UUID(integration_id)
    except ValueError:
        return None
    integration = await session.get(m.Integration, ident)
    if integration is None or integration.provider != provider or not integration.enabled:
        return None
    return integration


async def _repository(session, integration: m.Integration, full_name: str) -> m.Repository | None:
    return await session.scalar(
        select(m.Repository).where(
            m.Repository.integration_id == integration.id,
            func.lower(m.Repository.full_name) == full_name.lower(),
        )
    )


async def _process(
    session,
    state,
    integration,
    repo: m.Repository,
    data: PullRequestData,
    actor: str,
    delivery: dict[str, Any],
) -> JSONResponse:
    repo.last_webhook_at = datetime.now(UTC)
    pr, review = await pr_svc.handle_event(
        session, state, repo, data, trigger=ReviewTrigger.WEBHOOK, actor=actor
    )
    detail = f"PR #{pr.number} {pr.state}" + (" — revisão enfileirada" if review else "")
    await _record(
        session,
        integration,
        repo.integration.provider,
        outcome="processed",
        detail=detail,
        number=data.number,
        **delivery,
    )
    return _reply(200, "processed", detail)


# ----------------------------------------------------------------------------- GitHub
@router.post("/github/{integration_id}")
async def github(integration_id: str, request: Request, session: Session, state: State):
    body = await request.body()
    integration = await _integration(session, integration_id, "github")
    event = request.headers.get("X-GitHub-Event")
    delivery = {"event": event, "delivery_id": request.headers.get("X-GitHub-Delivery")}
    if integration is None:
        return _reply(404, "rejected", "integração não encontrada")
    secret = await state.providers.webhook_secret(integration)
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new((secret or "").encode(), body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(signature.encode(), expected.encode()):
        await _record(
            session,
            integration,
            "github",
            outcome="rejected",
            detail="assinatura inválida",
            **delivery,
        )
        return _reply(401, "rejected", "assinatura inválida")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _reply(400, "rejected", "JSON inválido")
    full_name = (payload.get("repository") or {}).get("full_name")
    delivery["repository"] = full_name
    if event == "ping":
        await _record(session, integration, "github", outcome="ignored", detail="ping", **delivery)
        return _reply(200, "ignored", "pong")
    action = payload.get("action")
    delivery["action"] = action
    if event != "pull_request" or action not in GITHUB_ACTIONS:
        await _record(
            session,
            integration,
            "github",
            outcome="ignored",
            detail=f"evento {event}/{action} não tratado",
            **delivery,
        )
        return _reply(202, "ignored", f"evento {event}/{action} não tratado")
    repo = await _repository(session, integration, full_name or "")
    if repo is None:
        await _record(
            session,
            integration,
            "github",
            outcome="ignored",
            detail="repositório não cadastrado no Sentinela",
            **delivery,
        )
        return _reply(202, "ignored", "repositório não cadastrado no Sentinela")
    data = GitHubClient._pr(payload["pull_request"])
    actor = (payload.get("sender") or {}).get("login") or "webhook"
    return await _process(session, state, integration, repo, data, actor, delivery)


# ----------------------------------------------------------------------------- GitLab
def _gitlab_payload_pr(payload: dict[str, Any]) -> PullRequestData:
    attrs = payload["object_attributes"]
    state = {"opened": "open", "merged": "merged"}.get(attrs.get("state", ""), "closed")
    last = attrs.get("last_commit") or {}
    return PullRequestData(
        number=int(attrs["iid"]),
        title=attrs.get("title") or "",
        description=attrs.get("description"),
        author_login=None,
        source_branch=attrs["source_branch"],
        target_branch=attrs["target_branch"],
        head_sha=last.get("id") or "",
        base_sha=None,
        web_url=attrs.get("url"),
        state=state,
        draft=bool(attrs.get("draft") or attrs.get("work_in_progress")),
    )


@router.post("/gitlab/{integration_id}")
async def gitlab(integration_id: str, request: Request, session: Session, state: State):
    body = await request.body()
    integration = await _integration(session, integration_id, "gitlab")
    event = request.headers.get("X-Gitlab-Event")
    delivery = {"event": event, "delivery_id": request.headers.get("X-Gitlab-Event-UUID")}
    if integration is None:
        return _reply(404, "rejected", "integração não encontrada")
    secret = await state.providers.webhook_secret(integration)
    token = request.headers.get("X-Gitlab-Token", "")
    if not secret or not hmac.compare_digest(token.encode(), secret.encode()):
        await _record(
            session,
            integration,
            "gitlab",
            outcome="rejected",
            detail="token do webhook inválido",
            **delivery,
        )
        return _reply(401, "rejected", "token do webhook inválido")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _reply(400, "rejected", "JSON inválido")
    full_name = (payload.get("project") or {}).get("path_with_namespace")
    attrs = payload.get("object_attributes") or {}
    action = attrs.get("action")
    delivery.update(repository=full_name, action=action)
    if payload.get("object_kind") != "merge_request" or action in GITLAB_IGNORED:
        await _record(
            session,
            integration,
            "gitlab",
            outcome="ignored",
            detail=f"evento {event}/{action} não tratado",
            **delivery,
        )
        return _reply(202, "ignored", f"evento {event}/{action} não tratado")
    repo = await _repository(session, integration, full_name or "")
    if repo is None:
        await _record(
            session,
            integration,
            "gitlab",
            outcome="ignored",
            detail="repositório não cadastrado no Sentinela",
            **delivery,
        )
        return _reply(202, "ignored", "repositório não cadastrado no Sentinela")
    # O payload não traz o autor nem o base_sha: consulta o MR na API.
    try:
        client = await state.providers.client(integration)
        assert isinstance(client, GitLabClient)
        data = await client.get_pull_request(repo.full_name, int(attrs["iid"]))
    except (ProviderError, KeyError, ValueError) as exc:
        log.warning(
            "GitLab: usando dados do webhook para %s!%s (%s)", full_name, attrs.get("iid"), exc
        )
        data = _gitlab_payload_pr(payload)
    actor = (payload.get("user") or {}).get("username") or "webhook"
    return await _process(session, state, integration, repo, data, actor, delivery)
