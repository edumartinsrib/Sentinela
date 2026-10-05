"""Server-Sent Events sobre o barramento (Redis ou memória)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

from sentinela_api.services.events import EventBus

PING_INTERVAL_S = 15


def format_event(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def sse_response(
    bus: EventBus, channels: list[str], initial: list[tuple[str, Any]] | None = None
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=1000)

        async def pump() -> None:
            async for item in bus.subscribe(*channels):
                if queue.full():
                    continue
                queue.put_nowait(item)

        task = asyncio.create_task(pump())
        try:
            yield ": conectado\n\n"
            for event, data in initial or []:
                yield format_event(event, json.dumps(data, default=str))
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), PING_INTERVAL_S)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield format_event(event, data)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
