"""Laço de manutenção: leases vencidas, runners sem sinal, status que falharam ao publicar
e conferência de adulteração do status do gate no provedor."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from sentinela_api import models as m
from sentinela_api.db import sessionmaker
from sentinela_api.providers.base import ProviderError
from sentinela_api.services import audit, gates, reviews, runners
from sentinela_api.state import AppState
from sentinela_core.enums import FINAL_GATE, PASSING_GATE, Enforcement, PullRequestState

log = logging.getLogger(__name__)


async def retry_publications(state: AppState, limit: int = 20) -> int:
    async with sessionmaker()() as session:
        ids = (
            await session.scalars(
                select(m.Gate.id)
                .where(
                    m.Gate.publish_error.is_not(None),
                    m.Gate.status.notin_([s.value for s in FINAL_GATE]),
                )
                .order_by(m.Gate.updated_at)
                .limit(limit)
            )
        ).all()
        for gate_id in ids:
            await gates.publish(session, state, gate_id, comment=True)
    return len(ids)


async def tamper_check(state: AppState, limit: int = 50) -> int:
    """Se o status do Sentinela aparece como sucesso no provedor sem o gate liberado,
    alguém publicou por fora: republica o status correto e registra na auditoria."""
    found = 0
    async with sessionmaker()() as session:
        prs = (
            (
                await session.scalars(
                    select(m.PullRequest)
                    .join(m.Gate, m.PullRequest.current_gate_id == m.Gate.id)
                    .where(
                        m.PullRequest.state == PullRequestState.OPEN,
                        m.Gate.status.notin_([s.value for s in (*PASSING_GATE, *FINAL_GATE)]),
                        m.Gate.published_state.is_not(None),
                    )
                    .order_by(m.Gate.updated_at.desc())
                    .limit(limit)
                )
            )
            .unique()
            .all()
        )
        for pr in prs:
            repo = pr.repository
            gate = pr.current_gate
            if gate is None or repo.enforcement == Enforcement.OBSERVE:
                continue
            if not gates.uses_status_check(repo):
                continue
            try:
                client = await state.providers.client(repo.integration)
                remote = await client.get_status(repo.full_name, gate.head_sha, repo.status_context)
            except ProviderError as exc:
                log.debug(
                    "conferência de status falhou para %s#%s: %s", repo.full_name, pr.number, exc
                )
                continue
            if remote == "success":
                found += 1
                audit.record(
                    session,
                    actor="sentinela",
                    actor_type="system",
                    action="gate.status_tampered",
                    resource_type="gate",
                    resource_id=gate.id,
                    team_id=pr.team_id,
                    detail=f"{repo.full_name}#{pr.number}: status {repo.status_context} estava "
                    f"como sucesso com o gate em {gate.status}; status republicado",
                )
                gate.published_state = None
                await session.commit()
                await gates.publish(session, state, gate.id)
    return found


async def run_once(state: AppState, *, tamper: bool) -> None:
    requeued = await reviews.requeue_expired(state)
    if requeued:
        log.warning("%d revisões com lease vencida voltaram para a fila", requeued)
    await runners.mark_offline(state.settings)
    await retry_publications(state)
    if tamper:
        await tamper_check(state)


async def run_forever(state: AppState) -> None:
    settings = state.settings
    last_tamper = datetime.now(UTC) - timedelta(seconds=settings.tamper_check_interval_s)
    while True:
        await asyncio.sleep(settings.reconcile_interval_s)
        try:
            now = datetime.now(UTC)
            tamper = (
                settings.tamper_check_enabled
                and (now - last_tamper).total_seconds() >= settings.tamper_check_interval_s
            )
            if tamper:
                last_tamper = now
            await run_once(state, tamper=tamper)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("falha no reconciliador")
