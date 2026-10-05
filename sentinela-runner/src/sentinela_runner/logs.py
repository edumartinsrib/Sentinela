"""Linhas de log da revisão: mascaramento de segredos e envio em lote para a API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from sentinela_runner.api import SentinelaApi

log = logging.getLogger("sentinela.runner")
MAX_LINE = 4000


class Masker:
    def __init__(self, values: list[str]):
        # mais longos primeiro (um segredo pode conter outro)
        self.values = sorted({v for v in values if v and len(v) >= 4}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self.values:
            if value in text:
                text = text.replace(value, "***")
        return text


class LogShipper:
    def __init__(self, api: SentinelaApi, review_id: str, masker: Masker, interval: float = 1.0):
        self.api = api
        self.review_id = review_id
        self.mask = masker
        self.interval = interval
        self._buffer: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def write(self, text: str, stream: str = "system") -> None:
        for line in text.splitlines() or [""]:
            line = self.mask(line)
            if len(line) > MAX_LINE:
                line = line[:MAX_LINE] + "…"
            self._buffer.append(
                {"ts": datetime.now(UTC).isoformat(), "stream": stream, "text": line}
            )
        log.debug("[%s] %s", self.review_id[:8], text[:200])

    def info(self, text: str) -> None:
        self.write(text, "system")

    async def flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch, self._buffer = self._buffer[:2000], self._buffer[2000:]
            try:
                await self.api.logs(self.review_id, batch)
            except Exception as exc:  # noqa: BLE001 - log é melhor esforço
                log.warning("falha ao enviar logs da revisão %s: %s", self.review_id, exc)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            await self.flush()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush()
