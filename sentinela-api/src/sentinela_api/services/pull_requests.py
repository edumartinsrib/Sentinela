"""Estado dos PRs a partir dos webhooks (ou da sincronização): cria o gate de cada commit
novo, enfileira a revisão e detecta merge sem gate liberado."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.db import lock_row
from sentinela_api.providers.base import ProviderError, PullRequestData
from sentinela_api.services import audit, gates, reviews
from sentinela_api.state import AppState
from sentinela_core.enums import (
    FINAL_GATE,
    PASSING_GATE,
    GateStatus,
    PullRequestState,
    ReviewStatus,
    ReviewTrigger,
)
from sentinela_core.paths import glob_match

log = logging.getLogger(__name__)


def is_gated_branch(repo: m.Repository, branch: str) -> bool:
    patterns = repo.gated_branches or [repo.default_branch]
    return any(glob_match(branch, p) for p in patterns)


async def _locked_pr(
    session: AsyncSession, repo: m.Repository, number: int
) -> m.PullRequest | None:
    pr_id = await session.scalar(
        select(m.PullRequest.id).where(
            m.PullRequest.repository_id == repo.id, m.PullRequest.number == number
        )
    )
    return await lock_row(session, m.PullRequest, pr_id) if pr_id is not None else None


async def _get_or_create(
    session: AsyncSession, repo: m.Repository, data: PullRequestData
) -> tuple[m.PullRequest, bool]:
    """Devolve o PR travado: webhooks simultâneos do mesmo PR são tratados um de cada vez."""
    pr = await _locked_pr(session, repo, data.number)
    if pr is not None:
        return pr, False
    pr = m.PullRequest(
        repository=repo,
        team_id=repo.team_id,
        current_gate=None,
        number=data.number,
        title=data.title[:500],
        source_branch=data.source_branch,
        target_branch=data.target_branch,
        head_sha=data.head_sha,
        state=PullRequestState.OPEN,
    )
    try:
        async with session.begin_nested():
            session.add(pr)
            await session.flush()
    except IntegrityError:
        # outro webhook criou o mesmo PR ao mesmo tempo: usa o dele
        if pr in session:
            session.expunge(pr)
        existing = await _locked_pr(session, repo, data.number)
        if existing is None:
            raise
        return existing, False
    return pr, True


async def _provider_head(state: AppState, repo: m.Repository, number: int) -> str | None:
    try:
        client = await state.providers.client(repo.integration)
        return (await client.get_pull_request(repo.full_name, number)).head_sha
    except ProviderError as exc:
        log.warning("não foi possível confirmar o head de %s#%s: %s", repo.full_name, number, exc)
        return None


async def handle_event(
    session: AsyncSession,
    state: AppState,
    repo: m.Repository,
    data: PullRequestData,
    *,
    trigger: ReviewTrigger,
    actor: str = "webhook",
) -> tuple[m.PullRequest, m.Review | None]:
    """Aplica o estado do PR vindo do provedor. Devolve o PR e a revisão criada (se houver)."""
    pr, _ = await _get_or_create(session, repo, data)
    pr.title = data.title[:500]
    pr.description = data.description
    if data.author_login:
        # Nunca apaga o autor conhecido: sem ele, ninguém consegue provar que não é o autor.
        pr.author_login = data.author_login
    pr.source_branch = data.source_branch
    pr.target_branch = data.target_branch
    pr.web_url = data.web_url
    pr.draft = data.draft
    if data.base_sha:
        pr.base_sha = data.base_sha
    gate = pr.current_gate

    # ------------------------------------------------------------ fechado ou merge
    if data.state != PullRequestState.OPEN:
        was_open = pr.state == PullRequestState.OPEN
        pr.state = data.state
        if gate is not None and gate.status not in FINAL_GATE:
            await reviews.cancel_active(session, gate.id, reason="PR fechado")
        if data.state == PullRequestState.MERGED and was_open:
            pr.merged_at = pr.merged_at or datetime.now(UTC)
            pr.merged_by = pr.merged_by or data.merged_by
            passed = gate is not None and (
                gate.status in PASSING_GATE or gate.status == GateStatus.MERGED
            )
            if pr.gated and not passed:
                pr.merged_without_gate = True
                audit.record(
                    session,
                    actor=data.merged_by or "provedor",
                    actor_type="provider",
                    action="pull_request.merged_without_gate",
                    resource_type="pull_request",
                    resource_id=pr.id,
                    team_id=pr.team_id,
                    detail=f"{repo.full_name}#{pr.number} recebeu merge com o gate em "
                    f"{gate.status if gate else 'sem gate'}",
                )
            if gate is not None:
                gate.status = GateStatus.MERGED
                gate.status_description = "Merge realizado"
        await session.commit()
        await gates.notify(state, repo.team.name, "pull_request", {"pull_request_id": str(pr.id)})
        return pr, None

    pr.state = PullRequestState.OPEN
    gated = (
        repo.enabled
        and is_gated_branch(repo, data.target_branch)
        and (repo.review_drafts or not data.draft)
    )
    pr.gated = gated
    if not gated:
        pr.head_sha = data.head_sha
        await session.commit()
        await gates.notify(state, repo.team.name, "pull_request", {"pull_request_id": str(pr.id)})
        return pr, None

    current_review = (
        await session.get(m.Review, gate.current_review_id)
        if gate is not None and gate.current_review_id
        else None
    )
    same_commit = (
        gate is not None
        and gate.head_sha == data.head_sha
        and gate.target_branch == data.target_branch
        and gate.status not in FINAL_GATE
        # PR reaberto: a revisão cancelada no fechamento precisa rodar de novo
        and current_review is not None
        and current_review.status != ReviewStatus.CANCELED
    )
    if same_commit and trigger != ReviewTrigger.MANUAL:
        pr.head_sha = data.head_sha
        await session.commit()
        return pr, None

    target = await session.scalar(
        select(m.Gate).where(m.Gate.pull_request_id == pr.id, m.Gate.head_sha == data.head_sha)
    )
    if (
        target is not None
        and target.status == GateStatus.STALE
        and trigger == ReviewTrigger.WEBHOOK
        and gate is not None
        and gate.id != target.id
    ):
        # Volta para um commit já substituído: pode ser force-push legítimo ou um webhook
        # atrasado/reenviado. Só o provedor sabe qual é o head de agora.
        head = await _provider_head(state, repo, data.number)
        if head is not None and head != data.head_sha:
            log.info(
                "webhook fora de ordem ignorado: %s#%s %s (head atual %s)",
                repo.full_name,
                data.number,
                data.head_sha[:10],
                head[:10],
            )
            await session.commit()
            return pr, None
    pr.head_sha = data.head_sha
    if target is None:
        target = m.Gate(
            pull_request_id=pr.id,
            head_sha=data.head_sha,
            base_sha=data.base_sha,
            target_branch=data.target_branch,
            policy=gates.policy_snapshot(repo),
            status=GateStatus.REVIEWING,
        )
        session.add(target)
        await session.flush()
    else:
        # mesmo commit de novo (retarget, force-push de volta, reabertura): nova revisão.
        # A política continua a do commit: mudanças de política valem para commits novos.
        target.status = GateStatus.REVIEWING
        target.target_branch = data.target_branch
        target.base_sha = data.base_sha or target.base_sha
    if gate is not None and gate.id != target.id and gate.status not in FINAL_GATE:
        await reviews.cancel_active(session, gate.id, reason="substituída por commit mais novo")
    await reviews.mark_superseded_gates(session, pr, keep=target.id)
    pr.current_gate = target
    review = await reviews.enqueue(
        session, state, gate=target, pr=pr, repo=repo, trigger=trigger, requested_by=actor
    )
    await session.commit()
    await reviews.wake_runners(state)
    await gates.publish(session, state, target.id, comment=review.status == "failed")
    await gates.notify(state, repo.team.name, "pull_request", {"pull_request_id": str(pr.id)})
    return pr, review


async def rerun(
    session: AsyncSession,
    state: AppState,
    pr: m.PullRequest,
    *,
    actor: str,
    model_override=None,
) -> m.Review:
    """Revisa de novo o commit atual (regras mudaram, falha da IA, pedido do time)."""
    repo = pr.repository
    gate = pr.current_gate
    if gate is None or gate.status in FINAL_GATE or pr.state != PullRequestState.OPEN:
        from sentinela_api.errors import conflict

        raise conflict("o PR não tem um gate aberto para revisar")
    # A política do gate não muda na reexecução: afrouxar a política e reexecutar não é
    # caminho para liberar um commit (a política nova vale a partir do próximo commit).
    review = await reviews.enqueue(
        session,
        state,
        gate=gate,
        pr=pr,
        repo=repo,
        trigger=ReviewTrigger.MANUAL,
        requested_by=actor,
        model_override=model_override,
    )
    audit.record(
        session,
        actor=actor,
        action="review.rerun",
        resource_type="pull_request",
        resource_id=pr.id,
        team_id=pr.team_id,
        detail=f"{repo.full_name}#{pr.number} @ {gate.head_sha[:10]}",
    )
    await session.commit()
    await reviews.wake_runners(state)
    await gates.publish(session, state, gate.id)
    await gates.notify(state, repo.team.name, "pull_request", {"pull_request_id": str(pr.id)})
    return review


async def sync_repository(
    session: AsyncSession, state: AppState, repo: m.Repository, *, actor: str
) -> tuple[int, int]:
    """Busca os PRs abertos no provedor e alinha o estado (útil sem webhook ou após falhas)."""
    client = await state.providers.client(repo.integration)
    items = await client.list_open_pull_requests(repo.full_name)
    queued = 0
    open_numbers = set()
    for data in items:
        open_numbers.add(data.number)
        _, review = await handle_event(
            session, state, repo, data, trigger=ReviewTrigger.SYNC, actor=actor
        )
        if review is not None:
            queued += 1
    # PRs que o Sentinela acha abertos mas não vieram na lista: confere um a um
    stale = (
        await session.scalars(
            select(m.PullRequest).where(
                m.PullRequest.repository_id == repo.id,
                m.PullRequest.state == PullRequestState.OPEN,
                m.PullRequest.number.notin_(open_numbers or {-1}),
            )
        )
    ).all()
    for pr in stale:
        data = await client.get_pull_request(repo.full_name, pr.number)
        await handle_event(session, state, repo, data, trigger=ReviewTrigger.SYNC, actor=actor)
    repo.last_sync_at = datetime.now(UTC)
    await session.commit()
    return len(items), queued
