"""Layer 3 — order routing for HIP-3 short leg + Ostium long leg."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from .config import Config
from .models import Mode, Position
from .ostium_adapter import OstiumHedgeAdapter

logger = logging.getLogger(__name__)

DEFAULT_SLIPPAGE = 0.01
LIMIT_FILL_TIMEOUT_SEC = 10


@dataclass
class Fill:
    price: float
    size: float
    fees_paid_usd: float = 0.0
    trade_index: int | None = None


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
            price=float(filled["avgPx"]), size=float(filled["totalSz"])
        )
    except (KeyError, IndexError, ValueError, TypeError):
        return Fill(fallback_price, fallback_size)


def _resting_oid(result) -> int | None:
    try:
        return result["response"]["data"]["statuses"][0]["resting"]["oid"]
    except (KeyError, IndexError, TypeError):
        return None


class OrderRouter:
    """Coordinates the two-leg open/close/rebalance flow.

    In ``Mode.SCANNER`` no orders are placed — calls return a synthetic
    Position so risk/reporting paths still exercise. In ``Mode.PAPER``
    orders go to HL testnet + Ostium Sepolia. In ``Mode.LIVE`` mainnet.
    """

    def __init__(
        self,
        cfg: Config,
        exchange,
        info,
        ostium: OstiumHedgeAdapter | None,
    ):
        self.cfg = cfg
        self._exchange = exchange
        self._info = info
        self._ostium = ostium

    async def open_delta_neutral(
        self, coin: str, notional_usd: float, entry_net_apr_pct: float
    ) -> Position | None:
        mids = await asyncio.to_thread(self._info.all_mids)
        mark = float(mids.get(coin, 0.0))
        if mark <= 0:
            logger.error("no mid for %s", coin)
            return None
        size = notional_usd / mark

        if self.cfg.mode == "scanner" or self._exchange is None:
            return self._scanner_position(
                coin, size, mark, notional_usd, entry_net_apr_pct
            )

        if self._ostium is None:
            logger.error("Ostium adapter required for paper/live")
            return None

        leg_a, leg_b = await asyncio.gather(
            self._short_hip3(coin, size, mark),
            self._ostium.buy(coin, notional_usd),
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
            mode=Mode(self.cfg.mode),
            hip3_size=-leg_a.size,
            ostium_size=leg_b.size,
            ostium_trade_index=leg_b.trade_index,
            hip3_entry_price=leg_a.price,
            ostium_entry_price=leg_b.price,
            notional_usd=notional_usd,
            entry_net_apr_pct=entry_net_apr_pct,
            fees_paid_bps=bps,
            opened_at=datetime.utcnow(),
        )

    async def close_delta_neutral(self, p: Position) -> None:
        if p.mode is Mode.SCANNER or self._exchange is None:
            logger.info("[scanner] would-close %s", p.coin)
            return
        if self._ostium is None:
            logger.error("Ostium adapter required for paper/live close")
            return
        leg_a, leg_b = await asyncio.gather(
            self._cover_hip3(p),
            self._ostium.sell(p.coin, abs(p.ostium_size), p.ostium_trade_index),
            return_exceptions=True,
        )
        if isinstance(leg_a, Exception):
            logger.error("close hip3 leg failed: %s", leg_a)
        if isinstance(leg_b, Exception):
            logger.error("close ostium leg failed: %s", leg_b)

    async def rebalance_hedge(
        self, p: Position, target_size: float
    ) -> Fill | None:
        delta = target_size - p.ostium_size
        if abs(delta) < 1e-9:
            return None
        if p.mode is Mode.SCANNER or self._ostium is None:
            logger.info("[scanner] would-rebalance %s by %+.4f", p.coin, delta)
            return Fill(price=p.ostium_entry_price, size=abs(delta))
        if delta > 0:
            return await self._ostium.buy(
                p.coin, delta * p.ostium_entry_price
            )
        return await self._ostium.sell(p.coin, -delta, p.ostium_trade_index)

    async def _short_hip3(
        self, coin: str, size: float, mark: float
    ) -> Fill:
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

        wallet_addr = getattr(
            getattr(self._exchange, "wallet", None), "address", None
        )
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
            if (status or {}).get("order", {}).get("status") == "filled":
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
            self._exchange.market_close,
            p.coin,
            size,
            None,
            DEFAULT_SLIPPAGE,
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
        if isinstance(leg_b, Fill) and leg_b.size > 0 and self._ostium is not None:
            try:
                await self._ostium.sell(coin, leg_b.size, leg_b.trade_index)
            except Exception:
                logger.exception("partial unwind B failed")

    def _scanner_position(
        self,
        coin: str,
        size: float,
        mark: float,
        notional: float,
        entry_net_apr_pct: float,
    ) -> Position:
        return Position(
            id=str(uuid.uuid4()),
            coin=coin,
            mode=Mode.SCANNER,
            hip3_size=-size,
            ostium_size=size,
            hip3_entry_price=mark,
            ostium_entry_price=mark,
            notional_usd=notional,
            entry_net_apr_pct=entry_net_apr_pct,
            fees_paid_bps=self.cfg.round_trip_fee_bps / 2,
            opened_at=datetime.utcnow(),
        )
