"""Validação do JWT de um provedor OIDC (Entra ID, Keycloak, Okta…) pelas chaves públicas."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx
import jwt
from jwt import PyJWKClient


@dataclass
class OidcIdentity:
    subject: str
    username: str
    display_name: str | None
    email: str | None = None
    groups: list[str] = field(default_factory=list)


class OidcVerifier:
    def __init__(self, authority: str, audience: str | None):
        self._authority = authority.rstrip("/")
        self._audience = audience
        self._jwks: PyJWKClient | None = None
        self._issuer: str | None = None
        self._lock = asyncio.Lock()

    async def _discover(self) -> None:
        async with self._lock:
            if self._jwks is not None:
                return
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.get(f"{self._authority}/.well-known/openid-configuration")
                resp.raise_for_status()
                meta = resp.json()
            self._issuer = meta.get("issuer")
            self._jwks = PyJWKClient(meta["jwks_uri"], cache_keys=True, lifespan=3600)

    async def verify(self, token: str) -> OidcIdentity:
        await self._discover()
        assert self._jwks is not None
        key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"verify_aud": True, "require": ["exp", "iat"]},
        )
        username = (
            claims.get("preferred_username")
            or claims.get("upn")
            or claims.get("email")
            or claims["sub"]
        )
        return OidcIdentity(
            subject=claims.get("oid") or claims["sub"],
            username=username.lower(),
            display_name=claims.get("name"),
            email=claims.get("email"),
            groups=list(claims.get("groups") or []),
        )
