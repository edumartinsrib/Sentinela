"""PRs, gates, apontamentos e revisões de um time (inclui os streams SSE do console)."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import ReviewRun, Session, State, View
from sentinela_api.errors import ApiError, conflict, not_found, unprocessable
from sentinela_api.routers.sse import sse_response
from sentinela_api.services import findings as finding_svc
from sentinela_api.services import gates, reviews
from sentinela_api.services import pull_requests as pr_svc
from sentinela_api.services.events import review_channel, team_channel
from sentinela_api.services.serializers import (
    GateCounts,
    approvals_count,
    decision_out,
    finding_out,
    gate_out,
    gate_summary,
    pr_fields,
    pr_list_out,
    review_out,
    review_statuses,
)
from sentinela_core.enums import (
    FINAL_GATE,
    SEVERITY_RANK,
    Decision,
    ReviewStatus,
    Severity,
)

router = APIRouter(prefix="/api/v1/teams/{team}", tags=["pull requests"])


async def _pr(session, team: m.Team, pr_id: uuid.UUID) -> m.PullRequest:
    pr = await session.get(m.PullRequest, pr_id)
    if pr is None or pr.team_id != team.id:
        raise not_found("pull request")
    return pr


# --------------------------------------------------------------------------- listagem
@router.get("/pull-requests", response_model=s.Page[s.PullRequestOut])
async def list_pull_requests(
    ctx: View,
    session: Session,
    state_filter: str = Query(default="open", alias="state"),
    gate: list[str] | None = Query(default=None),
    repository: str | None = None,
    q: str | None = None,
    author: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> s.Page[s.PullRequestOut]:
    query = (
        select(m.PullRequest)
        .outerjoin(m.Gate, m.PullRequest.current_gate_id == m.Gate.id)
        .join(m.Repository, m.Repository.id == m.PullRequest.repository_id)
        .where(m.PullRequest.team_id == ctx.team.id)
    )
    if state_filter != "all":
        query = query.where(m.PullRequest.state == state_filter)
    statuses = [x for item in gate or [] for x in item.split(",") if x]
    if statuses:
        query = query.where(m.Gate.status.in_(statuses))
    if repository:
        query = query.where(m.PullRequest.repository_id == uuid.UUID(repository))
    if author:
        query = query.where(m.PullRequest.author_login == author)
    if q:
        like = f"%{q.strip()}%"
        conds = [
            m.PullRequest.title.ilike(like),
            m.Repository.full_name.ilike(like),
            m.PullRequest.source_branch.ilike(like),
            m.PullRequest.author_login.ilike(like),
        ]
        if q.strip().lstrip("#").isdigit():
            conds.append(m.PullRequest.number == int(q.strip().lstrip("#")))
        query = query.where(or_(*conds))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        (
            await session.scalars(
                query.order_by(m.PullRequest.updated_at.desc()).limit(limit).offset(offset)
            )
        )
        .unique()
        .all()
    )
    return s.Page(
        items=await pr_list_out(session, list(rows)), total=total or 0, limit=limit, offset=offset
    )


# --------------------------------------------------------------------------- detalhe
async def build_detail(session, state, ctx, pr: m.PullRequest) -> s.PullRequestDetail:
    repo = pr.repository
    gate = pr.current_gate
    review = None
    ev = None
    findings: list[m.Finding] = []
    events: dict[uuid.UUID, list[m.FindingEvent]] = defaultdict(list)
    decisions: list[m.GateDecision] = []
    if gate is not None:
        if gate.current_review_id:
            review = await session.get(m.Review, gate.current_review_id)
        ev = await gates.evaluate(session, gate)
        findings = await gates.current_findings(session, gate)
        findings.sort(
            key=lambda f: (-SEVERITY_RANK[Severity(f.severity)], f.file or "", f.line or 0)
        )
        if findings:
            rows = await session.scalars(
                select(m.FindingEvent)
                .where(m.FindingEvent.finding_id.in_([f.id for f in findings]))
                .order_by(m.FindingEvent.at)
            )
            for e in rows.all():
                events[e.finding_id].append(e)
        decisions = list(
            (
                await session.scalars(
                    select(m.GateDecision)
                    .where(m.GateDecision.gate_id == gate.id)
                    .order_by(m.GateDecision.created_at.desc())
                )
            ).all()
        )

    all_gates = list(
        (
            await session.scalars(
                select(m.Gate)
                .where(m.Gate.pull_request_id == pr.id)
                .order_by(m.Gate.created_at.desc())
            )
        )
        .unique()
        .all()
    )
    review_ids = [g.current_review_id for g in all_gates]
    counts = await GateCounts.load(session, review_ids)
    statuses = await review_statuses(session, review_ids)
    approvals = await approvals_count(session, all_gates)
    history = []
    for g in all_gates:
        r = await session.get(m.Review, g.current_review_id) if g.current_review_id else None
        history.append(
            s.GateHistoryItem(
                gate=gate_summary(
                    g, counts, statuses.get(g.current_review_id), approvals.get(g.id, 0)
                ),
                review=review_out(r) if r else None,
            )
        )
    summary = None
    if gate is not None:
        summary = gate_summary(
            gate, counts, statuses.get(gate.current_review_id), approvals.get(gate.id, 0)
        )

    principal = ctx.principal
    is_author = gates.is_author(principal, pr)
    gate_open = gate is not None and gate.status not in FINAL_GATE and pr.state == "open"
    approve_reason = (
        gates.approve_block_reason(gate, principal, pr, ctx.can("gate.approve"))
        if gate is not None
        else "Este PR não passa pelo gate"
    )
    merge_reason = gates.merge_block_reason(pr, ctx.can("pr.merge"))
    block = (gate.policy or {}).get("block_severity", Severity.HIGH) if gate else Severity.HIGH
    sha = gate.head_sha if gate else pr.head_sha
    can_decide = gates.identity_block_reason(principal, pr) is None
    perms = s.Permissions(
        approve=approve_reason is None,
        approve_reason=approve_reason,
        reject=gate_open and ctx.can("gate.approve") and can_decide,
        waive=gate_open and ctx.can("finding.waive") and can_decide,
        dismiss=gate_open and ctx.can("finding.dismiss") and can_decide,
        dispute=gate_open and ctx.can("finding.dispute"),
        rerun=gate_open and ctx.can("review.run"),
        merge=merge_reason is None,
        merge_reason=merge_reason,
        override=gate_open and principal.is_superadmin,
        is_author=is_author,
    )
    return s.PullRequestDetail(
        **pr_fields(pr, summary),
        description=pr.description,
        current_gate=gate_out(gate, ev) if gate is not None and ev is not None else None,
        review=review_out(review) if review else None,
        findings=[finding_out(f, repo, sha, block, events.get(f.id)) for f in findings],
        decisions=[decision_out(d, gate.current_review_id if gate else None) for d in decisions],
        history=history,
        permissions=perms,
        merge_via_platform=gates.uses_platform_merge(repo),
        status_check=gates.uses_status_check(repo),
        enforcement=repo.enforcement,
    )


@router.get("/pull-requests/{pr_id}", response_model=s.PullRequestDetail)
async def get_pull_request(
    pr_id: uuid.UUID, ctx: View, session: Session, state: State
) -> s.PullRequestDetail:
    return await build_detail(session, state, ctx, await _pr(session, ctx.team, pr_id))


# --------------------------------------------------------------------------- ações
@router.post("/pull-requests/{pr_id}/reviews", response_model=s.ReviewOut, status_code=201)
async def rerun_review(
    pr_id: uuid.UUID, body: s.RerunIn, ctx: ReviewRun, session: Session, state: State
) -> s.ReviewOut:
    pr = await _pr(session, ctx.team, pr_id)
    override = None
    if body.model_id:
        if not ctx.principal.is_superadmin:
            raise ApiError(403, "só administradores globais escolhem outro modelo")
        override = uuid.UUID(body.model_id)
    review = await pr_svc.rerun(session, state, pr, actor=ctx.actor, model_override=override)
    review = await session.get(m.Review, review.id, populate_existing=True)
    return review_out(review)


@router.post("/pull-requests/{pr_id}/approve", response_model=s.PullRequestDetail)
async def approve(
    pr_id: uuid.UUID, body: s.DecisionIn, ctx: View, session: Session, state: State
) -> s.PullRequestDetail:
    pr = await _pr(session, ctx.team, pr_id)
    await gates.decide(
        session,
        state,
        principal=ctx.principal,
        team=ctx.team,
        pr=pr,
        decision=Decision.APPROVE,
        comment=body.comment,
        allowed=ctx.can("gate.approve"),
    )
    return await build_detail(session, state, ctx, pr)


@router.post("/pull-requests/{pr_id}/reject", response_model=s.PullRequestDetail)
async def reject(
    pr_id: uuid.UUID, body: s.RejectIn, ctx: View, session: Session, state: State
) -> s.PullRequestDetail:
    pr = await _pr(session, ctx.team, pr_id)
    await gates.decide(
        session,
        state,
        principal=ctx.principal,
        team=ctx.team,
        pr=pr,
        decision=Decision.REJECT,
        comment=body.comment,
        allowed=ctx.can("gate.approve"),
    )
    return await build_detail(session, state, ctx, pr)


@router.post("/pull-requests/{pr_id}/override", response_model=s.PullRequestDetail)
async def override(
    pr_id: uuid.UUID, body: s.OverrideIn, ctx: View, session: Session, state: State
) -> s.PullRequestDetail:
    pr = await _pr(session, ctx.team, pr_id)
    await gates.override(
        session, state, principal=ctx.principal, team=ctx.team, pr=pr, reason=body.reason
    )
    return await build_detail(session, state, ctx, pr)


@router.post("/pull-requests/{pr_id}/merge", response_model=s.MergeOut)
async def merge(
    pr_id: uuid.UUID, body: s.MergeIn, ctx: View, session: Session, state: State
) -> s.MergeOut:
    pr = await _pr(session, ctx.team, pr_id)
    result = await gates.merge(
        session,
        state,
        principal=ctx.principal,
        team=ctx.team,
        pr=pr,
        method=body.method.value if body.method else None,
        allowed=ctx.can("pr.merge"),
    )
    if not result.merged:
        raise conflict(f"o provedor recusou o merge: {result.message}")
    return s.MergeOut(merged=True, sha=result.sha, message=result.message)


# --------------------------------------------------------------------------- apontamentos
async def _finding(session, team: m.Team, finding_id: uuid.UUID) -> m.Finding:
    finding = await session.get(m.Finding, finding_id)
    if finding is None or finding.team_id != team.id:
        raise not_found("apontamento")
    return finding


async def _finding_response(session, finding: m.Finding) -> s.FindingOut:
    pr = await session.get(m.PullRequest, finding.pull_request_id)
    gate = await session.get(m.Gate, finding.gate_id)
    events = (
        await session.scalars(
            select(m.FindingEvent)
            .where(m.FindingEvent.finding_id == finding.id)
            .order_by(m.FindingEvent.at)
        )
    ).all()
    block = (gate.policy or {}).get("block_severity", Severity.HIGH) if gate else Severity.HIGH
    return finding_out(
        finding, pr.repository, gate.head_sha if gate else pr.head_sha, block, list(events)
    )


@router.post("/findings/{finding_id}/{action}", response_model=s.FindingOut)
async def finding_action(
    finding_id: uuid.UUID,
    action: str,
    body: s.FindingActionIn,
    ctx: View,
    session: Session,
    state: State,
) -> s.FindingOut:
    if action not in finding_svc.ACTIONS:
        raise not_found("ação")
    text = body.reason.strip()
    if action != "comment" and len(text) < 3:
        raise unprocessable("explique o motivo (mínimo de 3 caracteres)")
    finding = await _finding(session, ctx.team, finding_id)
    await finding_svc.act(session, state, ctx, finding, action, text)
    return await _finding_response(session, finding)


# --------------------------------------------------------------------------- revisões
async def _review(session, team: m.Team, review_id: uuid.UUID) -> m.Review:
    review = await session.get(m.Review, review_id)
    if review is None or review.team_id != team.id:
        raise not_found("revisão")
    return review


@router.get("/reviews/{review_id}", response_model=s.ReviewOut)
async def get_review(review_id: uuid.UUID, ctx: View, session: Session) -> s.ReviewOut:
    return review_out(await _review(session, ctx.team, review_id))


@router.get("/reviews/{review_id}/logs")
async def review_logs(
    review_id: uuid.UUID,
    ctx: View,
    session: Session,
    state: State,
    tail: int = Query(default=2000, ge=0, le=10_000),
) -> dict:
    review = await _review(session, ctx.team, review_id)
    return {"lines": await state.bus.get_logs(str(review.id), tail)}


@router.get("/reviews/{review_id}/stream")
async def review_stream(review_id: uuid.UUID, ctx: View, session: Session, state: State):
    review = await _review(session, ctx.team, review_id)
    lines = await state.bus.get_logs(str(review.id), 2000)
    initial = [("snapshot", {"status": review.status, "phase": review.phase, "lines": lines})]
    channel = review_channel(str(review.id))
    # devolve a conexão ao pool antes do stream: um SSE dura enquanto a aba estiver aberta
    await session.close()
    return sse_response(state.bus, [channel], initial)


@router.post("/reviews/{review_id}/cancel", response_model=s.ReviewOut)
async def cancel_review(
    review_id: uuid.UUID, ctx: ReviewRun, session: Session, state: State
) -> s.ReviewOut:
    review = await _review(session, ctx.team, review_id)
    if review.status not in (ReviewStatus.QUEUED, ReviewStatus.RUNNING):
        raise conflict("a revisão não está em andamento")
    await reviews.cancel_active(session, review.gate_id, reason=f"cancelada por {ctx.actor}")
    gate = await session.get(m.Gate, review.gate_id)
    if gate is not None and gate.current_review_id == review.id:
        await gates.recompute(session, gate)
    await session.commit()
    if gate is not None:
        await gates.publish(session, state, gate.id)
    await gates.notify(
        state,
        ctx.team.name,
        "review",
        {
            "review_id": str(review.id),
            "pull_request_id": str(review.pull_request_id),
            "status": review.status,
        },
    )
    return review_out(review)


# --------------------------------------------------------------------------- tempo real
@router.get("/events")
async def team_events(ctx: View, session: Session, state: State):
    channel = team_channel(ctx.team.name)
    await session.close()  # o stream não usa o banco: não segura conexão do pool
    return sse_response(state.bus, [channel])
