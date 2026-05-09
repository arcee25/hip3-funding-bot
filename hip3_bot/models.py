"""Domain dataclasses shared across layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class HedgeVenue(str, Enum):
    IBKR = "ibkr"
    HL_NATIVE = "hl_native"
    PAPER = "paper"


class ExitReason(str, Enum):
    DEPLOYER_HALT = "P0_deployer_halt"
    FUNDING_FLIP = "P1_funding_flip"
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
    coin: str
    funding_8h: float
    annualized_apr_pct: float
    mark_price: float
    open_interest: float
    long_skew: float
    book_depth_usd: float
    timestamp: datetime


@dataclass
class Position:
    id: str
    coin: str
    hedge_venue: HedgeVenue
    hip3_size: float
    hedge_size: float
    hip3_entry_price: float
    hedge_entry_price: float
    notional_usd: float
    entry_apr_pct: float
    fees_paid_bps: float = 0.0
    funding_received_usd: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    exit_reason: ExitReason | None = None
    realized_pnl_usd: float = 0.0
