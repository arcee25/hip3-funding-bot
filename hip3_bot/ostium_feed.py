"""Layer 1 — Ostium perp feed (Arbitrum, web3-based)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from .config import Config
from .models import OstiumSnapshot

logger = logging.getLogger(__name__)


class OstiumClient(Protocol):
    """Async protocol for the Ostium router/SDK wrapper.

    ``get_market(coin)`` resolves the coin string (e.g. ``"WTI"``) to a
    market struct: ``{"listed": bool, "funding_8h": float, "mark_price":
    float, "lp_long_usd": float}`` or ``None`` when not listed.

    Production: see ``hip3_bot._ostium_router.OstiumRouterClient`` (Task 5),
    backed by ``ostium-python-sdk``. Tests pass an ``AsyncMock``.
    """

    async def get_market(self, coin: str) -> dict | None: ...

    async def open_long(
        self,
        coin: str,
        notional_usd: float,
        max_slippage_bps: float,
    ) -> dict: ...

    async def close_long(self, coin: str, trade_index: int) -> dict: ...


class OstiumDataFeed:
    def __init__(self, cfg: Config, client: OstiumClient | None = None):
        self.cfg = cfg
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> OstiumClient:
        # Lazy import so unit tests don't require ostium-python-sdk.
        from ._ostium_router import OstiumRouterClient

        return OstiumRouterClient.from_config(self.cfg)

    async def snapshot(self, coin: str) -> OstiumSnapshot:
        try:
            payload = await self._client.get_market(coin)
        except Exception:
            logger.exception("Ostium get_market failed for %s", coin)
            payload = None

        now = datetime.utcnow()
        if not payload or not payload.get("listed"):
            return OstiumSnapshot(
                coin=coin,
                listed=False,
                funding_8h=0.0,
                annualized_apr_pct=0.0,
                mark_price=0.0,
                lp_liquidity_usd=0.0,
                timestamp=now,
            )

        funding_8h = float(payload.get("funding_8h", 0.0))
        return OstiumSnapshot(
            coin=coin,
            listed=True,
            funding_8h=funding_8h,
            annualized_apr_pct=funding_8h * 3 * 365 * 100,
            mark_price=float(payload.get("mark_price", 0.0)),
            lp_liquidity_usd=float(payload.get("lp_long_usd", 0.0)),
            timestamp=now,
        )
