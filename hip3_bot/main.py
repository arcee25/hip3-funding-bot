"""Process entry point."""
from __future__ import annotations

import asyncio
import logging
import signal

from .bot import Bot
from .config import Config


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run() -> None:
    cfg = Config.from_env()
    _setup_logging(cfg.log_level)
    bot = Bot(cfg)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        stop.set()
        bot.feed.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: SIGTERM not supported via add_signal_handler.

    run_task = asyncio.create_task(bot.run())
    stop_task = asyncio.create_task(stop.wait())
    _, pending = await asyncio.wait(
        {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()


def cli() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    cli()
