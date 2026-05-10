"""Process entry point with --confirm-live safeguard."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .bot import Bot
from .config import Config


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def require_confirm_live(mode: str, confirm: bool) -> None:
    """Refuse to start `live` mode without explicit operator confirmation.

    Spec § Risk Matrix: 'Operator launches with wrong mode flag' — loud
    startup banner + explicit `--confirm-live` CLI flag.
    """
    if mode == "live" and not confirm:
        sys.stderr.write(
            "ERROR: mode=live requires --confirm-live to start. "
            "Aborting to prevent accidental capital deployment.\n"
        )
        raise SystemExit(2)


def _print_banner(cfg: Config) -> None:
    bar = "=" * 60
    print(bar, flush=True)
    print(f"  hip3-funding-bot  mode = {cfg.mode.upper()}", flush=True)
    print(
        f"  HL testnet={cfg.hl_use_testnet}  "
        f"Ostium testnet={cfg.ostium_use_testnet}",
        flush=True,
    )
    print(
        f"  fee_drag={cfg.round_trip_fee_bps:.0f} bps  "
        f"min net APR={cfg.min_entry_apr_pct:.0f}%",
        flush=True,
    )
    print(bar, flush=True)


async def _run(confirm_live: bool) -> None:
    cfg = Config.from_env()
    require_confirm_live(cfg.mode, confirm_live)
    _setup_logging(cfg.log_level)
    _print_banner(cfg)

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
            pass

    run_task = asyncio.create_task(bot.run())
    stop_task = asyncio.create_task(stop.wait())
    _, pending = await asyncio.wait(
        {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()


def cli() -> None:
    parser = argparse.ArgumentParser(prog="hip3-bot")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required when MODE=live. Acknowledges live capital deployment.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.confirm_live))


if __name__ == "__main__":
    cli()
