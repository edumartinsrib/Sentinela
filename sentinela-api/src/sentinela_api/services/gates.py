"""Gate de um commit: política, recálculo, decisões humanas, liberação emergencial,
publicação do status no GitHub/GitLab e merge pela plataforma."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.db import lock_row
from sentinela_api.errors import ApiError, conflict, forbidden
from sentinela_api.providers.base import ProviderError, StatusState
from sentinela_api.services import audit
from sentinela_api.services.events import team_channel
from sentinela_api.state import AppState
from sentinela_core.enums import (
    FINAL_GATE,
    PASSING_GATE,
    ApprovalMode,
    Decision,
    Enforcement,
    FindingStatus,
    GateMode,
    GateStatus,
    PullRequestState,
    ReviewStatus,
    Severity,
)
from sentinela_core.gate import (
    DecisionState,
    FindingState,
    GateEvaluation,
    GatePolicy,
    can_approve,
    can_reject,
    evaluate_gate,
)

log = logging.getLogger(__name__)
COMMENT_MARKER = "<!-- sentinela:gate -->"


# ----------------------------------------------------------------------------- política
def policy_snapshot(repo: m.Repository) -> dict[str, Any]:
    return {
        "approval_mode": repo.approval_mode,
        "human_min_severity": repo.human_min_severity,
        "block_severity": repo.block_severity,
        "min_approvals": repo.min_approvals,
        "carry_waivers": repo.carry_waivers,
        "enforcement": repo.enforcement,
    }


def gate_policy(gate: m.Gate) -> GatePolicy:
    p = gate.policy or {}
    return GatePolicy(
        approval_mode=ApprovalMode(p.get("approval_mode", ApprovalMode.AI_WHEN_CLEAN)),
        human_min_severity=Severity(p.get("human_min_severity", Severity.INFO)),
        block_severity=Severity(p.get("block_severity", Severity.HIGH)),
        min_approvals=int(p.get("min_approvals", 1)),
    )


def uses_status_check(repo: m.Repository) -> bool:
    return repo.gate_mode in (GateMode.STATUS_CHECK, GateMode.BOTH)


def uses_platform_merge(repo: m.Repository) -> bool:
    return repo.gate_mode in (GateMode.PLATFORM_MERGE, GateMode.BOTH)


# ----------------------------------------------------------------------------- cálculo
async def current_findings(session: AsyncSession, gate: m.Gate) -> list[m.Finding]:
    if gate.current_review_id is None:
        return []
    rows = await session.scalars(
        select(m.Finding).where(m.Finding.review_id == gate.current_review_id)
    )
    return list(rows.all())


async def current_decisions(session: AsyncSession, gate: m.Gate) -> list[m.GateDecision]:
    """Aprovações valem para a revisão atual; reprovações valem para o commit inteiro
    (reexecutar a revisão não apaga um "não" — só quem reprovou muda o voto)."""
    if gate.current_review_id is None:
        return []
    rows = await session.scalars(
        select(m.GateDecision)
        .where(
            m.GateDecision.gate_id == gate.id,
            or_(
                m.GateDecision.review_id == gate.current_review_id,
                m.GateDecision.decision == Decision.REJECT.value,
            ),
        )
        .order_by(m.GateDecision.created_at)
    )
    return list(rows.all())


async def lock(session: AsyncSession, gate_id: uuid.UUID) -> m.Gate:
    """Trava a linha do gate e relê do banco: decisões, conclusões de revisão e
    reexecuções concorrentes não sobrescrevem umas às outras."""
    gate = await lock_row(session, m.Gate, gate_id)
    if gate is None:
        raise conflict("gate não encontrado")
    return gate


async def evaluate(session: AsyncSession, gate: m.Gate) -> GateEvaluation:
    review = await session.get(m.Review, gate.current_review_id) if gate.current_review_id else None
    findings = await current_findings(session, gate)
    decisions = await current_decisions(session, gate)
    return evaluate_gate(
        review_status=ReviewStatus(review.status) if review else None,
        findings=[FindingState(Severity(f.severity), FindingStatus(f.status)) for f in findings],
        decisions=[DecisionState(d.username, Decision(d.decision)) for d in decisions],
        policy=gate_policy(gate),
        human_required=gate.human_required,
        overridden_by=gate.override_by,
        stale=gate.status == GateStatus.STALE,
        merged=gate.status == GateStatus.MERGED,
    )


async def recompute(session: AsyncSession, gate: m.Gate) -> GateEvaluation:
    ev = await evaluate(session, gate)
    previous = gate.status
    gate.status = ev.status
    gate.status_description = ev.description[:300]
    gate.approvals_required = ev.approvals_required
    if ev.status in PASSING_GATE and previous not in PASSING_GATE:
        gate.decided_at = datetime.now(UTC)
    elif ev.status not in PASSING_GATE and ev.status not in FINAL_GATE:
        gate.decided_at = None
    return ev


# ----------------------------------------------------------------------------- publicação
_STATE: dict[GateStatus, StatusState] = {
    GateStatus.REVIEWING: "pending",
    GateStatus.AWAITING_APPROVAL: "pending",
    GateStatus.BLOCKED: "failure",
    GateStatus.REJECTED: "failure",
    GateStatus.ERROR: "error",
    GateStatus.APPROVED: "success",
    GateStatus.OVERRIDDEN: "success",
}


def provider_status(gate: m.Gate, repo: m.Repository) -> tuple[StatusState, str]:
    status = GateStatus(gate.status)
    state = _STATE.get(status, "pending")
    description = gate.status_description or ""
    if repo.enforcement == Enforcement.OBSERVE and state != "success":
        return "success", f"Modo observação — {description}"[:140]
    return state, description


def console_url(state: AppState, pr: m.PullRequest, team: m.Team) -> str:
    return f"{state.settings.public_url.rstrip('/')}/t/{team.name}/pull-requests/{pr.id}"


async def publish(
    session: AsyncSession, state: AppState, gate_id: uuid.UUID, *, comment: bool = False
) -> None:
    """Publica o status do gate no commit e (opcional) atualiza o comentário do PR.
    Falhas no provedor ficam registradas no gate e o reconciliador tenta de novo."""
    gate = await session.get(m.Gate, gate_id)
    if gate is None or gate.status in FINAL_GATE:
        return
    pr = await session.get(m.PullRequest, gate.pull_request_id)
    if pr is None or pr.current_gate_id != gate.id or pr.state != PullRequestState.OPEN:
        return
    repo = pr.repository
    if not uses_status_check(repo) and not repo.post_comments:
        return
    state_value, description = provider_status(gate, repo)
    errors: list[str] = []
    try:
        client = await state.providers.client(repo.integration)
    except ProviderError as exc:
        gate.publish_error = str(exc)
        await session.commit()
        return
    target = console_url(state, pr, repo.team)
    changed = (gate.published_state, gate.published_description) != (state_value, description)
    if uses_status_check(repo) and (changed or gate.publish_error):
        try:
            await client.set_status(
                repo.full_name, gate.head_sha, state_value, description, repo.status_context, target
            )
            gate.published_state = state_value
            gate.published_description = description
            gate.published_at = datetime.now(UTC)
        except ProviderError as exc:
            errors.append(f"status: {exc}")
    if repo.post_comments and comment:
        from sentinela_api.services.comments import render_comment

        try:
            body = await render_comment(session, state, gate, pr, repo, target)
            gate.comment_id = await client.upsert_comment(
                repo.full_name, pr.number, body, COMMENT_MARKER, gate.comment_id
            )
        except ProviderError as exc:
            errors.append(f"comentário: {exc}")
    gate.publish_error = "; ".join(errors) or None
    if errors:
        log.warning("falha ao publicar gate %s: %s", gate.id, gate.publish_error)
    await session.commit()


async def notify(state: AppState, team: str, event: str, data: dict[str, Any]) -> None:
    await state.bus.publish(team_channel(team), event, data)


# ----------------------------------------------------------------------------- decisões
def is_author(principal, pr: m.PullRequest) -> bool:
    return bool(pr.author_login) and pr.author_login.lower() in principal.provider_logins()


def provider_name(pr: m.PullRequest) -> str:
    return "GitHub" if pr.repository.integration.provider == "github" else "GitLab"


def identity_block_reason(principal, pr: m.PullRequest) -> str | None:
    """Quem decide precisa ser comprovadamente outra pessoa que não o autor: sem o autor
    identificado ou sem o login do decisor no provedor, a decisão fica bloqueada."""
    if not pr.author_login:
        return "O autor do PR não foi identificado; sincronize o repositório e tente de novo"
    if is_author(principal, pr):
        return "O autor do PR não pode decidir sobre o próprio gate"
    if not principal.provider_login(pr.repository.integration.provider):
        return (
            f"Vincule seu login do {provider_name(pr)} em Acesso: é o que comprova que você "
            "não é o autor do PR"
        )
    return None


def approve_block_reason(gate: m.Gate, principal, pr: m.PullRequest, allowed: bool) -> str | None:
    """Motivo para o botão Aprovar estar desabilitado (None = pode aprovar)."""
    if not allowed:
        return "Seu papel neste time não permite aprovar gates"
    identity = identity_block_reason(principal, pr)
    if identity:
        return identity
    status = GateStatus(gate.status)
    if status == GateStatus.BLOCKED:
        return "Há apontamentos bloqueantes sem justificativa"
    if status == GateStatus.REVIEWING:
        return "A revisão automática ainda está em andamento"
    if status == GateStatus.ERROR:
        return "A revisão automática falhou; execute de novo"
    if status in FINAL_GATE or status == GateStatus.OVERRIDDEN:
        return "Este gate não aceita mais decisões"
    if status == GateStatus.APPROVED and not gate.human_required:
        return "Aprovado pela IA: não há apontamentos"
    if not can_approve(status):
        return "Este gate não aceita aprovação agora"
    return None


async def decide(
    session: AsyncSession,
    state: AppState,
    *,
    principal,
    team: m.Team,
    pr: m.PullRequest,
    decision: Decision,
    comment: str | None,
    allowed: bool,
) -> m.Gate:
    if pr.current_gate_id is None:
        raise conflict("este PR não tem gate")
    gate = await lock(session, pr.current_gate_id)
    if decision == Decision.APPROVE:
        reason = approve_block_reason(gate, principal, pr, allowed)
        if reason:
            identity = reason == identity_block_reason(principal, pr)
            raise ApiError(403 if "papel" in reason or identity else 409, reason)
    else:
        if not allowed:
            raise forbidden("seu papel neste time não permite reprovar gates")
        identity = identity_block_reason(principal, pr)
        if identity:
            raise forbidden(identity)
        if not can_reject(GateStatus(gate.status)):
            raise conflict("este gate não aceita reprovação agora")
    session.add(
        m.GateDecision(
            gate_id=gate.id,
            username=principal.username,
            display_name=principal.user.display_name,
            decision=decision.value,
            comment=comment,
            review_id=gate.current_review_id,
        )
    )
    await session.flush()
    before = gate.status
    ev = await recompute(session, gate)
    audit.record(
        session,
        actor=principal.username,
        action=f"gate.{decision.value}",
        resource_type="gate",
        resource_id=gate.id,
        team_id=team.id,
        before={"status": before},
        after={"status": ev.status.value},
        detail=f"{pr.repository.full_name}#{pr.number} @ {gate.head_sha[:10]}"
        + (f": {comment}" if comment else ""),
    )
    await session.commit()
    await publish(session, state, gate.id, comment=True)
    await notify(state, team.name, "gate", {"pull_request_id": str(pr.id), "status": gate.status})
    return gate


async def override(
    session: AsyncSession,
    state: AppState,
    *,
    principal,
    team: m.Team,
    pr: m.PullRequest,
    reason: str,
) -> m.Gate:
    if pr.current_gate_id is None:
        raise conflict("este PR não tem gate")
    if not principal.is_superadmin:
        raise forbidden("só administradores globais liberam o gate em caráter emergencial")
    gate = await lock(session, pr.current_gate_id)
    if gate.status in FINAL_GATE:
        raise conflict("este gate não aceita mais decisões")
    before = gate.status
    gate.override_by = principal.username
    gate.override_reason = reason
    await recompute(session, gate)
    audit.record(
        session,
        actor=principal.username,
        action="gate.override",
        resource_type="gate",
        resource_id=gate.id,
        team_id=team.id,
        before={"status": before},
        after={"status": gate.status},
        detail=f"{pr.repository.full_name}#{pr.number}: {reason}",
    )
    await session.commit()
    await publish(session, state, gate.id, comment=True)
    await notify(state, team.name, "gate", {"pull_request_id": str(pr.id), "status": gate.status})
    return gate


# ----------------------------------------------------------------------------- merge
def merge_block_reason(pr: m.PullRequest, allowed: bool) -> str | None:
    repo = pr.repository
    if not uses_platform_merge(repo):
        return "O merge deste repositório é feito no " + (
            "GitHub" if repo.integration.provider == "github" else "GitLab"
        )
    if not allowed:
        return "Seu papel neste time não permite fazer merge"
    if pr.state != PullRequestState.OPEN:
        return "O PR não está aberto"
    gate = pr.current_gate
    if gate is None or gate.status not in PASSING_GATE:
        return "O gate ainda não foi liberado"
    if gate.head_sha != pr.head_sha:
        return "Há um commit mais novo aguardando revisão"
    return None


async def merge(
    session: AsyncSession,
    state: AppState,
    *,
    principal,
    team: m.Team,
    pr: m.PullRequest,
    method: str | None,
    allowed: bool,
):
    from sentinela_api.providers.base import MergeResult

    if pr.current_gate_id is not None:
        # relê o gate travado: uma revisão nova pode ter começado depois da tela abrir
        pr.current_gate = await lock(session, pr.current_gate_id)
    reason = merge_block_reason(pr, allowed)
    if reason:
        raise ApiError(403 if "papel" in reason else 409, reason)
    gate = pr.current_gate
    assert gate is not None
    repo = pr.repository
    # Solta a trava antes de chamar o provedor: o webhook do próprio merge volta para esta
    # API. O merge vai com o SHA do gate, então o provedor recusa se o head tiver mudado.
    await session.commit()
    try:
        client = await state.providers.client(repo.integration)
        result: MergeResult = await client.merge(
            repo.full_name, pr.number, gate.head_sha, method or repo.merge_method, pr.title
        )
    except ProviderError as exc:
        raise ApiError(502, f"falha no merge: {exc}") from exc
    audit.record(
        session,
        actor=principal.username,
        action="pull_request.merge" if result.merged else "pull_request.merge_refused",
        resource_type="pull_request",
        resource_id=pr.id,
        team_id=team.id,
        detail=f"{repo.full_name}#{pr.number} @ {gate.head_sha[:10]}"
        + (f": {result.message}" if result.message else ""),
    )
    if result.merged:
        pr.state = PullRequestState.MERGED
        pr.merged_at = datetime.now(UTC)
        pr.merged_by = principal.username
        gate.status = GateStatus.MERGED
    await session.commit()
    await notify(state, team.name, "pull_request", {"pull_request_id": str(pr.id)})
    return result
