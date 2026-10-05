from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from sentinela_runner.agent import Agent
from sentinela_runner.settings import RunnerSettings


async def amain() -> int:
    settings = RunnerSettings()
    agent = Agent(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, agent.stop)
    await agent.run()
    return 0


def run() -> None:
    logging.basicConfig(
        level=os.environ.get("SENTINELA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    code = 0
    with contextlib.suppress(KeyboardInterrupt):
        code = asyncio.run(amain())
    sys.exit(code)


if __name__ == "__main__":
    run()
