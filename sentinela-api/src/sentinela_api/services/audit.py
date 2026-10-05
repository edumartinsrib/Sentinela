"""Registro de auditoria: toda escrita gera uma linha no mesmo commit da alteração."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api.models import AuditLog

# Campos que nunca entram no before/after.
_REDACT = {"secret", "password", "secret_hash", "token_hash", "token", "webhook_secret"}


def snapshot(obj: Any, fields: list[str] | None = None) -> dict[str, Any] | None:
    """Fotografia JSON de um modelo SQLAlchemy (ou dict) para o before/after."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        data = dict(obj)
    else:
        cols = fields or [c.key for c in obj.__table__.columns]
        data = {c: getattr(obj, c) for c in cols}
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in _REDACT:
            continue
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, bytes):
            continue
        out[key] = value
    return out


def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: Any = None,
    team_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    detail: str | None = None,
    actor_type: str = "user",
) -> None:
    session.add(
        AuditLog(
            actor=actor,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            team_id=team_id,
            before=before,
            after=after,
            detail=detail,
        )
    )
