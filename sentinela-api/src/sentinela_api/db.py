from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sentinela_api.settings import Settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("engine não inicializado")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def lock_row[T](session: AsyncSession, model: type[T], ident) -> T | None:
    """SELECT ... FOR UPDATE na linha e relê só as colunas do objeto.

    Não usa populate_existing: com os relacionamentos carregados por join, ele recarregaria
    objetos vizinhos e deixaria relacionamentos já usados pelo chamador por carregar
    (o que, no modo assíncrono, quebra no próximo acesso)."""
    found = await session.scalar(
        select(model.id).where(model.id == ident).with_for_update()  # type: ignore[attr-defined]
    )
    if found is None:
        return None
    obj = await session.get(model, ident)
    if obj is not None:
        columns = [attr.key for attr in sa_inspect(model).column_attrs]
        await session.refresh(obj, attribute_names=columns)
    return obj
