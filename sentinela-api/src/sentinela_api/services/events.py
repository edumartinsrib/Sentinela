"""Barramento de eventos SSE e buffer das linhas de log de cada revisão.

Com Redis, os eventos chegam a todas as réplicas da API (pub/sub) e o buffer de log é
uma lista limitada por revisão. Sem Redis, tudo fica na memória do processo —
suficiente para uma réplica, desenvolvimento e testes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

log = logging.getLogger(__name__)

QUEUE_CHANNEL = "sentinela:queue"


def team_channel(team: str) -> str:
    return f"sentinela:team:{team}"


def review_channel(review_id: str) -> str:
    return f"sentinela:review:{review_id}"


def _log_key(review_id: str) -> str:
    return f"sentinela:reviewlog:{review_id}"


class EventBus:
    async def publish(self, channel: str, event: str, data: Any) -> None:
        raise NotImplementedError

    def subscribe(self, *channels: str) -> AsyncIterator[tuple[str, str]]:
        raise NotImplementedError

    async def append_logs(self, review_id: str, lines: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    async def get_logs(self, review_id: str, tail: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class MemoryEventBus(EventBus):
    def __init__(self, max_lines: int = 3000):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._logs: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_lines))

    async def publish(self, channel: str, event: str, data: Any) -> None:
        payload = json.dumps(data, default=str)
        for queue in list(self._subscribers.get(channel, ())):
            if queue.qsize() < 1000:
                queue.put_nowait((event, payload))

    async def subscribe(self, *channels: str) -> AsyncIterator[tuple[str, str]]:
        queue: asyncio.Queue = asyncio.Queue()
        for ch in channels:
            self._subscribers[ch].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            for ch in channels:
                self._subscribers[ch].discard(queue)

    async def append_logs(self, review_id: str, lines: list[dict[str, Any]]) -> None:
        self._logs[review_id].extend(lines)

    async def get_logs(self, review_id: str, tail: int) -> list[dict[str, Any]]:
        lines = list(self._logs.get(review_id, ()))
        return lines[-tail:] if tail else lines


class RedisEventBus(EventBus):
    def __init__(self, url: str, max_lines: int = 3000, ttl_s: int = 14 * 86400):
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)
        self._max_lines = max_lines
        self._ttl = ttl_s

    async def publish(self, channel: str, event: str, data: Any) -> None:
        message = json.dumps({"event": event, "data": data}, default=str)
        await self._redis.publish(channel, message)

    async def subscribe(self, *channels: str) -> AsyncIterator[tuple[str, str]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*channels)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    body = json.loads(message["data"])
                except (TypeError, json.JSONDecodeError):
                    continue
                yield body["event"], json.dumps(body["data"], default=str)
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose()

    async def append_logs(self, review_id: str, lines: list[dict[str, Any]]) -> None:
        if not lines:
            return
        key = _log_key(review_id)
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.rpush(key, *[json.dumps(line, default=str) for line in lines])
            pipe.ltrim(key, -self._max_lines, -1)
            pipe.expire(key, self._ttl)
            await pipe.execute()

    async def get_logs(self, review_id: str, tail: int) -> list[dict[str, Any]]:
        start = -tail if tail else 0
        raw = await self._redis.lrange(_log_key(review_id), start, -1)
        return [json.loads(r) for r in raw]

    async def close(self) -> None:
        await self._redis.aclose()


def build_event_bus(redis_url: str | None, max_lines: int, ttl_s: int) -> EventBus:
    if redis_url:
        return RedisEventBus(redis_url, max_lines, ttl_s)
    log.warning("Redis não configurado: eventos SSE e logs ao vivo só nesta réplica")
    return MemoryEventBus(max_lines)
