"""Shared pytest fixtures."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hip3_bot.config import Config
from hip3_bot.models import FundingSnapshot, HedgeVenue, Position


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        mode="scanner",
        hl_private_key=None,
        hl_account_address=None,
        hl_api_url="https://example",
        hl_use_testnet=True,
        ostium_rpc_url="https://example/arb",
        ostium_private_key=None,
        ostium_account_address=None,
        ostium_router_address="0x0000000000000000000000000000000000000000",
        ostium_use_testnet=True,
        telegram_bot_token=None,
        telegram_chat_id=None,
        db_path=tmp_path / "test.db",
        log_level="INFO",
        scan_interval_sec=30,
        min_entry_apr_pct=20.0,
        max_position_pct=0.10,
        kelly_fraction=0.25,
        round_trip_fee_bps=28.0,
        hl_round_trip_bps=18.0,
        ostium_round_trip_bps=10.0,
        min_book_depth_usd=50_000.0,
        long_skew_threshold=0.60,
        consecutive_positive_funding=3,
        delta_drift_threshold=0.05,
        exit_apr_pct=10.0,
        rebalance_interval_min=15,
        deployer_poll_sec=5,
        min_ostium_lp_usd=50_000.0,
        max_basis_pct=0.005,
        ostium_hostile_funding_ratio=0.50,
        ostium_max_slippage_bps=30.0,
    )


def make_snapshot(
    *,
    coin: str = "WTI",
    apr_pct: float = 25.0,
    long_skew: float = 0.7,
    book_depth_usd: float = 100_000.0,
) -> FundingSnapshot:
    funding_8h = apr_pct / (3 * 365 * 100)
    return FundingSnapshot(
        coin=coin,
        funding_8h=funding_8h,
        annualized_apr_pct=apr_pct,
        mark_price=80.0,
        open_interest=1_000_000.0,
        long_skew=long_skew,
        book_depth_usd=book_depth_usd,
        timestamp=datetime.utcnow(),
    )


def make_position(
    *,
    coin: str = "WTI",
    notional_usd: float = 10_000.0,
    hip3_size: float = -125.0,
    hedge_size: float = 125.0,
    hip3_entry: float = 80.0,
    hedge_entry: float = 80.0,
) -> Position:
    return Position(
        id="p1",
        coin=coin,
        hedge_venue=HedgeVenue.PAPER,
        hip3_size=hip3_size,
        hedge_size=hedge_size,
        hip3_entry_price=hip3_entry,
        hedge_entry_price=hedge_entry,
        notional_usd=notional_usd,
        entry_apr_pct=25.0,
    )
