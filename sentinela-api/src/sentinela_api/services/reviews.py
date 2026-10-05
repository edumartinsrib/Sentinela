"""Fila de revisões no Postgres: criação, reivindicação pelo runner (SKIP LOCKED),
heartbeat, conclusão com os achados, falha, cancelamento e retomada de leases vencidas."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.db import lock_row, sessionmaker
from sentinela_api.errors import ApiError, conflict
from sentinela_api.schemas import (
    ClaimedEngine,
    ClaimedPullRequest,
    ClaimedRepository,
    ClaimedReview,
    GitCredentials,
)
from sentinela_api.services import ai, gates, standards
from sentinela_api.services.events import QUEUE_CHANNEL, review_channel
from sentinela_api.state import AppState
from sentinela_core.enums import (
    ACTIVE_REVIEW,
    FINAL_GATE,
    FindingStatus,
    GateStatus,
    ReviewStatus,
    ReviewTrigger,
    Severity,
)
from sentinela_core.findings import ReviewResult
from sentinela_core.gate import FindingState, requires_human

log = logging.getLogger(__name__)

PHASES = {
    "claimed": "Reivindicada pelo runner",
    "cloning": "Baixando o código",
    "diff": "Calculando o diff",
    "patterns": "Aplicando regras de padrão",
    "ai": "Revisando com IA",
    "reporting": "Enviando o resultado",
}


def _now() -> datetime:
    return datetime.now(UTC)


# ----------------------------------------------------------------------------- criação
async def enqueue(
    session: AsyncSession,
    state: AppState,
    *,
    gate: m.Gate,
    pr: m.PullRequest,
    repo: m.Repository,
    trigger: ReviewTrigger,
    requested_by: str | None,
    model_override: uuid.UUID | None = None,
) -> m.Review:
    """Cria a revisão na fila e aponta o gate para ela. Aprovações anteriores deixam de
    valer; reprovações do mesmo commit continuam (ver gates.current_decisions)."""
    await cancel_active(session, gate.id, reason="substituída por nova revisão")
    profiles = [p for p in repo.profiles if p.enabled]
    model = await ai.resolve_model(session, repo, profiles, model_override)
    review = m.Review(
        gate_id=gate.id,
        pull_request_id=pr.id,
        team_id=pr.team_id,
        head_sha=gate.head_sha,
        trigger=trigger.value,
        requested_by=requested_by,
        profiles_snapshot=standards.snapshot(profiles),
        status=ReviewStatus.QUEUED,
    )
    if model is None:
        review.engine_kind = "none"
        review.status = ReviewStatus.FAILED
        review.error = "Nenhum modelo de IA habilitado. Configure em Administração → IA e modelos."
        review.finished_at = _now()
    else:
        review.engine_id = model.engine_id
        review.engine_kind = model.engine.kind
        review.model = model.model
        review.model_label = model.label
    if not profiles and review.status == ReviewStatus.QUEUED:
        review.status = ReviewStatus.FAILED
        review.error = "O repositório não tem perfil de padrão habilitado."
        review.finished_at = _now()
    session.add(review)
    await session.flush()
    gate.current_review_id = review.id
    gate.override_by = None
    gate.override_reason = None
    gate.human_required = True
    await gates.recompute(session, gate)
    return review


async def cancel_active(session: AsyncSession, gate_id: uuid.UUID, *, reason: str) -> list[str]:
    """Cancela revisões em fila/execução do gate. As em execução recebem o pedido no heartbeat."""
    rows = (
        await session.scalars(
            select(m.Review).where(
                m.Review.gate_id == gate_id, m.Review.status.in_([s.value for s in ACTIVE_REVIEW])
            )
        )
    ).all()
    ids = []
    for review in rows:
        ids.append(str(review.id))
        review.cancel_requested = True
        review.status = ReviewStatus.CANCELED
        review.error = reason
        review.finished_at = _now()
    return ids


async def wake_runners(state: AppState) -> None:
    await state.bus.publish(QUEUE_CHANNEL, "queued", {})


# ----------------------------------------------------------------------------- runner
async def _try_claim(state: AppState, runner_id: uuid.UUID, engines: list[str]) -> uuid.UUID | None:
    async with sessionmaker()() as session:
        review = await session.scalar(
            select(m.Review)
            .where(m.Review.status == ReviewStatus.QUEUED, m.Review.engine_kind.in_(engines))
            .order_by(m.Review.created_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=m.Review)
        )
        if review is None:
            return None
        review.status = ReviewStatus.RUNNING
        review.runner_id = runner_id
        review.attempt += 1
        review.started_at = _now()
        review.finished_at = None
        review.error = None
        review.phase = "claimed"
        review.lease_expires_at = _now() + timedelta(seconds=state.settings.review_lease_s)
        await session.commit()
        return review.id


async def claim(
    state: AppState, runner: m.Runner, engines: list[str], wait_s: float
) -> uuid.UUID | None:
    """Long-poll: tenta pegar uma revisão até `wait_s` segundos."""
    if not runner.enabled or runner.draining or not engines:
        return None
    deadline = asyncio.get_running_loop().time() + wait_s
    while True:
        review_id = await _try_claim(state, runner.id, engines)
        if review_id is not None:
            return review_id
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None
        await asyncio.sleep(min(1.0, remaining))


async def claim_payload(session: AsyncSession, state: AppState, review: m.Review) -> ClaimedReview:
    pr = review.pull_request
    repo = pr.repository
    integration = repo.integration
    token = await state.providers.token(integration)
    client = state.providers.build(integration, token)
    engine = await session.get(m.AiEngine, review.engine_id) if review.engine_id else None
    env = await ai.engine_env(state.secrets, engine) if engine else {}
    mask = [token, *env.values()]
    return ClaimedReview(
        id=str(review.id),
        attempt=review.attempt,
        team=repo.team.name,
        pull_request=ClaimedPullRequest(
            number=pr.number,
            title=pr.title,
            description=pr.description,
            author=pr.author_login,
            source_branch=pr.source_branch,
            target_branch=pr.target_branch,
            head_sha=review.head_sha,
            base_sha=pr.base_sha,
            web_url=pr.web_url,
        ),
        repository=ClaimedRepository(
            full_name=repo.full_name,
            provider=integration.provider,
            clone_url=repo.clone_url or client.clone_url(repo.full_name),
            web_url=repo.web_url,
        ),
        git=GitCredentials(username=client.clone_username, token=token),
        profiles=review.profiles_snapshot,
        engine=ClaimedEngine(
            kind=review.engine_kind,
            name=engine.name if engine else review.engine_kind,
            model=review.model,
            model_label=review.model_label,
            max_turns=engine.max_turns if engine else 30,
            timeout_s=engine.timeout_s if engine else 900,
            max_budget_usd=engine.max_budget_usd if engine else None,
            extra_args=list(engine.extra_args or []) if engine else [],
            env=env,
        ),
        max_diff_chars=state.settings.max_diff_chars,
        mask_values=[v for v in mask if v and len(v) >= 4],
    )


async def _lock_review(session: AsyncSession, review_id: uuid.UUID) -> m.Review | None:
    """Trava a revisão e relê do banco: conclusão, falha e retomada da lease não correm
    em paralelo sobre a mesma revisão (o runner pode reenviar depois de um timeout)."""
    return await lock_row(session, m.Review, review_id)


async def runner_review(session: AsyncSession, runner: m.Runner, review_id: str) -> m.Review:
    try:
        rid = uuid.UUID(review_id)
    except ValueError as exc:
        raise ApiError(404, "revisão não encontrada") from exc
    review = await session.get(m.Review, rid)
    if review is None:
        raise ApiError(404, "revisão não encontrada")
    if review.runner_id != runner.id:
        raise ApiError(403, "revisão não pertence a este runner")
    return review


async def heartbeat(session: AsyncSession, state: AppState, runner: m.Runner, running: list[str]):
    """Renova as leases e devolve as revisões que o runner deve abandonar."""
    cancel: list[str] = []
    ids = []
    for rid in running:
        try:
            ids.append(uuid.UUID(rid))
        except ValueError:
            cancel.append(rid)
    if not ids:
        return cancel
    rows = (await session.scalars(select(m.Review).where(m.Review.id.in_(ids)))).all()
    found = {r.id: r for r in rows}
    lease = _now() + timedelta(seconds=state.settings.review_lease_s)
    for rid in ids:
        review = found.get(rid)
        if (
            review is None
            or review.runner_id != runner.id
            or review.status != ReviewStatus.RUNNING
            or review.cancel_requested
        ):
            cancel.append(str(rid))
            continue
        review.lease_expires_at = lease
    return cancel


async def set_phase(
    session: AsyncSession, state: AppState, review: m.Review, phase: str, detail: str | None
) -> None:
    if review.status != ReviewStatus.RUNNING:
        raise conflict("a revisão não está em execução")
    review.phase = phase
    review.lease_expires_at = _now() + timedelta(seconds=state.settings.review_lease_s)
    await session.commit()
    data = {
        "review_id": str(review.id),
        "phase": phase,
        "label": PHASES.get(phase, phase),
        "detail": detail,
    }
    await state.bus.publish(review_channel(str(review.id)), "phase", data)
    await gates.notify(state, review.pull_request.repository.team.name, "review", data)


async def _previous_decisions(
    session: AsyncSession, pr_id: uuid.UUID, fingerprints: set[str], review_id: uuid.UUID
) -> dict[str, m.Finding]:
    """Justificativas/falsos positivos do mesmo PR, por impressão digital. Vale só a
    ocorrência mais recente: um apontamento reaberto depois não volta a ser herdado."""
    if not fingerprints:
        return {}
    rows = await session.scalars(
        select(m.Finding)
        .where(
            m.Finding.pull_request_id == pr_id,
            m.Finding.review_id != review_id,
            m.Finding.fingerprint.in_(fingerprints),
        )
        .order_by(m.Finding.created_at.desc(), m.Finding.id)
    )
    latest: dict[str, m.Finding] = {}
    for f in rows.all():
        latest.setdefault(f.fingerprint, f)
    return {
        fp: f
        for fp, f in latest.items()
        if f.status in (FindingStatus.WAIVED, FindingStatus.FALSE_POSITIVE)
    }


async def _earlier_findings(
    session: AsyncSession, gate_id: uuid.UUID, review_id: uuid.UUID
) -> list[FindingState]:
    rows = await session.scalars(
        select(m.Finding).where(m.Finding.gate_id == gate_id, m.Finding.review_id != review_id)
    )
    return [FindingState(Severity(f.severity), FindingStatus(f.status)) for f in rows.all()]


async def complete(
    session: AsyncSession,
    state: AppState,
    review: m.Review,
    result: ReviewResult,
    runner_id: uuid.UUID | None = None,
) -> None:
    locked = await _lock_review(session, review.id)
    if (
        locked is None
        or locked.status != ReviewStatus.RUNNING
        or (runner_id is not None and locked.runner_id != runner_id)
    ):
        # cancelada, substituída, já concluída ou devolvida à fila enquanto rodava
        log.info("resultado descartado da revisão %s (%s)", review.id, review.status)
        await session.rollback()
        return
    review = locked
    gate = await gates.lock(session, review.gate_id)
    pr = review.pull_request
    carry = bool((gate.policy or {}).get("carry_waivers", True))
    previous = (
        await _previous_decisions(
            session, pr.id, {f.fingerprint for f in result.findings}, review.id
        )
        if carry
        else {}
    )
    now = _now()
    states: list[FindingState] = []
    for item in result.findings:
        finding = m.Finding(
            review_id=review.id,
            gate_id=gate.id,
            pull_request_id=pr.id,
            team_id=review.team_id,
            rule_code=item.rule_code,
            rule_title=_rule_title(review, item.rule_code),
            profile_name=item.profile,
            source=item.source.value,
            category=item.category.value,
            severity=item.severity.value,
            file=item.file,
            line=item.line,
            end_line=item.end_line,
            title=item.title,
            description=item.description,
            suggestion=item.suggestion,
            evidence=item.evidence,
            confidence=item.confidence,
            in_diff=item.in_diff,
            fingerprint=item.fingerprint,
            status=FindingStatus.OPEN,
        )
        prior = previous.get(item.fingerprint)
        if prior is not None:
            finding.status = prior.status
            finding.status_reason = prior.status_reason
            finding.status_by = prior.status_by
            finding.status_at = now
            finding.inherited = True
        session.add(finding)
        states.append(FindingState(Severity(finding.severity), FindingStatus(finding.status)))
    stats = dict(result.stats or {})
    stats["findings"] = len(result.findings)
    stats["inherited"] = sum(1 for f in result.findings if f.fingerprint in previous)
    review.status = ReviewStatus.COMPLETED
    review.summary = result.summary or None
    review.stats = stats
    review.finished_at = now
    review.phase = None
    review.lease_expires_at = None
    await session.flush()
    if gate.current_review_id == review.id and gate.status not in FINAL_GATE:
        # Uma vez que o commit teve apontamento, reexecutar não devolve a decisão à IA.
        policy = gates.gate_policy(gate)
        earlier = await _earlier_findings(session, gate.id, review.id)
        gate.human_required = requires_human(states, policy) or requires_human(earlier, policy)
        await gates.recompute(session, gate)
    await session.commit()
    await _after_change(session, state, review, gate)


def _rule_title(review: m.Review, code: str) -> str | None:
    for profile in review.profiles_snapshot or []:
        for rule in profile.get("rules", []):
            if rule.get("code") == code:
                return rule.get("title")
    return None


async def fail(
    session: AsyncSession,
    state: AppState,
    review: m.Review,
    error: str,
    retryable: bool,
    *,
    runner_id: uuid.UUID | None = None,
    only_if_expired: bool = False,
) -> None:
    locked = await _lock_review(session, review.id)
    if (
        locked is None
        or locked.status != ReviewStatus.RUNNING
        or (runner_id is not None and locked.runner_id != runner_id)
        or (
            only_if_expired
            and locked.lease_expires_at is not None
            and locked.lease_expires_at >= _now()
        )
    ):
        await session.rollback()
        return
    review = locked
    gate = await gates.lock(session, review.gate_id)
    if retryable and review.attempt < state.settings.review_max_attempts:
        review.status = ReviewStatus.QUEUED
        review.runner_id = None
        review.phase = None
        review.error = error[:4000]
        review.lease_expires_at = None
        await session.commit()
        await wake_runners(state)
        await _notify_review(state, review)
        return
    review.status = ReviewStatus.FAILED
    review.error = error[:20_000]
    review.finished_at = _now()
    review.phase = None
    review.lease_expires_at = None
    if gate.current_review_id == review.id and gate.status not in FINAL_GATE:
        await gates.recompute(session, gate)
    await session.commit()
    await _after_change(session, state, review, gate)


async def _notify_review(state: AppState, review: m.Review) -> None:
    data = {
        "review_id": str(review.id),
        "pull_request_id": str(review.pull_request_id),
        "status": review.status,
    }
    await state.bus.publish(review_channel(str(review.id)), "status", data)
    await gates.notify(state, review.pull_request.repository.team.name, "review", data)


async def _after_change(
    session: AsyncSession, state: AppState, review: m.Review, gate: m.Gate
) -> None:
    await _notify_review(state, review)
    await gates.publish(session, state, gate.id, comment=True)
    await gates.notify(
        state,
        review.pull_request.repository.team.name,
        "gate",
        {"pull_request_id": str(review.pull_request_id), "status": gate.status},
    )


async def requeue_expired(state: AppState) -> int:
    """Revisões cujo runner parou de dar sinal voltam para a fila (ou falham)."""
    count = 0
    async with sessionmaker()() as session:
        rows = (
            await session.scalars(
                select(m.Review)
                .where(m.Review.status == ReviewStatus.RUNNING, m.Review.lease_expires_at < _now())
                .with_for_update(skip_locked=True, of=m.Review)
            )
        ).all()
        ids = [r.id for r in rows]
        await session.rollback()
        for review_id in ids:
            # cada uma é travada e conferida de novo: o heartbeat pode ter chegado no meio
            review = await session.get(m.Review, review_id)
            if review is None:
                continue
            await fail(
                session,
                state,
                review,
                "o runner parou de responder durante a revisão",
                retryable=True,
                only_if_expired=True,
            )
            count += 1
    return count


async def mark_superseded_gates(session: AsyncSession, pr: m.PullRequest, keep: uuid.UUID) -> None:
    await session.execute(
        update(m.Gate)
        .where(
            m.Gate.pull_request_id == pr.id,
            m.Gate.id != keep,
            m.Gate.status.notin_([s.value for s in FINAL_GATE]),
        )
        .values(status=GateStatus.STALE, status_description="Substituído por um commit mais novo")
    )
