"""Layer 1 — Ostium perp feed (Arbitrum, web3-based)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Protocol

from .config import Config
from .models import OstiumSnapshot

logger = logging.getLogger(__name__)


class OstiumClient(Protocol):
    """Thin protocol for Ostium router calls.

    The production implementation wraps `web3.py` against the Ostium
    router contract on Arbitrum. Each call resolves to the on-chain
    market struct for ``coin``: ``{"listed": bool, "funding_8h": float,
    "mark_price": float, "lp_long_usd": float}``.

    Tests pass a ``MagicMock`` shaped like this protocol.
    """

    def get_market(self, coin: str) -> dict | None: ...


class OstiumDataFeed:
    def __init__(self, cfg: Config, client: OstiumClient | None = None):
        self.cfg = cfg
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> OstiumClient:
        # Lazy import so unit tests don't require web3.
        from web3 import Web3

        from ._ostium_router import RouterClient

        w3 = Web3(Web3.HTTPProvider(self.cfg.ostium_rpc_url))
        return RouterClient(w3, self.cfg.ostium_router_address)

    async def snapshot(self, coin: str) -> OstiumSnapshot:
        try:
            payload = await asyncio.to_thread(self._client.get_market, coin)
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
