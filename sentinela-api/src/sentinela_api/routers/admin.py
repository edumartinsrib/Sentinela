"""Usuário atual, times, usuários, papéis e auditoria."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import AuditView, Session, SuperAdmin, TeamAdmin, User
from sentinela_api.errors import ApiError, conflict, not_found, unprocessable
from sentinela_api.security.auth import load_team
from sentinela_api.services import audit
from sentinela_api.services.serializers import audit_out, binding_out, team_out, user_out

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/me", response_model=s.MeOut)
async def me(session: Session, principal: User) -> s.MeOut:
    teams = (await session.scalars(select(m.Team).order_by(m.Team.name))).all()
    by_id = {t.id: t for t in teams}
    roles = [
        s.RoleAssignment(team=by_id[t].name if t in by_id else None, role=role)
        for t, role in principal.bindings
    ]
    if principal.is_superadmin:
        visible = list(teams)
        if not any(r.team is None and r.role == "admin" for r in roles):
            roles.append(s.RoleAssignment(team=None, role="admin"))
    else:
        visible = [t for t in teams if principal.roles_in(t.id)]
    u = principal.user
    return s.MeOut(
        id=str(u.id),
        username=u.username,
        display_name=u.display_name,
        email=u.email,
        is_superadmin=principal.is_superadmin,
        github_login=u.github_login,
        gitlab_username=u.gitlab_username,
        roles=roles,
        teams=[team_out(t) for t in visible],
    )


# --------------------------------------------------------------------------- times
@router.get("/teams", response_model=list[s.TeamOut])
async def list_teams(session: Session, principal: User) -> list[s.TeamOut]:
    teams = (await session.scalars(select(m.Team).order_by(m.Team.name))).all()
    return [team_out(t) for t in teams if principal.is_superadmin or principal.roles_in(t.id)]


@router.post("/teams", response_model=s.TeamOut, status_code=201)
async def create_team(body: s.TeamCreate, session: Session, principal: SuperAdmin) -> s.TeamOut:
    if await session.scalar(select(m.Team.id).where(m.Team.name == body.name)):
        raise conflict(f"time {body.name} já existe")
    team = m.Team(
        name=body.name, display_name=body.display_name or body.name, description=body.description
    )
    session.add(team)
    await session.flush()
    audit.record(
        session,
        actor=principal.username,
        action="team.create",
        resource_type="team",
        resource_id=team.id,
        team_id=team.id,
        after=audit.snapshot(team),
    )
    await session.commit()
    await session.refresh(team)
    return team_out(team)


@router.patch("/teams/{team}", response_model=s.TeamOut)
async def update_team(body: s.TeamUpdate, ctx: TeamAdmin, session: Session) -> s.TeamOut:
    before = audit.snapshot(ctx.team)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(ctx.team, key, value)
    audit.record(
        session,
        actor=ctx.actor,
        action="team.update",
        resource_type="team",
        resource_id=ctx.team.id,
        team_id=ctx.team.id,
        before=before,
        after=audit.snapshot(ctx.team),
    )
    await session.commit()
    return team_out(ctx.team)


# --------------------------------------------------------------------------- usuários
@router.get("/users", response_model=list[s.UserOut])
async def list_users(session: Session, principal: User) -> list[s.UserOut]:
    if not principal.is_superadmin and not any(r == "admin" for _, r in principal.bindings):
        raise ApiError(403, "apenas administradores")
    users = (await session.scalars(select(m.User).order_by(m.User.username))).all()
    return [user_out(u) for u in users]


@router.post("/users", response_model=s.UserOut, status_code=201)
async def create_user(body: s.UserCreate, session: Session, principal: SuperAdmin) -> s.UserOut:
    username = body.username.strip().lower()
    if await session.scalar(select(m.User.id).where(m.User.username == username)):
        raise conflict("usuário já existe")
    user = m.User(
        username=username,
        display_name=body.display_name or username,
        email=body.email,
        is_superadmin=body.is_superadmin,
        github_login=(body.github_login or "").strip() or None,
        gitlab_username=(body.gitlab_username or "").strip() or None,
    )
    session.add(user)
    await session.flush()
    audit.record(
        session,
        actor=principal.username,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        after=audit.snapshot(user),
    )
    await session.commit()
    await session.refresh(user)
    return user_out(user)


@router.patch("/users/{user_id}", response_model=s.UserOut)
async def update_user(
    user_id: uuid.UUID, body: s.UserUpdate, session: Session, principal: SuperAdmin
) -> s.UserOut:
    """Só administradores globais alteram logins dos provedores: são eles que impedem o
    autor de aprovar o próprio PR."""
    user = await session.get(m.User, user_id)
    if user is None:
        raise not_found("usuário")
    before = audit.snapshot(user)
    data = body.model_dump(exclude_unset=True)
    if data.get("is_superadmin") is False and user.id == principal.user.id:
        raise conflict("você não pode remover o próprio acesso de administrador")
    for key, value in data.items():
        if key in ("github_login", "gitlab_username", "email"):
            value = (value or "").strip() or None
        elif value is None:
            continue
        setattr(user, key, value)
    audit.record(
        session,
        actor=principal.username,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        before=before,
        after=audit.snapshot(user),
    )
    await session.commit()
    return user_out(user)


# --------------------------------------------------------------------------- papéis
async def _bindings(session, team_id: uuid.UUID | None) -> list[s.RoleBindingOut]:
    query = select(m.RoleBinding).order_by(m.RoleBinding.created_at)
    query = query.where(
        m.RoleBinding.team_id.is_(None) if team_id is None else m.RoleBinding.team_id == team_id
    )
    return [binding_out(b) for b in (await session.scalars(query)).all()]


async def _create_binding(
    session, actor: str, team: m.Team | None, body: s.RoleBindingCreate
) -> s.RoleBindingOut:
    if bool(body.username) == bool(body.group):
        raise unprocessable("informe usuário ou grupo (um dos dois)")
    user = None
    if body.username:
        username = body.username.strip().lower()
        user = await session.scalar(select(m.User).where(m.User.username == username))
        if user is None:
            user = m.User(username=username, display_name=username)
            session.add(user)
            await session.flush()
    dup = await session.scalar(
        select(m.RoleBinding.id).where(
            m.RoleBinding.team_id.is_(None) if team is None else m.RoleBinding.team_id == team.id,
            m.RoleBinding.role == body.role.value,
            m.RoleBinding.user_id == user.id if user else m.RoleBinding.group == body.group,
        )
    )
    if dup:
        raise conflict("esse papel já está atribuído")
    binding = m.RoleBinding(
        team=team,
        user=user,
        group=body.group,
        role=body.role.value,
        created_by=actor,
    )
    session.add(binding)
    await session.flush()
    audit.record(
        session,
        actor=actor,
        action="role.grant",
        resource_type="role_binding",
        resource_id=binding.id,
        team_id=team.id if team else None,
        after={
            "user": user.username if user else None,
            "group": body.group,
            "role": body.role.value,
        },
    )
    await session.commit()
    return binding_out(binding)


@router.get("/teams/{team}/roles", response_model=list[s.RoleBindingOut])
async def list_team_roles(ctx: TeamAdmin, session: Session) -> list[s.RoleBindingOut]:
    return await _bindings(session, ctx.team.id)


@router.post("/teams/{team}/roles", response_model=s.RoleBindingOut, status_code=201)
async def create_team_role(
    body: s.RoleBindingCreate, ctx: TeamAdmin, session: Session
) -> s.RoleBindingOut:
    return await _create_binding(session, ctx.actor, ctx.team, body)


@router.delete("/teams/{team}/roles/{binding_id}", status_code=204)
async def delete_team_role(binding_id: uuid.UUID, ctx: TeamAdmin, session: Session) -> Response:
    binding = await session.get(m.RoleBinding, binding_id)
    if binding is None or binding.team_id != ctx.team.id:
        raise not_found("papel")
    audit.record(
        session,
        actor=ctx.actor,
        action="role.revoke",
        resource_type="role_binding",
        resource_id=binding.id,
        team_id=ctx.team.id,
        before={
            "user": binding.user.username if binding.user else None,
            "group": binding.group,
            "role": binding.role,
        },
    )
    await session.delete(binding)
    await session.commit()
    return Response(status_code=204)


@router.get("/roles", response_model=list[s.RoleBindingOut])
async def list_global_roles(session: Session, principal: SuperAdmin) -> list[s.RoleBindingOut]:
    return await _bindings(session, None)


@router.post("/roles", response_model=s.RoleBindingOut, status_code=201)
async def create_global_role(
    body: s.RoleBindingCreate, session: Session, principal: SuperAdmin
) -> s.RoleBindingOut:
    return await _create_binding(session, principal.username, None, body)


@router.delete("/roles/{binding_id}", status_code=204)
async def delete_global_role(
    binding_id: uuid.UUID, session: Session, principal: SuperAdmin
) -> Response:
    binding = await session.get(m.RoleBinding, binding_id)
    if binding is None or binding.team_id is not None:
        raise not_found("papel")
    audit.record(
        session,
        actor=principal.username,
        action="role.revoke",
        resource_type="role_binding",
        resource_id=binding.id,
        before={
            "user": binding.user.username if binding.user else None,
            "group": binding.group,
            "role": binding.role,
        },
    )
    await session.delete(binding)
    await session.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- auditoria
async def _audit_page(
    session, team_id, *, limit, offset, action, actor, resource_type, since, until
) -> s.Page[s.AuditOut]:
    query = select(m.AuditLog)
    if team_id is not None:
        query = query.where(m.AuditLog.team_id == team_id)
    if action:
        query = query.where(m.AuditLog.action.startswith(action))
    if actor:
        query = query.where(m.AuditLog.actor == actor)
    if resource_type:
        query = query.where(m.AuditLog.resource_type == resource_type)
    if since:
        query = query.where(m.AuditLog.at >= since)
    if until:
        query = query.where(m.AuditLog.at <= until)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.scalars(
            query.order_by(m.AuditLog.at.desc(), m.AuditLog.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    teams = dict((await session.execute(select(m.Team.id, m.Team.name))).all())
    return s.Page(
        items=[audit_out(r, teams) for r in rows], total=total or 0, limit=limit, offset=offset
    )


@router.get("/teams/{team}/audit", response_model=s.Page[s.AuditOut])
async def team_audit(
    ctx: AuditView,
    session: Session,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> s.Page[s.AuditOut]:
    return await _audit_page(
        session,
        ctx.team.id,
        limit=limit,
        offset=offset,
        action=action,
        actor=actor,
        resource_type=resource_type,
        since=since,
        until=until,
    )


@router.get("/audit", response_model=s.Page[s.AuditOut])
async def global_audit(
    session: Session,
    principal: SuperAdmin,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    team: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> s.Page[s.AuditOut]:
    team_id = (await load_team(session, team)).id if team else None
    return await _audit_page(
        session,
        team_id,
        limit=limit,
        offset=offset,
        action=action,
        actor=actor,
        resource_type=resource_type,
        since=since,
        until=until,
    )
