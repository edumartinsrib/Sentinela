"""Conversão dos modelos para os esquemas de saída."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.settings import Settings
from sentinela_core.enums import (
    UNRESOLVED_FINDING,
    FindingStatus,
    Severity,
    severity_at_least,
)
from sentinela_core.gate import GateEvaluation


def team_out(t: m.Team) -> s.TeamOut:
    return s.TeamOut(
        id=str(t.id),
        name=t.name,
        display_name=t.display_name,
        description=t.description,
        created_at=t.created_at,
    )


def user_out(u: m.User) -> s.UserOut:
    return s.UserOut(
        id=str(u.id),
        username=u.username,
        display_name=u.display_name,
        email=u.email,
        is_superadmin=u.is_superadmin,
        github_login=u.github_login,
        gitlab_username=u.gitlab_username,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def binding_out(b: m.RoleBinding) -> s.RoleBindingOut:
    return s.RoleBindingOut(
        id=str(b.id),
        team=b.team.name if b.team else None,
        username=b.user.username if b.user else None,
        display_name=b.user.display_name if b.user else None,
        group=b.group,
        role=b.role,
        created_by=b.created_by,
        created_at=b.created_at,
    )


def audit_out(row: m.AuditLog, teams: dict[uuid.UUID, str]) -> s.AuditOut:
    return s.AuditOut(
        id=row.id,
        at=row.at,
        actor=row.actor,
        actor_type=row.actor_type,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        team=teams.get(row.team_id) if row.team_id else None,
        before=row.before,
        after=row.after,
        detail=row.detail,
    )


# ----------------------------------------------------------------------------- IA
def model_out(model: m.AiModel) -> s.AiModelOut:
    return s.AiModelOut(
        id=str(model.id),
        engine_id=str(model.engine_id),
        engine_name=model.engine.name,
        engine_kind=model.engine.kind,
        model=model.model,
        label=model.label,
        description=model.description,
        enabled=model.enabled,
        is_default=model.is_default,
    )


def engine_out(engine: m.AiEngine, runners_online: int) -> s.AiEngineOut:
    return s.AiEngineOut(
        id=str(engine.id),
        kind=engine.kind,
        name=engine.name,
        description=engine.description,
        enabled=engine.enabled,
        extra_args=list(engine.extra_args or []),
        max_turns=engine.max_turns,
        timeout_s=engine.timeout_s,
        max_budget_usd=engine.max_budget_usd,
        secret_env_names=list(engine.secret_env_names or []),
        models=[model_out(md) for md in engine.models],
        runners_online=runners_online,
    )


# ----------------------------------------------------------------------------- integrações
def webhook_url(settings: Settings, integration: m.Integration) -> str:
    return f"{settings.public_api_url.rstrip('/')}/webhooks/{integration.provider}/{integration.id}"


def integration_out(
    settings: Settings, i: m.Integration, secret: dict[str, Any] | None, repositories: int
) -> s.IntegrationOut:
    secret = secret or {}
    return s.IntegrationOut(
        id=str(i.id),
        name=i.name,
        provider=i.provider,
        api_url=i.api_url,
        web_url=i.web_url,
        enabled=i.enabled,
        bot_login=i.bot_login,
        has_token=bool(secret.get("token")),
        has_webhook_secret=bool(secret.get("webhook_secret")),
        webhook_url=webhook_url(settings, i),
        last_check_at=i.last_check_at,
        last_check_ok=i.last_check_ok,
        last_check_detail=i.last_check_detail,
        repositories=repositories,
        created_at=i.created_at,
    )


# ----------------------------------------------------------------------------- padrões
def rule_out(r: m.Rule, violations: int = 0) -> s.RuleOut:
    return s.RuleOut(
        id=str(r.id),
        code=r.code,
        title=r.title,
        category=r.category,
        severity=r.severity,
        kind=r.kind,
        instruction=r.instruction or "",
        pattern=r.pattern,
        ignore_case=r.ignore_case,
        paths=list(r.paths or []),
        exclude_paths=list(r.exclude_paths or []),
        suggestion=r.suggestion,
        reference_url=r.reference_url,
        enabled=r.enabled,
        position=r.position,
        created_at=r.created_at,
        updated_at=r.updated_at,
        violations_30d=violations,
    )


def _profile_base(p: m.Profile, repos: list[s.RefOut]) -> dict[str, Any]:
    enabled = [r for r in p.rules if r.enabled]
    return dict(
        id=str(p.id),
        name=p.name,
        description=p.description,
        path_globs=list(p.path_globs or []),
        enabled=p.enabled,
        model_id=str(p.model_id) if p.model_id else None,
        model_label=p.model.label if p.model else None,
        rules_total=len(p.rules),
        rules_enabled=len(enabled),
        rules_by_category=dict(Counter(r.category for r in enabled)),
        rules_by_kind=dict(Counter(r.kind for r in enabled)),
        blocking_rules=sum(1 for r in enabled if severity_at_least(r.severity, Severity.HIGH)),
        repositories=repos,
        updated_at=p.updated_at,
        updated_by=p.updated_by,
        created_at=p.created_at,
    )


def profile_summary(p: m.Profile, repos: list[s.RefOut]) -> s.ProfileSummary:
    return s.ProfileSummary(**_profile_base(p, repos))


def profile_out(p: m.Profile, repos: list[s.RefOut], violations: dict[str, int]) -> s.ProfileOut:
    return s.ProfileOut(
        **_profile_base(p, repos),
        instructions=p.instructions or "",
        rules=[rule_out(r, violations.get(r.code, 0)) for r in p.rules],
    )


# ----------------------------------------------------------------------------- repositórios
def repo_web_url(repo: m.Repository) -> str:
    return repo.web_url or f"{repo.integration.web_url.rstrip('/')}/{repo.full_name}"


def repository_out(settings: Settings, repo: m.Repository, open_prs: int) -> s.RepositoryOut:
    return s.RepositoryOut(
        id=str(repo.id),
        team=repo.team.name,
        integration=s.IntegrationRef(
            id=str(repo.integration.id),
            name=repo.integration.name,
            provider=repo.integration.provider,
        ),
        full_name=repo.full_name,
        external_id=repo.external_id,
        web_url=repo_web_url(repo),
        clone_url=repo.clone_url,
        default_branch=repo.default_branch,
        gated_branches=list(repo.gated_branches or []) or [repo.default_branch],
        gate_mode=repo.gate_mode,
        enforcement=repo.enforcement,
        merge_method=repo.merge_method,
        status_context=repo.status_context,
        approval_mode=repo.approval_mode,
        human_min_severity=repo.human_min_severity,
        block_severity=repo.block_severity,
        min_approvals=repo.min_approvals,
        carry_waivers=repo.carry_waivers,
        post_comments=repo.post_comments,
        review_drafts=repo.review_drafts,
        model_id=str(repo.model_id) if repo.model_id else None,
        model_label=repo.model.label if repo.model else None,
        enabled=repo.enabled,
        webhook_url=webhook_url(settings, repo.integration),
        webhook_configured=bool(repo.webhook_id) or repo.last_webhook_at is not None,
        last_webhook_at=repo.last_webhook_at,
        last_sync_at=repo.last_sync_at,
        profiles=[s.RefOut(id=str(p.id), name=p.name) for p in repo.profiles],
        open_pull_requests=open_prs,
        created_at=repo.created_at,
    )


# ----------------------------------------------------------------------------- gates e PRs
class GateCounts:
    """Contagem de apontamentos da revisão atual de cada gate (para listas)."""

    def __init__(self) -> None:
        self.by_review: dict[uuid.UUID, list[tuple[str, str, int]]] = defaultdict(list)

    @classmethod
    async def load(cls, session: AsyncSession, review_ids: list[uuid.UUID]) -> GateCounts:
        out = cls()
        ids = [r for r in review_ids if r]
        if not ids:
            return out
        rows = await session.execute(
            select(m.Finding.review_id, m.Finding.severity, m.Finding.status, func.count())
            .where(m.Finding.review_id.in_(ids))
            .group_by(m.Finding.review_id, m.Finding.severity, m.Finding.status)
        )
        for review_id, severity, status, count in rows.all():
            out.by_review[review_id].append((severity, status, count))
        return out

    def summary(self, gate: m.Gate) -> tuple[int, int, int, dict[str, int]]:
        block = (gate.policy or {}).get("block_severity", Severity.HIGH)
        total = unresolved = blocking = 0
        by_sev: dict[str, int] = {}
        for severity, status, count in self.by_review.get(gate.current_review_id, []):
            total += count
            if FindingStatus(status) in UNRESOLVED_FINDING:
                unresolved += count
                by_sev[severity] = by_sev.get(severity, 0) + count
                if severity_at_least(severity, block):
                    blocking += count
        return total, unresolved, blocking, by_sev


async def review_statuses(
    session: AsyncSession, review_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    ids = [r for r in review_ids if r]
    if not ids:
        return {}
    rows = await session.execute(select(m.Review.id, m.Review.status).where(m.Review.id.in_(ids)))
    return dict(rows.all())


async def approvals_count(session: AsyncSession, gates: list[m.Gate]) -> dict[uuid.UUID, int]:
    pairs = [(g.id, g.current_review_id) for g in gates if g.current_review_id]
    if not pairs:
        return {}
    rows = await session.execute(
        select(
            m.GateDecision.gate_id,
            m.GateDecision.review_id,
            m.GateDecision.username,
            m.GateDecision.decision,
        )
        .where(m.GateDecision.gate_id.in_([p[0] for p in pairs]))
        .order_by(m.GateDecision.created_at)
    )
    current = dict(pairs)
    latest: dict[tuple[uuid.UUID, str], str] = {}
    for gate_id, review_id, username, decision in rows.all():
        if current.get(gate_id) == review_id:
            latest[(gate_id, username)] = decision
    out: dict[uuid.UUID, int] = defaultdict(int)
    for (gate_id, _), decision in latest.items():
        if decision == "approve":
            out[gate_id] += 1
    return out


def gate_summary(
    gate: m.Gate, counts: GateCounts, review_status: str | None, approvals: int
) -> s.GateSummary:
    total, unresolved, blocking, by_sev = counts.summary(gate)
    return s.GateSummary(
        id=str(gate.id),
        status=gate.status,
        description=gate.status_description,
        head_sha=gate.head_sha,
        human_required=gate.human_required,
        approvals=approvals,
        approvals_required=gate.approvals_required,
        findings_total=total,
        findings_open=unresolved,
        findings_blocking=blocking,
        by_severity=by_sev,
        review_status=review_status,
        created_at=gate.created_at,
        updated_at=gate.updated_at,
    )


def repo_ref(repo: m.Repository) -> s.RepoRef:
    return s.RepoRef(
        id=str(repo.id),
        full_name=repo.full_name,
        provider=repo.integration.provider,
        web_url=repo_web_url(repo),
    )


def pr_fields(pr: m.PullRequest, gate: s.GateSummary | None) -> dict[str, Any]:
    return dict(
        id=str(pr.id),
        repository=repo_ref(pr.repository),
        number=pr.number,
        title=pr.title,
        author_login=pr.author_login,
        source_branch=pr.source_branch,
        target_branch=pr.target_branch,
        head_sha=pr.head_sha,
        web_url=pr.web_url,
        state=pr.state,
        draft=pr.draft,
        gated=pr.gated,
        merged_at=pr.merged_at,
        merged_by=pr.merged_by,
        merged_without_gate=pr.merged_without_gate,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        gate=gate,
    )


async def pr_list_out(session: AsyncSession, prs: list[m.PullRequest]) -> list[s.PullRequestOut]:
    gate_list = [pr.current_gate for pr in prs if pr.current_gate is not None]
    review_ids = [g.current_review_id for g in gate_list]
    counts = await GateCounts.load(session, review_ids)
    statuses = await review_statuses(session, review_ids)
    approvals = await approvals_count(session, gate_list)
    out = []
    for pr in prs:
        g = pr.current_gate
        summary = (
            gate_summary(g, counts, statuses.get(g.current_review_id), approvals.get(g.id, 0))
            if g is not None
            else None
        )
        out.append(s.PullRequestOut(**pr_fields(pr, summary)))
    return out


def gate_out(gate: m.Gate, ev: GateEvaluation) -> s.GateOut:
    return s.GateOut(
        id=str(gate.id),
        head_sha=gate.head_sha,
        base_sha=gate.base_sha,
        target_branch=gate.target_branch,
        status=gate.status,
        description=gate.status_description,
        human_required=gate.human_required,
        approvals=ev.approvals,
        approvals_required=gate.approvals_required,
        approved_by=ev.approved_by,
        rejected_by=ev.rejected_by,
        blocking=ev.blocking,
        unresolved=ev.unresolved,
        policy=gate.policy or {},
        decided_at=gate.decided_at,
        override_by=gate.override_by,
        override_reason=gate.override_reason,
        published_state=gate.published_state,
        published_description=gate.published_description,
        published_at=gate.published_at,
        publish_error=gate.publish_error,
        created_at=gate.created_at,
        updated_at=gate.updated_at,
    )


def review_out(r: m.Review) -> s.ReviewOut:
    duration = None
    if r.started_at and r.finished_at:
        duration = (r.finished_at - r.started_at).total_seconds()
    snapshot = r.profiles_snapshot or []
    return s.ReviewOut(
        id=str(r.id),
        gate_id=str(r.gate_id),
        pull_request_id=str(r.pull_request_id),
        status=r.status,
        trigger=r.trigger,
        requested_by=r.requested_by,
        engine_kind=r.engine_kind,
        model=r.model,
        model_label=r.model_label,
        runner_name=r.runner.name if r.runner else None,
        attempt=r.attempt,
        phase=r.phase,
        profiles=[p.get("name", "") for p in snapshot],
        rules=sum(len(p.get("rules", [])) for p in snapshot),
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        duration_s=duration,
        error=r.error,
        summary=r.summary,
        stats=r.stats or {},
        cancel_requested=r.cancel_requested,
    )


def file_url(repo: m.Repository, sha: str, path: str | None, line: int | None) -> str | None:
    if not path:
        return None
    base = repo_web_url(repo).rstrip("/")
    sep = "/-/blob/" if repo.integration.provider == "gitlab" else "/blob/"
    anchor = f"#L{line}" if line else ""
    return f"{base}{sep}{sha}/{quote(path)}{anchor}"


def finding_out(
    f: m.Finding,
    repo: m.Repository,
    sha: str,
    block_severity: str,
    events: list[m.FindingEvent] | None = None,
) -> s.FindingOut:
    return s.FindingOut(
        id=str(f.id),
        review_id=str(f.review_id),
        rule_code=f.rule_code,
        rule_title=f.rule_title,
        profile_name=f.profile_name,
        source=f.source,
        category=f.category,
        severity=f.severity,
        file=f.file,
        line=f.line,
        end_line=f.end_line,
        title=f.title,
        description=f.description,
        suggestion=f.suggestion,
        evidence=f.evidence,
        confidence=f.confidence,
        in_diff=f.in_diff,
        fingerprint=f.fingerprint,
        status=f.status,
        status_reason=f.status_reason,
        status_by=f.status_by,
        status_at=f.status_at,
        inherited=f.inherited,
        blocking=FindingStatus(f.status) in UNRESOLVED_FINDING
        and severity_at_least(f.severity, block_severity),
        file_url=file_url(repo, sha, f.file, f.line),
        created_at=f.created_at,
        events=[
            s.FindingEventOut(at=e.at, actor=e.actor, action=e.action, comment=e.comment)
            for e in events or []
        ],
    )


def decision_out(d: m.GateDecision, current_review: uuid.UUID | None) -> s.DecisionOut:
    return s.DecisionOut(
        id=str(d.id),
        username=d.username,
        display_name=d.display_name,
        decision=d.decision,
        comment=d.comment,
        created_at=d.created_at,
        # reprovação vale para o commit inteiro; aprovação, só para a revisão atual
        current=d.review_id == current_review or d.decision == "reject",
    )


def runner_out(r: m.Runner) -> s.RunnerOut:
    return s.RunnerOut(
        id=str(r.id),
        name=r.name,
        hostname=r.hostname,
        os=r.os,
        labels=list(r.labels or []),
        engines=dict(r.engines or {}),
        slots=r.slots,
        status=r.status,
        enabled=r.enabled,
        draining=r.draining,
        last_heartbeat_at=r.last_heartbeat_at,
        agent_version=r.agent_version,
        running_reviews=list(r.running_reviews or []),
        created_at=r.created_at,
    )
