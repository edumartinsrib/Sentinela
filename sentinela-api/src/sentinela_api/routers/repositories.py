"""Repositórios de um time: perfis aplicados, modo do gate, política de aprovação,
webhook e diagnóstico da proteção de branch no provedor."""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import RepoWrite, Session, State, View
from sentinela_api.errors import ApiError, conflict, not_found, unprocessable
from sentinela_api.providers.base import ProviderError
from sentinela_api.services import audit, gates
from sentinela_api.services import pull_requests as pr_svc
from sentinela_api.services.serializers import repository_out, webhook_url
from sentinela_core.enums import PullRequestState
from sentinela_core.paths import is_valid_glob

router = APIRouter(prefix="/api/v1/teams/{team}/repositories", tags=["repositórios"])


async def _repo(session, team: m.Team, repo_id: uuid.UUID) -> m.Repository:
    repo = await session.get(m.Repository, repo_id)
    if repo is None or repo.team_id != team.id:
        raise not_found("repositório")
    return repo


async def _open_counts(session, team_id) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(m.PullRequest.repository_id, func.count())
        .where(m.PullRequest.team_id == team_id, m.PullRequest.state == PullRequestState.OPEN)
        .group_by(m.PullRequest.repository_id)
    )
    return dict(rows.all())


async def _out(session, state, repo: m.Repository) -> s.RepositoryOut:
    counts = await _open_counts(session, repo.team_id)
    return repository_out(state.settings, repo, counts.get(repo.id, 0))


async def _profiles(session, team: m.Team, ids: list[str]) -> list[m.Profile]:
    out = []
    for raw in ids:
        try:
            profile = await session.get(m.Profile, uuid.UUID(raw))
        except ValueError:
            profile = None
        if profile is None or profile.team_id != team.id:
            raise unprocessable(f"perfil {raw} não existe neste time")
        out.append(profile)
    return out


def _clone_url(raw: str | None, integration: m.Integration, ctx, state) -> str | None:
    """O runner manda o token da integração para este endereço: só o administrador global
    troca, e só para o mesmo host da integração (file:// apenas no modo de desenvolvimento)."""
    value = (raw or "").strip()
    if not value:
        return None
    if not ctx.principal.is_superadmin:
        raise ApiError(403, "só administradores globais definem o endereço de clone")
    parts = urlsplit(value)
    if parts.scheme == "file":
        if state.settings.auth_mode != "dev":
            raise unprocessable("clone por file:// só no modo de desenvolvimento")
        return value
    allowed = {urlsplit(u).netloc.lower() for u in (integration.web_url, integration.api_url) if u}
    if parts.scheme not in ("https", "http") or parts.netloc.lower() not in allowed:
        raise unprocessable(
            "o endereço de clone precisa usar o mesmo host da integração "
            f"({', '.join(sorted(allowed))})"
        )
    if parts.username or parts.password:
        raise unprocessable("o endereço de clone não pode ter credenciais")
    return value


def _branches(values: list[str] | None, default: str) -> list[str]:
    clean = [b.strip() for b in (values or []) if b and b.strip()]
    bad = [b for b in clean if not is_valid_glob(b)]
    if bad:
        raise unprocessable(f"branch inválida: {', '.join(bad)}")
    return clean or [default]


@router.get("", response_model=list[s.RepositoryOut])
async def list_repositories(ctx: View, session: Session, state: State) -> list[s.RepositoryOut]:
    repos = (
        (
            await session.scalars(
                select(m.Repository)
                .where(m.Repository.team_id == ctx.team.id)
                .order_by(m.Repository.full_name)
            )
        )
        .unique()
        .all()
    )
    counts = await _open_counts(session, ctx.team.id)
    return [repository_out(state.settings, r, counts.get(r.id, 0)) for r in repos]


