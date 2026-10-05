from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from sentinela_api import __version__
from sentinela_api import schemas as s
from sentinela_api.deps import Session, State

router = APIRouter()


@router.get("/api/v1/config", response_model=s.ConfigOut, tags=["console"])
async def config(state: State) -> s.ConfigOut:
    st = state.settings
    return s.ConfigOut(
        auth=s.AuthConfig(
            mode=st.auth_mode,
            authority=st.oidc_authority,
            client_id=st.oidc_client_id,
            scopes=st.oidc_scopes.split(),
        ),
        version=__version__,
        public_api_url=st.public_api_url,
    )


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(session: Session) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
