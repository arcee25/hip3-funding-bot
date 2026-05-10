"""Domain dataclasses shared across layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Mode(str, Enum):
    SCANNER = "scanner"
    PAPER = "paper"
    LIVE = "live"


class ExitReason(str, Enum):
    DEPLOYER_HALT = "P0_deployer_halt"
    FUNDING_FLIP = "P1_funding_flip"
    OSTIUM_HOSTILE = "P1b_ostium_hostile"
    APR_DECAY = "P2_apr_decay"
    DELTA_REBALANCE = "P3_delta_rebalance"
    PLANNED_ROTATION = "P4_planned"
    MANUAL = "manual"


@dataclass
class Market:
    coin: str
    is_hip3: bool
    age_days: int | None = None
    deployer_address: str | None = None


@dataclass
class FundingSnapshot:
    """Hyperliquid HIP-3 perp snapshot (the short leg)."""

    coin: str
    funding_8h: float
    annualized_apr_pct: float
    mark_price: float
    open_interest: float
    long_skew: float
    book_depth_usd: float
    timestamp: datetime


@dataclass
class OstiumSnapshot:
    """Ostium perp snapshot (the long hedge leg)."""

    coin: str
    listed: bool
    funding_8h: float                  # Ostium long-side funding rate
    annualized_apr_pct: float
    mark_price: float
    lp_liquidity_usd: float            # available LP in long-direction
    timestamp: datetime


@dataclass
class Position:
    id: str
    coin: str
    mode: Mode
    hip3_size: float
    ostium_size: float
    ostium_trade_index: int | None = None
    hip3_entry_price: float = 0.0
    ostium_entry_price: float = 0.0
    notional_usd: float = 0.0
    entry_net_apr_pct: float = 0.0
    fees_paid_bps: float = 0.0
    funding_received_usd: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    exit_reason: ExitReason | None = None
    realized_pnl_usd: float = 0.0
