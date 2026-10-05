"""Autenticação dos usuários do console e RBAC por time."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Header, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api.db import get_session
from sentinela_api.errors import ApiError
from sentinela_api.models import RoleBinding, Team, User
from sentinela_api.state import AppState, get_state

DEV_USER_HEADER = "X-Sentinela-User"

# Ação → papéis que a permitem no time.
PERMISSIONS: dict[str, set[str]] = {
    "view": {"admin", "tech_lead", "reviewer", "developer", "reader"},
    # perfis de padrão e regras
    "standards.write": {"admin", "tech_lead"},
    # repositórios do time e política do gate
    "repo.write": {"admin", "tech_lead"},
    "review.run": {"admin", "tech_lead", "reviewer", "developer"},
    "gate.approve": {"admin", "tech_lead", "reviewer"},
    # aceitar um apontamento como exceção (com justificativa)
    "finding.waive": {"admin", "tech_lead"},
    # descartar como falso positivo
    "finding.dismiss": {"admin", "tech_lead", "reviewer"},
    "finding.dispute": {"admin", "tech_lead", "reviewer", "developer"},
    "pr.merge": {"admin", "tech_lead", "reviewer", "developer"},
    "audit.view": {"admin", "tech_lead"},
    "team.admin": {"admin"},
}


@dataclass
class Principal:
    user: User
    groups: list[str] = field(default_factory=list)
    # (team_id ou None para todos, papel)
    bindings: list[tuple[uuid.UUID | None, str]] = field(default_factory=list)
    group_admin: bool = False

    @property
    def username(self) -> str:
        return self.user.username

    @property
    def is_superadmin(self) -> bool:
        return self.user.is_superadmin or self.group_admin

    def roles_in(self, team_id: uuid.UUID) -> set[str]:
        return {role for t, role in self.bindings if t is None or t == team_id}

    def can(self, action: str, team: Team) -> bool:
        if self.is_superadmin:
            return True
        return bool(self.roles_in(team.id) & PERMISSIONS[action])

    def provider_login(self, provider: str) -> str | None:
        """Login vinculado explicitamente no provedor (só ele comprova quem é quem)."""
        value = self.user.github_login if provider == "github" else self.user.gitlab_username
        return value.lower() if value else None

    def provider_logins(self) -> set[str]:
        """Todos os nomes pelos quais a pessoa pode ser o autor (para bloquear, não liberar)."""
        logins = {self.user.username.lower()}
        for value in (self.user.github_login, self.user.gitlab_username):
            if value:
                logins.add(value.lower())
        if self.user.email:
            logins.add(self.user.email.lower().split("@")[0])
        return logins


async def _load_bindings(
    session: AsyncSession, user: User, groups: list[str]
) -> list[tuple[uuid.UUID | None, str]]:
    conds = [RoleBinding.user_id == user.id]
    if groups:
        conds.append(RoleBinding.group.in_(groups))
    rows = await session.execute(select(RoleBinding.team_id, RoleBinding.role).where(or_(*conds)))
    return [(t, role) for t, role in rows.all()]


async def upsert_user(
    session: AsyncSession,
    username: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
    external_id: str | None = None,
    bootstrap_admin: bool = False,
) -> User:
    user = await session.scalar(select(User).where(User.username == username))
    now = datetime.now(UTC)
    if user is None:
        user = User(
            username=username,
            display_name=display_name or username,
            email=email,
            external_id=external_id,
            is_superadmin=bootstrap_admin,
            last_login_at=now,
        )
        session.add(user)
        await session.commit()
        return user
    changed = False
    if user.last_login_at is None or now - user.last_login_at > timedelta(minutes=5):
        user.last_login_at = now
        changed = True
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        changed = True
    if email and user.email != email:
        user.email = email
        changed = True
    if bootstrap_admin and not user.is_superadmin:
        user.is_superadmin = True
        changed = True
    if changed:
        await session.commit()
    return user


async def get_principal(
    request: Request,
    session: AsyncSession = Depends(get_session),
    state: AppState = Depends(get_state),
    authorization: str | None = Header(default=None),
    x_sentinela_user: str | None = Header(default=None),
) -> Principal:
    settings = state.settings
    if settings.auth_mode == "dev":
        username = (x_sentinela_user or "").strip().lower()
        if not username and authorization and authorization.lower().startswith("bearer dev:"):
            username = authorization[len("bearer dev:") :].strip().lower()
        if not username:
            raise ApiError(401, f"informe o usuário ({DEV_USER_HEADER}) no modo dev")
        user = await upsert_user(
            session, username, bootstrap_admin=username in settings.bootstrap_admin_list
        )
        groups: list[str] = []
    else:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise ApiError(401, "token ausente")
        assert state.oidc is not None
        try:
            ident = await state.oidc.verify(authorization[7:])
        except Exception as exc:  # noqa: BLE001 - qualquer falha do JWT vira 401
            raise ApiError(401, f"token inválido: {exc}") from exc
        user = await upsert_user(
            session,
            ident.username,
            display_name=ident.display_name,
            email=ident.email,
            external_id=ident.subject,
            bootstrap_admin=ident.username in settings.bootstrap_admin_list,
        )
        groups = ident.groups

    principal = Principal(
        user=user,
        groups=groups,
        bindings=await _load_bindings(session, user, groups),
        group_admin=bool(set(groups) & set(settings.admin_group_list)),
    )
    request.state.principal = principal
    return principal


@dataclass
class TeamContext:
    team: Team
    principal: Principal

    @property
    def actor(self) -> str:
        return self.principal.username

    def can(self, action: str) -> bool:
        return self.principal.can(action, self.team)

    def require(self, action: str) -> None:
        if not self.can(action):
            raise ApiError(403, f"sem permissão para {action} no time {self.team.name}")


async def load_team(session: AsyncSession, name: str) -> Team:
    team = await session.scalar(select(Team).where(Team.name == name))
    if team is None:
        raise ApiError(404, f"time {name} não encontrado")
    return team


def require(action: str) -> Callable[..., Coroutine[Any, Any, TeamContext]]:
    """Dependência: carrega o time do path `{team}` e exige a permissão."""

    async def dep(
        team: str,
        session: AsyncSession = Depends(get_session),
        principal: Principal = Depends(get_principal),
    ) -> TeamContext:
        ctx = TeamContext(team=await load_team(session, team), principal=principal)
        ctx.require(action)
        return ctx

    return dep


def require_superadmin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_superadmin:
        raise ApiError(403, "apenas administradores globais")
    return principal
