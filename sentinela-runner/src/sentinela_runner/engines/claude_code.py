"""Claude Code em modo não interativo (`claude -p`), só leitura e com saída estruturada.

Endurecimento padrão (`SENTINELA_CLAUDE_HARDENING=restricted`): `--restricted` remove as
ferramentas que executam código e ignora os arquivos de configuração do repositório (hooks,
permissões e MCP vindos do PR não são carregados); `--tools Read,Grep,Glob` e
`--permission-mode dontAsk` garantem que nada além de leitura roda. Quando a versão instalada
tem `--safe-mode`, ele também entra: desliga CLAUDE.md, skills, plugins, hooks e comandos
personalizados (o executor já remove os arquivos de instrução do checkout; isto cobre os do
usuário do runner).
"""

from __future__ import annotations

import json

from sentinela_core.findings import AI_OUTPUT_SCHEMA, AiOutput, parse_ai_output
from sentinela_runner import process
from sentinela_runner.engines.base import (
    Engine,
    EngineError,
    EngineRequest,
    EngineResponse,
    cli_version,
    engine_env,
)

READ_TOOLS = "Read,Grep,Glob"


def _load_result(stdout: str) -> dict:
    """Objeto final de `--output-format json` (pode vir sozinho ou depois de outras linhas)."""
    text = stdout.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    return {}


class ClaudeCodeEngine(Engine):
    kind = "claude_code"

    def __init__(self, path: str = "claude", hardening: str = "restricted"):
        self.path = path
        self.hardening = hardening
        self.safe_mode = False

    async def detect(self) -> str | None:
        version = await cli_version(self.path)
        if version is not None:
            self.safe_mode = await self._supports("--safe-mode")
        return version

    async def _supports(self, flag: str) -> bool:
        try:
            result = await process.run([self.path, "--help"], timeout=30)
        except (process.ProcessTimeout, OSError):
            return False
        return flag in (result.stdout or "")

    def argv(self, req: EngineRequest) -> list[str]:
        argv = [
            self.path,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(AI_OUTPUT_SCHEMA, separators=(",", ":")),
            "--tools",
            READ_TOOLS,
            "--allowedTools",
            READ_TOOLS,
            "--permission-mode",
            "dontAsk",
            "--max-turns",
            str(req.max_turns),
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--append-system-prompt",
            req.system_prompt,
            "--add-dir",
            str(req.scratch),
        ]
        if self.hardening == "restricted":
            argv.append("--restricted")
        elif self.hardening == "bare":
            argv.append("--bare")
        else:
            argv += ["--setting-sources", "user"]
        if self.safe_mode and self.hardening != "bare":
            argv.append("--safe-mode")
        if req.model:
            argv += ["--model", req.model]
        if req.max_budget_usd:
            argv += ["--max-budget-usd", f"{req.max_budget_usd:.2f}"]
        return argv + list(req.extra_args)

    async def review(self, req: EngineRequest) -> EngineResponse:
        env = engine_env(
            {
                "DISABLE_AUTOUPDATER": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                **({"CLAUDE_CODE_SAFE_MODE": "1"} if self.hardening != "bare" else {}),
                **req.env,
            }
        )
        argv = self.argv(req)
        req.log.info(
            f"executando Claude Code (modelo {req.model or 'padrão'}, "
            f"até {req.max_turns} turnos, {req.timeout_s}s)"
        )
        try:
            result = await process.run(
                argv,
                cwd=str(req.workdir),
                env=env,
                stdin=req.user_prompt,
                timeout=req.timeout_s,
                cancel=req.cancel,
                on_stderr=lambda line: req.log.write(line, "stderr"),
            )
        except FileNotFoundError as exc:
            raise EngineError(f"Claude Code não encontrado em {self.path}", False) from exc
        except process.ProcessTimeout as exc:
            raise EngineError(f"Claude Code excedeu o tempo: {exc}") from exc
        return self.parse(result, req)

    def parse(self, result: process.ProcessResult, req: EngineRequest) -> EngineResponse:
        data = _load_result(result.stdout)
        if not data:
            tail = (result.stderr or result.stdout).strip()[-1500:]
            raise EngineError(
                f"Claude Code terminou com código {result.returncode} sem resultado: {tail}"
            )
        stats = {
            "engine": self.kind,
            "cost_usd": data.get("total_cost_usd"),
            "turns": data.get("num_turns"),
            "duration_ms": data.get("duration_ms"),
            "usage": data.get("usage"),
            "terminal_reason": data.get("terminal_reason"),
        }
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            reason = data.get("terminal_reason") or data.get("subtype")
            message = data.get("result") or reason or "erro"
            retryable = reason not in ("max_turns_reached", "budget_exceeded")
            raise EngineError(
                f"Claude Code não concluiu a revisão ({reason}): {message}", retryable
            )
        structured = data.get("structured_output")
        try:
            output: AiOutput = parse_ai_output(
                structured if isinstance(structured, dict) else data.get("result") or ""
            )
        except ValueError as exc:
            raise EngineError(f"resposta do Claude Code fora do formato: {exc}") from exc
        req.log.info(
            f"Claude Code concluiu: {len(output.findings)} apontamento(s), "
            f"{stats['turns']} turno(s), custo estimado US$ {stats['cost_usd'] or 0:.4f}"
        )
        return EngineResponse(output, stats)
