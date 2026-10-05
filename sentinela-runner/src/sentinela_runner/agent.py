"""Ciclo de vida do runner: registro, slots que pegam revisões, heartbeat e cancelamento."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket

import httpx

from sentinela_runner import __version__, identity
from sentinela_runner.api import ApiError, SentinelaApi
from sentinela_runner.engines import Engine, available_engines
from sentinela_runner.executor import ReviewExecutor
from sentinela_runner.settings import RunnerSettings

log = logging.getLogger("sentinela.runner")


class Agent:
    def __init__(self, settings: RunnerSettings, api: SentinelaApi | None = None):
        self.settings = settings
        self.api = api or SentinelaApi(settings.api_url)
        self.engines: dict[str, tuple[Engine, str]] = {}
        self.config: dict = {}
        self.running: dict[str, asyncio.Event] = {}
        self._stop = asyncio.Event()

    @property
    def engine_versions(self) -> dict[str, str]:
        return {kind: version for kind, (_, version) in self.engines.items()}

    # ------------------------------------------------------------------ registro
    async def register(self) -> None:
        delay = 2.0
        while not self._stop.is_set():
            try:
                await self._register_once()
                return
            except (httpx.TransportError, ApiError) as exc:
                # 409: o runner antigo com este nome ainda consta como ativo; espera ele
                # sair do ar em vez de desistir (comum ao recriar o container sem o volume).
                if isinstance(exc, ApiError) and exc.status < 500 and exc.status != 409:
                    raise
                log.warning("registro adiado (%s); nova tentativa em %.0fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _register_once(self) -> None:
        home = self.settings.home
        ident = identity.load(home)
        if ident and ident.api_url == self.settings.api_url:
            self.api.token = ident.runner_token
            try:
                self.config = await self.api.config()
                log.info("runner %s autenticado", self.config["runner_name"])
                return
            except ApiError as exc:
                if exc.status != 401:
                    raise
                log.warning("token do runner recusado; registrando de novo")
        if not self.settings.registration_token:
            raise SystemExit("SENTINELA_REGISTRATION_TOKEN é obrigatório no primeiro registro")
        self.api.token = None
        resp = await self.api.register(
            {
                "registration_token": self.settings.registration_token,
                "name": self.settings.name,
                "hostname": socket.gethostname(),
                "os": self.settings.os_name,
                "labels": self.settings.label_list,
                "engines": self.engine_versions,
                "slots": self.settings.slots,
                "agent_version": __version__,
            }
        )
        self.api.token = resp["runner_token"]
        self.config = resp["config"]
        identity.save(
            home, identity.Identity(resp["runner_id"], resp["runner_token"], self.settings.api_url)
        )
        log.info("runner %s registrado", self.config["runner_name"])

    # ------------------------------------------------------------------ laços
    async def heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                resp = await self.api.heartbeat(
                    list(self.running), self.engine_versions, self.settings.slots
                )
                self.config = resp["config"]
                for rid in resp.get("cancel", []):
                    event = self.running.get(rid)
                    if event and not event.is_set():
                        log.info("cancelando a revisão %s a pedido da API", rid)
                        event.set()
            except (httpx.HTTPError, ApiError) as exc:
                log.warning("heartbeat falhou: %s", exc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), self.config.get("heartbeat_interval_s", 10)
                )

    async def slot_loop(self, slot: int, executor: ReviewExecutor) -> None:
        kinds = list(self.engines)
        while not self._stop.is_set():
            if not self.config.get("enabled", True) or self.config.get("draining"):
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), 5)
                continue
            try:
                review = await self.api.claim(kinds, float(self.config.get("claim_wait_s", 20)))
            except (httpx.HTTPError, ApiError) as exc:
                log.warning("slot %d: falha ao pedir revisão: %s", slot, exc)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), 5)
                continue
            if review is None:
                continue
            cancel = asyncio.Event()
            self.running[review["id"]] = cancel
            try:
                await executor.run(review, cancel)
            finally:
                self.running.pop(review["id"], None)

    async def run(self) -> None:
        self.engines = await available_engines(self.settings)
        if not self.engines:
            raise SystemExit(
                "Nenhum motor de IA encontrado: instale o Claude Code (claude) ou a Copilot CLI "
                "(copilot), ou ajuste SENTINELA_CLAUDE_PATH/SENTINELA_COPILOT_PATH."
            )
        log.info(
            "motores disponíveis: %s",
            ", ".join(f"{k} ({v})" for k, v in self.engine_versions.items()),
        )
        await self.register()
        executor = ReviewExecutor(self.settings, self.api, self.engines)
        tasks = [asyncio.create_task(self.heartbeat_loop())]
        tasks += [
            asyncio.create_task(self.slot_loop(i, executor)) for i in range(self.settings.slots)
        ]
        await self._stop.wait()
        log.info("parando: aguardando %d revisão(ões) em andamento", len(self.running))
        for event in self.running.values():
            event.set()
        await asyncio.wait(tasks, timeout=self.settings.kill_grace_s + 15)
        for task in tasks:
            task.cancel()
        await self.api.close()

    def stop(self) -> None:
        self._stop.set()
