"""Layer 3 — order routing for HIP-3 short leg + hedge long leg."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Protocol

from .config import Config
from .models import HedgeVenue, Position

logger = logging.getLogger(__name__)

DEFAULT_SLIPPAGE = 0.01
LIMIT_FILL_TIMEOUT_SEC = 10


@dataclass
class Fill:
    price: float
    size: float
    fees_paid_usd: float = 0.0


class HedgeAdapter(Protocol):
    venue: HedgeVenue

    async def buy(self, coin: str, notional_usd: float) -> Fill: ...
    async def sell(self, coin: str, size: float) -> Fill: ...


class PaperHedgeAdapter:
    """Records intended hedges without sending. Used for dry-run / paper."""

    venue = HedgeVenue.PAPER

    def __init__(self, ref_price_fn: Callable[[str], Awaitable[float]]):
        self._ref = ref_price_fn

    async def buy(self, coin: str, notional_usd: float) -> Fill:
        price = await self._ref(coin)
        size = notional_usd / price if price > 0 else 0.0
        logger.info("[paper hedge] BUY %s sz=%.4f @ %.4f", coin, size, price)
        return Fill(price=price, size=size)

    async def sell(self, coin: str, size: float) -> Fill:
        price = await self._ref(coin)
        logger.info("[paper hedge] SELL %s sz=%.4f @ %.4f", coin, size, price)
        return Fill(price=price, size=size)


class HLNativeHedgeAdapter:
    """Hedge using a Hyperliquid native (non-HIP-3) commodity perp.

    Used when CME is closed or as a fallback when IBKR is unreachable.
    """

    venue = HedgeVenue.HL_NATIVE

    DEFAULT_MAP: dict[str, str] = {
        # HIP-3 base → HL native equivalent (placeholder mapping).
        "WTI": "OIL",
        "BRENT": "OIL",
    }

    def __init__(self, exchange, info, hedge_coin_map: dict[str, str] | None = None):
        self._exchange = exchange
        self._info = info
        self._map = {**self.DEFAULT_MAP, **(hedge_coin_map or {})}

    def _hedge_coin(self, coin: str) -> str:
        base = coin.upper().split("-")[0]
        return self._map.get(base, base)

    async def buy(self, coin: str, notional_usd: float) -> Fill:
        hc = self._hedge_coin(coin)
        mids = await asyncio.to_thread(self._info.all_mids)
        price = float(mids.get(hc, 0.0))
        if price <= 0:
            raise RuntimeError(f"no mid for hedge coin {hc}")
        size = notional_usd / price
        result = await asyncio.to_thread(
            self._exchange.market_open, hc, True, size, None, DEFAULT_SLIPPAGE
        )
        return _parse_hl_fill(result, fallback_price=price, fallback_size=size)

    async def sell(self, coin: str, size: float) -> Fill:
        hc = self._hedge_coin(coin)
        result = await asyncio.to_thread(
            self._exchange.market_close, hc, size, None, DEFAULT_SLIPPAGE
        )
        return _parse_hl_fill(result, fallback_price=0.0, fallback_size=size)


class IBKRHedgeAdapter:
    """Hedge via IBKR using ETFs (USO for WTI, SLV for silver, etc.)."""

    venue = HedgeVenue.IBKR

    ETF_MAP: dict[str, str] = {
        "WTI": "USO",
        "BRENT": "BNO",
        "SILVER": "SLV",
        "GOLD": "GLD",
        "COPPER": "CPER",
        "PLATINUM": "PPLT",
        "PALLADIUM": "PALL",
    }

    def __init__(self, ib):
        self._ib = ib

    def _etf_for(self, coin: str) -> str:
        base = coin.upper().split("-")[0]
        symbol = self.ETF_MAP.get(base)
        if not symbol:
            raise ValueError(f"no ETF mapping for {coin}")
        return symbol

    async def buy(self, coin: str, notional_usd: float) -> Fill:
        from ib_insync import MarketOrder, Stock

        symbol = self._etf_for(coin)
        contract = Stock(symbol, "SMART", "USD")
        await self._ib.qualifyContractsAsync(contract)
        ticker = self._ib.reqMktData(contract, "", False, False)
        await asyncio.sleep(1.0)
        price = ticker.marketPrice() or ticker.last or ticker.close
        if not price or price <= 0:
            raise RuntimeError(f"no IBKR market price for {symbol}")
        shares = max(1, round(notional_usd / price))
        trade = self._ib.placeOrder(contract, MarketOrder("BUY", shares))
        await asyncio.wait_for(trade.filledEvent, timeout=30)
        avg = trade.orderStatus.avgFillPrice or price
        return Fill(price=avg, size=shares)

    async def sell(self, coin: str, size: float) -> Fill:
        from ib_insync import MarketOrder, Stock

        symbol = self._etf_for(coin)
        contract = Stock(symbol, "SMART", "USD")
        await self._ib.qualifyContractsAsync(contract)
        trade = self._ib.placeOrder(contract, MarketOrder("SELL", abs(size)))
        await asyncio.wait_for(trade.filledEvent, timeout=30)
        avg = trade.orderStatus.avgFillPrice or 0.0
        return Fill(price=avg, size=abs(size))


def _parse_hl_fill(
    result, fallback_price: float, fallback_size: float
) -> Fill:
    try:
        if not result or result.get("status") != "ok":
            return Fill(fallback_price, fallback_size)
        statuses = result["response"]["data"]["statuses"]
        filled = statuses[0].get("filled") if statuses else None
        if not filled:
            return Fill(fallback_price, fallback_size)
        return Fill(
            price=float(filled["avgPx"]),
            size=float(filled["totalSz"]),
        )
    except (KeyError, IndexError, ValueError, TypeError):
        return Fill(fallback_price, fallback_size)


def _resting_oid(result) -> int | None:
    try:
        return result["response"]["data"]["statuses"][0]["resting"]["oid"]
    except (KeyError, IndexError, TypeError):
        return None


class OrderRouter:
    """Coordinates the two-leg open/close/rebalance flow."""

    def __init__(
        self,
        cfg: Config,
        exchange,
        info,
        hedge: HedgeAdapter,
    ):
        self.cfg = cfg
        self._exchange = exchange
        self._info = info
        self._hedge = hedge

    async def open_delta_neutral(
        self, coin: str, notional_usd: float, entry_apr_pct: float
    ) -> Position | None:
        mids = await asyncio.to_thread(self._info.all_mids)
        mark = float(mids.get(coin, 0.0))
        if mark <= 0:
            logger.error("no mid for %s", coin)
            return None
        size = notional_usd / mark

        if self.cfg.dry_run or self._exchange is None:
            return self._paper_position(
                coin, size, mark, notional_usd, entry_apr_pct
            )

        leg_a, leg_b = await asyncio.gather(
            self._short_hip3(coin, size, mark),
            self._hedge.buy(coin, notional_usd),
            return_exceptions=True,
        )
        if isinstance(leg_a, Exception) or isinstance(leg_b, Exception):
            logger.error("leg failure A=%r B=%r", leg_a, leg_b)
            await self._unwind_partial(coin, leg_a, leg_b)
            return None

        fees = leg_a.fees_paid_usd + leg_b.fees_paid_usd
        bps = (fees / notional_usd * 10_000) if notional_usd > 0 else 0.0

        return Position(
            id=str(uuid.uuid4()),
            coin=coin,
            hedge_venue=self._hedge.venue,
            hip3_size=-leg_a.size,
            hedge_size=leg_b.size,
            hip3_entry_price=leg_a.price,
            hedge_entry_price=leg_b.price,
            notional_usd=notional_usd,
            entry_apr_pct=entry_apr_pct,
            fees_paid_bps=bps,
            opened_at=datetime.utcnow(),
        )

    async def close_delta_neutral(self, p: Position) -> None:
        if self.cfg.dry_run or self._exchange is None:
            logger.info("[dry] close %s", p.coin)
            return
        leg_a, leg_b = await asyncio.gather(
            self._cover_hip3(p),
            self._hedge.sell(p.coin, abs(p.hedge_size)),
            return_exceptions=True,
        )
        if isinstance(leg_a, Exception):
            logger.error("close hip3 leg failed: %s", leg_a)
        if isinstance(leg_b, Exception):
            logger.error("close hedge leg failed: %s", leg_b)

    async def rebalance_hedge(
        self, p: Position, target_size: float
    ) -> Fill | None:
        delta = target_size - p.hedge_size
        if abs(delta) < 1e-9:
            return None
        if self.cfg.dry_run or self._exchange is None:
            logger.info("[dry] rebalance %s by %+.4f", p.coin, delta)
            return Fill(price=p.hedge_entry_price, size=abs(delta))
        if delta > 0:
            return await self._hedge.buy(p.coin, delta * p.hedge_entry_price)
        return await self._hedge.sell(p.coin, -delta)

    async def _short_hip3(
        self, coin: str, size: float, mark: float
    ) -> Fill:
        # Limit at mid; slide to taker on timeout.
        result = await asyncio.to_thread(
            self._exchange.order,
            coin,
            False,
            size,
            mark,
            {"limit": {"tif": "Gtc"}},
            False,
        )
        oid = _resting_oid(result)
        if oid is None:
            return _parse_hl_fill(result, mark, size)

        wallet_addr = getattr(self._exchange, "wallet", None)
        wallet_addr = getattr(wallet_addr, "address", None)

        for _ in range(LIMIT_FILL_TIMEOUT_SEC):
            await asyncio.sleep(1.0)
            if not wallet_addr:
                break
            try:
                status = await asyncio.to_thread(
                    self._info.query_order_by_oid, wallet_addr, oid
                )
            except Exception:
                break
            order_status = (
                (status or {}).get("order", {}).get("status")
            )
            if order_status == "filled":
                return _parse_hl_fill(result, mark, size)

        try:
            await asyncio.to_thread(self._exchange.cancel, coin, oid)
        except Exception:
            logger.exception("cancel failed for %s oid=%s", coin, oid)
        result2 = await asyncio.to_thread(
            self._exchange.market_open,
            coin,
            False,
            size,
            None,
            DEFAULT_SLIPPAGE,
        )
        return _parse_hl_fill(result2, mark, size)

    async def _cover_hip3(self, p: Position) -> Fill:
        size = abs(p.hip3_size)
        result = await asyncio.to_thread(
            self._exchange.market_close, p.coin, size, None, DEFAULT_SLIPPAGE
        )
        return _parse_hl_fill(result, p.hip3_entry_price, size)

    async def _unwind_partial(self, coin: str, leg_a, leg_b) -> None:
        if isinstance(leg_a, Fill) and leg_a.size > 0:
            try:
                await asyncio.to_thread(
                    self._exchange.market_close,
                    coin,
                    leg_a.size,
                    None,
                    DEFAULT_SLIPPAGE,
                )
            except Exception:
                logger.exception("partial unwind A failed")
        if isinstance(leg_b, Fill) and leg_b.size > 0:
            try:
                await self._hedge.sell(coin, leg_b.size)
            except Exception:
                logger.exception("partial unwind B failed")

    def _paper_position(
        self,
        coin: str,
        size: float,
        mark: float,
        notional: float,
        apr: float,
    ) -> Position:
        return Position(
            id=str(uuid.uuid4()),
            coin=coin,
            hedge_venue=self._hedge.venue,
            hip3_size=-size,
            hedge_size=size,
            hip3_entry_price=mark,
            hedge_entry_price=mark,
            notional_usd=notional,
            entry_apr_pct=apr,
            fees_paid_bps=self.cfg.round_trip_fee_bps / 2,
            opened_at=datetime.utcnow(),
        )
