from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinela_core.diff import DiffFile
from sentinela_core.findings import AiOutput
from sentinela_core.rules import ProfileSpec
from sentinela_runner import process
from sentinela_runner.logs import LogShipper

# Variáveis do host repassadas às CLIs de IA (credenciais de nuvem, proxy, certificados).
ENV_PREFIXES = (
    "ANTHROPIC_",
    "CLAUDE_CODE_",
    "CLAUDE_CONFIG_DIR",
    "AWS_",
    "GOOGLE_",
    "CLOUD_ML_",
    "VERTEX_",
    "AZURE_",
    "COPILOT_",
    "GH_",
    "GITHUB_TOKEN",
    "XDG_",
)
ENV_EXACT = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
    "REQUESTS_CA_BUNDLE",
    "DISABLE_AUTOUPDATER",
    "DISABLE_TELEMETRY",
    "DISABLE_ERROR_REPORTING",
)


class EngineError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class EngineRequest:
    workdir: Path
    scratch: Path
    system_prompt: str
    user_prompt: str
    model: str
    max_turns: int
    timeout_s: int
    max_budget_usd: float | None
    extra_args: list[str]
    env: dict[str, str]
    log: LogShipper
    cancel: asyncio.Event
    files: list[DiffFile] = field(default_factory=list)
    profiles: list[ProfileSpec] = field(default_factory=list)
    reviewed_files: list[str] = field(default_factory=list)


@dataclass
class EngineResponse:
    output: AiOutput
    stats: dict[str, Any] = field(default_factory=dict)


def engine_env(extra: dict[str, str]) -> dict[str, str]:
    # Variáveis vazias ficam de fora: ANTHROPIC_API_KEY="" atrapalha o login por outro meio.
    env = {
        k: v
        for k, v in os.environ.items()
        if v and (k in ENV_EXACT or any(k.startswith(p) for p in ENV_PREFIXES))
    }
    env.update(extra)
    return env


async def cli_version(path: str) -> str | None:
    exe = shutil.which(path)
    if exe is None:
        return None
    try:
        result = await process.run([exe, "--version"], timeout=30)
    except (process.ProcessTimeout, OSError):
        return None
    if result.returncode != 0:
        return None
    first = (result.stdout or result.stderr).strip().splitlines()
    return first[0][:80] if first else "?"


class Engine:
    kind: str = ""

    async def detect(self) -> str | None:
        raise NotImplementedError

    async def review(self, req: EngineRequest) -> EngineResponse:
        raise NotImplementedError
