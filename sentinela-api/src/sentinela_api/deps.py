"""Aliases de dependências usados pelas rotas."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api.db import get_session
from sentinela_api.security.auth import (
    Principal,
    TeamContext,
    get_principal,
    require,
    require_superadmin,
)
from sentinela_api.state import AppState, get_state

Session = Annotated[AsyncSession, Depends(get_session)]
State = Annotated[AppState, Depends(get_state)]
User = Annotated[Principal, Depends(get_principal)]
SuperAdmin = Annotated[Principal, Depends(require_superadmin)]

View = Annotated[TeamContext, Depends(require("view"))]
StandardsWrite = Annotated[TeamContext, Depends(require("standards.write"))]
RepoWrite = Annotated[TeamContext, Depends(require("repo.write"))]
ReviewRun = Annotated[TeamContext, Depends(require("review.run"))]
AuditView = Annotated[TeamContext, Depends(require("audit.view"))]
TeamAdmin = Annotated[TeamContext, Depends(require("team.admin"))]
