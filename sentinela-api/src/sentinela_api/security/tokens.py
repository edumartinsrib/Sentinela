"""Tokens opacos dos runners e de registro: `<prefixo><uuid>.<segredo>`; só o hash fica no banco."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

REGISTRATION_PREFIX = "snt_reg_"
RUNNER_PREFIX = "snt_rn_"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_secret(secret: str, digest: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), digest)


def make_token(prefix: str, ident: uuid.UUID) -> tuple[str, str]:
    """Devolve (token, hash do segredo)."""
    secret = secrets.token_urlsafe(32)
    return f"{prefix}{ident}.{secret}", hash_secret(secret)


def parse_token(token: str, prefix: str) -> tuple[uuid.UUID, str] | None:
    if not token.startswith(prefix):
        return None
    ident, _, secret = token[len(prefix) :].partition(".")
    if not secret:
        return None
    try:
        return uuid.UUID(ident), secret
    except ValueError:
        return None
