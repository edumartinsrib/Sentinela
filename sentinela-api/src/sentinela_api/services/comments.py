"""Comentário único (atualizado a cada mudança) que o Sentinela mantém no PR/MR."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.services import gates
from sentinela_api.state import AppState
from sentinela_core.enums import (
    SEVERITY_RANK,
    UNRESOLVED_FINDING,
    FindingStatus,
    GateStatus,
    Severity,
    label,
)

STATUS_TITLE = {
    GateStatus.REVIEWING: "Revisão em andamento",
    GateStatus.BLOCKED: "Bloqueado",
    GateStatus.AWAITING_APPROVAL: "Aguardando aprovação",
    GateStatus.APPROVED: "Aprovado",
    GateStatus.REJECTED: "Reprovado",
    GateStatus.ERROR: "Falha na revisão",
    GateStatus.OVERRIDDEN: "Liberado em caráter emergencial",
    GateStatus.STALE: "Substituído",
    GateStatus.MERGED: "Merge realizado",
}
MAX_LISTED = 15


def _location(f: m.Finding) -> str:
    if not f.file:
        return ""
    return f" — `{f.file}{':' + str(f.line) if f.line else ''}`"


async def render_comment(
    session: AsyncSession,
    state: AppState,
    gate: m.Gate,
    pr: m.PullRequest,
    repo: m.Repository,
    target_url: str,
) -> str:
    review = await session.get(m.Review, gate.current_review_id) if gate.current_review_id else None
    findings = await gates.current_findings(session, gate)
    status = GateStatus(gate.status)
    lines = [gates.COMMENT_MARKER, f"### Sentinela — {STATUS_TITLE.get(status, status)}", ""]
    lines.append(gate.status_description or "")
    if repo.enforcement == "observe":
        lines += ["", "_Repositório em modo observação: o gate não bloqueia o merge._"]

    if findings:
        open_ = [f for f in findings if FindingStatus(f.status) in UNRESOLVED_FINDING]
        lines += ["", "| Severidade | Em aberto | Total |", "| --- | ---: | ---: |"]
        for sev in sorted(Severity, key=lambda s: -SEVERITY_RANK[s]):
            total = sum(1 for f in findings if f.severity == sev)
            if total:
                pending = sum(1 for f in open_ if f.severity == sev)
                lines.append(f"| {label(sev)} | {pending} | {total} |")
        ordered = sorted(
            open_, key=lambda f: (-SEVERITY_RANK[Severity(f.severity)], f.file or "", f.line or 0)
        )
        if ordered:
            lines += ["", "**Apontamentos em aberto**", ""]
            for f in ordered[:MAX_LISTED]:
                lines.append(f"- **{label(f.severity)}** · `{f.rule_code}` {f.title}{_location(f)}")
            if len(ordered) > MAX_LISTED:
                lines.append(f"- … e mais {len(ordered) - MAX_LISTED}")
        else:
            lines += [
                "",
                "Todos os apontamentos foram tratados (exceção aceita ou falso positivo).",
            ]
    elif review and review.status == "completed":
        lines += ["", "Nenhuma divergência em relação aos padrões do time."]

    if review and review.status == "failed" and review.error:
        lines += ["", f"> {review.error.splitlines()[0][:300]}"]
    if review and review.summary:
        lines += [
            "",
            "<details><summary>Resumo da IA</summary>",
            "",
            review.summary,
            "",
            "</details>",
        ]

    footer = [f"[Abrir no Sentinela]({target_url})", f"commit `{gate.head_sha[:10]}`"]
    if review and review.model_label:
        footer.append(f"modelo: {review.model_label}")
    lines += ["", " · ".join(footer)]
    return "\n".join(lines)
