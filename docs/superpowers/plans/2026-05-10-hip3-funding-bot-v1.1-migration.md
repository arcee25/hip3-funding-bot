# HIP-3 Funding Bot v1.1 Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the existing v1.0 implementation (IBKR/CME/ETF hedge, 4-condition entry, 18 bps fee drag, single hedge_venue setting) to v1.1 of `hip3-funding-bot-spec.md` (Ostium-perp hedge on Arbitrum, 6-condition net-APR entry gate, 28 bps fee drag, runtime mode flag with `--confirm-live`, P1b Ostium-hostile exit, split storage tables, `[DRY-RUN]` Telegram tagging).

**Architecture diff vs v1.0:**
- **New module `hip3_bot/ostium_feed.py`** — Ostium perp data over web3 (funding 8h, mark price, LP liquidity, listed flag).
- **New module `hip3_bot/ostium_adapter.py`** — Ostium order placement (long-only hedge leg).
- **Removed** — `PaperHedgeAdapter`, `HLNativeHedgeAdapter`, `IBKRHedgeAdapter` (spec line 123 forbids proxy hedges).
- **Modified** — `config.py` (modes, Ostium fields, 28 bps default, `--confirm-live`), `models.py` (`Mode` enum, `OstiumSnapshot`, `OSTIUM_HOSTILE` exit reason, mode field on `Position`), `db.py` (split `trade_log` / `simulated_trade_log`, mode column on records), `signals.py` (net APR + 6-condition gate signature), `risk.py` (P1b trigger), `bot.py` (mode-aware storage + `[DRY-RUN]` Telegram tagging, OstiumDataFeed wiring), `main.py` (CLI parser for `--confirm-live`, mode banner), `reporting.py` (read both tables).
- **Stale CLAUDE.md** — refresh first.

