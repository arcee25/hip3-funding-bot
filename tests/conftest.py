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
        hl_private_key=None,
        hl_account_address=None,
        hl_api_url="https://example",
        hl_use_testnet=True,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
        ibkr_client_id=1,
        telegram_bot_token=None,
        telegram_chat_id=None,
        db_path=tmp_path / "test.db",
        log_level="INFO",
        scan_interval_sec=30,
        dry_run=True,
        hedge_venue="paper",
        min_entry_apr_pct=20.0,
        max_position_pct=0.10,
        kelly_fraction=0.25,
        round_trip_fee_bps=18.0,
        min_book_depth_usd=50_000.0,
        long_skew_threshold=0.60,
        consecutive_positive_funding=3,
        delta_drift_threshold=0.05,
        exit_apr_pct=10.0,
        rebalance_interval_min=15,
        deployer_poll_sec=5,
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
