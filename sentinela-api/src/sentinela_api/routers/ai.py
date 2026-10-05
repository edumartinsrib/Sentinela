"""Motores e modelos de IA. Leitura para todos; alteração só por administradores globais."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from sentinela_api import models as m
from sentinela_api import schemas as s
from sentinela_api.deps import Session, State, SuperAdmin, User
from sentinela_api.errors import conflict, not_found
from sentinela_api.services import ai as ai_svc
from sentinela_api.services import audit
from sentinela_api.services.secrets import engine_path
from sentinela_api.services.serializers import engine_out, model_out
from sentinela_core.enums import RunnerStatus

router = APIRouter(prefix="/api/v1/ai", tags=["ia"])


async def _runners_by_kind(session) -> dict[str, int]:
    rows = (
        await session.scalars(
            select(m.Runner).where(m.Runner.status == RunnerStatus.ONLINE, m.Runner.enabled)
        )
    ).all()
    out: dict[str, int] = {}
    for r in rows:
        for kind in r.engines or {}:
            out[kind] = out.get(kind, 0) + 1
    return out


async def _engine(session, engine_id: uuid.UUID) -> m.AiEngine:
    engine = await session.get(m.AiEngine, engine_id)
    if engine is None:
        raise not_found("motor")
    return engine


async def _model(session, model_id: uuid.UUID) -> m.AiModel:
    model = await session.get(m.AiModel, model_id)
    if model is None:
        raise not_found("modelo")
    return model


@router.get("/engines", response_model=list[s.AiEngineOut])
async def list_engines(session: Session, principal: User) -> list[s.AiEngineOut]:
    engines = (await session.scalars(select(m.AiEngine).order_by(m.AiEngine.name))).all()
    online = await _runners_by_kind(session)
    return [engine_out(e, online.get(e.kind, 0)) for e in engines]


@router.post("/engines", response_model=s.AiEngineOut, status_code=201)
async def create_engine(
    body: s.AiEngineCreate, session: Session, principal: SuperAdmin
) -> s.AiEngineOut:
    if await session.scalar(select(m.AiEngine.id).where(m.AiEngine.name == body.name)):
        raise conflict("já existe um motor com esse nome")
    engine = m.AiEngine(**body.model_dump(mode="json"))
    session.add(engine)
    await session.flush()
    audit.record(
        session,
        actor=principal.username,
        action="ai.engine.create",
        resource_type="ai_engine",
        resource_id=engine.id,
        after=audit.snapshot(engine),
    )
    await session.commit()
    engine = await _engine(session, engine.id)
    await session.refresh(engine, ["models"])
    return engine_out(engine, (await _runners_by_kind(session)).get(engine.kind, 0))


@router.patch("/engines/{engine_id}", response_model=s.AiEngineOut)
async def update_engine(
    engine_id: uuid.UUID, body: s.AiEngineUpdate, session: Session, principal: SuperAdmin
) -> s.AiEngineOut:
    engine = await _engine(session, engine_id)
    before = audit.snapshot(engine)
    data = body.model_dump(exclude_unset=True, mode="json")
    for key, value in data.items():
        if key == "max_budget_usd":
            setattr(engine, key, value or None)
        elif value is not None:
            setattr(engine, key, value)
    audit.record(
        session,
        actor=principal.username,
        action="ai.engine.update",
        resource_type="ai_engine",
        resource_id=engine.id,
        before=before,
        after=audit.snapshot(engine),
    )
    await session.commit()
    return engine_out(engine, (await _runners_by_kind(session)).get(engine.kind, 0))


@router.delete("/engines/{engine_id}", status_code=204)
async def delete_engine(
    engine_id: uuid.UUID, session: Session, state: State, principal: SuperAdmin
) -> Response:
    engine = await _engine(session, engine_id)
    audit.record(
        session,
        actor=principal.username,
        action="ai.engine.delete",
        resource_type="ai_engine",
        resource_id=engine.id,
        before=audit.snapshot(engine),
    )
    await session.delete(engine)
    await session.commit()
    await state.secrets.delete(engine_path(engine_id))
    return Response(status_code=204)


@router.put("/engines/{engine_id}/secrets", response_model=s.AiEngineOut)
async def set_engine_secrets(
    engine_id: uuid.UUID,
    body: s.EngineSecretsIn,
    session: Session,
    state: State,
    principal: SuperAdmin,
) -> s.AiEngineOut:
    """Variáveis secretas entregues ao runner junto com a revisão (ex.: ANTHROPIC_API_KEY,
    COPILOT_GITHUB_TOKEN). Os valores não voltam pela API."""
    engine = await _engine(session, engine_id)
    current = await state.secrets.read(engine_path(engine.id)) or {}
    for name, value in body.values.items():
        if value:
            current[name] = value
        else:
            current.pop(name, None)
    await state.secrets.write(engine_path(engine.id), current)
    engine.secret_env_names = sorted(current)
    audit.record(
        session,
        actor=principal.username,
        action="ai.engine.secrets",
        resource_type="ai_engine",
        resource_id=engine.id,
        detail="variáveis: " + (", ".join(sorted(body.values)) or "-"),
    )
    await session.commit()
    return engine_out(engine, (await _runners_by_kind(session)).get(engine.kind, 0))


@router.get("/models", response_model=list[s.AiModelOut])
async def list_models(session: Session, principal: User) -> list[s.AiModelOut]:
    rows = (
        await session.scalars(
            select(m.AiModel).join(m.AiEngine).order_by(m.AiEngine.name, m.AiModel.label)
        )
    ).all()
    return [model_out(x) for x in rows]


@router.post("/models", response_model=s.AiModelOut, status_code=201)
async def create_model(
    body: s.AiModelCreate, session: Session, principal: SuperAdmin
) -> s.AiModelOut:
    engine = await _engine(session, uuid.UUID(body.engine_id))
    model_name = body.model.strip()
    if await session.scalar(
        select(m.AiModel.id).where(m.AiModel.engine_id == engine.id, m.AiModel.model == model_name)
    ):
        raise conflict("esse modelo já está cadastrado neste motor")
    model = m.AiModel(
        engine=engine,
        model=model_name,
        label=body.label,
        description=body.description,
        enabled=body.enabled,
        is_default=False,
    )
    session.add(model)
    await session.flush()
    if body.is_default:
        await ai_svc.set_default_model(session, model.id)
        model.is_default = True
    audit.record(
        session,
        actor=principal.username,
        action="ai.model.create",
        resource_type="ai_model",
        resource_id=model.id,
        after=audit.snapshot(model),
    )
    await session.commit()
    return model_out(model)


@router.patch("/models/{model_id}", response_model=s.AiModelOut)
async def update_model(
    model_id: uuid.UUID, body: s.AiModelUpdate, session: Session, principal: SuperAdmin
) -> s.AiModelOut:
    model = await _model(session, model_id)
    before = audit.snapshot(model)
    data = body.model_dump(exclude_unset=True)
    for key in ("model", "label", "description", "enabled"):
        if key in data and (data[key] is not None or key == "description"):
            setattr(model, key, data[key].strip() if key == "model" else data[key])
    if data.get("is_default"):
        await ai_svc.set_default_model(session, model.id)
        model.is_default = True
    elif data.get("is_default") is False:
        model.is_default = False
    audit.record(
        session,
        actor=principal.username,
        action="ai.model.update",
        resource_type="ai_model",
        resource_id=model.id,
        before=before,
        after=audit.snapshot(model),
    )
    await session.commit()
    await session.refresh(model)
    return model_out(model)


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: uuid.UUID, session: Session, principal: SuperAdmin) -> Response:
    model = await _model(session, model_id)
    audit.record(
        session,
        actor=principal.username,
        action="ai.model.delete",
        resource_type="ai_model",
        resource_id=model.id,
        before=audit.snapshot(model),
    )
    await session.delete(model)
    await session.commit()
    return Response(status_code=204)


class DefaultModelIn(BaseModel):
    model_id: str


@router.put("/default", response_model=s.AiModelOut)
async def set_default(
    body: DefaultModelIn, session: Session, principal: SuperAdmin
) -> s.AiModelOut:
    model = await _model(session, uuid.UUID(body.model_id))
    if not model.enabled:
        raise conflict("habilite o modelo antes de torná-lo padrão")
    await ai_svc.set_default_model(session, model.id)
    audit.record(
        session,
        actor=principal.username,
        action="ai.model.default",
        resource_type="ai_model",
        resource_id=model.id,
        detail=model.label,
    )
    await session.commit()
    await session.refresh(model)
    return model_out(model)
