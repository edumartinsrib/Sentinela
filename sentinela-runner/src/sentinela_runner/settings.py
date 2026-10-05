from __future__ import annotations

import os
import platform
import socket
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_home() -> str:
    if os.name == "nt":
        return str(Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "sentinela-runner")
    return str(Path.home() / ".sentinela-runner")


class RunnerSettings(BaseSettings):
    """Configuração local do runner (variáveis de ambiente SENTINELA_*)."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True, env_file=None)

    api_url: str = Field(default="http://localhost:8000", validation_alias="SENTINELA_API_URL")
    registration_token: str | None = Field(
        default=None, validation_alias="SENTINELA_REGISTRATION_TOKEN"
    )
    name: str = Field(
        default_factory=lambda: socket.gethostname().upper(),
        validation_alias="SENTINELA_RUNNER_NAME",
    )
    home: Path = Field(
        default_factory=lambda: Path(_default_home()), validation_alias="SENTINELA_RUNNER_HOME"
    )
    labels: str = Field(default="", validation_alias="SENTINELA_LABELS")
    slots: int = Field(default=2, ge=1, le=64, validation_alias="SENTINELA_SLOTS")
    # Motores oferecidos: lista separada por vírgula ou "auto" (detecta claude e copilot no PATH).
    engines: str = Field(default="auto", validation_alias="SENTINELA_ENGINES")
    enable_fake_engine: bool = Field(default=False, validation_alias="SENTINELA_ENABLE_FAKE_ENGINE")
    git_path: str = Field(default="git", validation_alias="SENTINELA_GIT_PATH")
    claude_path: str = Field(default="claude", validation_alias="SENTINELA_CLAUDE_PATH")
    copilot_path: str = Field(default="copilot", validation_alias="SENTINELA_COPILOT_PATH")
    # restricted: --restricted (sem ferramentas de execução, ignora settings do repositório)
    # bare: --bare (exige ANTHROPIC_API_KEY ou Bedrock/Vertex)
    # settings: --setting-sources user (para versões sem --restricted)
    claude_hardening: Literal["restricted", "bare", "settings"] = Field(
        default="restricted", validation_alias="SENTINELA_CLAUDE_HARDENING"
    )
    fetch_depth: int = Field(default=200, ge=1, validation_alias="SENTINELA_FETCH_DEPTH")
    keep_workspaces: bool = Field(default=False, validation_alias="SENTINELA_KEEP_WORKSPACES")
    kill_grace_s: int = Field(default=10, validation_alias="SENTINELA_KILL_GRACE_S")
    log_push_interval_s: float = Field(
        default=1.0, validation_alias="SENTINELA_LOG_PUSH_INTERVAL_S"
    )
    git_timeout_s: int = Field(default=600, validation_alias="SENTINELA_GIT_TIMEOUT_S")

    @property
    def label_list(self) -> list[str]:
        labels = [x.strip() for x in self.labels.split(",") if x.strip()]
        return labels or [platform.system().lower()]

    @property
    def os_name(self) -> str:
        return platform.system().lower()

    @property
    def engine_list(self) -> list[str] | None:
        if self.engines.strip().lower() == "auto":
            return None
        return [x.strip() for x in self.engines.split(",") if x.strip()]
