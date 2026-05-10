"""Layer 3 — Ostium long-leg hedge adapter."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class OstiumHedgeAdapter:
    """Long-only hedge against Ostium LP, backed by an async OstiumClient.

    Returned ``Fill`` carries an extra ``trade_index`` (set on buy, used
    on close). The bot persists it on Position.ostium_trade_index so a
    later close can find the right open trade via the SDK.
    """

    def __init__(self, client, max_slippage_bps: float):
        self._client = client
        self._max_slippage_bps = max_slippage_bps

    async def buy(self, coin: str, notional_usd: float):
        from .execution import Fill

        try:
            res = await self._client.open_long(
                coin, notional_usd, self._max_slippage_bps
            )
        except Exception as e:
            logger.exception("Ostium open_long failed")
            if "oracle" in str(e).lower():
                await asyncio.sleep(2.0)
                res = await self._client.open_long(
                    coin, notional_usd, self._max_slippage_bps
                )
            else:
                raise
        return Fill(
            price=float(res["fill_price"]),
            size=float(res["size"]),
            fees_paid_usd=float(res.get("fees_usd", 0.0)),
            trade_index=res.get("trade_index"),
        )

    async def sell(self, coin: str, size: float, trade_index: int | None):
        from .execution import Fill

        if trade_index is None:
            raise RuntimeError(
                f"Ostium sell({coin}): trade_index is required to close"
            )
        res = await self._client.close_long(coin, trade_index)
        return Fill(
            price=float(res["fill_price"]),
            size=float(res["size"]),
            fees_paid_usd=float(res.get("fees_usd", 0.0)),
        )
