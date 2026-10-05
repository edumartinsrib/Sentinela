"""Runners e tokens de registro (console, administradores globais)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response
from sqlalchemy import select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import Session, SuperAdmin, User
from sentinela_api.errors import conflict, not_found
from sentinela_api.services import audit
from sentinela_api.services import runners as svc
from sentinela_api.services.serializers import runner_out

router = APIRouter(prefix="/api/v1", tags=["runners"])


def _token_out(t: m.RunnerRegistrationToken) -> s.RegistrationTokenOut:
    return s.RegistrationTokenOut(
        id=str(t.id),
        description=t.description,
        created_by=t.created_by,
        created_at=t.created_at,
        expires_at=t.expires_at,
        revoked_at=t.revoked_at,
        last_used_at=t.last_used_at,
    )


@router.get("/runners", response_model=list[s.RunnerOut])
async def list_runners(session: Session, principal: User) -> list[s.RunnerOut]:
    rows = (await session.scalars(select(m.Runner).order_by(m.Runner.name))).all()
    return [runner_out(r) for r in rows]


@router.patch("/runners/{runner_id}", response_model=s.RunnerOut)
async def update_runner(
    runner_id: uuid.UUID, body: s.RunnerUpdate, session: Session, principal: SuperAdmin
) -> s.RunnerOut:
    runner = await session.get(m.Runner, runner_id)
    if runner is None:
        raise not_found("runner")
    before = audit.snapshot(runner)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(runner, key, value)
    audit.record(
        session,
        actor=principal.username,
        action="runner.update",
        resource_type="runner",
        resource_id=runner.id,
        before=before,
        after=audit.snapshot(runner),
    )
    await session.commit()
    return runner_out(runner)


@router.delete("/runners/{runner_id}", status_code=204)
async def delete_runner(runner_id: uuid.UUID, session: Session, principal: SuperAdmin) -> Response:
    runner = await session.get(m.Runner, runner_id)
    if runner is None:
        raise not_found("runner")
    if runner.status == "online" and runner.running_reviews:
        raise conflict("o runner está executando revisões; drene antes de remover")
    audit.record(
        session,
        actor=principal.username,
        action="runner.delete",
        resource_type="runner",
        resource_id=runner.id,
        before=audit.snapshot(runner),
    )
    await session.delete(runner)
    await session.commit()
    return Response(status_code=204)


@router.get("/runner-tokens", response_model=list[s.RegistrationTokenOut])
async def list_tokens(session: Session, principal: SuperAdmin) -> list[s.RegistrationTokenOut]:
    rows = (
        await session.scalars(
            select(m.RunnerRegistrationToken).order_by(m.RunnerRegistrationToken.created_at.desc())
        )
    ).all()
    return [_token_out(t) for t in rows]


@router.post("/runner-tokens", response_model=s.RegistrationTokenCreated, status_code=201)
async def create_token(
    body: s.RegistrationTokenCreate, session: Session, principal: SuperAdmin
) -> s.RegistrationTokenCreated:
    reg, token = await svc.create_registration_token(
        session, body.description, principal.username, body.expires_in_days
    )
    audit.record(
        session,
        actor=principal.username,
        action="runner_token.create",
        resource_type="runner_token",
        resource_id=reg.id,
        detail=body.description,
    )
    await session.commit()
    await session.refresh(reg)
    return s.RegistrationTokenCreated(**_token_out(reg).model_dump(), token=token)


@router.delete("/runner-tokens/{token_id}", status_code=204)
async def revoke_token(token_id: uuid.UUID, session: Session, principal: SuperAdmin) -> Response:
    reg = await session.get(m.RunnerRegistrationToken, token_id)
    if reg is None:
        raise not_found("token")
    reg.revoked_at = datetime.now(UTC)
    audit.record(
        session,
        actor=principal.username,
        action="runner_token.revoke",
        resource_type="runner_token",
        resource_id=reg.id,
    )
    await session.commit()
    return Response(status_code=204)
