"""Motores de revisão disponíveis no runner."""

from __future__ import annotations

from sentinela_runner.engines.base import Engine, EngineError, EngineRequest, EngineResponse
from sentinela_runner.engines.claude_code import ClaudeCodeEngine
from sentinela_runner.engines.copilot_cli import CopilotCliEngine
from sentinela_runner.engines.fake import FakeEngine
from sentinela_runner.settings import RunnerSettings

__all__ = ["Engine", "EngineError", "EngineRequest", "EngineResponse", "available_engines"]


async def available_engines(settings: RunnerSettings) -> dict[str, tuple[Engine, str]]:
    """Motores instalados (tipo → (motor, versão)). Respeita SENTINELA_ENGINES."""
    candidates: list[Engine] = [
        ClaudeCodeEngine(settings.claude_path, settings.claude_hardening),
        CopilotCliEngine(settings.copilot_path),
    ]
    if settings.enable_fake_engine:
        candidates.append(FakeEngine())
    wanted = settings.engine_list
    out: dict[str, tuple[Engine, str]] = {}
    for engine in candidates:
        if wanted is not None and engine.kind not in wanted:
            continue
        version = await engine.detect()
        if version:
            out[engine.kind] = (engine, version)
    return out
