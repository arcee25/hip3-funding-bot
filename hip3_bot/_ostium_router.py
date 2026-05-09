"""Production Ostium router client (web3 stub).

The exact ABI and method names depend on the deployed Ostium router.
This module isolates the on-chain integration so the feed's test seam
remains clean. Phase 2 wires up real methods against Arbitrum Sepolia.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class RouterClient:
    """Stub. Real implementation calls Ostium router methods via web3.

    Expected behavior:
      get_market(coin) -> {
        "listed": bool,
        "funding_8h": float,   # 8-hour funding rate as decimal
        "mark_price": float,   # USD per unit underlying
        "lp_long_usd": float,  # available LP liquidity, long direction
      } or None when not listed.

    Until ABIs are integrated, this returns None for every coin so the
    bot fails-closed: scanner/paper modes log "Ostium not listed",
    live mode refuses to enter.
    """

    def __init__(self, w3, router_address: str):
        self._w3 = w3
        self._router_address = router_address
        self._contract = None  # populated when ABI is wired

    def get_market(self, coin: str) -> dict | None:
        if self._contract is None:
            logger.warning(
                "Ostium router contract not wired yet; %s treated as unlisted",
                coin,
            )
            return None
        # Real implementation: contract.functions.market(coin).call()
        return None

    def open_long(
        self, coin: str, notional_usd: float, max_slippage_bps: float
    ) -> dict:
        """Open long via Ostium router.

        Returns ``{"fill_price": float, "size": float, "fees_usd": float}``.
        Stubbed until ABI is wired; raises NotImplementedError to make the
        adapter fail-loud rather than silently zero-fill.
        """
        raise NotImplementedError(
            "Ostium router.open_long not yet wired to live ABI"
        )

    def close_long(self, coin: str, size: float) -> dict:
        raise NotImplementedError(
            "Ostium router.close_long not yet wired to live ABI"
        )
