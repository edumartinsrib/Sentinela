"""Execução de subprocessos com timeout, cancelamento (grupo de processos) e stderr no log."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass


class Canceled(Exception):
    pass


class ProcessTimeout(Exception):
    pass


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def _kill(proc: asyncio.subprocess.Process, grace: float) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        await proc.wait()


async def run(
    argv: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: float | None = None,  # noqa: ASYNC109 - também mata o grupo de processos
    cancel: asyncio.Event | None = None,
    on_stderr: Callable[[str], None] | None = None,
    on_stdout: Callable[[str], None] | None = None,
    grace: float = 10.0,
) -> ProcessResult:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    out_chunks: list[str] = []
    err_chunks: list[str] = []

    async def pump(stream: asyncio.StreamReader, sink: list[str], cb) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            sink.append(text)
            if cb:
                cb(text.rstrip("\n"))

    async def feed() -> None:
        if stdin is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with contextlib.suppress(Exception):
                proc.stdin.close()

    assert proc.stdout and proc.stderr
    work = asyncio.gather(
        feed(),
        pump(proc.stdout, out_chunks, on_stdout),
        pump(proc.stderr, err_chunks, on_stderr),
        proc.wait(),
    )
    waiters = [asyncio.ensure_future(work)]
    cancel_task = asyncio.ensure_future(cancel.wait()) if cancel else None
    if cancel_task:
        waiters.append(cancel_task)
    try:
        done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if waiters[0] not in done:
            await _kill(proc, grace)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(waiters[0], 5)
            if cancel_task and cancel_task in done:
                raise Canceled()
            raise ProcessTimeout(f"tempo limite de {timeout:.0f}s excedido")
    finally:
        if cancel_task and not cancel_task.done():
            cancel_task.cancel()
    return ProcessResult(proc.returncode or 0, "".join(out_chunks), "".join(err_chunks))
