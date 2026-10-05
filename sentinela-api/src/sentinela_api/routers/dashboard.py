from __future__ import annotations

from fastapi import APIRouter

from sentinela_api import schemas as s
from sentinela_api.deps import Session, View
from sentinela_api.services import dashboard

router = APIRouter(prefix="/api/v1/teams/{team}", tags=["painel"])


@router.get("/dashboard", response_model=s.DashboardOut)
async def get_dashboard(ctx: View, session: Session) -> s.DashboardOut:
    return await dashboard.build(session, ctx)
