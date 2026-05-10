"""Ostium router client backed by ostium-python-sdk."""
from __future__ import annotations

import asyncio
import logging

from .config import Config

logger = logging.getLogger(__name__)


class PairResolver:
    """Resolve coin ticker → Ostium pair_id at startup, cache thereafter."""

    def __init__(self, sdk):
        self._sdk = sdk
        self._cache: dict[str, int] | None = None
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._cache is not None:
            return
        async with self._lock:
            if self._cache is not None:
                return
            pairs = await self._sdk.subgraph.get_pairs()
            cache: dict[str, int] = {}
            for p in pairs:
                ticker = (p.get("from") or "").upper()
                pid = p.get("id")
                if ticker and pid is not None:
                    cache[ticker] = int(pid)
            self._cache = cache
            logger.info("PairResolver loaded %d Ostium pairs", len(cache))

    async def pair_id(self, coin: str) -> int | None:
        await self._ensure_loaded()
        # ``coin`` may be ``"WTI"`` or ``"WTI-PERP"`` — normalize.
        base = coin.upper().split("-")[0]
        return self._cache.get(base)

    async def pair_record(self, coin: str) -> dict | None:
        """Return the raw subgraph payload for the pair (or None).

        Refreshes the subgraph each call so funding/LP fields stay current.
        Cheap relative to the 30s scan interval.
        """
        await self._ensure_loaded()
        base = coin.upper().split("-")[0]
        try:
            pairs = await self._sdk.subgraph.get_pairs()
        except Exception:
            logger.exception("get_pairs failed")
            return None
        for p in pairs:
            if (p.get("from") or "").upper() == base:
                return p
        return None


class OstiumRouterClient:
    """Implements the OstiumClient protocol via ostium-python-sdk.

    NOTE: subgraph field names for funding rate and LP liquidity are
    best-effort here. Phase 3 Task 6 does a Sepolia smoke run and pins
    down the actual response shape; if a field is missing or mis-named,
    this client returns the value as 0.0 (which causes the entry gate
    to fail-closed because LP < $50k or basis is uncomputable).
    """

    # Candidate field names tried in order until one is found numeric.
    FUNDING_FIELDS = ("funding_8h", "fundingRate", "funding")
    LP_FIELDS = ("lp_long_usd", "longCollateral", "openLongCollateral")

    def __init__(self, sdk, default_collateral_usd: float):
        self._sdk = sdk
        self._resolver = PairResolver(sdk)
        self._default_collateral = default_collateral_usd

    @classmethod
    def from_config(cls, cfg: Config) -> "OstiumRouterClient":
        from ostium_python_sdk import NetworkConfig, OstiumSDK

        net_cfg = (
            NetworkConfig.testnet()
            if cfg.ostium_use_testnet
            else NetworkConfig.mainnet()
        )
        sdk = OstiumSDK(
            net_cfg,
            cfg.ostium_private_key,
            cfg.ostium_rpc_url,
        )
        return cls(sdk, default_collateral_usd=1_000.0)

    async def get_market(self, coin: str) -> dict | None:
        pair = await self._resolver.pair_record(coin)
        if pair is None:
            return None
        try:
            mark, _, _ = await self._sdk.price.get_price(
                coin.upper().split("-")[0], "USD"
            )
        except Exception:
            logger.exception("get_price failed for %s", coin)
            mark = 0.0

        funding_8h = _first_float(pair, self.FUNDING_FIELDS, default=0.0)
        lp_long = _first_float(pair, self.LP_FIELDS, default=0.0)

        return {
            "listed": True,
            "funding_8h": funding_8h,
            "mark_price": float(mark),
            "lp_long_usd": lp_long,
        }

    async def open_long(
        self,
        coin: str,
        notional_usd: float,
        max_slippage_bps: float,
    ) -> dict:
        pid = await self._resolver.pair_id(coin)
        if pid is None:
            raise RuntimeError(f"{coin} is not listed on Ostium")

        try:
            mark, _, _ = await self._sdk.price.get_price(
                coin.upper().split("-")[0], "USD"
            )
        except Exception:
            logger.exception("get_price failed pre-open for %s", coin)
            mark = 0.0
        if not mark or mark <= 0:
            raise RuntimeError(f"no Ostium mark for {coin}")

        # SDK takes percent; convert from bps (30 bps → 0.3%).
        self._sdk.ostium.set_slippage_percentage(max_slippage_bps / 100.0)

        # Pick leverage such that collateral × leverage ≈ notional, bounded
        # to the SDK's stated max (200x). Tune in Phase 4.
        leverage = max(
            1, min(200, round(notional_usd / self._default_collateral))
        )
        collateral = notional_usd / leverage

        trade_params = {
            "collateral": collateral,
            "leverage": leverage,
            "asset_type": pid,
            "direction": True,  # long
            "order_type": "MARKET",
        }
        receipt = self._sdk.ostium.perform_trade(
            trade_params, at_price=float(mark)
        )
        return {
            "fill_price": float(mark),
            "size": notional_usd / float(mark),
            "fees_usd": 0.0,
            "trade_index": receipt.get("trade_index"),
        }

    async def close_long(self, coin: str, trade_index: int) -> dict:
        pid = await self._resolver.pair_id(coin)
        if pid is None:
            raise RuntimeError(f"{coin} is not listed on Ostium")
        receipt = self._sdk.ostium.close_trade(pid, trade_index)
        try:
            mark, _, _ = await self._sdk.price.get_price(
                coin.upper().split("-")[0], "USD"
            )
        except Exception:
            mark = 0.0
        return {
            "fill_price": float(mark or 0.0),
            "size": 0.0,  # SDK doesn't directly report fill size; receipt parsing TBD
            "fees_usd": 0.0,
        }


def _first_float(d: dict, keys: tuple[str, ...], default: float) -> float:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return default
