"""GitHub Copilot CLI em modo programático (`copilot -p`), só leitura.

O prompt completo vai num arquivo fora do checkout (`--add-dir`), porque a linha de comando
tem limite de tamanho; leitura liberada, shell e escrita negadas, sem instruções
personalizadas do repositório e sem servidores MCP embutidos.
"""

from __future__ import annotations

from sentinela_core.findings import parse_ai_output
from sentinela_runner import process
from sentinela_runner.engines.base import (
    Engine,
    EngineError,
    EngineRequest,
    EngineResponse,
    cli_version,
    engine_env,
)


class CopilotCliEngine(Engine):
    kind = "copilot_cli"

    def __init__(self, path: str = "copilot"):
        self.path = path

    async def detect(self) -> str | None:
        return await cli_version(self.path)

    def argv(self, req: EngineRequest, prompt_file: str) -> list[str]:
        instruction = (
            f"Leia o arquivo {prompt_file} e siga exatamente as instruções dele. "
            "Responda somente com o objeto JSON pedido no final do arquivo."
        )
        argv = [
            self.path,
            "-p",
            instruction,
            "-s",
            "--no-ask-user",
            "--no-custom-instructions",
            "--disable-builtin-mcps",
            "--allow-tool",
            "read",
            "--deny-tool",
            "shell",
            "--deny-tool",
            "write",
            "--add-dir",
            str(req.scratch),
        ]
        if req.model:
            argv += ["--model", req.model]
        if req.env:
            argv += ["--secret-env-vars", ",".join(sorted(req.env))]
        return argv + list(req.extra_args)

    async def review(self, req: EngineRequest) -> EngineResponse:
        prompt_file = req.scratch / "revisao.md"
        prompt_file.write_text(req.system_prompt + "\n\n" + req.user_prompt, encoding="utf-8")
        argv = self.argv(req, str(prompt_file))
        req.log.info(f"executando Copilot CLI (modelo {req.model or 'padrão'}, {req.timeout_s}s)")
        try:
            result = await process.run(
                argv,
                cwd=str(req.workdir),
                env=engine_env(req.env),
                timeout=req.timeout_s,
                cancel=req.cancel,
                on_stderr=lambda line: req.log.write(line, "stderr"),
            )
        except FileNotFoundError as exc:
            raise EngineError(f"Copilot CLI não encontrada em {self.path}", False) from exc
        except process.ProcessTimeout as exc:
            raise EngineError(f"Copilot CLI excedeu o tempo: {exc}") from exc
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip()[-1500:]
            raise EngineError(f"Copilot CLI terminou com código {result.returncode}: {tail}")
        try:
            output = parse_ai_output(result.stdout)
        except ValueError as exc:
            raise EngineError(f"resposta da Copilot CLI fora do formato: {exc}") from exc
        req.log.info(f"Copilot CLI concluiu: {len(output.findings)} apontamento(s)")
        return EngineResponse(output, {"engine": self.kind})
