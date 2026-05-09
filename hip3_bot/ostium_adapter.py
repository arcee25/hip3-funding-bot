"""Layer 3 — Ostium long-leg hedge adapter (Arbitrum web3)."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class OstiumHedgeAdapter:
    """Long-only hedge against Ostium LP.

    `client` is the same OstiumClient protocol as the data feed but with
    additional ``open_long(coin, notional_usd, max_slippage_bps)`` and
    ``close_long(coin, size)`` methods. The production client wraps the
    Ostium router contract on Arbitrum; tests pass a MagicMock.
    """

    def __init__(self, client, max_slippage_bps: float):
        self._client = client
        self._max_slippage_bps = max_slippage_bps

    async def buy(self, coin: str, notional_usd: float):
        from .execution import Fill

        try:
            res = await asyncio.to_thread(
                self._client.open_long,
                coin,
                notional_usd,
                self._max_slippage_bps,
            )
        except Exception as e:
            logger.exception("Ostium open_long failed")
            # Spec § Trade Execution: retry once after 2s on oracle deviation.
            if "oracle" in str(e).lower():
                await asyncio.sleep(2.0)
                res = await asyncio.to_thread(
                    self._client.open_long,
                    coin,
                    notional_usd,
                    self._max_slippage_bps,
                )
            else:
                raise
        return Fill(
            price=float(res["fill_price"]),
            size=float(res["size"]),
            fees_paid_usd=float(res.get("fees_usd", 0.0)),
        )

    async def sell(self, coin: str, size: float):
        from .execution import Fill

        res = await asyncio.to_thread(self._client.close_long, coin, size)
        return Fill(
            price=float(res["fill_price"]),
            size=float(res["size"]),
            fees_paid_usd=float(res.get("fees_usd", 0.0)),
        )
