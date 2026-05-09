"""Layer 1 — Hyperliquid funding/mark/OI feed (REST poll, WebSocket-ready)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable

from .config import Config
from .models import FundingSnapshot, Market

logger = logging.getLogger(__name__)

# Heuristic until the meta endpoint exposes a deployer flag.
HIP3_COIN_HINTS: set[str] = {
    "WTI",
    "BRENT",
    "NATGAS",
    "GAS",
    "SILVER",
    "GOLD",
    "COPPER",
    "PLATINUM",
    "PALLADIUM",
}

SnapshotHandler = Callable[[FundingSnapshot], Awaitable[None]]


def is_hip3_market(name: str, meta_universe_entry: dict | None = None) -> bool:
    if meta_universe_entry and meta_universe_entry.get("isHip3"):
        return True
    base = name.upper().split("-")[0]
    return base in HIP3_COIN_HINTS


class HLDataFeed:
    """Polls funding / mark / OI from Hyperliquid REST every scan interval.

    For each HIP-3 coin that crosses the entry APR threshold, fetches an L2
    book snapshot to validate top-of-book depth. WebSocket subscription for
    sub-second updates is left to a follow-up — REST polling at 30s satisfies
    Phase 1 of the spec.
    """

    def __init__(self, cfg: Config, info=None):
        self.cfg = cfg
        self._info = info if info is not None else self._build_info()
        self._running = False

    def _build_info(self):
        from hyperliquid.info import Info

        url = (
            "https://api.hyperliquid-testnet.xyz"
            if self.cfg.hl_use_testnet
            else self.cfg.hl_api_url
        )
        return Info(url, skip_ws=True)

    async def list_markets(self) -> list[Market]:
        meta = await asyncio.to_thread(self._info.meta)
        out: list[Market] = []
        for u in meta.get("universe", []):
            name = u.get("name", "")
            out.append(
                Market(
                    coin=name,
                    is_hip3=is_hip3_market(name, u),
                    deployer_address=u.get("deployer"),
                )
            )
        return out

    async def snapshot_all(self) -> list[FundingSnapshot]:
        meta_ctx = await asyncio.to_thread(self._info.meta_and_asset_ctxs)
        if not meta_ctx or len(meta_ctx) < 2:
            return []
        universe = meta_ctx[0].get("universe", [])
        ctxs = meta_ctx[1]
        now = datetime.utcnow()

        snaps: list[FundingSnapshot] = []
        for u, ctx in zip(universe, ctxs):
            coin = u.get("name")
            if not coin or not is_hip3_market(coin, u):
                continue
            try:
                snaps.append(self._build_snapshot(coin, ctx, now))
            except (TypeError, ValueError) as e:
                logger.warning("bad ctx for %s: %s", coin, e)

        await self._enrich_with_book_depth(snaps)
        return snaps

    def _build_snapshot(
        self, coin: str, ctx: dict, now: datetime
    ) -> FundingSnapshot:
        funding_8h = float(ctx.get("funding", 0.0))
        mark = float(ctx.get("markPx", 0.0))
        oi = float(ctx.get("openInterest", 0.0))
        # HL ctx doesn't directly expose long/short ratio. Use signed
        # premium as a proxy: persistent positive premium implies the
        # crowd is paying up for longs. Clip to [0,1].
        try:
            premium = float(ctx.get("premium", 0.0))
        except (TypeError, ValueError):
            premium = 0.0
        long_skew = max(0.0, min(1.0, 0.5 + premium * 5))
        return FundingSnapshot(
            coin=coin,
            funding_8h=funding_8h,
            annualized_apr_pct=funding_8h * 3 * 365 * 100,
            mark_price=mark,
            open_interest=oi,
            long_skew=long_skew,
            book_depth_usd=0.0,
            timestamp=now,
        )

    async def _enrich_with_book_depth(
        self, snaps: list[FundingSnapshot]
    ) -> None:
        # Only fetch L2 for snapshots where APR is high enough to matter.
        candidates = [
            s
            for s in snaps
            if s.annualized_apr_pct >= self.cfg.min_entry_apr_pct
        ]
        if not candidates:
            return
        results = await asyncio.gather(
            *(self._book_depth_usd(s.coin) for s in candidates),
            return_exceptions=True,
        )
        for s, depth in zip(candidates, results):
            s.book_depth_usd = depth if isinstance(depth, float) else 0.0

    async def _book_depth_usd(self, coin: str) -> float:
        try:
            book = await asyncio.to_thread(self._info.l2_snapshot, coin)
        except Exception:
            logger.exception("l2_snapshot failed for %s", coin)
            return 0.0
        levels = book.get("levels") if book else None
        if not levels or len(levels) < 2:
            return 0.0
        bids, asks = levels[0][:5], levels[1][:5]
        bid_depth = sum(float(l["sz"]) * float(l["px"]) for l in bids)
        ask_depth = sum(float(l["sz"]) * float(l["px"]) for l in asks)
        return min(bid_depth, ask_depth)

    async def run(self, handler: SnapshotHandler) -> None:
        self._running = True
        while self._running:
            try:
                snaps = await self.snapshot_all()
                for s in snaps:
                    await handler(s)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("snapshot loop error")
            await asyncio.sleep(self.cfg.scan_interval_sec)

    def stop(self) -> None:
        self._running = False
