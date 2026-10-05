"""Regra do gate, sem banco nem rede: dado o estado da revisão, os achados e as
decisões humanas, calcula a situação do gate de um commit.

Política padrão (pedido do produto):
- revisão sem apontamentos → a IA aprova sozinha;
- com apontamentos → exige aprovação humana de alguém que não seja o autor;
- apontamentos de severidade ≥ `block_severity` precisam de justificativa (exceção aceita)
  ou ser descartados como falso positivo antes de qualquer aprovação.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sentinela_core.enums import (
    UNRESOLVED_FINDING,
    ApprovalMode,
    Decision,
    FindingStatus,
    GateStatus,
    ReviewStatus,
    Severity,
    severity_at_least,
)


@dataclass(frozen=True)
class GatePolicy:
    approval_mode: ApprovalMode = ApprovalMode.AI_WHEN_CLEAN
    # A partir de que severidade um apontamento exige aprovação humana.
    human_min_severity: Severity = Severity.INFO
    # A partir de que severidade um apontamento bloqueia até ser justificado.
    block_severity: Severity = Severity.HIGH
    min_approvals: int = 1


@dataclass(frozen=True)
class FindingState:
    severity: Severity
    status: FindingStatus


@dataclass(frozen=True)
class DecisionState:
    username: str
    decision: Decision


@dataclass
class GateEvaluation:
    status: GateStatus
    description: str
    blocking: int = 0
    unresolved: int = 0
    approvals: int = 0
    approvals_required: int = 0
    approved_by: list[str] = field(default_factory=list)
    rejected_by: list[str] = field(default_factory=list)


def requires_human(findings: Iterable[FindingState], policy: GatePolicy) -> bool:
    """Decidido quando a revisão termina. Todo apontamento real conta, inclusive os aceitos
    como exceção em um commit anterior (a aprovação vale por commit); só o falso positivo
    herdado não exige humano."""
    if policy.approval_mode == ApprovalMode.ALWAYS_HUMAN:
        return True
    return any(
        f.status != FindingStatus.FALSE_POSITIVE
        and severity_at_least(f.severity, policy.human_min_severity)
        for f in findings
    )


def latest_decisions(decisions: Iterable[DecisionState]) -> dict[str, Decision]:
    """Vale a última decisão de cada pessoa (a lista vem em ordem cronológica)."""
    out: dict[str, Decision] = {}
    for d in decisions:
        out[d.username] = d.decision
    return out


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def evaluate_gate(
    *,
    review_status: ReviewStatus | None,
    findings: list[FindingState],
    decisions: list[DecisionState],
    policy: GatePolicy,
    human_required: bool,
    overridden_by: str | None = None,
    stale: bool = False,
    merged: bool = False,
) -> GateEvaluation:
    # Os contadores valem para qualquer situação final (merge, liberação emergencial,
    # substituído): o console continua mostrando o que ficou em aberto naquele commit.
    unresolved = [f for f in findings if f.status in UNRESOLVED_FINDING]
    blocking = [f for f in unresolved if severity_at_least(f.severity, policy.block_severity)]
    latest = latest_decisions(decisions)
    approved_by = sorted(u for u, d in latest.items() if d == Decision.APPROVE)
    rejected_by = sorted(u for u, d in latest.items() if d == Decision.REJECT)
    required = max(policy.min_approvals, 1) if human_required else 0
    base = dict(
        blocking=len(blocking),
        unresolved=len(unresolved),
        approvals=len(approved_by),
        approvals_required=required,
        approved_by=approved_by,
        rejected_by=rejected_by,
    )

    if merged:
        return GateEvaluation(GateStatus.MERGED, "Merge realizado", **base)
    if stale:
        return GateEvaluation(GateStatus.STALE, "Substituído por um commit mais novo", **base)
    if overridden_by:
        return GateEvaluation(
            GateStatus.OVERRIDDEN, f"Liberado em caráter emergencial por {overridden_by}", **base
        )
    if review_status in (None, ReviewStatus.QUEUED, ReviewStatus.RUNNING):
        return GateEvaluation(GateStatus.REVIEWING, "Revisão automática em andamento")
    if review_status != ReviewStatus.COMPLETED:
        return GateEvaluation(
            GateStatus.ERROR, "A revisão automática falhou; execute de novo pelo Sentinela"
        )

    if rejected_by:
        return GateEvaluation(
            GateStatus.REJECTED, f"Reprovado por {', '.join(rejected_by)}", **base
        )
    if blocking:
        return GateEvaluation(
            GateStatus.BLOCKED,
            f"{_plural(len(blocking), 'apontamento bloqueante', 'apontamentos bloqueantes')}"
            " sem justificativa",
            **base,
        )
    if not human_required:
        return GateEvaluation(GateStatus.APPROVED, "Aprovado pela IA: nenhum apontamento", **base)
    if len(approved_by) >= required:
        return GateEvaluation(GateStatus.APPROVED, f"Aprovado por {', '.join(approved_by)}", **base)
    total = len(findings)
    return GateEvaluation(
        GateStatus.AWAITING_APPROVAL,
        f"Aguardando aprovação humana ({len(approved_by)}/{required})"
        + (f" — {_plural(total, 'apontamento', 'apontamentos')}" if total else ""),
        **base,
    )


def can_approve(status: GateStatus) -> bool:
    return status in (GateStatus.AWAITING_APPROVAL, GateStatus.APPROVED, GateStatus.REJECTED)


def can_reject(status: GateStatus) -> bool:
    return status in (
        GateStatus.AWAITING_APPROVAL,
        GateStatus.APPROVED,
        GateStatus.BLOCKED,
        GateStatus.REJECTED,
    )