@router.post("", response_model=s.RepositoryOut, status_code=201)
async def create_repository(
    body: s.RepositoryCreate, ctx: RepoWrite, session: Session, state: State
) -> s.RepositoryOut:
    integration = await session.get(m.Integration, uuid.UUID(body.integration_id))
    if integration is None:
        raise not_found("integração")
    if not integration.enabled:
        raise conflict("integração desabilitada")
    full_name = body.full_name.strip().strip("/")
    if not body.lookup and not ctx.principal.is_superadmin:
        # Sem a consulta, o nome não é conferido no provedor (grafia, existência, acesso).
        raise ApiError(403, "só administradores globais cadastram sem consultar o provedor")
    external_id = web = None
    default_branch = "main"
    if body.lookup:
        try:
            client = await state.providers.client(integration)
            remote = await client.get_repository(full_name)
        except ProviderError as exc:
            raise ApiError(422, f"não foi possível acessar {full_name}: {exc}") from exc
        full_name, external_id = remote.full_name, remote.external_id
        default_branch, web = remote.default_branch, remote.web_url
    existing = await session.scalar(
        select(m.Repository).where(
            m.Repository.integration_id == integration.id,
            func.lower(m.Repository.full_name) == full_name.lower(),
        )
    )
    if existing is not None:
        raise conflict(f"{full_name} já está cadastrado no time {existing.team.name}")
    if body.enforcement.value != "enforce" and not ctx.principal.is_superadmin:
        raise ApiError(403, "só administradores globais deixam um repositório em observação")
    clone_url = _clone_url(body.clone_url, integration, ctx, state)
    profiles = await _profiles(session, ctx.team, body.profile_ids)
    repo = m.Repository(
        team=ctx.team,
        integration=integration,
        full_name=full_name,
        external_id=external_id,
        web_url=web,
        clone_url=clone_url,
        default_branch=default_branch,
        gated_branches=_branches(body.gated_branches, default_branch),
        gate_mode=body.gate_mode.value,
        enforcement=body.enforcement.value,
        merge_method=body.merge_method.value,
        status_context=body.status_context,
        approval_mode=body.approval_mode.value,
        human_min_severity=body.human_min_severity.value,
        block_severity=body.block_severity.value,
        min_approvals=body.min_approvals,
        carry_waivers=body.carry_waivers,
        post_comments=body.post_comments,
        review_drafts=body.review_drafts,
        created_by=ctx.actor,
        model=None,
        profiles=profiles,
    )
    session.add(repo)
    await session.flush()
    audit.record(
        session,
        actor=ctx.actor,
        action="repository.create",
        resource_type="repository",
        resource_id=repo.id,
        team_id=ctx.team.id,
        after={**(audit.snapshot(repo) or {}), "profiles": [p.name for p in profiles]},
    )
    await session.commit()
    return await _out(session, state, repo)


@router.get("/{repo_id}", response_model=s.RepositoryOut)
async def get_repository(
    repo_id: uuid.UUID, ctx: View, session: Session, state: State
) -> s.RepositoryOut:
    return await _out(session, state, await _repo(session, ctx.team, repo_id))


@router.patch("/{repo_id}", response_model=s.RepositoryOut)
async def update_repository(
    repo_id: uuid.UUID, body: s.RepositoryUpdate, ctx: RepoWrite, session: Session, state: State
) -> s.RepositoryOut:
    repo = await _repo(session, ctx.team, repo_id)
    before = {**(audit.snapshot(repo) or {}), "profiles": [p.name for p in repo.profiles]}
    data = body.model_dump(exclude_unset=True, mode="json")
    if "model_id" in data:
        if not ctx.principal.is_superadmin:
            raise ApiError(403, "só administradores globais escolhem o modelo de IA")
        model_id = data.pop("model_id")
        repo.model = await session.get(m.AiModel, uuid.UUID(model_id)) if model_id else None
    if "profile_ids" in data:
        repo.profiles = await _profiles(session, ctx.team, data.pop("profile_ids") or [])
    if "gated_branches" in data:
        repo.gated_branches = _branches(data.pop("gated_branches"), repo.default_branch)
    if "clone_url" in data:
        repo.clone_url = _clone_url(data.pop("clone_url"), repo.integration, ctx, state)
    relaxing = data.get("enforcement") not in (None, repo.enforcement) and (
        data.get("enforcement") != "enforce"
    )
    if relaxing and not ctx.principal.is_superadmin:
        # Observação publica "success" em todos os PRs: não pode ser atalho do tech lead.
        raise ApiError(403, "só administradores globais deixam um repositório em observação")
    for key, value in data.items():
        if value is not None:
            setattr(repo, key, value)
    audit.record(
        session,
        actor=ctx.actor,
        action="repository.update",
        resource_type="repository",
        resource_id=repo.id,
        team_id=ctx.team.id,
        before=before,
        after={**(audit.snapshot(repo) or {}), "profiles": [p.name for p in repo.profiles]},
    )
    await session.commit()
    # o modo observação muda o status publicado dos gates abertos
    if "enforcement" in data or "status_context" in data:
        open_gates = (
            await session.scalars(
                select(m.PullRequest.current_gate_id).where(
                    m.PullRequest.repository_id == repo.id,
                    m.PullRequest.state == PullRequestState.OPEN,
                    m.PullRequest.current_gate_id.is_not(None),
                )
            )
        ).all()
        for gate_id in open_gates:
            gate = await session.get(m.Gate, gate_id)
            if gate is not None:
                gate.published_state = None
                await session.commit()
                await gates.publish(session, state, gate_id)
    return await _out(session, state, repo)


