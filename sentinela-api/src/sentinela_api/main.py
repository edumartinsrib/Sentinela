"""Aplicação FastAPI do Sentinela."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from sentinela_api import __version__
from sentinela_api import models as m
from sentinela_api.db import dispose_engine, init_engine, sessionmaker
from sentinela_api.errors import install_handlers
from sentinela_api.providers.base import ProviderFactory
from sentinela_api.routers import (
    admin,
    ai,
    dashboard,
    integrations,
    public,
    pull_requests,
    repositories,
    runner_api,
    runners,
    standards,
    webhooks,
)
from sentinela_api.security.oidc import OidcVerifier
from sentinela_api.services import ai as ai_svc
from sentinela_api.services import runners as runner_svc
from sentinela_api.services.events import build_event_bus
from sentinela_api.services.secrets import SecretStore, build_secret_store
from sentinela_api.settings import Settings, get_settings
from sentinela_api.state import AppState

log = logging.getLogger(__name__)


async def seed(settings: Settings) -> None:
    async with sessionmaker()() as session:
        if settings.default_team and not await session.scalar(select(m.Team.id).limit(1)):
            name = settings.default_team
            session.add(
                m.Team(
                    name=name,
                    display_name=name.replace("-", " ").capitalize(),
                    description="Time criado na primeira inicialização",
                )
            )
        await ai_svc.seed_engines(session, fake=settings.enable_fake_engine)
        if settings.bootstrap_runner_token:
            await runner_svc.bootstrap_registration_token(session, settings.bootstrap_runner_token)
        await session.commit()


async def build_state(
    settings: Settings,
    *,
    secrets_store: SecretStore | None = None,
    provider_transport: httpx.AsyncBaseTransport | None = None,
) -> AppState:
    store = secrets_store or build_secret_store(settings)
    return AppState(
        settings=settings,
        secrets=store,
        bus=build_event_bus(
            settings.redis_url, settings.log_buffer_lines, settings.log_buffer_ttl_s
        ),
        providers=ProviderFactory(
            store, timeout=settings.provider_timeout_s, transport=provider_transport
        ),
        oidc=(
            OidcVerifier(settings.oidc_authority, settings.effective_oidc_audience)
            if settings.auth_mode == "oidc" and settings.oidc_authority
            else None
        ),
    )


def create_app(settings: Settings | None = None, *, state: AppState | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.check_security()
        if settings.auth_mode == "dev":
            log.warning(
                "MODO DE DESENVOLVIMENTO: qualquer cliente se identifica pelo cabeçalho "
                "X-Sentinela-User, sem senha. Nunca use assim fora da sua máquina."
            )
        init_engine(settings)
        app_state = state or await build_state(settings)
        app.state.sentinela = app_state
        await seed(settings)
        tasks = []
        if settings.reconciler_enabled:
            from sentinela_api.services.reconciler import run_forever

            tasks.append(asyncio.create_task(run_forever(app_state)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            await app_state.bus.close()
            await dispose_engine()

    app = FastAPI(
        title="Sentinela — API",
        version=__version__,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    install_handlers(app)
    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            allow_credentials="*" not in origins,
        )
    for module in (
        public,
        admin,
        ai,
        integrations,
        standards,
        repositories,
        pull_requests,
        dashboard,
        runners,
        runner_api,
        webhooks,
    ):
        app.include_router(module.router)
    return app


def run() -> None:
    import os

    import uvicorn

    logging.basicConfig(
        level=os.environ.get("SENTINELA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        "sentinela_api.main:create_app",
        factory=True,
        host=os.environ.get("SENTINELA_HOST", "0.0.0.0"),
        port=int(os.environ.get("SENTINELA_PORT", "8000")),
        proxy_headers=True,
        log_config=None,
        # Conexões SSE e long-poll dos runners não fecham sozinhas: não segura o deploy.
        timeout_graceful_shutdown=int(os.environ.get("SENTINELA_SHUTDOWN_TIMEOUT_S", "10")),
    )


if __name__ == "__main__":
    run()