**Tech Stack:** Python 3.11+. Ostium integration uses `web3.py` directly with contract ABIs (the spec accepts this fallback when `ostium-python-sdk` isn't ready). Pyth oracle reads through Ostium's contract methods. Arbitrum RPC URL configurable via env.

**Source spec:** `hip3-funding-bot-spec.md` (v1.1). Read it first.

**TDD discipline:** Every task: red → green → refactor → commit. Pure logic gets unit tests with mocked Ostium info client (same seam as `HLDataFeed`). Live Ostium against Arbitrum Sepolia is verified manually in Task 12.

---

## File Map (changes from v1.0)

```
hip3_bot/
├── config.py            ─ MODIFY: add mode, ostium_*, --confirm-live wiring; default fee 28
├── models.py            ─ MODIFY: add Mode enum, OstiumSnapshot, OSTIUM_HOSTILE; Position.mode
├── db.py                ─ MODIFY: split trade_log + simulated_trade_log; mode-aware queries
├── signals.py           ─ MODIFY: evaluate_entry takes ostium snapshot; 6-condition gate
├── risk.py              ─ MODIFY: evaluate_exit takes ostium snapshot; P1b
├── ostium_feed.py       ─ CREATE: OstiumDataFeed (web3-based)
├── ostium_adapter.py    ─ CREATE: OstiumHedgeAdapter
├── execution.py         ─ MODIFY: drop Paper/HLNative/IBKR adapters; OrderRouter takes Ostium adapter only
├── bot.py               ─ MODIFY: wire OstiumDataFeed; mode-aware storage; [DRY-RUN] alerts
├── main.py              ─ MODIFY: argparse --confirm-live; loud mode banner
├── reporting.py         ─ MODIFY: read both tables; mode-aware totals
└── alerts.py            ─ MODIFY: prefix [DRY-RUN] when mode in {scanner,paper}

tests/
├── test_signals.py      ─ MODIFY: net APR + 6-condition tests
├── test_risk.py         ─ MODIFY: P1b tests; ostium snapshot in evaluate_exit
├── test_db.py           ─ MODIFY: trade_log vs simulated_trade_log
├── test_ostium_feed.py  ─ CREATE: snapshot building, listed-but-illiquid, missing
├── test_execution.py    ─ MODIFY: OrderRouter with mock Ostium adapter
├── test_reporting.py    ─ MODIFY: cross-table summary
└── test_main.py         ─ CREATE: --confirm-live gate
```

---

## Task 1: Refresh CLAUDE.md to v1.1

**Files:**
- Modify: `CLAUDE.md`

The current CLAUDE.md describes v1.0 (IBKR/USO/GLD/SLV, 4-condition gate, 18 bps fee drag). Subagents will read it and be misled. Fix first.

- [ ] **Step 1.1: Replace CLAUDE.md content**

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Delta-neutral funding rate farming bot for Hyperliquid HIP-3 perpetual markets. Hedge leg is Ostium perp on Arbitrum (Pyth oracle), not IBKR/CME ETFs. Strategy: scan HIP-3 markets for crowded retail longs (commodities — WTI, Brent, Silver), enter delta-neutral (short HIP-3 perp + long Ostium perp), extract net funding yield. Spec version: 1.1. Python 3.11+.

## Architecture (5 Layers)

1. **Data** — Hyperliquid WS/REST funding+mark+OI; Ostium perp feed over web3 (mark, funding, LP liquidity, listed status).
2. **Signal Engine** — Net APR (HL APR − Ostium APR), 6-condition entry gate, fractional-Kelly sizing.
3. **Execution** — Two-leg routing: Leg A short HIP-3 (limit-then-slide), Leg B long Ostium perp (max-slippage 30 bps, oracle-deviation retry once). Delta target 0 ± 2%, rebalance every 15 min on Ostium only.
4. **Risk Monitor** — P0 deployer halt > P1 HL funding flip > **P1b Ostium funding hostile (Ostium long > 50% HL short)** > P2 net APR < 10% > P3 delta drift > 5% > P4 planned rotation.
5. **Reporting** — Telegram (mode-tagged), SQLite (`trade_log` + `simulated_trade_log`), daily realized vs projected APR.

## Runtime Modes

`mode: scanner | paper | live` from config; fixed at process start.

| Mode | Feeds | Order Placement | Storage |
|---|---|---|---|
| `scanner` | mainnet | none — log would-be entries | `simulated_trade_log` |
| `paper` | testnet (HL testnet + Ostium Sepolia) | real testnet API | `simulated_trade_log` |
| `live` | mainnet | real mainnet | `trade_log` |

`live` requires explicit `--confirm-live` CLI flag at startup. Telegram alerts in `scanner`/`paper` are tagged `[DRY-RUN]`.

## Critical Business Rules

- **Net APR** = HL funding APR − Ostium funding APR. The signal threshold (20%) is on net, not raw HL.
- **Six-condition entry gate** (ALL required): net APR > 20%; ≥3 consec positive HL funding; HL OI long skew > 60%; HL top-of-book depth > $50k; **Ostium lists same underlying with LP > $50k long-direction**; **basis `|ostium_mark − hl_mark| / hl_mark < 0.005`**.
- **Round-trip fee drag = 28 bps** (HL 18 + Ostium 10). Pre-calculated before every entry.
- **Position sizing**: fractional Kelly (0.25×), capped 10% of capital per position. Haircut for markets < 30 days old.
- **No proxy hedges** — if Ostium doesn't list the underlying, has < $50k LP, or basis exceeds 50 bps: skip the signal and Telegram-alert. Spec line 123 forbids fallback hedges (HL native, ETF, etc.) — they reintroduce directional risk that 28 bps fee math cannot absorb.
- **Pre-funded margin** — USDC on both Hyperliquid AND Ostium (Arbitrum-deposited), default 50/50. The bot does NOT bridge in the entry hot path. Cross-venue rebalance is Phase 4.
- **Deployer halt** — monitor HIP-3 contract events every 5s; settle to mark before HL settles.

## Key Formulas

```python
hl_apr      = hl_funding_8h     * 3 * 365 * 100
ostium_apr  = ostium_funding_8h * 3 * 365 * 100
net_apr     = hl_apr - ostium_apr
fee_drag_bps    = 28          # HL 18 + Ostium 10
min_hold_hours  = (fee_drag_bps / 100 / net_apr) * 8760
size = min(kelly_f * 0.25, 0.10) * capital
```

## Key Libraries

- `hyperliquid-python-sdk` — HL order placement + WebSocket
- `web3.py` — Ostium contract calls on Arbitrum (until `ostium-python-sdk` is verified available)
- `pandas` / `numpy` — funding analysis, Kelly
- `aiohttp` / `asyncio` — async I/O
- `python-telegram-bot` — alerts
- `APScheduler` — rebalance/reporting cron
- `sqlite3` — persistence (built-in)

## Build Phases

Phase 1 (scanner mode + alerts), Phase 2 (paper trading on HL testnet + Ostium Sepolia), Phase 3 (live with 5-10% capital + `--confirm-live` flag), Phase 4 (multi-market rotation + cross-venue capital auto-rebalance). See `hip3-funding-bot-spec.md` for full v1.1 details.
```

- [ ] **Step 1.2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: refresh CLAUDE.md to spec v1.1 (Ostium hedge, 6-condition gate, modes)"
```

---

## Task 2: Config — modes, Ostium fields, 28 bps default

**Files:**
- Modify: `hip3_bot/config.py`

- [ ] **Step 2.1: Replace `Config` and `from_env` with v1.1 fields**

The full target file (overwrite `hip3_bot/config.py`):

```python
"""Environment-driven configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    if val is None or val == "":
        return default
    return val


def _env_bool(key: str, default: bool = False) -> bool:
    val = _env(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    val = _env(key)
    return int(val) if val else default


def _env_float(key: str, default: float) -> float:
    val = _env(key)
    return float(val) if val else default


@dataclass(frozen=True)
class Config:
    # Mode
    mode: str  # "scanner" | "paper" | "live"

    # Hyperliquid
    hl_private_key: str | None
    hl_account_address: str | None
    hl_api_url: str
    hl_use_testnet: bool

    # Ostium (Arbitrum)
    ostium_rpc_url: str
    ostium_private_key: str | None
    ostium_account_address: str | None
    ostium_router_address: str
    ostium_use_testnet: bool

    # Telegram
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    # Bot
    db_path: Path
    log_level: str
    scan_interval_sec: int

    # Strategy thresholds
    min_entry_apr_pct: float
    max_position_pct: float
    kelly_fraction: float
    round_trip_fee_bps: float
    hl_round_trip_bps: float
    ostium_round_trip_bps: float
    min_book_depth_usd: float
    long_skew_threshold: float
    consecutive_positive_funding: int
    delta_drift_threshold: float
    exit_apr_pct: float
    rebalance_interval_min: int
    deployer_poll_sec: int

    # v1.1 thresholds
    min_ostium_lp_usd: float
    max_basis_pct: float
    ostium_hostile_funding_ratio: float
    ostium_max_slippage_bps: float

    @classmethod
    def from_env(cls) -> "Config":
        mode = (_env("MODE", "scanner") or "scanner").lower()
        if mode not in {"scanner", "paper", "live"}:
            raise RuntimeError(
                f"MODE must be scanner|paper|live, got {mode!r}"
            )
        return cls(
            mode=mode,
            hl_private_key=_env("HL_PRIVATE_KEY"),
            hl_account_address=_env("HL_ACCOUNT_ADDRESS"),
            hl_api_url=_env("HL_API_URL", "https://api.hyperliquid.xyz"),
            hl_use_testnet=_env_bool("HL_USE_TESTNET", mode != "live"),
            ostium_rpc_url=_env(
                "OSTIUM_RPC_URL",
                "https://arb1.arbitrum.io/rpc"
                if mode == "live"
                else "https://sepolia-rollup.arbitrum.io/rpc",
            ),
            ostium_private_key=_env("OSTIUM_PRIVATE_KEY"),
            ostium_account_address=_env("OSTIUM_ACCOUNT_ADDRESS"),
            ostium_router_address=_env(
                "OSTIUM_ROUTER_ADDRESS",
                "0x0000000000000000000000000000000000000000",
            ),
            ostium_use_testnet=_env_bool(
                "OSTIUM_USE_TESTNET", mode != "live"
            ),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            db_path=Path(_env("DB_PATH", "./hip3_bot.db")),
            log_level=_env("LOG_LEVEL", "INFO"),
            scan_interval_sec=_env_int("SCAN_INTERVAL_SEC", 30),
            min_entry_apr_pct=_env_float("MIN_ENTRY_APR_PCT", 20.0),
            max_position_pct=_env_float("MAX_POSITION_PCT", 0.10),
            kelly_fraction=_env_float("KELLY_FRACTION", 0.25),
            round_trip_fee_bps=_env_float("ROUND_TRIP_FEE_BPS", 28.0),
            hl_round_trip_bps=_env_float("HL_ROUND_TRIP_BPS", 18.0),
            ostium_round_trip_bps=_env_float(
                "OSTIUM_ROUND_TRIP_BPS", 10.0
            ),
            min_book_depth_usd=_env_float("MIN_BOOK_DEPTH_USD", 50_000.0),
            long_skew_threshold=_env_float("LONG_SKEW_THRESHOLD", 0.60),
            consecutive_positive_funding=_env_int(
                "CONSECUTIVE_POSITIVE_FUNDING", 3
            ),
            delta_drift_threshold=_env_float(
                "DELTA_DRIFT_THRESHOLD", 0.05
            ),
            exit_apr_pct=_env_float("EXIT_APR_PCT", 10.0),
            rebalance_interval_min=_env_int(
                "REBALANCE_INTERVAL_MIN", 15
            ),
            deployer_poll_sec=_env_int("DEPLOYER_POLL_SEC", 5),
            min_ostium_lp_usd=_env_float(
                "MIN_OSTIUM_LP_USD", 50_000.0
            ),
            max_basis_pct=_env_float("MAX_BASIS_PCT", 0.005),
            ostium_hostile_funding_ratio=_env_float(
                "OSTIUM_HOSTILE_FUNDING_RATIO", 0.50
            ),
            ostium_max_slippage_bps=_env_float(
                "OSTIUM_MAX_SLIPPAGE_BPS", 30.0
            ),
        )

    @property
    def is_dry_run(self) -> bool:
        """scanner and paper modes never touch live mainnet capital."""
        return self.mode in ("scanner", "paper")
```

- [ ] **Step 2.2: Update `.env.example` to match new fields**

Replace `.env.example` content:

```
# Mode: scanner | paper | live
MODE=scanner

# Hyperliquid
HL_PRIVATE_KEY=
HL_ACCOUNT_ADDRESS=
HL_API_URL=https://api.hyperliquid.xyz
HL_USE_TESTNET=true

# Ostium (Arbitrum)
OSTIUM_RPC_URL=
OSTIUM_PRIVATE_KEY=
OSTIUM_ACCOUNT_ADDRESS=
OSTIUM_ROUTER_ADDRESS=
OSTIUM_USE_TESTNET=true

# Telegram alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Bot
DB_PATH=./hip3_bot.db
LOG_LEVEL=INFO
SCAN_INTERVAL_SEC=30

# Strategy thresholds
MIN_ENTRY_APR_PCT=20
MAX_POSITION_PCT=0.10
KELLY_FRACTION=0.25
ROUND_TRIP_FEE_BPS=28
HL_ROUND_TRIP_BPS=18
OSTIUM_ROUND_TRIP_BPS=10
MIN_BOOK_DEPTH_USD=50000
LONG_SKEW_THRESHOLD=0.60
CONSECUTIVE_POSITIVE_FUNDING=3
DELTA_DRIFT_THRESHOLD=0.05
EXIT_APR_PCT=10
REBALANCE_INTERVAL_MIN=15
DEPLOYER_POLL_SEC=5
MIN_OSTIUM_LP_USD=50000
MAX_BASIS_PCT=0.005
OSTIUM_HOSTILE_FUNDING_RATIO=0.50
OSTIUM_MAX_SLIPPAGE_BPS=30
```

- [ ] **Step 2.3: Update `tests/conftest.py` `cfg` fixture to match new fields**

Replace the `cfg` fixture in `tests/conftest.py`:

```python
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
```

- [ ] **Step 2.4: Run existing tests — most fail due to signature changes; that's expected**

```bash
pytest tests/ -x 2>&1 | tail -20
```

Expected: failures because downstream code still references removed fields like `hedge_venue` and `dry_run`. We fix those in subsequent tasks. For now, verify only that `Config.from_env()` itself imports and tests using only `cfg` fixture+pure math pass.

- [ ] **Step 2.5: Commit**

```bash
git add hip3_bot/config.py .env.example tests/conftest.py
git commit -m "config: v1.1 modes, Ostium fields, 28 bps round-trip default"
```

---

## Task 3: Models — `Mode`, `OstiumSnapshot`, `OSTIUM_HOSTILE`, `Position.mode`

**Files:**
- Modify: `hip3_bot/models.py`

- [ ] **Step 3.1: Replace `hip3_bot/models.py`**

```python
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
    hip3_entry_price: float
    ostium_entry_price: float
    notional_usd: float
    entry_net_apr_pct: float
    fees_paid_bps: float = 0.0
    funding_received_usd: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    exit_reason: ExitReason | None = None
    realized_pnl_usd: float = 0.0
```

- [ ] **Step 3.2: Update `tests/conftest.py` `make_position` and `make_snapshot` helpers, add `make_ostium_snapshot`**

Replace the helpers in `tests/conftest.py` (keep imports + `cfg` fixture):

```python
from hip3_bot.models import (
    FundingSnapshot,
    Mode,
    OstiumSnapshot,
    Position,
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


def make_ostium_snapshot(
    *,
    coin: str = "WTI",
    listed: bool = True,
    apr_pct: float = 5.0,
    mark_price: float = 80.0,
    lp_liquidity_usd: float = 100_000.0,
) -> OstiumSnapshot:
    funding_8h = apr_pct / (3 * 365 * 100)
    return OstiumSnapshot(
        coin=coin,
        listed=listed,
        funding_8h=funding_8h,
        annualized_apr_pct=apr_pct,
        mark_price=mark_price,
        lp_liquidity_usd=lp_liquidity_usd,
        timestamp=datetime.utcnow(),
    )


def make_position(
    *,
    coin: str = "WTI",
    notional_usd: float = 10_000.0,
    hip3_size: float = -125.0,
    ostium_size: float = 125.0,
    hip3_entry: float = 80.0,
    ostium_entry: float = 80.0,
    mode: Mode = Mode.SCANNER,
) -> Position:
    return Position(
        id="p1",
        coin=coin,
        mode=mode,
        hip3_size=hip3_size,
        ostium_size=ostium_size,
        hip3_entry_price=hip3_entry,
        ostium_entry_price=ostium_entry,
        notional_usd=notional_usd,
        entry_net_apr_pct=20.0,
    )
```

- [ ] **Step 3.3: Smoke-import**

```bash
python -c "from hip3_bot.models import Mode, OstiumSnapshot, Position, ExitReason; print(Mode.LIVE, ExitReason.OSTIUM_HOSTILE)"
```

Expected: `Mode.LIVE P1b_ostium_hostile`.

- [ ] **Step 3.4: Commit**

```bash
git add hip3_bot/models.py tests/conftest.py
git commit -m "models: v1.1 Mode enum, OstiumSnapshot, OSTIUM_HOSTILE exit, Position.mode"
```

---

## Task 4: Database — split `trade_log` and `simulated_trade_log`

**Files:**
- Modify: `hip3_bot/db.py`
- Modify: `tests/test_db.py`

Spec § Layer 5: live fills go into `trade_log`, scanner/paper into `simulated_trade_log`. Both share schema.

- [ ] **Step 4.1: Replace `hip3_bot/db.py`**

```python
"""SQLite persistence: funding history, trade tables, events."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .models import ExitReason, Mode, Position

POSITION_COLS = """
    id TEXT PRIMARY KEY,
    coin TEXT NOT NULL,
    mode TEXT NOT NULL,
    hip3_size REAL NOT NULL,
    ostium_size REAL NOT NULL,
    hip3_entry_price REAL NOT NULL,
    ostium_entry_price REAL NOT NULL,
    notional_usd REAL NOT NULL,
    entry_net_apr_pct REAL NOT NULL,
    fees_paid_bps REAL NOT NULL DEFAULT 0,
    funding_received_usd REAL NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_reason TEXT,
    realized_pnl_usd REAL NOT NULL DEFAULT 0
"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS funding_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    hl_funding_8h REAL NOT NULL,
    hl_apr_pct REAL NOT NULL,
    ostium_funding_8h REAL,
    ostium_apr_pct REAL,
    net_apr_pct REAL,
    hl_mark_price REAL NOT NULL,
    ostium_mark_price REAL,
    open_interest REAL NOT NULL,
    long_skew REAL NOT NULL,
    hl_book_depth_usd REAL NOT NULL,
    ostium_lp_usd REAL,
    ostium_listed INTEGER,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_funding_coin_ts
    ON funding_history(coin, timestamp DESC);

CREATE TABLE IF NOT EXISTS trade_log ({POSITION_COLS});
CREATE INDEX IF NOT EXISTS idx_trade_open ON trade_log(closed_at);
CREATE INDEX IF NOT EXISTS idx_trade_coin_open ON trade_log(coin, closed_at);

CREATE TABLE IF NOT EXISTS simulated_trade_log ({POSITION_COLS});
CREATE INDEX IF NOT EXISTS idx_sim_open ON simulated_trade_log(closed_at);
CREATE INDEX IF NOT EXISTS idx_sim_coin_open
    ON simulated_trade_log(coin, closed_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);
"""


def _table_for_mode(mode: Mode) -> str:
    return "trade_log" if mode is Mode.LIVE else "simulated_trade_log"


class Database:
    def __init__(self, path: Path):
        self.path = path
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def record_funding(
        self,
        coin: str,
        hl_funding_8h: float,
        hl_apr_pct: float,
        hl_mark_price: float,
        open_interest: float,
        long_skew: float,
        hl_book_depth_usd: float,
        ostium_funding_8h: float | None = None,
        ostium_apr_pct: float | None = None,
        ostium_mark_price: float | None = None,
        ostium_lp_usd: float | None = None,
        ostium_listed: bool | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        net = (
            hl_apr_pct - ostium_apr_pct
            if ostium_apr_pct is not None
            else hl_apr_pct
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO funding_history(coin,hl_funding_8h,hl_apr_pct,"
                "ostium_funding_8h,ostium_apr_pct,net_apr_pct,"
                "hl_mark_price,ostium_mark_price,open_interest,long_skew,"
                "hl_book_depth_usd,ostium_lp_usd,ostium_listed,timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    coin,
                    hl_funding_8h,
                    hl_apr_pct,
                    ostium_funding_8h,
                    ostium_apr_pct,
                    net,
                    hl_mark_price,
                    ostium_mark_price,
                    open_interest,
                    long_skew,
                    hl_book_depth_usd,
                    ostium_lp_usd,
                    int(ostium_listed) if ostium_listed is not None else None,
                    (timestamp or datetime.utcnow()).isoformat(),
                ),
            )

    def recent_hl_funding(self, coin: str, limit: int = 10) -> list[float]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT hl_funding_8h FROM funding_history WHERE coin=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (coin, limit),
            ).fetchall()
        return [r["hl_funding_8h"] for r in rows]

    def open_positions(self, mode: Mode) -> list[Position]:
        table = _table_for_mode(mode)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM {table} WHERE closed_at IS NULL"
            ).fetchall()
        return [_row_to_position(r) for r in rows]

    def open_position_for(
        self, coin: str, mode: Mode
    ) -> Position | None:
        table = _table_for_mode(mode)
        with self._conn() as c:
            row = c.execute(
                f"SELECT * FROM {table} "
                "WHERE coin=? AND closed_at IS NULL LIMIT 1",
                (coin,),
            ).fetchone()
        return _row_to_position(row) if row else None

    def closed_in_last_day(
        self, mode: Mode, now: datetime | None = None
    ) -> list[Position]:
        now = now or datetime.utcnow()
        cutoff = (now - timedelta(days=1)).isoformat()
        table = _table_for_mode(mode)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM {table} "
                "WHERE closed_at IS NOT NULL AND closed_at >= ?",
                (cutoff,),
            ).fetchall()
        return [_row_to_position(r) for r in rows]

    def upsert_position(self, p: Position) -> None:
        table = _table_for_mode(p.mode)
        with self._conn() as c:
            c.execute(
                f"INSERT INTO {table}(id,coin,mode,hip3_size,ostium_size,"
                "hip3_entry_price,ostium_entry_price,notional_usd,"
                "entry_net_apr_pct,fees_paid_bps,funding_received_usd,"
                "opened_at,closed_at,exit_reason,realized_pnl_usd) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "hip3_size=excluded.hip3_size,"
                "ostium_size=excluded.ostium_size,"
                "fees_paid_bps=excluded.fees_paid_bps,"
                "funding_received_usd=excluded.funding_received_usd,"
                "closed_at=excluded.closed_at,"
                "exit_reason=excluded.exit_reason,"
                "realized_pnl_usd=excluded.realized_pnl_usd",
                (
                    p.id,
                    p.coin,
                    p.mode.value,
                    p.hip3_size,
                    p.ostium_size,
                    p.hip3_entry_price,
                    p.ostium_entry_price,
                    p.notional_usd,
                    p.entry_net_apr_pct,
                    p.fees_paid_bps,
                    p.funding_received_usd,
                    p.opened_at.isoformat(),
                    p.closed_at.isoformat() if p.closed_at else None,
                    p.exit_reason.value if p.exit_reason else None,
                    p.realized_pnl_usd,
                ),
            )

    def log_event(self, kind: str, data: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO events(timestamp,kind,data) VALUES (?,?,?)",
                (
                    datetime.utcnow().isoformat(),
                    kind,
                    json.dumps(data, default=str),
                ),
            )


def _row_to_position(r: sqlite3.Row) -> Position:
    return Position(
        id=r["id"],
        coin=r["coin"],
        mode=Mode(r["mode"]),
        hip3_size=r["hip3_size"],
        ostium_size=r["ostium_size"],
        hip3_entry_price=r["hip3_entry_price"],
        ostium_entry_price=r["ostium_entry_price"],
        notional_usd=r["notional_usd"],
        entry_net_apr_pct=r["entry_net_apr_pct"],
        fees_paid_bps=r["fees_paid_bps"],
        funding_received_usd=r["funding_received_usd"],
        opened_at=datetime.fromisoformat(r["opened_at"]),
        closed_at=(
            datetime.fromisoformat(r["closed_at"]) if r["closed_at"] else None
        ),
        exit_reason=(
            ExitReason(r["exit_reason"]) if r["exit_reason"] else None
        ),
        realized_pnl_usd=r["realized_pnl_usd"],
    )
```

- [ ] **Step 4.2: Replace `tests/test_db.py` with v1.1 tests**

```python
from __future__ import annotations

from datetime import datetime, timedelta

from hip3_bot.db import Database
from hip3_bot.models import ExitReason, Mode

from .conftest import make_position


def test_record_and_query_funding(cfg):
    db = Database(cfg.db_path)
    db.record_funding(
        coin="WTI",
        hl_funding_8h=0.0001,
        hl_apr_pct=10.95,
        hl_mark_price=80.0,
        open_interest=1_000_000,
        long_skew=0.7,
        hl_book_depth_usd=100_000,
        ostium_funding_8h=0.00005,
        ostium_apr_pct=5.475,
        ostium_mark_price=80.1,
        ostium_lp_usd=120_000,
        ostium_listed=True,
    )
    db.record_funding(
        coin="WTI",
        hl_funding_8h=0.0001,
        hl_apr_pct=10.95,
        hl_mark_price=80.0,
        open_interest=1_000_000,
        long_skew=0.7,
        hl_book_depth_usd=100_000,
    )
    assert len(db.recent_hl_funding("WTI", 10)) == 2


def test_simulated_trade_log_for_scanner_and_paper(cfg):
    db = Database(cfg.db_path)
    sc = make_position(coin="WTI", mode=Mode.SCANNER)
    sc.id = "sc1"
    pa = make_position(coin="GOLD", mode=Mode.PAPER)
    pa.id = "pa1"
    db.upsert_position(sc)
    db.upsert_position(pa)

    assert len(db.open_positions(Mode.SCANNER)) == 1
    assert len(db.open_positions(Mode.PAPER)) == 1
    assert db.open_positions(Mode.LIVE) == []


def test_trade_log_for_live(cfg):
    db = Database(cfg.db_path)
    p = make_position(coin="WTI", mode=Mode.LIVE)
    db.upsert_position(p)

    assert len(db.open_positions(Mode.LIVE)) == 1
    assert db.open_positions(Mode.SCANNER) == []


def test_open_position_for_filters_by_mode(cfg):
    db = Database(cfg.db_path)
    sc = make_position(coin="WTI", mode=Mode.SCANNER)
    sc.id = "sc1"
    db.upsert_position(sc)

    assert db.open_position_for("WTI", Mode.SCANNER) is not None
    assert db.open_position_for("WTI", Mode.LIVE) is None


def test_upsert_updates_existing(cfg):
    db = Database(cfg.db_path)
    p = make_position(mode=Mode.PAPER)
    db.upsert_position(p)
    p.funding_received_usd = 42.0
    db.upsert_position(p)
    fetched = db.open_position_for("WTI", Mode.PAPER)
    assert fetched is not None
    assert fetched.funding_received_usd == 42.0


def test_closed_position_exits_open_set(cfg):
    db = Database(cfg.db_path)
    p = make_position(mode=Mode.PAPER)
    p.closed_at = datetime.utcnow()
    p.exit_reason = ExitReason.OSTIUM_HOSTILE
    p.realized_pnl_usd = 50.0
    db.upsert_position(p)

    assert db.open_positions(Mode.PAPER) == []
    assert len(db.closed_in_last_day(Mode.PAPER)) == 1


def test_closed_in_last_day_filters_old(cfg):
    db = Database(cfg.db_path)
    p = make_position(mode=Mode.PAPER)
    p.closed_at = datetime.utcnow() - timedelta(days=2)
    p.exit_reason = ExitReason.MANUAL
    db.upsert_position(p)
    assert db.closed_in_last_day(Mode.PAPER) == []


def test_log_event_persists(cfg):
    db = Database(cfg.db_path)
    db.log_event("entry", {"coin": "WTI", "size": 1000})
    with db._conn() as c:
        rows = c.execute("SELECT kind, data FROM events").fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "entry"
```

- [ ] **Step 4.3: Run db tests — expect all pass**

```bash
pytest tests/test_db.py -v
```

- [ ] **Step 4.4: Commit**

```bash
git add hip3_bot/db.py tests/test_db.py
git commit -m "db: split trade_log + simulated_trade_log; net APR + Ostium fields in funding_history"
```

---

## Task 5: Ostium data feed

**Files:**
- Create: `hip3_bot/ostium_feed.py`
- Create: `tests/test_ostium_feed.py`

`OstiumDataFeed` mirrors `HLDataFeed`'s shape: a thin async wrapper around an injectable info client. The real client is built lazily from `web3.py` with the configured router contract; tests pass a `MagicMock`.

The exact contract method names depend on the deployed Ostium router. We define a thin protocol the feed expects, document the methods, and structure for ABI swap.

- [ ] **Step 5.1: Write failing tests in `tests/test_ostium_feed.py`**

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hip3_bot.ostium_feed import OstiumDataFeed


def _fake_client(market_payload):
    """`market_payload` is the dict the client returns for `coin`."""
    client = MagicMock()
    client.get_market.return_value = market_payload
    return client


@pytest.mark.asyncio
async def test_snapshot_listed_market(cfg):
    payload = {
        "listed": True,
        "funding_8h": 0.00005,
        "mark_price": 80.1,
        "lp_long_usd": 120_000.0,
    }
    feed = OstiumDataFeed(cfg, client=_fake_client(payload))
    snap = await feed.snapshot("WTI")
    assert snap.listed is True
    assert snap.funding_8h == pytest.approx(0.00005)
    assert snap.annualized_apr_pct == pytest.approx(
        0.00005 * 3 * 365 * 100
    )
    assert snap.mark_price == 80.1
    assert snap.lp_liquidity_usd == 120_000.0
    assert snap.coin == "WTI"


@pytest.mark.asyncio
async def test_snapshot_unlisted_returns_listed_false(cfg):
    feed = OstiumDataFeed(cfg, client=_fake_client(None))
    snap = await feed.snapshot("UNKNOWN")
    assert snap.listed is False
    assert snap.lp_liquidity_usd == 0.0
    assert snap.funding_8h == 0.0


@pytest.mark.asyncio
async def test_snapshot_handles_client_error(cfg):
    client = MagicMock()
    client.get_market.side_effect = RuntimeError("rpc down")
    feed = OstiumDataFeed(cfg, client=client)
    snap = await feed.snapshot("WTI")
    assert snap.listed is False  # fail-closed: never enter on errors
```

- [ ] **Step 5.2: Run — expect ImportError**

```bash
pytest tests/test_ostium_feed.py -v
```

- [ ] **Step 5.3: Implement `hip3_bot/ostium_feed.py`**

```python
"""Layer 1 — Ostium perp feed (Arbitrum, web3-based)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Protocol

from .config import Config
from .models import OstiumSnapshot

logger = logging.getLogger(__name__)


class OstiumClient(Protocol):
    """Thin protocol for Ostium router calls.

    The production implementation wraps `web3.py` against the Ostium
    router contract on Arbitrum. Each call resolves to the on-chain
    market struct for ``coin``: ``{"listed": bool, "funding_8h": float,
    "mark_price": float, "lp_long_usd": float}``.

    Tests pass a ``MagicMock`` shaped like this protocol.
    """

    def get_market(self, coin: str) -> dict | None: ...


class OstiumDataFeed:
    def __init__(self, cfg: Config, client: OstiumClient | None = None):
        self.cfg = cfg
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> OstiumClient:
        # Lazy import so unit tests don't require web3.
        from web3 import Web3

        from ._ostium_router import RouterClient  # see Step 5.4

        w3 = Web3(Web3.HTTPProvider(self.cfg.ostium_rpc_url))
        return RouterClient(w3, self.cfg.ostium_router_address)

    async def snapshot(self, coin: str) -> OstiumSnapshot:
        try:
            payload = await asyncio.to_thread(self._client.get_market, coin)
        except Exception:
            logger.exception("Ostium get_market failed for %s", coin)
            payload = None

        now = datetime.utcnow()
        if not payload or not payload.get("listed"):
            return OstiumSnapshot(
                coin=coin,
                listed=False,
                funding_8h=0.0,
                annualized_apr_pct=0.0,
                mark_price=0.0,
                lp_liquidity_usd=0.0,
                timestamp=now,
            )

        funding_8h = float(payload.get("funding_8h", 0.0))
        return OstiumSnapshot(
            coin=coin,
            listed=True,
            funding_8h=funding_8h,
            annualized_apr_pct=funding_8h * 3 * 365 * 100,
            mark_price=float(payload.get("mark_price", 0.0)),
            lp_liquidity_usd=float(payload.get("lp_long_usd", 0.0)),
            timestamp=now,
        )
```

- [ ] **Step 5.4: Stub the production router client `hip3_bot/_ostium_router.py`**

```python
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
```

- [ ] **Step 5.5: Run — expect 3 passed**

```bash
pytest tests/test_ostium_feed.py -v
```

- [ ] **Step 5.6: Commit**

```bash
git add hip3_bot/ostium_feed.py hip3_bot/_ostium_router.py tests/test_ostium_feed.py
git commit -m "ostium_feed: web3-based Ostium snapshot with fail-closed missing/error handling"
```

---

## Task 6: Signals — net APR + 6-condition entry gate

**Files:**
- Modify: `hip3_bot/signals.py`
- Modify: `tests/test_signals.py`

`evaluate_entry` now takes both HL and Ostium snapshots and uses net APR.

- [ ] **Step 6.1: Replace `hip3_bot/signals.py`**

```python
"""Layer 2 — net APR + 6-condition entry gate + fractional Kelly sizing."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .config import Config
from .models import FundingSnapshot, OstiumSnapshot


def annualize_funding(funding_8h: float) -> float:
    """Convert 8-hour funding rate to annualized APR (percent)."""
    return funding_8h * 3 * 365 * 100


def net_apr_pct(
    hl: FundingSnapshot, ostium: OstiumSnapshot
) -> float:
    """Spec § Step 02: net APR = HL APR − Ostium APR."""
    return hl.annualized_apr_pct - ostium.annualized_apr_pct


def min_hold_hours(net_apr_pct_value: float, fee_drag_bps: float) -> float:
    """Minimum hold (hours) to recoup round-trip fees at the given net APR."""
    if net_apr_pct_value <= 0:
        return float("inf")
    return (fee_drag_bps / net_apr_pct_value) * 8760 / 100


def basis_pct(hl: FundingSnapshot, ostium: OstiumSnapshot) -> float:
    if hl.mark_price <= 0:
        return float("inf")
    return abs(ostium.mark_price - hl.mark_price) / hl.mark_price


@dataclass
class EntryDecision:
    enter: bool
    reasons: list[str]
    hl_snapshot: FundingSnapshot
    ostium_snapshot: OstiumSnapshot
    net_apr_pct: float
    consecutive_positive: int


def evaluate_entry(
    hl: FundingSnapshot,
    ostium: OstiumSnapshot,
    recent_hl_funding_8h: list[float],
    cfg: Config,
) -> EntryDecision:
    """Six-condition entry gate from spec v1.1 § Step 03."""
    reasons: list[str] = []
    consecutive = _count_leading_positive(recent_hl_funding_8h)
    net = net_apr_pct(hl, ostium)

    # 1) Net APR > threshold
    if net <= cfg.min_entry_apr_pct:
        reasons.append(
            f"net APR {net:.1f}% <= {cfg.min_entry_apr_pct:.1f}%"
        )
    # 2) Consecutive positive HL funding
    if consecutive < cfg.consecutive_positive_funding:
        reasons.append(
            f"{consecutive} consecutive positive HL funding intervals "
            f"(need {cfg.consecutive_positive_funding})"
        )
    # 3) HL OI long skew
    if hl.long_skew <= cfg.long_skew_threshold:
        reasons.append(
            f"long skew {hl.long_skew:.2f} <= "
            f"{cfg.long_skew_threshold:.2f}"
        )
    # 4) HL book depth
    if hl.book_depth_usd < cfg.min_book_depth_usd:
        reasons.append(
            f"HL book depth ${hl.book_depth_usd:,.0f} < "
            f"${cfg.min_book_depth_usd:,.0f}"
        )
    # 5) Ostium listed + LP liquidity
    if not ostium.listed:
        reasons.append(f"Ostium does not list {hl.coin}")
    elif ostium.lp_liquidity_usd < cfg.min_ostium_lp_usd:
        reasons.append(
            f"Ostium LP ${ostium.lp_liquidity_usd:,.0f} < "
            f"${cfg.min_ostium_lp_usd:,.0f}"
        )
    # 6) Basis check
    if ostium.listed:
        b = basis_pct(hl, ostium)
        if b >= cfg.max_basis_pct:
            reasons.append(
                f"basis {b:.4f} >= {cfg.max_basis_pct:.4f} "
                f"({b * 10_000:.0f} bps cap)"
            )

    return EntryDecision(
        enter=not reasons,
        reasons=reasons,
        hl_snapshot=hl,
        ostium_snapshot=ostium,
        net_apr_pct=net,
        consecutive_positive=consecutive,
    )


def _count_leading_positive(history: list[float]) -> int:
    n = 0
    for f in history:
        if f > 0:
            n += 1
        else:
            break
    return n


def kelly_size_usd(
    net_apr_pct_value: float,
    hl_funding_history_8h: list[float],
    capital_usd: float,
    cfg: Config,
    market_age_days: int | None = None,
) -> float:
    """Fractional Kelly notional in USD using NET APR as the edge."""
    if net_apr_pct_value <= cfg.min_entry_apr_pct or capital_usd <= 0:
        return 0.0

    edge = net_apr_pct_value / 100.0
    variance = _annualized_variance(hl_funding_history_8h)
    if variance <= 0:
        kelly_f = cfg.max_position_pct / cfg.kelly_fraction
    else:
        kelly_f = edge / variance

    fraction = min(kelly_f * cfg.kelly_fraction, cfg.max_position_pct)
    if market_age_days is not None and market_age_days < 30:
        fraction *= max(0.25, market_age_days / 30.0)
    return max(0.0, fraction) * capital_usd


def _annualized_variance(history: list[float]) -> float:
    if len(history) < 2:
        return 0.0
    annualized = [annualize_funding(f) / 100.0 for f in history]
    return statistics.pvariance(annualized)
```

- [ ] **Step 6.2: Replace `tests/test_signals.py`**

```python
from __future__ import annotations

import math

from hip3_bot.signals import (
    annualize_funding,
    basis_pct,
    evaluate_entry,
    kelly_size_usd,
    min_hold_hours,
    net_apr_pct,
)

from .conftest import make_ostium_snapshot, make_snapshot


def test_annualize_funding_matches_spec_formula():
    assert annualize_funding(0.0001) == 0.0001 * 3 * 365 * 100


def test_net_apr_subtracts_ostium():
    hl = make_snapshot(apr_pct=25.0)
    os = make_ostium_snapshot(apr_pct=5.0)
    assert net_apr_pct(hl, os) == 20.0


def test_min_hold_hours_at_20_net_apr_28bps_is_about_122h():
    # 28 / 20 * 8760 / 100 = 122.64 hours
    assert math.isclose(min_hold_hours(20.0, 28.0), 122.64, abs_tol=0.01)


def test_basis_pct():
    hl = make_snapshot()
    os = make_ostium_snapshot(mark_price=80.4)
    assert basis_pct(hl, os) == pytest_approx(0.005)


def test_entry_gate_passes_all_six_conditions(cfg):
    hl = make_snapshot(apr_pct=25.0, long_skew=0.7, book_depth_usd=100_000)
    os = make_ostium_snapshot(
        apr_pct=2.0, lp_liquidity_usd=100_000, mark_price=80.0
    )
    history = [0.0001, 0.0001, 0.0001, 0.0001]
    d = evaluate_entry(hl, os, history, cfg)
    assert d.enter is True
    assert d.reasons == []
    assert d.net_apr_pct == 23.0


def test_entry_gate_blocks_low_net_apr(cfg):
    hl = make_snapshot(apr_pct=25.0)
    os = make_ostium_snapshot(apr_pct=10.0)  # net = 15%, below 20
    d = evaluate_entry(hl, os, [0.0001] * 4, cfg)
    assert d.enter is False
    assert any("net APR" in r for r in d.reasons)


def test_entry_gate_blocks_unlisted_ostium(cfg):
    hl = make_snapshot(apr_pct=25.0)
    os = make_ostium_snapshot(listed=False)
    d = evaluate_entry(hl, os, [0.0001] * 4, cfg)
    assert d.enter is False
    assert any("does not list" in r for r in d.reasons)


def test_entry_gate_blocks_thin_ostium_lp(cfg):
    hl = make_snapshot(apr_pct=25.0)
    os = make_ostium_snapshot(apr_pct=2.0, lp_liquidity_usd=30_000)
    d = evaluate_entry(hl, os, [0.0001] * 4, cfg)
    assert d.enter is False
    assert any("LP" in r for r in d.reasons)


def test_entry_gate_blocks_wide_basis(cfg):
    hl = make_snapshot(apr_pct=25.0)
    # 80 vs 81 → 1.25% basis, exceeds 0.5% cap
    os = make_ostium_snapshot(apr_pct=2.0, mark_price=81.0)
    d = evaluate_entry(hl, os, [0.0001] * 4, cfg)
    assert d.enter is False
    assert any("basis" in r for r in d.reasons)


def test_entry_gate_blocks_low_skew(cfg):
    hl = make_snapshot(apr_pct=25.0, long_skew=0.55)
    os = make_ostium_snapshot(apr_pct=2.0)
    d = evaluate_entry(hl, os, [0.0001] * 4, cfg)
    assert d.enter is False


def test_entry_gate_blocks_thin_hl_book(cfg):
    hl = make_snapshot(apr_pct=25.0, book_depth_usd=30_000)
    os = make_ostium_snapshot(apr_pct=2.0)
    d = evaluate_entry(hl, os, [0.0001] * 4, cfg)
    assert d.enter is False


def test_entry_gate_requires_consecutive_positive_funding(cfg):
    hl = make_snapshot(apr_pct=25.0)
    os = make_ostium_snapshot(apr_pct=2.0)
    d = evaluate_entry(hl, os, [0.0001, -0.0001, 0.0001], cfg)
    assert d.enter is False
    assert d.consecutive_positive == 1


def test_kelly_size_capped_at_max_pct(cfg):
    history = [0.0001] * 10
    size = kelly_size_usd(50.0, history, 100_000, cfg)
    assert size <= 100_000 * cfg.max_position_pct + 1e-6


def test_kelly_size_zero_below_threshold(cfg):
    assert kelly_size_usd(15.0, [0.0001] * 5, 100_000, cfg) == 0.0


def test_kelly_size_haircut_for_new_market(cfg):
    big = kelly_size_usd(50.0, [0.0001] * 5, 100_000, cfg, market_age_days=60)
    young = kelly_size_usd(50.0, [0.0001] * 5, 100_000, cfg, market_age_days=10)
    assert young < big


# Local approx wrapper to keep this file self-contained.
def pytest_approx(value, abs_tol: float = 1e-9):
    import pytest

    return pytest.approx(value, abs=abs_tol)
```

- [ ] **Step 6.3: Run — expect all signals tests pass**

```bash
pytest tests/test_signals.py -v
```

- [ ] **Step 6.4: Commit**

```bash
git add hip3_bot/signals.py tests/test_signals.py
git commit -m "signals: net APR + 6-condition entry gate (Ostium listing, LP, basis)"
```

---

## Task 7: Risk — P1b Ostium-hostile exit + Ostium snapshot in `evaluate_exit`

**Files:**
- Modify: `hip3_bot/risk.py`
- Modify: `tests/test_risk.py`

`evaluate_exit` now takes `OstiumSnapshot`. P1b fires after P1: Ostium long-side funding > 50% of HL short-side funding.

- [ ] **Step 7.1: Replace `hip3_bot/risk.py`**

```python
"""Layer 4 — exit triggers (P0 → P1 → P1b → P2) + delta drift."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .models import ExitReason, FundingSnapshot, OstiumSnapshot, Position


@dataclass
class ExitDecision:
    should_exit: bool
    reason: ExitReason | None
    note: str = ""


def evaluate_exit(
    p: Position,
    hl: FundingSnapshot,
    ostium: OstiumSnapshot,
    deployer_halted: bool,
    cfg: Config,
) -> ExitDecision:
    """Priority-ordered exit check P0 → P1 → P1b → P2."""
    if deployer_halted:
        return ExitDecision(
            True,
            ExitReason.DEPLOYER_HALT,
            "deployer halt detected — emergency exit",
        )
    if hl.funding_8h < 0:
        return ExitDecision(
            True,
            ExitReason.FUNDING_FLIP,
            f"HL funding flipped negative: {hl.funding_8h:.6f}",
        )
    if _ostium_hostile(hl, ostium, cfg):
        return ExitDecision(
            True,
            ExitReason.OSTIUM_HOSTILE,
            "Ostium long funding > "
            f"{cfg.ostium_hostile_funding_ratio:.0%} of HL short funding",
        )
    net = hl.annualized_apr_pct - ostium.annualized_apr_pct
    if net < cfg.exit_apr_pct:
        return ExitDecision(
            True,
            ExitReason.APR_DECAY,
            f"net APR decayed to {net:.1f}%",
        )
    return ExitDecision(False, None)


def _ostium_hostile(
    hl: FundingSnapshot,
    ostium: OstiumSnapshot,
    cfg: Config,
) -> bool:
    """Spec § P1b: Ostium long > ratio × HL short funding."""
    if hl.funding_8h <= 0:
        # Without HL short yield to compare against, treat funding flip
        # as the primary trigger; P1b doesn't apply.
        return False
    return ostium.funding_8h > cfg.ostium_hostile_funding_ratio * hl.funding_8h


def delta_drift(p: Position, hip3_mark: float, ostium_mark: float) -> float:
    """Net delta as a fraction of position notional (+long / -short)."""
    if p.notional_usd <= 0:
        return 0.0
    hip3_value = p.hip3_size * hip3_mark
    hedge_value = p.ostium_size * ostium_mark
    return (hip3_value + hedge_value) / p.notional_usd


def needs_rebalance(drift_frac: float, cfg: Config) -> bool:
    return abs(drift_frac) > cfg.delta_drift_threshold


def target_hedge_size(p: Position, ostium_mark: float) -> float:
    """Ostium size that neutralizes the HIP-3 leg at the current Ostium mark."""
    if ostium_mark <= 0:
        return p.ostium_size
    target_notional = abs(p.hip3_size) * p.hip3_entry_price
    return target_notional / ostium_mark


def realized_apr_pct(p: Position, held_hours: float) -> float:
    if held_hours <= 0 or p.notional_usd <= 0:
        return 0.0
    fee_drag_usd = p.fees_paid_bps / 10_000.0 * p.notional_usd
    net_usd = p.funding_received_usd - fee_drag_usd
    return (net_usd / p.notional_usd) * (8760.0 / held_hours) * 100
```

- [ ] **Step 7.2: Replace `tests/test_risk.py`**

```python
from __future__ import annotations

from hip3_bot.models import ExitReason
from hip3_bot.risk import (
    delta_drift,
    evaluate_exit,
    needs_rebalance,
    realized_apr_pct,
    target_hedge_size,
)

from .conftest import make_ostium_snapshot, make_position, make_snapshot


def _hl(funding_8h: float, apr: float):
    snap = make_snapshot(apr_pct=apr)
    snap.funding_8h = funding_8h
    return snap


def _os(funding_8h: float, apr: float = 0.0):
    snap = make_ostium_snapshot(apr_pct=apr)
    snap.funding_8h = funding_8h
    return snap


def test_p0_deployer_halt_takes_priority(cfg):
    d = evaluate_exit(
        make_position(),
        _hl(0.0001, 25.0),
        _os(0.00001, 1.0),
        deployer_halted=True,
        cfg=cfg,
    )
    assert d.should_exit
    assert d.reason == ExitReason.DEPLOYER_HALT


def test_p1_funding_flip_negative(cfg):
    d = evaluate_exit(
        make_position(),
        _hl(-0.0001, -10.0),
        _os(0.00001, 1.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert d.should_exit
    assert d.reason == ExitReason.FUNDING_FLIP


def test_p1b_ostium_hostile_when_more_than_50pct_of_hl(cfg):
    # HL pays you 0.0001/8h short; Ostium charges 0.00006/8h long → 60% of HL.
    d = evaluate_exit(
        make_position(),
        _hl(0.0001, 25.0),
        _os(0.00006, 16.4),
        deployer_halted=False,
        cfg=cfg,
    )
    assert d.should_exit
    assert d.reason == ExitReason.OSTIUM_HOSTILE


def test_p1b_does_not_trigger_when_under_50pct(cfg):
    d = evaluate_exit(
        make_position(),
        _hl(0.0001, 25.0),
        _os(0.00004, 11.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert not d.should_exit


def test_p2_apr_decay_below_threshold(cfg):
    d = evaluate_exit(
        make_position(),
        _hl(0.0000001, 5.0),
        _os(0.00, 0.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert d.should_exit
    assert d.reason == ExitReason.APR_DECAY


def test_no_exit_when_healthy(cfg):
    d = evaluate_exit(
        make_position(),
        _hl(0.0001, 25.0),
        _os(0.00001, 1.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert not d.should_exit


def test_delta_drift_neutral_at_entry_marks():
    p = make_position()
    assert abs(delta_drift(p, hip3_mark=80.0, ostium_mark=80.0)) < 1e-9


def test_delta_drift_negative_when_hip3_outpaces_hedge():
    p = make_position()
    drift = delta_drift(p, hip3_mark=88.0, ostium_mark=80.0)
    assert drift < 0


def test_needs_rebalance_threshold(cfg):
    assert needs_rebalance(0.06, cfg)
    assert not needs_rebalance(0.04, cfg)


def test_target_hedge_size_neutralizes_at_same_mark():
    p = make_position()
    assert abs(target_hedge_size(p, ostium_mark=80.0) - 125.0) < 1e-9


def test_realized_apr_pct_zero_for_zero_hold():
    assert realized_apr_pct(make_position(), 0) == 0.0
```

- [ ] **Step 7.3: Run — expect all risk tests pass**

```bash
pytest tests/test_risk.py -v
```

- [ ] **Step 7.4: Commit**

```bash
git add hip3_bot/risk.py tests/test_risk.py
git commit -m "risk: P1b Ostium-hostile exit; evaluate_exit takes both snapshots"
```

---

## Task 8: Ostium hedge adapter; remove Paper/HLNative/IBKR

**Files:**
- Create: `hip3_bot/ostium_adapter.py`
- Modify: `hip3_bot/execution.py` (remove obsolete adapters; OrderRouter accepts only an OstiumHedgeAdapter, scanner-mode no-ops orders)
- Modify: `tests/test_execution.py`

- [ ] **Step 8.1: Write `hip3_bot/ostium_adapter.py`**

```python
"""Layer 3 — Ostium long-leg hedge adapter (Arbitrum web3)."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class OstiumHedgeAdapter:
    """Long-only hedge against Ostium LP.

    `client` is the same OstiumClient protocol as the data feed but with
    additional ``open_long(coin, notional_usd, max_slippage_bps)`` and
    ``close_long(coin, size)`` methods. The production client wraps the
    Ostium router contract on Arbitrum; tests pass a MagicMock.
    """

    def __init__(self, client, max_slippage_bps: float):
        self._client = client
        self._max_slippage_bps = max_slippage_bps

    async def buy(self, coin: str, notional_usd: float):
        from .execution import Fill

        try:
            res = await asyncio.to_thread(
                self._client.open_long,
                coin,
                notional_usd,
                self._max_slippage_bps,
            )
        except Exception as e:
            logger.exception("Ostium open_long failed")
            # Spec § Trade Execution: retry once after 2s on oracle deviation.
            if "oracle" in str(e).lower():
                await asyncio.sleep(2.0)
                res = await asyncio.to_thread(
                    self._client.open_long,
                    coin,
                    notional_usd,
                    self._max_slippage_bps,
                )
            else:
                raise
        return Fill(
            price=float(res["fill_price"]),
            size=float(res["size"]),
            fees_paid_usd=float(res.get("fees_usd", 0.0)),
        )

    async def sell(self, coin: str, size: float):
        from .execution import Fill

        res = await asyncio.to_thread(self._client.close_long, coin, size)
        return Fill(
            price=float(res["fill_price"]),
            size=float(res["size"]),
            fees_paid_usd=float(res.get("fees_usd", 0.0)),
        )
```

- [ ] **Step 8.2: Replace `hip3_bot/execution.py` (drop obsolete adapters; mode-aware OrderRouter)**

```python
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
            self._ostium.sell(p.coin, abs(p.ostium_size)),
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
        return await self._ostium.sell(p.coin, -delta)

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
                await self._ostium.sell(coin, leg_b.size)
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
```

- [ ] **Step 8.3: Replace `tests/test_execution.py`**

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hip3_bot.execution import (
    Fill,
    OrderRouter,
    _parse_hl_fill,
    _resting_oid,
)
from hip3_bot.models import Mode
from hip3_bot.ostium_adapter import OstiumHedgeAdapter

from .conftest import make_position


def test_parse_hl_fill_success():
    result = {
        "status": "ok",
        "response": {
            "data": {
                "statuses": [{"filled": {"avgPx": "80.5", "totalSz": "10"}}]
            }
        },
    }
    fill = _parse_hl_fill(result, fallback_price=0.0, fallback_size=0.0)
    assert fill.price == 80.5
    assert fill.size == 10.0


def test_parse_hl_fill_falls_back_on_error():
    fill = _parse_hl_fill(
        {"status": "err"}, fallback_price=80.0, fallback_size=10.0
    )
    assert fill.price == 80.0
    assert fill.size == 10.0


def test_resting_oid_extracts_oid():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [{"resting": {"oid": 42}}]}},
    }
    assert _resting_oid(result) == 42


def test_resting_oid_returns_none_when_filled():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [{"filled": {"avgPx": "1"}}]}},
    }
    assert _resting_oid(result) is None


def test_fill_dataclass_defaults():
    f = Fill(price=10.0, size=5.0)
    assert f.fees_paid_usd == 0.0


def _ostium_adapter_returning(price: float, size: float) -> OstiumHedgeAdapter:
    client = MagicMock()
    client.open_long.return_value = {
        "fill_price": price,
        "size": size,
        "fees_usd": 0.0,
    }
    client.close_long.return_value = {
        "fill_price": price,
        "size": size,
        "fees_usd": 0.0,
    }
    return OstiumHedgeAdapter(client, max_slippage_bps=30.0)


@pytest.mark.asyncio
async def test_open_delta_neutral_scanner_creates_synthetic_position(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    pos = await router.open_delta_neutral(
        "WTI", notional_usd=8_000.0, entry_net_apr_pct=20.0
    )
    assert pos is not None
    assert pos.mode is Mode.SCANNER
    assert pos.hip3_size < 0
    assert pos.ostium_size > 0
    assert abs(abs(pos.hip3_size) - pos.ostium_size) < 1e-9


@pytest.mark.asyncio
async def test_open_delta_neutral_returns_none_when_no_mid(cfg):
    info = MagicMock()
    info.all_mids.return_value = {}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    assert await router.open_delta_neutral("WTI", 8_000.0, 20.0) is None


@pytest.mark.asyncio
async def test_close_delta_neutral_scanner_is_noop(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    pos = await router.open_delta_neutral("WTI", 8_000.0, 20.0)
    assert pos is not None
    await router.close_delta_neutral(pos)


@pytest.mark.asyncio
async def test_rebalance_hedge_scanner_returns_fill(cfg):
    info = MagicMock()
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    p = make_position(ostium_size=125.0, mode=Mode.SCANNER)
    fill = await router.rebalance_hedge(p, target_size=120.0)
    assert fill is not None
    assert fill.size == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_rebalance_hedge_no_op_when_target_matches(cfg):
    info = MagicMock()
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    p = make_position(ostium_size=125.0, mode=Mode.SCANNER)
    assert await router.rebalance_hedge(p, target_size=125.0) is None


@pytest.mark.asyncio
async def test_ostium_adapter_buy_calls_client():
    adapter = _ostium_adapter_returning(price=80.0, size=100.0)
    fill = await adapter.buy("WTI", 8_000.0)
    assert fill.price == 80.0
    assert fill.size == 100.0
```

- [ ] **Step 8.4: Run — expect all execution tests pass**

```bash
pytest tests/test_execution.py tests/test_ostium_feed.py -v
```

- [ ] **Step 8.5: Commit**

```bash
git add hip3_bot/ostium_adapter.py hip3_bot/execution.py tests/test_execution.py
git commit -m "execution: drop Paper/HLNative/IBKR; OrderRouter takes Ostium adapter only; mode-aware"
```

---

## Task 9: Bot orchestrator — Ostium feed wiring + mode-aware storage + DRY-RUN tagging

**Files:**
- Modify: `hip3_bot/alerts.py` (mode-prefix tagging)
- Modify: `hip3_bot/bot.py`

- [ ] **Step 9.1: Update `hip3_bot/alerts.py`**

```python
"""Telegram alerter. Falls back to logging when not configured."""
from __future__ import annotations

import logging

from .config import Config
from .models import Mode

logger = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._bot = None
        if cfg.telegram_bot_token and cfg.telegram_chat_id:
            try:
                from telegram import Bot

                self._bot = Bot(token=cfg.telegram_bot_token)
            except ImportError:
                logger.warning("python-telegram-bot not installed")

    @property
    def _prefix(self) -> str:
        if self.cfg.mode in (Mode.SCANNER.value, Mode.PAPER.value):
            return "[DRY-RUN] "
        return ""

    async def send(self, text: str) -> None:
        msg = f"{self._prefix}{text}"
        if not self._bot:
            logger.info("[alert] %s", msg)
            return
        try:
            await self._bot.send_message(
                chat_id=self.cfg.telegram_chat_id,
                text=msg,
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("telegram send failed; text=%s", msg)
```

- [ ] **Step 9.2: Replace `hip3_bot/bot.py`**

```python
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
        # Build a real Ostium client — same client class used by the feed
        # plus order-placement methods. Phase 2 wires actual ABIs.
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
```

- [ ] **Step 9.3: Smoke-import**

```bash
python -c "from hip3_bot.bot import Bot; print('ok')"
```

- [ ] **Step 9.4: Commit**

```bash
git add hip3_bot/alerts.py hip3_bot/bot.py
git commit -m "bot: wire OstiumDataFeed + OstiumHedgeAdapter; mode-aware storage; [DRY-RUN] tagging"
```

---

## Task 10: `main.py` — `--confirm-live` CLI gate + mode banner

**Files:**
- Modify: `hip3_bot/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 10.1: Write failing tests**

```python
# tests/test_main.py
from __future__ import annotations

import os

import pytest

from hip3_bot.main import require_confirm_live


def test_require_confirm_live_passes_for_scanner():
    require_confirm_live("scanner", confirm=False)


def test_require_confirm_live_passes_for_paper():
    require_confirm_live("paper", confirm=False)


def test_require_confirm_live_fails_without_flag():
    with pytest.raises(SystemExit):
        require_confirm_live("live", confirm=False)


def test_require_confirm_live_passes_with_flag():
    require_confirm_live("live", confirm=True)
```

- [ ] **Step 10.2: Run — expect ImportError**

- [ ] **Step 10.3: Replace `hip3_bot/main.py`**

```python
"""Process entry point with --confirm-live safeguard."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .bot import Bot
from .config import Config


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def require_confirm_live(mode: str, confirm: bool) -> None:
    """Refuse to start `live` mode without explicit operator confirmation.

    Spec § Risk Matrix: 'Operator launches with wrong mode flag' — loud
    startup banner + explicit `--confirm-live` CLI flag.
    """
    if mode == "live" and not confirm:
        sys.stderr.write(
            "ERROR: mode=live requires --confirm-live to start. "
            "Aborting to prevent accidental capital deployment.\n"
        )
        raise SystemExit(2)


def _print_banner(cfg: Config) -> None:
    bar = "=" * 60
    print(bar, flush=True)
    print(f"  hip3-funding-bot  mode = {cfg.mode.upper()}", flush=True)
    print(
        f"  HL testnet={cfg.hl_use_testnet}  "
        f"Ostium testnet={cfg.ostium_use_testnet}",
        flush=True,
    )
    print(f"  fee_drag={cfg.round_trip_fee_bps:.0f} bps  "
          f"min net APR={cfg.min_entry_apr_pct:.0f}%", flush=True)
    print(bar, flush=True)


async def _run(confirm_live: bool) -> None:
    cfg = Config.from_env()
    require_confirm_live(cfg.mode, confirm_live)
    _setup_logging(cfg.log_level)
    _print_banner(cfg)

    bot = Bot(cfg)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        stop.set()
        bot.feed.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):
            pass

    run_task = asyncio.create_task(bot.run())
    stop_task = asyncio.create_task(stop.wait())
    _, pending = await asyncio.wait(
        {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()


def cli() -> None:
    parser = argparse.ArgumentParser(prog="hip3-bot")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required when MODE=live. Acknowledges live capital deployment.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.confirm_live))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 10.4: Run — expect 4 passed**

```bash
pytest tests/test_main.py -v
```

- [ ] **Step 10.5: Commit**

```bash
git add hip3_bot/main.py tests/test_main.py
git commit -m "main: --confirm-live gate + mode banner"
```

---

## Task 11: Reporting — mode-aware

**Files:**
- Modify: `hip3_bot/reporting.py`
- Modify: `tests/test_reporting.py`

- [ ] **Step 11.1: Replace `hip3_bot/reporting.py`**

```python
"""Layer 5 — daily realized vs projected APR report."""
from __future__ import annotations

from datetime import datetime

from .db import Database
from .models import Mode
from .risk import realized_apr_pct


def daily_report(
    db: Database, mode: Mode, now: datetime | None = None
) -> str:
    now = now or datetime.utcnow()
    open_positions = db.open_positions(mode)
    closed = db.closed_in_last_day(mode, now)

    lines = [
        f"📊 *Daily Report* ({mode.value}) — {now:%Y-%m-%d %H:%M}Z"
    ]
    lines.append(f"Open positions: {len(open_positions)}")

    for p in open_positions:
        held_h = (now - p.opened_at).total_seconds() / 3600.0
        realized = realized_apr_pct(p, held_h)
        lines.append(
            f"  • {p.coin}: ${p.notional_usd:,.0f}  "
            f"projected {p.entry_net_apr_pct:.1f}%  "
            f"realized {realized:.1f}%  "
            f"held {held_h:.1f}h"
        )

    if closed:
        total_pnl = sum(p.realized_pnl_usd for p in closed)
        lines.append("")
        lines.append(f"Closed (24h): {len(closed)}, total ${total_pnl:,.2f}")
        for p in closed:
            lines.append(
                f"  • {p.coin}: ${p.realized_pnl_usd:+,.2f}  "
                f"reason {p.exit_reason.value if p.exit_reason else '-'}"
            )
    return "\n".join(lines)
```

- [ ] **Step 11.2: Replace `tests/test_reporting.py`**

```python
from __future__ import annotations

from datetime import datetime

from hip3_bot.db import Database
from hip3_bot.models import ExitReason, Mode
from hip3_bot.reporting import daily_report

from .conftest import make_position


def test_daily_report_no_positions(cfg):
    db = Database(cfg.db_path)
    report = daily_report(
        db, Mode.SCANNER, now=datetime(2026, 5, 10, 12, 0)
    )
    assert "Daily Report (scanner)" in report
    assert "Open positions: 0" in report


def test_daily_report_lists_open_position(cfg):
    db = Database(cfg.db_path)
    p = make_position(mode=Mode.PAPER)
    p.opened_at = datetime(2026, 5, 10, 0, 0)
    db.upsert_position(p)
    report = daily_report(
        db, Mode.PAPER, now=datetime(2026, 5, 10, 12, 0)
    )
    assert "WTI" in report
    assert "$10,000" in report


def test_daily_report_summarizes_closed(cfg):
    db = Database(cfg.db_path)
    p = make_position(mode=Mode.PAPER)
    p.closed_at = datetime.utcnow()
    p.exit_reason = ExitReason.OSTIUM_HOSTILE
    p.realized_pnl_usd = 42.0
    db.upsert_position(p)
    report = daily_report(db, Mode.PAPER)
    assert "Closed (24h): 1" in report
    assert "$42" in report
    assert "P1b_ostium_hostile" in report


def test_daily_report_isolated_per_mode(cfg):
    db = Database(cfg.db_path)
    sc = make_position(coin="WTI", mode=Mode.SCANNER)
    sc.id = "sc1"
    db.upsert_position(sc)
    paper_report = daily_report(db, Mode.PAPER)
    assert "Open positions: 0" in paper_report
```

- [ ] **Step 11.3: Run — expect 4 passed**

```bash
pytest tests/test_reporting.py -v
```

- [ ] **Step 11.4: Commit**

```bash
git add hip3_bot/reporting.py tests/test_reporting.py
git commit -m "reporting: mode-aware daily report (separate trade vs sim tables)"
```

---

## Task 12: Full suite verification + plan provenance link

**Files:**
- (final integration)

- [ ] **Step 12.1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all green (count will be ~55+).

- [ ] **Step 12.2: Smoke-run scanner mode for 30s**

```bash
MODE=scanner DRY_RUN=true python -m hip3_bot.main
# Ctrl+C after ~30s
```

Expected:
- Mode banner prints once.
- One Telegram-or-log alert: `[DRY-RUN] 🤖 hip3-bot starting (mode=scanner, ...)`.
- `funding_history` rows inserted for HIP-3 markets.
- No tracebacks.

- [ ] **Step 12.3: Verify SQLite split**

```bash
sqlite3 hip3_bot.db ".tables"
```

Expected: `events  funding_history  simulated_trade_log  trade_log` — both trade tables present.

- [ ] **Step 12.4: Refuse-to-start `live` test**

```bash
MODE=live python -m hip3_bot.main 2>&1 | head -3
```

Expected: `ERROR: mode=live requires --confirm-live to start.`

- [ ] **Step 12.5: Update v1.0 plan to reference v1.1 plan**

Modify the top of `docs/superpowers/plans/2026-05-09-hip3-funding-bot.md` to add a one-line provenance note immediately after the H1:

```markdown
> **Superseded by [2026-05-10-hip3-funding-bot-v1.1-migration.md](2026-05-10-hip3-funding-bot-v1.1-migration.md)** for spec v1.1 (Ostium hedge, 6-condition gate, runtime modes).
```

- [ ] **Step 12.6: Final commit**

```bash
git add docs/superpowers/plans/2026-05-09-hip3-funding-bot.md
git commit -m "docs: link v1.0 plan to v1.1 migration plan"
```

---

## Self-Review Checklist

**Spec coverage (v1.1):**
- ✅ Ostium feed: Task 5
- ✅ Ostium adapter: Task 8
- ✅ Net APR + 6-condition gate: Task 6
- ✅ 28 bps fee drag default: Task 2
- ✅ Mode flag + table split: Tasks 2, 3, 4
- ✅ `--confirm-live` CLI: Task 10
- ✅ `[DRY-RUN]` Telegram tagging: Task 9
- ✅ P1b Ostium-hostile exit: Task 7
- ✅ Bot orchestrator wiring: Task 9
- ✅ CLAUDE.md refresh: Task 1
- ✅ Reporting mode-aware: Task 11
- ✅ Verification: Task 12

**Phase 3 deferrals (called out, not in this plan):**
- Pre-funded margin manager (50/50 USDC across HL + Ostium) — Phase 3 work
- Live Ostium ABI integration in `_ostium_router.py` — Phase 3 work; current stub is fail-closed
- Cross-venue capital auto-rebalance — Phase 4

**Placeholder scan:** No "TBD"/"implement later"/"similar to". Every code step has complete code.

**Type/name consistency:** `Mode`, `OstiumSnapshot`, `OstiumDataFeed`, `OstiumHedgeAdapter`, `OstiumClient`, `entry_net_apr_pct`, `ostium_size`, `OSTIUM_HOSTILE`, `evaluate_entry(hl, ostium, history, cfg)`, `evaluate_exit(p, hl, ostium, deployer_halted, cfg)`, `daily_report(db, mode, now=None)` — all consistent across tasks.
