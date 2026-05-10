"""Main orchestrator wiring HL feed + Ostium feed + signals + risk."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .alerts import TelegramAlerter
from .config import Config
from .data_feed import HLDataFeed
from .db import Database
from .execution import OrderRouter
from .models import ExitReason, FundingSnapshot, Mode, OstiumSnapshot, Position
from .ostium_adapter import OstiumHedgeAdapter
from .ostium_feed import OstiumDataFeed
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
        self.mode = Mode(cfg.mode)
        self.db = Database(cfg.db_path)
        self.alerter = TelegramAlerter(cfg)

        self.exchange, self.info = self._build_hl_clients()
        self.feed = HLDataFeed(cfg, info=self.info)
        self.ostium_feed = OstiumDataFeed(cfg)
        self.ostium_adapter = self._build_ostium_adapter()
        self.router = OrderRouter(
            cfg, self.exchange, self.info, self.ostium_adapter
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
        if self.mode is Mode.SCANNER or not self.cfg.hl_private_key:
            return None, info
        from eth_account import Account
        from hyperliquid.exchange import Exchange

        wallet = Account.from_key(self.cfg.hl_private_key)
        exchange = Exchange(
            wallet, url, account_address=self.cfg.hl_account_address
        )
        return exchange, info

    def _build_ostium_adapter(self) -> OstiumHedgeAdapter | None:
        if self.mode is Mode.SCANNER:
            return None
        try:
            from ._ostium_router import RouterClient
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(self.cfg.ostium_rpc_url))
            client = RouterClient(w3, self.cfg.ostium_router_address)
            return OstiumHedgeAdapter(
                client, max_slippage_bps=self.cfg.ostium_max_slippage_bps
            )
        except Exception:
            logger.exception("Ostium adapter init failed")
            return None

    async def run(self) -> None:
        await self.alerter.send(
            f"🤖 hip3-bot starting "
            f"(mode={self.mode.value}, "
            f"hl_testnet={self.cfg.hl_use_testnet}, "
            f"ostium_testnet={self.cfg.ostium_use_testnet})"
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
            logger.exception("capital fetch failed; using 100k default")
            self._capital_usd = 100_000.0

    async def _handle_snapshot(self, hl_snap: FundingSnapshot) -> None:
        ostium_snap = await self.ostium_feed.snapshot(hl_snap.coin)
        self.db.record_funding(
            coin=hl_snap.coin,
            hl_funding_8h=hl_snap.funding_8h,
            hl_apr_pct=hl_snap.annualized_apr_pct,
            hl_mark_price=hl_snap.mark_price,
            open_interest=hl_snap.open_interest,
            long_skew=hl_snap.long_skew,
            hl_book_depth_usd=hl_snap.book_depth_usd,
            ostium_funding_8h=ostium_snap.funding_8h,
            ostium_apr_pct=ostium_snap.annualized_apr_pct,
            ostium_mark_price=ostium_snap.mark_price,
            ostium_lp_usd=ostium_snap.lp_liquidity_usd,
            ostium_listed=ostium_snap.listed,
        )
        existing = self.db.open_position_for(hl_snap.coin, self.mode)
        if existing:
            await self._evaluate_exit(existing, hl_snap, ostium_snap)
        else:
            await self._evaluate_entry(hl_snap, ostium_snap)

    async def _evaluate_entry(
        self, hl: FundingSnapshot, ostium: OstiumSnapshot
    ) -> None:
        history = self.db.recent_hl_funding(hl.coin, 6)
        decision = evaluate_entry(hl, ostium, history, self.cfg)
        if not decision.enter:
            return

        size_usd = kelly_size_usd(
            decision.net_apr_pct, history, self._capital_usd, self.cfg
        )
        if size_usd <= 0:
            return

        await self.alerter.send(
            f"🎯 *Entry signal* {hl.coin}\n"
            f"net APR: {decision.net_apr_pct:.1f}%  "
            f"HL skew: {hl.long_skew:.2f}  "
            f"Ostium LP: ${ostium.lp_liquidity_usd:,.0f}\n"
            f"Sizing: ${size_usd:,.0f}"
        )
        position = await self.router.open_delta_neutral(
            hl.coin, size_usd, decision.net_apr_pct
        )
        if position is None:
            await self.alerter.send(f"⚠️ entry failed for {hl.coin}")
            return
        self.db.upsert_position(position)
        self.db.log_event(
            "entry",
            {
                "coin": hl.coin,
                "size_usd": size_usd,
                "net_apr_pct": decision.net_apr_pct,
                "position_id": position.id,
                "mode": self.mode.value,
            },
        )

    async def _evaluate_exit(
        self,
        p: Position,
        hl: FundingSnapshot,
        ostium: OstiumSnapshot,
    ) -> None:
        decision = evaluate_exit(
            p,
            hl,
            ostium,
            deployer_halted=self._deployer_halted.get(hl.coin, False),
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
                "mode": self.mode.value,
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
        positions = self.db.open_positions(self.mode)
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
                if hip3_mark <= 0:
                    continue
                ostium_snap = await self.ostium_feed.snapshot(p.coin)
                ostium_mark = (
                    ostium_snap.mark_price
                    if ostium_snap.listed
                    else hip3_mark
                )
                drift = delta_drift(p, hip3_mark, ostium_mark)
                if not needs_rebalance(drift, self.cfg):
                    continue
                target = target_hedge_size(p, ostium_mark)
                fill = await self.router.rebalance_hedge(p, target)
                if fill is not None:
                    p.ostium_size = target
                    self.db.upsert_position(p)
                    await self.alerter.send(
                        f"⚖️ rebalanced {p.coin} drift={drift:+.2%}"
                    )
                    self.db.log_event(
                        "rebalance",
                        {
                            "coin": p.coin,
                            "drift": drift,
                            "new_ostium_size": target,
                        },
                    )
            except Exception:
                logger.exception("rebalance %s failed", p.coin)

    async def _daily_report_loop(self) -> None:
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                await self.alerter.send(daily_report(self.db, self.mode))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("daily report failed")

    async def _deployer_watch_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.deployer_poll_sec)
            try:
                meta = await asyncio.to_thread(self.info.meta)
                live_coins = {
                    u.get("name")
                    for u in meta.get("universe", [])
                    if not u.get("isDelisted")
                }
                for p in self.db.open_positions(self.mode):
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
