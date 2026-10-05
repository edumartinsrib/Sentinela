"""Motores (Claude Code, Copilot CLI) e modelos de IA: escolha do modelo de cada revisão."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinela_api import models as m
from sentinela_api.services.secrets import SecretStore, engine_path
from sentinela_core.enums import EngineKind

DEFAULT_ENGINES = [
    {
        "kind": EngineKind.CLAUDE_CODE,
        "name": "Claude Code",
        "description": "claude -p em modo somente leitura (Read, Grep, Glob) com saída "
        "estruturada. "
        "Autenticação por ANTHROPIC_API_KEY, Bedrock ou Vertex no runner ou nos segredos do motor.",
        "models": [
            ("sonnet", "Claude Sonnet (versão mais recente)", True),
            ("opus", "Claude Opus (versão mais recente)", False),
            ("haiku", "Claude Haiku (versão mais recente)", False),
        ],
    },
    {
        "kind": EngineKind.COPILOT_CLI,
        "name": "GitHub Copilot CLI",
        "description": "copilot -p com leitura liberada e escrita/shell negadas. Autenticação por "
        "COPILOT_GITHUB_TOKEN (token com permissão Copilot Requests).",
        "models": [("", "Padrão da Copilot CLI", False)],
    },
]

FAKE_ENGINE = {
    "kind": EngineKind.FAKE,
    "name": "Simulador local",
    "description": "Heurísticas locais, sem IA. Só para desenvolvimento, demonstração e testes.",
    "models": [("simulador", "Simulador (sem IA)", False)],
}


async def ensure_engine(session: AsyncSession, spec: dict, *, make_default: bool) -> None:
    engine = await session.scalar(select(m.AiEngine).where(m.AiEngine.kind == spec["kind"]))
    if engine is not None:
        return
    engine = m.AiEngine(
        kind=spec["kind"].value,
        name=spec["name"],
        description=spec["description"],
        enabled=True,
    )
    session.add(engine)
    await session.flush()
    for model, label, default in spec["models"]:
        session.add(
            m.AiModel(
                engine_id=engine.id,
                model=model,
                label=label,
                enabled=True,
                is_default=default and make_default,
            )
        )
    await session.flush()


async def seed_engines(session: AsyncSession, *, fake: bool) -> None:
    has_default = await session.scalar(select(m.AiModel.id).where(m.AiModel.is_default).limit(1))
    for spec in DEFAULT_ENGINES:
        await ensure_engine(session, spec, make_default=not has_default and not fake)
    if fake:
        await ensure_engine(session, FAKE_ENGINE, make_default=False)
        if not has_default:
            # No ambiente de demonstração o simulador vira o padrão.
            await session.execute(update(m.AiModel).values(is_default=False))
            fake_model = await session.scalar(
                select(m.AiModel).join(m.AiEngine).where(m.AiEngine.kind == EngineKind.FAKE)
            )
            if fake_model:
                fake_model.is_default = True


async def set_default_model(session: AsyncSession, model_id: uuid.UUID) -> None:
    await session.execute(
        update(m.AiModel).where(m.AiModel.id != model_id).values(is_default=False)
    )
    await session.execute(update(m.AiModel).where(m.AiModel.id == model_id).values(is_default=True))


def _usable(model: m.AiModel | None) -> bool:
    return bool(model and model.enabled and model.engine.enabled)


async def resolve_model(
    session: AsyncSession,
    repo: m.Repository,
    profiles: list[m.Profile],
    override_id: uuid.UUID | None = None,
) -> m.AiModel | None:
    """Precedência: reexecução escolhida pelo admin > repositório > perfil > padrão global
    > qualquer modelo habilitado."""
    if override_id:
        model = await session.get(m.AiModel, override_id)
        if _usable(model):
            return model
    if _usable(repo.model):
        return repo.model
    for profile in profiles:
        if _usable(profile.model):
            return profile.model
    default = await session.scalar(select(m.AiModel).where(m.AiModel.is_default).limit(1))
    if _usable(default):
        return default
    candidates = await session.scalars(
        select(m.AiModel)
        .join(m.AiEngine)
        .where(m.AiModel.enabled, m.AiEngine.enabled)
        .order_by(m.AiEngine.name, m.AiModel.label)
    )
    return candidates.first()


async def engine_env(secrets: SecretStore, engine: m.AiEngine) -> dict[str, str]:
    data = await secrets.read(engine_path(engine.id)) or {}
    return {k: str(v) for k, v in data.items() if v}