@router.delete("/{repo_id}", status_code=204)
async def delete_repository(repo_id: uuid.UUID, ctx: RepoWrite, session: Session) -> Response:
    repo = await _repo(session, ctx.team, repo_id)
    audit.record(
        session,
        actor=ctx.actor,
        action="repository.delete",
        resource_type="repository",
        resource_id=repo.id,
        team_id=ctx.team.id,
        before=audit.snapshot(repo),
    )
    await session.delete(repo)
    await session.commit()
    return Response(status_code=204)


@router.post("/{repo_id}/sync", response_model=s.SyncOut)
async def sync_repository(
    repo_id: uuid.UUID, ctx: RepoWrite, session: Session, state: State
) -> s.SyncOut:
    repo = await _repo(session, ctx.team, repo_id)
    try:
        total, queued = await pr_svc.sync_repository(session, state, repo, actor=ctx.actor)
    except ProviderError as exc:
        raise ApiError(502, f"falha ao consultar o provedor: {exc}") from exc
    return s.SyncOut(pull_requests=total, reviews_queued=queued)


@router.post("/{repo_id}/webhook", response_model=s.RepositoryOut)
async def create_webhook(
    repo_id: uuid.UUID, ctx: RepoWrite, session: Session, state: State
) -> s.RepositoryOut:
    repo = await _repo(session, ctx.team, repo_id)
    secret = await state.providers.webhook_secret(repo.integration)
    if not secret:
        raise conflict("a integração não tem segredo de webhook")
    url = webhook_url(state.settings, repo.integration)
    try:
        client = await state.providers.client(repo.integration)
        repo.webhook_id = await client.create_webhook(repo.full_name, url, secret)
    except ProviderError as exc:
        raise ApiError(502, f"não foi possível criar o webhook: {exc}") from exc
    audit.record(
        session,
        actor=ctx.actor,
        action="repository.webhook",
        resource_type="repository",
        resource_id=repo.id,
        team_id=ctx.team.id,
        detail=url,
    )
    await session.commit()
    return await _out(session, state, repo)


@router.get("/{repo_id}/protection", response_model=s.ProtectionOut)
async def protection(
    repo_id: uuid.UUID, ctx: View, session: Session, state: State, branch: str | None = None
) -> s.ProtectionOut:
    repo = await _repo(session, ctx.team, repo_id)
    concrete = [b for b in (repo.gated_branches or []) if not any(c in b for c in "*?[{")]
    target = branch or (concrete[0] if concrete else repo.default_branch)
    try:
        client = await state.providers.client(repo.integration)
        report = await client.check_protection(
            repo.full_name,
            target,
            repo.status_context,
            require_status=gates.uses_status_check(repo),
            platform_merge=gates.uses_platform_merge(repo),
        )
    except ProviderError as exc:
        raise ApiError(502, f"não foi possível consultar a proteção: {exc}") from exc
    return s.ProtectionOut(
        ok=report.ok, branch=target, checks=[s.ProtectionCheck(**c) for c in report.checks]
    )
