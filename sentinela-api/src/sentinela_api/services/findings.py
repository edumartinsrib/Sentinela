"""Ações sobre um apontamento: justificar (exceção aceita), descartar como falso positivo,
contestar, reabrir e comentar. Cada ação vira um evento no histórico e recalcula o gate."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.errors import ApiError, conflict, forbidden
from sentinela_api.security.auth import TeamContext
from sentinela_api.services import audit, gates
from sentinela_api.state import AppState
from sentinela_core.enums import FINAL_GATE, FindingStatus, Severity, severity_at_least

# ação → (permissão, estados de origem, estado de destino)
ACTIONS: dict[str, tuple[str, set[FindingStatus], FindingStatus | None]] = {
    "waive": (
        "finding.waive",
        {FindingStatus.OPEN, FindingStatus.DISPUTED},
        FindingStatus.WAIVED,
    ),
    "dismiss": (
        "finding.dismiss",
        {FindingStatus.OPEN, FindingStatus.DISPUTED},
        FindingStatus.FALSE_POSITIVE,
    ),
    "dispute": ("finding.dispute", {FindingStatus.OPEN}, FindingStatus.DISPUTED),
    "reopen": (
        "finding.dismiss",
        {FindingStatus.WAIVED, FindingStatus.FALSE_POSITIVE, FindingStatus.DISPUTED},
        FindingStatus.OPEN,
    ),
    "comment": ("view", set(FindingStatus), None),
}

LABELS = {
    "waive": "aceitou como exceção",
    "dismiss": "marcou como falso positivo",
    "dispute": "contestou",
    "reopen": "reabriu",
    "comment": "comentou",
}


async def act(
    session: AsyncSession,
    state: AppState,
    ctx: TeamContext,
    finding: m.Finding,
    action: str,
    text: str,
) -> m.Finding:
    permission, sources, target = ACTIONS[action]
    if not ctx.can(permission):
        raise forbidden(f"seu papel não permite: {LABELS[action]}")
    pr = await session.get(m.PullRequest, finding.pull_request_id)
    if pr is None:
        raise ApiError(404, "apontamento não encontrado")
    # trava o gate e relê o apontamento: duas pessoas agindo ao mesmo tempo não se atropelam
    gate = await gates.lock(session, finding.gate_id)
    await session.refresh(finding)
    if action != "comment":
        if pr.current_gate_id != gate.id or gate.current_review_id != finding.review_id:
            raise conflict("este apontamento é de uma revisão antiga; veja a revisão atual")
        if gate.status in FINAL_GATE:
            raise conflict("este gate não aceita mais mudanças")
        if action in ("waive", "dismiss"):
            identity = gates.identity_block_reason(ctx.principal, pr)
            if identity:
                raise forbidden(identity)
        blocking = severity_at_least(
            Severity(finding.severity), gates.gate_policy(gate).block_severity
        )
        if action == "dismiss" and blocking and not ctx.can("finding.waive"):
            # Falso positivo num bloqueante libera o merge: decisão do tech lead, como a exceção.
            raise forbidden("só o tech lead descarta apontamentos que bloqueiam o merge")
    if FindingStatus(finding.status) not in sources:
        raise conflict(f"não é possível {action} um apontamento em {finding.status}")
    before = finding.status
    if target is not None:
        finding.status = target
        finding.status_reason = text if target != FindingStatus.OPEN else None
        finding.status_by = ctx.actor
        finding.status_at = datetime.now(UTC)
        finding.inherited = False
    session.add(m.FindingEvent(finding_id=finding.id, actor=ctx.actor, action=action, comment=text))
    if target is not None:
        audit.record(
            session,
            actor=ctx.actor,
            action=f"finding.{action}",
            resource_type="finding",
            resource_id=finding.id,
            team_id=ctx.team.id,
            before={"status": before},
            after={"status": finding.status},
            detail=f"{pr.repository.full_name}#{pr.number} [{finding.rule_code}] "
            f"{finding.title}: {text}",
        )
        await session.flush()
        await gates.recompute(session, gate)
    await session.commit()
    if target is not None:
        await gates.publish(session, state, gate.id, comment=True)
    await gates.notify(
        state,
        ctx.team.name,
        "finding",
        {"pull_request_id": str(pr.id), "finding_id": str(finding.id), "status": finding.status},
    )
    return finding
