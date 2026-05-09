"""Main orchestrator wiring the 5 layers together."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .alerts import TelegramAlerter
from .config import Config
from .data_feed import HLDataFeed
from .db import Database
from .execution import (
    HedgeAdapter,
    HLNativeHedgeAdapter,
    IBKRHedgeAdapter,
    OrderRouter,
    PaperHedgeAdapter,
)
from .models import ExitReason, FundingSnapshot, Position
from .reporting import daily_report
from .risk import (
    delta_drift,
    evaluate_exit,
    needs_rebalance,
    realized_apr_pct,
    target_hedge_size,
)
from .signals import evaluate_entry, kelly_size_usd

logger = logging.getLogger(__name__)


class Bot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.alerter = TelegramAlerter(cfg)

        self.exchange, self.info = self._build_hl_clients()
        self.feed = HLDataFeed(cfg, info=self.info)
        self.router = OrderRouter(
            cfg, self.exchange, self.info, self._build_hedge()
        )

        self._capital_usd: float = 0.0
        self._deployer_halted: dict[str, bool] = {}

    def _build_hl_clients(self):
        from hyperliquid.info import Info

        url = (
            "https://api.hyperliquid-testnet.xyz"
            if self.cfg.hl_use_testnet
            else self.cfg.hl_api_url
        )
        info = Info(url, skip_ws=True)
        if self.cfg.dry_run or not self.cfg.hl_private_key:
            return None, info
        from eth_account import Account
        from hyperliquid.exchange import Exchange

        wallet = Account.from_key(self.cfg.hl_private_key)
        exchange = Exchange(
            wallet, url, account_address=self.cfg.hl_account_address
        )
        return exchange, info

    def _build_hedge(self) -> HedgeAdapter:
        venue = self.cfg.hedge_venue.lower()
        if venue == "ibkr" and not self.cfg.dry_run:
            try:
                from ib_insync import IB

                ib = IB()
                ib.connect(
                    self.cfg.ibkr_host,
                    self.cfg.ibkr_port,
                    clientId=self.cfg.ibkr_client_id,
                )
                return IBKRHedgeAdapter(ib)
            except Exception:
                logger.exception("IBKR connection failed; using paper")
        if venue == "hl_native" and self.exchange is not None:
            return HLNativeHedgeAdapter(self.exchange, self.info)

        async def ref_price(coin: str) -> float:
            try:
                mids = await asyncio.to_thread(self.info.all_mids)
                return float(mids.get(coin, 0.0))
            except Exception:
                return 0.0

        return PaperHedgeAdapter(ref_price)

    async def run(self) -> None:
        await self.alerter.send(
            f"🤖 hip3-bot starting (dry_run={self.cfg.dry_run}, "
            f"testnet={self.cfg.hl_use_testnet}, "
            f"hedge={self.cfg.hedge_venue})"
        )
        await self._refresh_capital()
        await asyncio.gather(
            self.feed.run(self._handle_snapshot),
            self._rebalance_loop(),
            self._daily_report_loop(),
            self._deployer_watch_loop(),
        )

    async def _refresh_capital(self) -> None:
        if not self.cfg.hl_account_address:
            self._capital_usd = 100_000.0
            return
        try:
            state = await asyncio.to_thread(
                self.info.user_state, self.cfg.hl_account_address
            )
            self._capital_usd = float(
                state.get("marginSummary", {}).get(
                    "accountValue", 100_000.0
                )
            )
        except Exception:
            logger.exception("capital fetch failed; using paper default")
            self._capital_usd = 100_000.0

    async def _handle_snapshot(self, snap: FundingSnapshot) -> None:
        self.db.record_funding(snap)
        existing = self.db.open_position_for(snap.coin)
        if existing:
            await self._evaluate_exit(existing, snap)
        else:
            await self._evaluate_entry(snap)

    async def _evaluate_entry(self, snap: FundingSnapshot) -> None:
        history = self.db.recent_funding(snap.coin, 6)
        decision = evaluate_entry(snap, history, self.cfg)
        if not decision.enter:
            return

        size_usd = kelly_size_usd(
            snap.annualized_apr_pct, history, self._capital_usd, self.cfg
        )
        if size_usd <= 0:
            return

        await self.alerter.send(
            f"🎯 *Entry signal* {snap.coin}\n"
            f"APR: {snap.annualized_apr_pct:.1f}%  "
            f"skew: {snap.long_skew:.2f}  "
            f"depth: ${snap.book_depth_usd:,.0f}\n"
            f"Sizing: ${size_usd:,.0f}"
        )
        position = await self.router.open_delta_neutral(
            snap.coin, size_usd, snap.annualized_apr_pct
        )
        if position is None:
            await self.alerter.send(f"⚠️ entry failed for {snap.coin}")
            return
        self.db.upsert_position(position)
        self.db.log_event(
            "entry",
            {
                "coin": snap.coin,
                "size_usd": size_usd,
                "apr": snap.annualized_apr_pct,
                "position_id": position.id,
            },
        )

    async def _evaluate_exit(
        self, p: Position, snap: FundingSnapshot
    ) -> None:
        decision = evaluate_exit(
            p,
            snap,
            deployer_halted=self._deployer_halted.get(snap.coin, False),
            cfg=self.cfg,
        )
        if decision.should_exit and decision.reason is not None:
            await self._close(p, decision.reason, decision.note)

    async def _close(
        self, p: Position, reason: ExitReason, note: str
    ) -> None:
        await self.alerter.send(
            f"🚪 closing *{p.coin}* — {reason.value}\n{note}"
        )
        await self.router.close_delta_neutral(p)
        p.closed_at = datetime.utcnow()
        p.exit_reason = reason
        held_h = (p.closed_at - p.opened_at).total_seconds() / 3600.0
        # Conservative realized P&L: funding received less fee drag.
        p.realized_pnl_usd = p.funding_received_usd - (
            p.fees_paid_bps / 10_000.0 * p.notional_usd
        )
        self.db.upsert_position(p)
        self.db.log_event(
            "exit",
            {
                "coin": p.coin,
                "reason": reason.value,
                "pnl_usd": p.realized_pnl_usd,
                "realized_apr_pct": realized_apr_pct(p, held_h),
                "held_hours": held_h,
            },
        )

    async def _rebalance_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.rebalance_interval_min * 60)
            try:
                await self._rebalance_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("rebalance error")

    async def _rebalance_all(self) -> None:
        positions = self.db.open_positions()
        if not positions:
            return
        try:
            mids = await asyncio.to_thread(self.info.all_mids)
        except Exception:
            logger.exception("mids fetch failed in rebalance loop")
            return
        for p in positions:
            try:
                hip3_mark = float(mids.get(p.coin, 0.0))
                hedge_mark = hip3_mark
                if hip3_mark <= 0:
                    continue
                drift = delta_drift(p, hip3_mark, hedge_mark)
                if not needs_rebalance(drift, self.cfg):
                    continue
                target = target_hedge_size(p, hedge_mark)
                fill = await self.router.rebalance_hedge(p, target)
                if fill is not None:
                    p.hedge_size = target
                    self.db.upsert_position(p)
                    await self.alerter.send(
                        f"⚖️ rebalanced {p.coin} drift={drift:+.2%}"
                    )
                    self.db.log_event(
                        "rebalance",
                        {
                            "coin": p.coin,
                            "drift": drift,
                            "new_hedge_size": target,
                        },
                    )
            except Exception:
                logger.exception("rebalance %s failed", p.coin)

    async def _daily_report_loop(self) -> None:
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                await self.alerter.send(daily_report(self.db))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("daily report failed")

    async def _deployer_watch_loop(self) -> None:
        """Poll the deployer endpoint for halt events.

        The HL meta endpoint exposes deployer addresses on HIP-3 markets.
        Without an explicit on-chain event API in the SDK yet, this polls
        meta and watches for a market disappearing or being flagged
        ``isDelisted``. Refines as the SDK evolves.
        """
        while True:
            await asyncio.sleep(self.cfg.deployer_poll_sec)
            try:
                meta = await asyncio.to_thread(self.info.meta)
                live_coins = {
                    u.get("name")
                    for u in meta.get("universe", [])
                    if not u.get("isDelisted")
                }
                for p in self.db.open_positions():
                    halted = p.coin not in live_coins
                    self._deployer_halted[p.coin] = halted
                    if halted:
                        await self.alerter.send(
                            f"🚨 deployer halt suspected for {p.coin}"
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("deployer watch error")
