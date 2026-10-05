"""Dependências de longa duração da aplicação, montadas no lifespan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from sentinela_api.providers.base import ProviderFactory
    from sentinela_api.security.oidc import OidcVerifier
    from sentinela_api.services.events import EventBus
    from sentinela_api.services.secrets import SecretStore
    from sentinela_api.settings import Settings


@dataclass
class AppState:
    settings: Settings
    secrets: SecretStore
    bus: EventBus
    providers: ProviderFactory
    oidc: OidcVerifier | None
    extra: dict[str, Any] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    return request.app.state.sentinela
