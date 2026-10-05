"""Registro, autenticação e heartbeat dos runners."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.db import sessionmaker
from sentinela_api.errors import ApiError
from sentinela_api.schemas import RunnerConfig, RunnerRegister
from sentinela_api.security.tokens import (
    REGISTRATION_PREFIX,
    RUNNER_PREFIX,
    hash_secret,
    make_token,
    parse_token,
    verify_secret,
)
from sentinela_api.settings import Settings
from sentinela_core.enums import ReviewStatus, RunnerStatus

log = logging.getLogger(__name__)
HEARTBEAT_INTERVAL_S = 10


def _now() -> datetime:
    return datetime.now(UTC)


def runner_config(settings: Settings, runner: m.Runner) -> RunnerConfig:
    return RunnerConfig(
        runner_id=str(runner.id),
        runner_name=runner.name,
        heartbeat_interval_s=HEARTBEAT_INTERVAL_S,
        claim_wait_s=settings.claim_wait_s,
        enabled=runner.enabled,
        draining=runner.draining,
    )


async def register(
    session: AsyncSession, body: RunnerRegister, settings: Settings
) -> tuple[m.Runner, str]:
    parsed = parse_token(body.registration_token, REGISTRATION_PREFIX)
    if parsed is None:
        raise ApiError(401, "token de registro inválido")
    token_id, secret = parsed
    reg = await session.get(m.RunnerRegistrationToken, token_id)
    now = _now()
    if (
        reg is None
        or reg.revoked_at is not None
        or (reg.expires_at is not None and reg.expires_at < now)
        or not verify_secret(secret, reg.token_hash)
    ):
        raise ApiError(401, "token de registro inválido, revogado ou vencido")
    reg.last_used_at = now
    runner = await session.scalar(
        select(m.Runner).where(m.Runner.name == body.name).with_for_update()
    )
    if runner is not None:
        # Reaproveitar o nome é para o runner que perdeu a identidade (volume apagado).
        # Com o original ainda ativo, seria tomar o lugar dele e das revisões em curso.
        recent = runner.last_heartbeat_at and runner.last_heartbeat_at > now - timedelta(
            seconds=settings.runner_offline_after_s
        )
        if recent:
            raise ApiError(409, f"já existe um runner ativo chamado {body.name}")
        orphan = (
            await session.scalars(
                select(m.Review).where(
                    m.Review.runner_id == runner.id, m.Review.status == ReviewStatus.RUNNING
                )
            )
        ).all()
        for review in orphan:
            review.status = ReviewStatus.QUEUED
            review.runner_id = None
            review.phase = None
            review.lease_expires_at = None
    runner_id = runner.id if runner else uuid.uuid4()
    token, digest = make_token(RUNNER_PREFIX, runner_id)
    if runner is None:
        runner = m.Runner(id=runner_id, name=body.name, secret_hash=digest)
        session.add(runner)
    runner.secret_hash = digest
    runner.hostname = body.hostname
    runner.os = body.os
    runner.labels = body.labels
    runner.engines = body.engines
    runner.slots = body.slots
    runner.agent_version = body.agent_version
    runner.status = RunnerStatus.ONLINE
    runner.last_heartbeat_at = now
    await session.commit()
    log.info("runner %s registrado", runner.name)
    return runner, token


async def authenticate(session: AsyncSession, token: str) -> m.Runner:
    parsed = parse_token(token, RUNNER_PREFIX)
    if parsed is None:
        raise ApiError(401, "token de runner inválido")
    runner_id, secret = parsed
    runner = await session.get(m.Runner, runner_id)
    if runner is None or not verify_secret(secret, runner.secret_hash):
        raise ApiError(401, "token de runner inválido")
    return runner


async def touch(
    session: AsyncSession,
    runner: m.Runner,
    running: list[str],
    engines: dict[str, str] | None,
    slots: int | None,
) -> None:
    runner.last_heartbeat_at = _now()
    runner.status = RunnerStatus.ONLINE
    runner.running_reviews = running
    if engines is not None:
        runner.engines = engines
    if slots is not None:
        runner.slots = slots


async def mark_offline(settings: Settings) -> int:
    limit = _now() - timedelta(seconds=settings.runner_offline_after_s)
    async with sessionmaker()() as session:
        result = await session.execute(
            update(m.Runner)
            .where(m.Runner.status == RunnerStatus.ONLINE, m.Runner.last_heartbeat_at < limit)
            .values(status=RunnerStatus.OFFLINE, running_reviews=[])
        )
        await session.commit()
        return result.rowcount or 0


async def create_registration_token(
    session: AsyncSession, description: str, created_by: str | None, expires_in_days: int | None
) -> tuple[m.RunnerRegistrationToken, str]:
    token_id = uuid.uuid4()
    token, digest = make_token(REGISTRATION_PREFIX, token_id)
    reg = m.RunnerRegistrationToken(
        id=token_id,
        description=description,
        token_hash=digest,
        created_by=created_by,
        expires_at=_now() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    session.add(reg)
    await session.flush()
    return reg, token


async def bootstrap_registration_token(session: AsyncSession, token: str) -> None:
    parsed = parse_token(token, REGISTRATION_PREFIX)
    if parsed is None:
        log.warning("SENTINELA_BOOTSTRAP_RUNNER_TOKEN inválido (esperado snt_reg_<uuid>.<segredo>)")
        return
    token_id, secret = parsed
    if await session.get(m.RunnerRegistrationToken, token_id) is not None:
        return
    session.add(
        m.RunnerRegistrationToken(
            id=token_id,
            description="bootstrap (ambiente de desenvolvimento)",
            token_hash=hash_secret(secret),
            created_by="system",
        )
    )
