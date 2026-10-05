"""Números do painel de um time."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.security.auth import TeamContext
from sentinela_api.services import gates as gate_svc
from sentinela_api.services.serializers import pr_list_out
from sentinela_core.enums import GateStatus, PullRequestState, RunnerStatus

TZ = ZoneInfo("America/Sao_Paulo")
DAYS = 14


def _now() -> datetime:
    return datetime.now(UTC)


async def _count_open_by_status(session: AsyncSession, team_id) -> dict[str, int]:
    rows = await session.execute(
        select(m.Gate.status, func.count())
        .join(m.PullRequest, m.PullRequest.current_gate_id == m.Gate.id)
        .where(
            m.PullRequest.team_id == team_id,
            m.PullRequest.state == PullRequestState.OPEN,
            m.PullRequest.gated,
        )
        .group_by(m.Gate.status)
    )
    return dict(rows.all())


async def build(session: AsyncSession, ctx: TeamContext) -> s.DashboardOut:
    team = ctx.team
    now = _now()
    open_status = await _count_open_by_status(session, team.id)

    week = now - timedelta(days=7)
    month = now - timedelta(days=30)
    decided = (
        await session.execute(
            select(m.Gate.human_required, m.Gate.created_at, m.Gate.decided_at, m.Gate.override_by)
            .join(m.PullRequest, m.PullRequest.id == m.Gate.pull_request_id)
            .where(m.PullRequest.team_id == team.id, m.Gate.decided_at >= week)
        )
    ).all()
    approved = [r for r in decided if not r.override_by]
    human_minutes = [
        (r.decided_at - r.created_at).total_seconds() / 60 for r in approved if r.human_required
    ]

    merged_without = await session.scalar(
        select(func.count())
        .select_from(m.PullRequest)
        .where(
            m.PullRequest.team_id == team.id,
            m.PullRequest.merged_without_gate,
            m.PullRequest.merged_at >= month,
        )
    )
    overrides = await session.scalar(
        select(func.count())
        .select_from(m.AuditLog)
        .where(
            m.AuditLog.team_id == team.id,
            m.AuditLog.action == "gate.override",
            m.AuditLog.at >= month,
        )
    )
    stats_rows = (
        await session.scalars(
            select(m.Review.stats).where(m.Review.team_id == team.id, m.Review.finished_at >= week)
        )
    ).all()
    cost = sum(float((st or {}).get("cost_usd") or 0) for st in stats_rows)

    # ------------------------------------------------------------ série diária
    start = (now.astimezone(TZ) - timedelta(days=DAYS - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    rows = (
        await session.execute(
            select(m.Gate.created_at, m.Gate.status, m.Gate.human_required, m.Gate.decided_at)
            .join(m.PullRequest, m.PullRequest.id == m.Gate.pull_request_id)
            .where(m.PullRequest.team_id == team.id, m.Gate.created_at >= start)
        )
    ).all()
    days = {(start + timedelta(days=i)).date().isoformat(): [0, 0, 0, 0] for i in range(DAYS)}
    for created_at, status, human, decided_at in rows:
        key = created_at.astimezone(TZ).date().isoformat()
        if key not in days:
            continue
        if decided_at is not None and status != GateStatus.OVERRIDDEN:
            days[key][1 if human else 0] += 1
        elif status in (GateStatus.BLOCKED, GateStatus.REJECTED):
            days[key][2] += 1
        else:
            days[key][3] += 1
    daily = [
        s.DailyPoint(day=k, approved_ai=v[0], approved_human=v[1], blocked=v[2], other=v[3])
        for k, v in days.items()
    ]

    # ------------------------------------------------------------ regras mais violadas
    top = (
        await session.execute(
            select(
                m.Finding.rule_code,
                func.max(m.Finding.rule_title),
                func.max(m.Finding.category),
                func.max(m.Finding.severity),
                func.count(),
                func.sum(case((m.Finding.status == "waived", 1), else_=0)),
                func.sum(case((m.Finding.status == "false_positive", 1), else_=0)),
            )
            .where(
                m.Finding.team_id == team.id,
                m.Finding.created_at >= month,
                m.Finding.inherited.is_(False),
            )
            .group_by(m.Finding.rule_code)
            .order_by(func.count().desc())
            .limit(8)
        )
    ).all()
    top_rules = [
        s.RuleCount(
            rule_code=code,
            rule_title=title,
            category=cat,
            severity=sev,
            count=count,
            waived=waived or 0,
            dismissed=dismissed or 0,
        )
        for code, title, cat, sev, count, waived, dismissed in top
    ]
    by_category = dict(
        (
            await session.execute(
                select(m.Finding.category, func.count())
                .where(
                    m.Finding.team_id == team.id,
                    m.Finding.created_at >= month,
                    m.Finding.inherited.is_(False),
                )
                .group_by(m.Finding.category)
            )
        ).all()
    )

    # ------------------------------------------------------------ filas
    awaiting = (
        (
            await session.scalars(
                select(m.PullRequest)
                .join(m.Gate, m.PullRequest.current_gate_id == m.Gate.id)
                .where(
                    m.PullRequest.team_id == team.id,
                    m.PullRequest.state == PullRequestState.OPEN,
                    m.Gate.status == GateStatus.AWAITING_APPROVAL,
                )
                .order_by(m.Gate.updated_at)
                .limit(20)
            )
        )
        .unique()
        .all()
    )
    mine = (
        [pr for pr in awaiting if not gate_svc.is_author(ctx.principal, pr)]
        if ctx.can("gate.approve")
        else []
    )
    recent = (
        (
            await session.scalars(
                select(m.PullRequest)
                .where(m.PullRequest.team_id == team.id)
                .order_by(m.PullRequest.updated_at.desc())
                .limit(8)
            )
        )
        .unique()
        .all()
    )
    runners = (
        await session.execute(select(m.Runner.status, func.count()).group_by(m.Runner.status))
    ).all()
    runner_counts = dict(runners)

    return s.DashboardOut(
        kpis=s.DashboardKpis(
            awaiting_approval=open_status.get(GateStatus.AWAITING_APPROVAL, 0),
            blocked=open_status.get(GateStatus.BLOCKED, 0)
            + open_status.get(GateStatus.REJECTED, 0),
            reviewing=open_status.get(GateStatus.REVIEWING, 0),
            errors=open_status.get(GateStatus.ERROR, 0),
            approved_7d=len(approved),
            approved_by_ai_7d=sum(1 for r in approved if not r.human_required),
            merged_without_gate_30d=merged_without or 0,
            overrides_30d=overrides or 0,
            median_approval_minutes_7d=round(statistics.median(human_minutes), 1)
            if human_minutes
            else None,
            ai_cost_usd_7d=round(cost, 4),
        ),
        daily=daily,
        top_rules=top_rules,
        by_category=by_category,
        my_queue=await pr_list_out(session, list(mine)[:8]),
        recent=await pr_list_out(session, list(recent)),
        runners_online=runner_counts.get(RunnerStatus.ONLINE, 0),
        runners_total=sum(runner_counts.values()),
    )
