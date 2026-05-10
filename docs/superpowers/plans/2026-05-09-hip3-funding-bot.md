# HIP-3 Funding Rate Farming Bot Implementation Plan

> **Superseded by [2026-05-10-hip3-funding-bot-v1.1-migration.md](2026-05-10-hip3-funding-bot-v1.1-migration.md)** for spec v1.1 (Ostium hedge, 6-condition gate, runtime modes).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python 3.11+ delta-neutral funding rate farming bot for Hyperliquid HIP-3 perpetuals — scanner first, then paper trading, then live with hedge.

**Architecture:** Five-layer async package. Layer 1 (`data_feed`) polls Hyperliquid for funding/mark/OI; Layer 2 (`signals`) normalizes APR, gates entries, sizes positions via fractional Kelly; Layer 3 (`execution`) routes a two-leg short-HIP-3 + long-hedge order with pluggable hedge venues; Layer 4 (`risk`) runs priority-ordered exit triggers (deployer halt > funding flip > APR decay) and delta-drift rebalance; Layer 5 (`reporting`) writes SQLite + Telegram + daily APR reports. The orchestrator (`bot.py`) wires the layers together as concurrent asyncio tasks.

**Tech Stack:** Python 3.11+, `hyperliquid-python-sdk`, `ib_insync`, `aiohttp`, `python-telegram-bot`, `APScheduler`, `python-dotenv`, `sqlite3` (built-in), `pytest` + `pytest-asyncio`.

**Source spec:** `hip3-funding-bot-spec.md`. Read it before starting; the spec is authoritative on thresholds, formulas, and exit priority.

**TDD discipline:** Every task that touches code follows red → green → refactor → commit. Tests for pure logic (signals, risk, db, reporting) are unit tests. The data feed, execution router, and bot orchestrator are integration-shaped — we mock the HL/IBKR SDK boundaries and verify behavior in tests; live validation happens on testnet in Task 24.

---

## File Map

```
hip3-funding-bot/
├── pyproject.toml              # Task 1
├── requirements.txt            # Task 1
├── .env.example                # Task 1
├── .gitignore                  # Task 1
├── hip3_bot/
│   ├── __init__.py             # Task 1
│   ├── config.py               # Task 2  — env Config dataclass
│   ├── models.py               # Task 3  — domain dataclasses
│   ├── db.py                   # Task 4  — SQLite persistence
│   ├── signals.py              # Tasks 5-7 — APR / entry / Kelly
│   ├── data_feed.py            # Task 8  — HL REST poll + L2
│   ├── alerts.py               # Task 9  — Telegram alerter
│   ├── risk.py                 # Tasks 10-12 — exit, drift, realized APR
│   ├── execution.py            # Tasks 13-17 — hedges + OrderRouter
│   ├── reporting.py            # Task 18 — daily report
│   ├── bot.py                  # Tasks 19-22 — orchestrator
│   └── main.py                 # Task 23 — asyncio entry point
└── tests/
    ├── __init__.py             # Task 1
    ├── conftest.py             # Task 3
    ├── test_db.py              # Task 4
    ├── test_signals.py         # Tasks 5-7
    ├── test_data_feed.py       # Task 8
    ├── test_risk.py            # Tasks 10-12
    ├── test_execution.py       # Tasks 13-17
    └── test_reporting.py       # Task 18
```

Each Python module has one responsibility. Files that change together (e.g. all signal logic) live together.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `hip3_bot/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1.1: Write `pyproject.toml`**

```toml
[project]
name = "hip3-funding-bot"
version = "0.1.0"
description = "Delta-neutral funding rate farming bot for Hyperliquid HIP-3 perpetual markets"
requires-python = ">=3.11"
dependencies = [
    "hyperliquid-python-sdk>=0.7.0",
    "ib_insync>=0.9.86",
    "pandas>=2.0",
    "numpy>=1.24",
    "aiohttp>=3.9",
    "python-telegram-bot>=21.0",
    "APScheduler>=3.10",
    "python-dotenv>=1.0",
    "eth-account>=0.10",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-asyncio>=0.21"]

[project.scripts]
hip3-bot = "hip3_bot.main:cli"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["hip3_bot*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 1.2: Write `requirements.txt`** (mirrors `pyproject.toml` with dev extras pinned for CI)

```
hyperliquid-python-sdk>=0.7.0
ib_insync>=0.9.86
pandas>=2.0
numpy>=1.24
aiohttp>=3.9
python-telegram-bot>=21.0
APScheduler>=3.10
python-dotenv>=1.0
eth-account>=0.10
pytest>=7.0
pytest-asyncio>=0.21
```

- [ ] **Step 1.3: Write `.env.example`**

```
HL_PRIVATE_KEY=
HL_ACCOUNT_ADDRESS=
HL_API_URL=https://api.hyperliquid.xyz
HL_USE_TESTNET=true

IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

DB_PATH=./hip3_bot.db
LOG_LEVEL=INFO
SCAN_INTERVAL_SEC=30
DRY_RUN=true
HEDGE_VENUE=paper

MIN_ENTRY_APR_PCT=20
MAX_POSITION_PCT=0.10
KELLY_FRACTION=0.25
ROUND_TRIP_FEE_BPS=18
MIN_BOOK_DEPTH_USD=50000
LONG_SKEW_THRESHOLD=0.60
CONSECUTIVE_POSITIVE_FUNDING=3
DELTA_DRIFT_THRESHOLD=0.05
EXIT_APR_PCT=10
REBALANCE_INTERVAL_MIN=15
DEPLOYER_POLL_SEC=5
```

- [ ] **Step 1.4: Write `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
venv/
.env
*.db
*.db-journal
*.log
.pytest_cache/
.coverage
build/
dist/
*.egg-info/
.idea/
.vscode/
```

- [ ] **Step 1.5: Write empty `hip3_bot/__init__.py` and `tests/__init__.py`**

```python
# hip3_bot/__init__.py
"""hip3-funding-bot — delta-neutral funding farming on Hyperliquid HIP-3."""
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 1.6: Install deps + verify pytest runs (no tests yet, exits 5 = "no tests collected")**

```bash
pip install -r requirements.txt
pytest tests/
```

Expected: `no tests ran` (exit code 5). That's fine — proves the harness works.

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml requirements.txt .env.example .gitignore hip3_bot tests
git commit -m "scaffold: project metadata, deps, package skeleton"
```

---

## Task 2: Config dataclass

**Files:**
- Create: `hip3_bot/config.py`

The `Config` is a frozen dataclass loaded from env vars (with optional `.env` via `python-dotenv`). All thresholds in the spec become typed fields with sensible defaults.

- [ ] **Step 2.1: Write `hip3_bot/config.py`**

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
    hl_private_key: str | None
    hl_account_address: str | None
    hl_api_url: str
    hl_use_testnet: bool

    ibkr_host: str
    ibkr_port: int
    ibkr_client_id: int

    telegram_bot_token: str | None
    telegram_chat_id: str | None

    db_path: Path
    log_level: str
    scan_interval_sec: int
    dry_run: bool
    hedge_venue: str

    min_entry_apr_pct: float
    max_position_pct: float
    kelly_fraction: float
    round_trip_fee_bps: float
    min_book_depth_usd: float
    long_skew_threshold: float
    consecutive_positive_funding: int
    delta_drift_threshold: float
    exit_apr_pct: float
    rebalance_interval_min: int
    deployer_poll_sec: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            hl_private_key=_env("HL_PRIVATE_KEY"),
            hl_account_address=_env("HL_ACCOUNT_ADDRESS"),
            hl_api_url=_env("HL_API_URL", "https://api.hyperliquid.xyz"),
            hl_use_testnet=_env_bool("HL_USE_TESTNET", True),
            ibkr_host=_env("IBKR_HOST", "127.0.0.1"),
            ibkr_port=_env_int("IBKR_PORT", 7497),
            ibkr_client_id=_env_int("IBKR_CLIENT_ID", 1),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            db_path=Path(_env("DB_PATH", "./hip3_bot.db")),
            log_level=_env("LOG_LEVEL", "INFO"),
            scan_interval_sec=_env_int("SCAN_INTERVAL_SEC", 30),
            dry_run=_env_bool("DRY_RUN", True),
            hedge_venue=_env("HEDGE_VENUE", "paper"),
            min_entry_apr_pct=_env_float("MIN_ENTRY_APR_PCT", 20.0),
            max_position_pct=_env_float("MAX_POSITION_PCT", 0.10),
            kelly_fraction=_env_float("KELLY_FRACTION", 0.25),
            round_trip_fee_bps=_env_float("ROUND_TRIP_FEE_BPS", 18.0),
            min_book_depth_usd=_env_float("MIN_BOOK_DEPTH_USD", 50_000.0),
            long_skew_threshold=_env_float("LONG_SKEW_THRESHOLD", 0.60),
            consecutive_positive_funding=_env_int("CONSECUTIVE_POSITIVE_FUNDING", 3),
            delta_drift_threshold=_env_float("DELTA_DRIFT_THRESHOLD", 0.05),
            exit_apr_pct=_env_float("EXIT_APR_PCT", 10.0),
            rebalance_interval_min=_env_int("REBALANCE_INTERVAL_MIN", 15),
            deployer_poll_sec=_env_int("DEPLOYER_POLL_SEC", 5),
        )
```

- [ ] **Step 2.2: Smoke-import**

Run: `python -c "from hip3_bot.config import Config; print(Config.from_env())"`
Expected: prints a `Config(...)` repr with default values.

- [ ] **Step 2.3: Commit**

```bash
git add hip3_bot/config.py
git commit -m "config: env-driven Config dataclass with spec thresholds"
```

---

## Task 3: Domain models + test fixtures

**Files:**
- Create: `hip3_bot/models.py`
- Create: `tests/conftest.py`

- [ ] **Step 3.1: Write `hip3_bot/models.py`**

```python
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
```

- [ ] **Step 3.2: Write `tests/conftest.py` with shared fixtures**

```python
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
```

- [ ] **Step 3.3: Smoke-import + run pytest** (no tests yet, but conftest must import cleanly)

```bash
pytest tests/ -v
```

Expected: exits 5 (`no tests ran`). If it errors, the conftest import is broken — fix before continuing.

- [ ] **Step 3.4: Commit**

```bash
git add hip3_bot/models.py tests/conftest.py
git commit -m "models: domain dataclasses + shared test fixtures"
```

---

## Task 4: SQLite Database

**Files:**
- Create: `hip3_bot/db.py`
- Create: `tests/test_db.py`

The DB stores funding history (for entry-gate consecutive-positive checks), positions (open + closed), and arbitrary events for the audit log.

- [ ] **Step 4.1: Write the failing tests** in `tests/test_db.py`

```python
from __future__ import annotations

from datetime import datetime, timedelta

from hip3_bot.db import Database
from hip3_bot.models import ExitReason

from .conftest import make_position, make_snapshot


def test_record_and_query_funding(cfg):
    db = Database(cfg.db_path)
    db.record_funding(make_snapshot(coin="WTI"))
    db.record_funding(make_snapshot(coin="WTI"))
    db.record_funding(make_snapshot(coin="SILVER"))

    assert len(db.recent_funding("WTI", 10)) == 2
    assert len(db.recent_funding("SILVER", 10)) == 1
    assert db.recent_funding("UNKNOWN") == []


def test_upsert_position_and_open_query(cfg):
    db = Database(cfg.db_path)
    p = make_position()
    db.upsert_position(p)

    assert len(db.open_positions()) == 1
    assert db.open_position_for("WTI") is not None
    assert db.open_position_for("SILVER") is None


def test_upsert_updates_existing(cfg):
    db = Database(cfg.db_path)
    p = make_position()
    db.upsert_position(p)

    p.funding_received_usd = 42.0
    db.upsert_position(p)

    fetched = db.open_position_for("WTI")
    assert fetched is not None
    assert fetched.funding_received_usd == 42.0


def test_closed_position_no_longer_open(cfg):
    db = Database(cfg.db_path)
    p = make_position()
    p.closed_at = datetime.utcnow()
    p.exit_reason = ExitReason.FUNDING_FLIP
    p.realized_pnl_usd = 50.0
    db.upsert_position(p)

    assert db.open_positions() == []
    assert len(db.closed_in_last_day()) == 1


def test_closed_in_last_day_filters_old(cfg):
    db = Database(cfg.db_path)
    p = make_position()
    p.closed_at = datetime.utcnow() - timedelta(days=2)
    p.exit_reason = ExitReason.MANUAL
    db.upsert_position(p)

    assert db.closed_in_last_day() == []


def test_log_event_persists(cfg):
    db = Database(cfg.db_path)
    db.log_event("entry", {"coin": "WTI", "size": 1000})
    with db._conn() as c:
        rows = c.execute("SELECT kind, data FROM events").fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "entry"
    assert "WTI" in rows[0]["data"]
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError: hip3_bot.db` — all tests collected fail.

- [ ] **Step 4.3: Implement `hip3_bot/db.py`**

```python
"""SQLite persistence: funding history, positions, events."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .models import ExitReason, FundingSnapshot, HedgeVenue, Position

SCHEMA = """
CREATE TABLE IF NOT EXISTS funding_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    funding_8h REAL NOT NULL,
    annualized_apr_pct REAL NOT NULL,
    mark_price REAL NOT NULL,
    open_interest REAL NOT NULL,
    long_skew REAL NOT NULL,
    book_depth_usd REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_funding_coin_ts
    ON funding_history(coin, timestamp DESC);

CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    coin TEXT NOT NULL,
    hedge_venue TEXT NOT NULL,
    hip3_size REAL NOT NULL,
    hedge_size REAL NOT NULL,
    hip3_entry_price REAL NOT NULL,
    hedge_entry_price REAL NOT NULL,
    notional_usd REAL NOT NULL,
    entry_apr_pct REAL NOT NULL,
    fees_paid_bps REAL NOT NULL DEFAULT 0,
    funding_received_usd REAL NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_reason TEXT,
    realized_pnl_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pos_open ON positions(closed_at);
CREATE INDEX IF NOT EXISTS idx_pos_coin_open
    ON positions(coin, closed_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);
"""


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

    def record_funding(self, snap: FundingSnapshot) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO funding_history(coin,funding_8h,"
                "annualized_apr_pct,mark_price,open_interest,long_skew,"
                "book_depth_usd,timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (snap.coin, snap.funding_8h, snap.annualized_apr_pct,
                 snap.mark_price, snap.open_interest, snap.long_skew,
                 snap.book_depth_usd, snap.timestamp.isoformat()),
            )

    def recent_funding(self, coin: str, limit: int = 10) -> list[float]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT funding_8h FROM funding_history WHERE coin=? "
                "ORDER BY timestamp DESC LIMIT ?", (coin, limit),
            ).fetchall()
        return [r["funding_8h"] for r in rows]

    def open_positions(self) -> list[Position]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM positions WHERE closed_at IS NULL"
            ).fetchall()
        return [_row_to_position(r) for r in rows]

    def open_position_for(self, coin: str) -> Position | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM positions WHERE coin=? AND closed_at IS NULL "
                "LIMIT 1", (coin,),
            ).fetchone()
        return _row_to_position(row) if row else None

    def closed_in_last_day(self, now: datetime | None = None) -> list[Position]:
        now = now or datetime.utcnow()
        cutoff = (now - timedelta(days=1)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM positions WHERE closed_at IS NOT NULL "
                "AND closed_at >= ?", (cutoff,),
            ).fetchall()
        return [_row_to_position(r) for r in rows]

    def upsert_position(self, p: Position) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO positions(id,coin,hedge_venue,hip3_size,"
                "hedge_size,hip3_entry_price,hedge_entry_price,notional_usd,"
                "entry_apr_pct,fees_paid_bps,funding_received_usd,opened_at,"
                "closed_at,exit_reason,realized_pnl_usd) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "hip3_size=excluded.hip3_size,"
                "hedge_size=excluded.hedge_size,"
                "fees_paid_bps=excluded.fees_paid_bps,"
                "funding_received_usd=excluded.funding_received_usd,"
                "closed_at=excluded.closed_at,"
                "exit_reason=excluded.exit_reason,"
                "realized_pnl_usd=excluded.realized_pnl_usd",
                (p.id, p.coin, p.hedge_venue.value, p.hip3_size, p.hedge_size,
                 p.hip3_entry_price, p.hedge_entry_price, p.notional_usd,
                 p.entry_apr_pct, p.fees_paid_bps, p.funding_received_usd,
                 p.opened_at.isoformat(),
                 p.closed_at.isoformat() if p.closed_at else None,
                 p.exit_reason.value if p.exit_reason else None,
                 p.realized_pnl_usd),
            )

    def log_event(self, kind: str, data: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO events(timestamp,kind,data) VALUES (?,?,?)",
                (datetime.utcnow().isoformat(), kind,
                 json.dumps(data, default=str)),
            )


def _row_to_position(r: sqlite3.Row) -> Position:
    return Position(
        id=r["id"], coin=r["coin"],
        hedge_venue=HedgeVenue(r["hedge_venue"]),
        hip3_size=r["hip3_size"], hedge_size=r["hedge_size"],
        hip3_entry_price=r["hip3_entry_price"],
        hedge_entry_price=r["hedge_entry_price"],
        notional_usd=r["notional_usd"],
        entry_apr_pct=r["entry_apr_pct"],
        fees_paid_bps=r["fees_paid_bps"],
        funding_received_usd=r["funding_received_usd"],
        opened_at=datetime.fromisoformat(r["opened_at"]),
        closed_at=datetime.fromisoformat(r["closed_at"]) if r["closed_at"] else None,
        exit_reason=ExitReason(r["exit_reason"]) if r["exit_reason"] else None,
        realized_pnl_usd=r["realized_pnl_usd"],
    )
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -v
```

Expected: 6 passed.

- [ ] **Step 4.5: Commit**

```bash
git add hip3_bot/db.py tests/test_db.py
git commit -m "db: SQLite persistence for funding, positions, events"
```

---

## Task 5: APR formulas (annualize, min_hold_hours)

**Files:**
- Create: `hip3_bot/signals.py` (initial — partial)
- Create: `tests/test_signals.py` (initial — partial)

The spec defines two pure formulas: `annualized_apr = funding_8h * 3 * 365 * 100` and `min_hold_hours = (fee_drag_bps / annualized_apr) * 8760`.

- [ ] **Step 5.1: Write failing tests** in `tests/test_signals.py`

```python
from __future__ import annotations

import math

from hip3_bot.signals import annualize_funding, min_hold_hours


def test_annualize_funding_matches_spec_formula():
    # 0.0001 per 8h × 3 × 365 × 100 = 10.95% APR
    assert annualize_funding(0.0001) == 0.0001 * 3 * 365 * 100


def test_min_hold_hours_at_20_apr_18bps_is_about_79h():
    # 18 / 20 * 8760 / 100 ≈ 78.84 hours
    assert math.isclose(min_hold_hours(20.0, 18.0), 78.84, abs_tol=0.01)


def test_min_hold_hours_zero_apr_is_infinite():
    assert min_hold_hours(0.0, 18.0) == float("inf")
```

- [ ] **Step 5.2: Run tests — expect ImportError**

```bash
pytest tests/test_signals.py -v
```

Expected: `ModuleNotFoundError: hip3_bot.signals`.

- [ ] **Step 5.3: Implement initial `hip3_bot/signals.py`**

```python
"""Layer 2 — funding APR analysis, entry gate, fractional Kelly sizing."""
from __future__ import annotations


def annualize_funding(funding_8h: float) -> float:
    """Convert 8-hour funding rate to annualized APR (percent)."""
    return funding_8h * 3 * 365 * 100


def min_hold_hours(annualized_apr_pct: float, fee_drag_bps: float) -> float:
    """Minimum hold (hours) to recoup round-trip fees at the given APR."""
    if annualized_apr_pct <= 0:
        return float("inf")
    return (fee_drag_bps / annualized_apr_pct) * 8760 / 100
```

- [ ] **Step 5.4: Run tests — expect 3 passed**

```bash
pytest tests/test_signals.py -v
```

- [ ] **Step 5.5: Commit**

```bash
git add hip3_bot/signals.py tests/test_signals.py
git commit -m "signals: APR annualization + min_hold_hours formulas"
```

---

## Task 6: Entry gate (4-condition)

**Files:**
- Modify: `hip3_bot/signals.py` (append `evaluate_entry`)
- Modify: `tests/test_signals.py` (append entry-gate tests)

Spec: enter only if APR > 20% AND ≥3 consecutive positive funding intervals AND OI long skew > 60% AND book depth > $50k.

- [ ] **Step 6.1: Append failing tests** to `tests/test_signals.py`

```python
from hip3_bot.signals import evaluate_entry

from .conftest import make_snapshot


def test_entry_gate_passes_all_four_conditions(cfg):
    snap = make_snapshot(apr_pct=25.0, long_skew=0.7, book_depth_usd=100_000)
    history = [0.0001, 0.0001, 0.0001, 0.0001]
    decision = evaluate_entry(snap, history, cfg)
    assert decision.enter is True
    assert decision.consecutive_positive == 4
    assert decision.reasons == []


def test_entry_gate_blocks_low_apr(cfg):
    snap = make_snapshot(apr_pct=15.0)
    decision = evaluate_entry(snap, [0.0001] * 4, cfg)
    assert decision.enter is False
    assert any("APR" in r for r in decision.reasons)


def test_entry_gate_blocks_low_skew(cfg):
    snap = make_snapshot(long_skew=0.55)
    decision = evaluate_entry(snap, [0.0001] * 4, cfg)
    assert decision.enter is False
    assert any("skew" in r for r in decision.reasons)


def test_entry_gate_blocks_thin_book(cfg):
    snap = make_snapshot(book_depth_usd=30_000)
    decision = evaluate_entry(snap, [0.0001] * 4, cfg)
    assert decision.enter is False
    assert any("depth" in r for r in decision.reasons)


def test_entry_gate_requires_consecutive_positive_funding(cfg):
    snap = make_snapshot()
    decision = evaluate_entry(snap, [0.0001, -0.0001, 0.0001], cfg)
    assert decision.enter is False
    assert decision.consecutive_positive == 1
```

- [ ] **Step 6.2: Run tests — expect ImportError on `evaluate_entry`**

```bash
pytest tests/test_signals.py -v
```

- [ ] **Step 6.3: Append to `hip3_bot/signals.py`**

```python
from dataclasses import dataclass

from .config import Config
from .models import FundingSnapshot


@dataclass
class EntryDecision:
    enter: bool
    reasons: list[str]
    snapshot: FundingSnapshot
    consecutive_positive: int


def evaluate_entry(
    snap: FundingSnapshot,
    recent_funding_8h: list[float],
    cfg: Config,
) -> EntryDecision:
    """Four-condition entry gate from the spec."""
    reasons: list[str] = []
    consecutive = _count_leading_positive(recent_funding_8h)

    if snap.annualized_apr_pct <= cfg.min_entry_apr_pct:
        reasons.append(
            f"APR {snap.annualized_apr_pct:.1f}% <= "
            f"{cfg.min_entry_apr_pct:.1f}%"
        )
    if consecutive < cfg.consecutive_positive_funding:
        reasons.append(
            f"{consecutive} consecutive positive funding intervals "
            f"(need {cfg.consecutive_positive_funding})"
        )
    if snap.long_skew <= cfg.long_skew_threshold:
        reasons.append(
            f"long skew {snap.long_skew:.2f} <= "
            f"{cfg.long_skew_threshold:.2f}"
        )
    if snap.book_depth_usd < cfg.min_book_depth_usd:
        reasons.append(
            f"book depth ${snap.book_depth_usd:,.0f} < "
            f"${cfg.min_book_depth_usd:,.0f}"
        )

    return EntryDecision(
        enter=not reasons,
        reasons=reasons,
        snapshot=snap,
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
```

- [ ] **Step 6.4: Run tests — expect 8 passed**

```bash
pytest tests/test_signals.py -v
```

- [ ] **Step 6.5: Commit**

```bash
git add hip3_bot/signals.py tests/test_signals.py
git commit -m "signals: 4-condition entry gate"
```

---

## Task 7: Fractional Kelly sizing

**Files:**
- Modify: `hip3_bot/signals.py` (append `kelly_size_usd`)
- Modify: `tests/test_signals.py` (append Kelly tests)

Spec: `size = min(kelly_f * 0.25, 0.10) * capital`. Reduce for markets <30 days old.

- [ ] **Step 7.1: Append failing tests**

```python
from hip3_bot.signals import kelly_size_usd


def test_kelly_size_capped_at_max_pct(cfg):
    capital = 100_000
    history = [0.0001] * 10  # near-constant funding → tiny variance
    size = kelly_size_usd(50.0, history, capital, cfg)
    assert size <= capital * cfg.max_position_pct + 1e-6


def test_kelly_size_zero_below_threshold(cfg):
    assert kelly_size_usd(15.0, [0.0001] * 5, 100_000, cfg) == 0.0


def test_kelly_size_haircut_for_new_market(cfg):
    big = kelly_size_usd(50.0, [0.0001] * 5, 100_000, cfg, market_age_days=60)
    young = kelly_size_usd(50.0, [0.0001] * 5, 100_000, cfg, market_age_days=10)
    assert young < big


def test_kelly_size_zero_capital_returns_zero(cfg):
    assert kelly_size_usd(50.0, [0.0001] * 5, 0, cfg) == 0.0
```

- [ ] **Step 7.2: Run — expect ImportError**

- [ ] **Step 7.3: Append to `hip3_bot/signals.py`**

```python
import statistics


def kelly_size_usd(
    apr_pct: float,
    funding_history_8h: list[float],
    capital_usd: float,
    cfg: Config,
    market_age_days: int | None = None,
) -> float:
    """Fractional Kelly notional in USD.

    edge = APR (decimal); variance = annualized variance of historical
    funding. Result is clamped to ``cfg.max_position_pct`` and haircut for
    markets younger than 30 days.
    """
    if apr_pct <= cfg.min_entry_apr_pct or capital_usd <= 0:
        return 0.0

    edge = apr_pct / 100.0
    variance = _annualized_variance(funding_history_8h)
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

- [ ] **Step 7.4: Run — expect 12 passed in `test_signals.py`**

- [ ] **Step 7.5: Commit**

```bash
git add hip3_bot/signals.py tests/test_signals.py
git commit -m "signals: fractional Kelly sizing with new-market haircut"
```

---

## Task 8: Hyperliquid data feed

**Files:**
- Create: `hip3_bot/data_feed.py`
- Create: `tests/test_data_feed.py`

We mock the HL `Info` client to test snapshot construction in isolation. The feed polls `meta_and_asset_ctxs()` to build `FundingSnapshot`s for HIP-3 coins, then enriches the high-APR ones with `l2_snapshot()` for top-of-book depth.

- [ ] **Step 8.1: Write failing tests** in `tests/test_data_feed.py`

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hip3_bot.data_feed import HLDataFeed, is_hip3_market


def test_is_hip3_by_explicit_flag():
    assert is_hip3_market("BTC", {"isHip3": True}) is True


def test_is_hip3_by_coin_hint():
    assert is_hip3_market("WTI") is True
    assert is_hip3_market("WTI-PERP") is True
    assert is_hip3_market("SILVER") is True
    assert is_hip3_market("BTC") is False


def _fake_info(meta_ctx, l2_response=None):
    info = MagicMock()
    info.meta_and_asset_ctxs.return_value = meta_ctx
    info.l2_snapshot.return_value = l2_response or {
        "levels": [
            [{"px": "80.0", "sz": "1000"}],
            [{"px": "80.1", "sz": "1000"}],
        ]
    }
    return info


@pytest.mark.asyncio
async def test_snapshot_all_filters_to_hip3_only(cfg):
    meta_ctx = [
        {"universe": [
            {"name": "WTI", "isHip3": True},
            {"name": "BTC"},
        ]},
        [
            {"funding": "0.0001", "markPx": "80", "openInterest": "100",
             "premium": "0.005", "dayNtlVlm": "100000000"},
            {"funding": "0.00005", "markPx": "70000", "openInterest": "1000",
             "premium": "0", "dayNtlVlm": "200000000"},
        ],
    ]
    feed = HLDataFeed(cfg, info=_fake_info(meta_ctx))
    snaps = await feed.snapshot_all()

    assert {s.coin for s in snaps} == {"WTI"}
    wti = snaps[0]
    assert wti.funding_8h == pytest.approx(0.0001)
    assert wti.annualized_apr_pct == pytest.approx(0.0001 * 3 * 365 * 100)
    assert wti.long_skew > 0.5  # positive premium → long skew
    assert wti.book_depth_usd > 0  # enriched (APR > 10% threshold)


@pytest.mark.asyncio
async def test_snapshot_skips_book_depth_for_low_apr(cfg):
    # APR will be 10.95% which is below default 20% min, so no L2 fetch.
    meta_ctx = [
        {"universe": [{"name": "WTI", "isHip3": True}]},
        [{"funding": "0.0001", "markPx": "80", "openInterest": "100",
          "premium": "0", "dayNtlVlm": "0"}],
    ]
    info = _fake_info(meta_ctx)
    feed = HLDataFeed(cfg, info=info)
    await feed.snapshot_all()

    info.l2_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_handles_empty_meta(cfg):
    feed = HLDataFeed(cfg, info=_fake_info([]))
    assert await feed.snapshot_all() == []
```

- [ ] **Step 8.2: Run — expect import error on `HLDataFeed`**

- [ ] **Step 8.3: Implement `hip3_bot/data_feed.py`**

```python
"""Layer 1 — Hyperliquid funding/mark/OI feed (REST poll)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable

from .config import Config
from .models import FundingSnapshot, Market

logger = logging.getLogger(__name__)

HIP3_COIN_HINTS: set[str] = {
    "WTI", "BRENT", "NATGAS", "GAS", "SILVER", "GOLD",
    "COPPER", "PLATINUM", "PALLADIUM",
}

SnapshotHandler = Callable[[FundingSnapshot], Awaitable[None]]


def is_hip3_market(name: str, meta_universe_entry: dict | None = None) -> bool:
    if meta_universe_entry and meta_universe_entry.get("isHip3"):
        return True
    base = name.upper().split("-")[0]
    return base in HIP3_COIN_HINTS


class HLDataFeed:
    """Polls funding / mark / OI from Hyperliquid REST every scan interval."""

    def __init__(self, cfg: Config, info=None):
        self.cfg = cfg
        self._info = info if info is not None else self._build_info()
        self._running = False

    def _build_info(self):
        from hyperliquid.info import Info

        url = ("https://api.hyperliquid-testnet.xyz"
               if self.cfg.hl_use_testnet else self.cfg.hl_api_url)
        return Info(url, skip_ws=True)

    async def list_markets(self) -> list[Market]:
        meta = await asyncio.to_thread(self._info.meta)
        return [
            Market(coin=u.get("name", ""),
                   is_hip3=is_hip3_market(u.get("name", ""), u),
                   deployer_address=u.get("deployer"))
            for u in meta.get("universe", [])
        ]

    async def snapshot_all(self) -> list[FundingSnapshot]:
        meta_ctx = await asyncio.to_thread(self._info.meta_and_asset_ctxs)
        if not meta_ctx or len(meta_ctx) < 2:
            return []
        universe = meta_ctx[0].get("universe", [])
        ctxs = meta_ctx[1]
        now = datetime.utcnow()

        snaps: list[FundingSnapshot] = []
        for u, ctx in zip(universe, ctxs):
            coin = u.get("name")
            if not coin or not is_hip3_market(coin, u):
                continue
            try:
                snaps.append(self._build_snapshot(coin, ctx, now))
            except (TypeError, ValueError) as e:
                logger.warning("bad ctx for %s: %s", coin, e)

        await self._enrich_with_book_depth(snaps)
        return snaps

    def _build_snapshot(self, coin: str, ctx: dict,
                        now: datetime) -> FundingSnapshot:
        funding_8h = float(ctx.get("funding", 0.0))
        mark = float(ctx.get("markPx", 0.0))
        oi = float(ctx.get("openInterest", 0.0))
        try:
            premium = float(ctx.get("premium", 0.0))
        except (TypeError, ValueError):
            premium = 0.0
        # HL ctx doesn't expose long/short ratio. Use signed premium as a
        # proxy: sustained positive premium implies the crowd is paying
        # up to be long. Clip to [0,1].
        long_skew = max(0.0, min(1.0, 0.5 + premium * 5))
        return FundingSnapshot(
            coin=coin, funding_8h=funding_8h,
            annualized_apr_pct=funding_8h * 3 * 365 * 100,
            mark_price=mark, open_interest=oi,
            long_skew=long_skew, book_depth_usd=0.0,
            timestamp=now,
        )

    async def _enrich_with_book_depth(
        self, snaps: list[FundingSnapshot]
    ) -> None:
        candidates = [s for s in snaps
                      if s.annualized_apr_pct >= self.cfg.min_entry_apr_pct]
        if not candidates:
            return
        results = await asyncio.gather(
            *(self._book_depth_usd(s.coin) for s in candidates),
            return_exceptions=True,
        )
        for s, depth in zip(candidates, results):
            s.book_depth_usd = depth if isinstance(depth, float) else 0.0

    async def _book_depth_usd(self, coin: str) -> float:
        try:
            book = await asyncio.to_thread(self._info.l2_snapshot, coin)
        except Exception:
            logger.exception("l2_snapshot failed for %s", coin)
            return 0.0
        levels = book.get("levels") if book else None
        if not levels or len(levels) < 2:
            return 0.0
        bids, asks = levels[0][:5], levels[1][:5]
        bid_depth = sum(float(l["sz"]) * float(l["px"]) for l in bids)
        ask_depth = sum(float(l["sz"]) * float(l["px"]) for l in asks)
        return min(bid_depth, ask_depth)

    async def run(self, handler: SnapshotHandler) -> None:
        self._running = True
        while self._running:
            try:
                snaps = await self.snapshot_all()
                for s in snaps:
                    await handler(s)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("snapshot loop error")
            await asyncio.sleep(self.cfg.scan_interval_sec)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 8.4: Run — expect 4 passed**

```bash
pytest tests/test_data_feed.py -v
```

- [ ] **Step 8.5: Commit**

```bash
git add hip3_bot/data_feed.py tests/test_data_feed.py
git commit -m "data_feed: HL REST poll for HIP-3 funding/mark/OI + book depth"
```

---

## Task 9: Telegram alerter

**Files:**
- Create: `hip3_bot/alerts.py`

The alerter sends to Telegram if configured, otherwise logs. No tests — it's a thin wrapper over the SDK and not worth the mocking overhead.

- [ ] **Step 9.1: Write `hip3_bot/alerts.py`**

```python
"""Telegram alerter. Falls back to logging when not configured."""
from __future__ import annotations

import logging

from .config import Config

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

    async def send(self, text: str) -> None:
        if not self._bot:
            logger.info("[alert] %s", text)
            return
        try:
            await self._bot.send_message(
                chat_id=self.cfg.telegram_chat_id,
                text=text, parse_mode="Markdown",
            )
        except Exception:
            logger.exception("telegram send failed; text=%s", text)
```

- [ ] **Step 9.2: Smoke import**

```bash
python -c "from hip3_bot.alerts import TelegramAlerter; print('ok')"
```

- [ ] **Step 9.3: Commit**

```bash
git add hip3_bot/alerts.py
git commit -m "alerts: Telegram alerter with logging fallback"
```

---

## Task 10: Exit triggers (P0–P2)

**Files:**
- Create: `hip3_bot/risk.py`
- Create: `tests/test_risk.py`

Spec priority: P0 deployer halt > P1 funding flip > P2 APR decay. P3 (drift) is rebalance-only, not a close — handled in Task 11.

- [ ] **Step 10.1: Write failing tests**

```python
from __future__ import annotations

from hip3_bot.models import ExitReason
from hip3_bot.risk import evaluate_exit

from .conftest import make_position, make_snapshot


def _snap_with_funding(funding_8h: float, apr: float):
    snap = make_snapshot(apr_pct=apr)
    snap.funding_8h = funding_8h
    return snap


def test_p0_deployer_halt_takes_priority(cfg):
    decision = evaluate_exit(
        make_position(), _snap_with_funding(0.0001, 25.0),
        deployer_halted=True, cfg=cfg,
    )
    assert decision.should_exit
    assert decision.reason == ExitReason.DEPLOYER_HALT


def test_p1_funding_flip_negative(cfg):
    decision = evaluate_exit(
        make_position(), _snap_with_funding(-0.0001, 25.0),
        deployer_halted=False, cfg=cfg,
    )
    assert decision.should_exit
    assert decision.reason == ExitReason.FUNDING_FLIP


def test_p2_apr_decay_below_threshold(cfg):
    decision = evaluate_exit(
        make_position(), _snap_with_funding(0.0000001, 5.0),
        deployer_halted=False, cfg=cfg,
    )
    assert decision.should_exit
    assert decision.reason == ExitReason.APR_DECAY


def test_no_exit_when_healthy(cfg):
    decision = evaluate_exit(
        make_position(), _snap_with_funding(0.0001, 25.0),
        deployer_halted=False, cfg=cfg,
    )
    assert not decision.should_exit
```

- [ ] **Step 10.2: Run — expect ImportError**

- [ ] **Step 10.3: Implement `hip3_bot/risk.py` (initial)**

```python
"""Layer 4 — exit triggers and delta drift monitoring."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .models import ExitReason, FundingSnapshot, Position


@dataclass
class ExitDecision:
    should_exit: bool
    reason: ExitReason | None
    note: str = ""


def evaluate_exit(
    p: Position,
    snap: FundingSnapshot,
    deployer_halted: bool,
    cfg: Config,
) -> ExitDecision:
    """Priority-ordered exit check P0 → P2."""
    if deployer_halted:
        return ExitDecision(True, ExitReason.DEPLOYER_HALT,
                            "deployer halt detected — emergency exit")
    if snap.funding_8h < 0:
        return ExitDecision(True, ExitReason.FUNDING_FLIP,
                            f"funding flipped negative: {snap.funding_8h:.6f}")
    if snap.annualized_apr_pct < cfg.exit_apr_pct:
        return ExitDecision(True, ExitReason.APR_DECAY,
                            f"APR decayed to {snap.annualized_apr_pct:.1f}%")
    return ExitDecision(False, None)
```

- [ ] **Step 10.4: Run — expect 4 passed**

- [ ] **Step 10.5: Commit**

```bash
git add hip3_bot/risk.py tests/test_risk.py
git commit -m "risk: priority-ordered P0-P2 exit triggers"
```

---

## Task 11: Delta drift + target hedge size

**Files:**
- Modify: `hip3_bot/risk.py` (append `delta_drift`, `needs_rebalance`, `target_hedge_size`)
- Modify: `tests/test_risk.py` (append drift tests)

- [ ] **Step 11.1: Append failing tests**

```python
from hip3_bot.risk import delta_drift, needs_rebalance, target_hedge_size


def test_delta_drift_neutral_at_entry_marks():
    p = make_position()
    assert abs(delta_drift(p, hip3_mark=80.0, hedge_mark=80.0)) < 1e-9


def test_delta_drift_negative_when_hip3_outpaces_hedge():
    p = make_position()
    drift = delta_drift(p, hip3_mark=88.0, hedge_mark=80.0)
    assert drift < 0


def test_needs_rebalance_threshold(cfg):
    assert needs_rebalance(0.06, cfg) is True
    assert needs_rebalance(-0.06, cfg) is True
    assert needs_rebalance(0.04, cfg) is False


def test_target_hedge_size_neutralizes_at_same_mark():
    p = make_position()
    assert abs(target_hedge_size(p, hedge_mark=80.0) - 125.0) < 1e-9


def test_target_hedge_size_scales_with_hedge_mark():
    p = make_position()
    assert abs(target_hedge_size(p, hedge_mark=160.0) - 62.5) < 1e-9
```

- [ ] **Step 11.2: Run — expect ImportError**

- [ ] **Step 11.3: Append to `hip3_bot/risk.py`**

```python
def delta_drift(p: Position, hip3_mark: float, hedge_mark: float) -> float:
    """Net delta as a fraction of position notional (+long / -short)."""
    if p.notional_usd <= 0:
        return 0.0
    hip3_value = p.hip3_size * hip3_mark
    hedge_value = p.hedge_size * hedge_mark
    return (hip3_value + hedge_value) / p.notional_usd


def needs_rebalance(drift_frac: float, cfg: Config) -> bool:
    return abs(drift_frac) > cfg.delta_drift_threshold


def target_hedge_size(p: Position, hedge_mark: float) -> float:
    """Hedge size that neutralizes the HIP-3 leg at the current hedge mark."""
    if hedge_mark <= 0:
        return p.hedge_size
    target_notional = abs(p.hip3_size) * p.hip3_entry_price
    return target_notional / hedge_mark
```

- [ ] **Step 11.4: Run — expect 9 passed**

- [ ] **Step 11.5: Commit**

```bash
git add hip3_bot/risk.py tests/test_risk.py
git commit -m "risk: delta drift + target hedge size for P3 rebalance"
```

---

## Task 12: Realized APR

**Files:**
- Modify: `hip3_bot/risk.py` (append `realized_apr_pct`)
- Modify: `tests/test_risk.py` (append realized-APR tests)

- [ ] **Step 12.1: Append failing tests**

```python
from hip3_bot.risk import realized_apr_pct


def test_realized_apr_pct_zero_for_zero_hold():
    p = make_position()
    assert realized_apr_pct(p, 0) == 0.0


def test_realized_apr_pct_positive_when_funding_exceeds_fees():
    p = make_position(notional_usd=10_000)
    p.funding_received_usd = 100.0
    p.fees_paid_bps = 9.0
    apr = realized_apr_pct(p, held_hours=24.0)
    assert apr > 0
```

- [ ] **Step 12.2: Run — expect ImportError**

- [ ] **Step 12.3: Append to `hip3_bot/risk.py`**

```python
def realized_apr_pct(p: Position, held_hours: float) -> float:
    if held_hours <= 0 or p.notional_usd <= 0:
        return 0.0
    fee_drag_usd = p.fees_paid_bps / 10_000.0 * p.notional_usd
    net_usd = p.funding_received_usd - fee_drag_usd
    return (net_usd / p.notional_usd) * (8760.0 / held_hours) * 100
```

- [ ] **Step 12.4: Run — expect 11 passed in `test_risk.py`**

- [ ] **Step 12.5: Commit**

```bash
git add hip3_bot/risk.py tests/test_risk.py
git commit -m "risk: realized_apr_pct for reporting and exit decisions"
```

---

## Task 13: Hedge adapter Protocol + Paper adapter

**Files:**
- Create: `hip3_bot/execution.py` (initial)
- Create: `tests/test_execution.py` (initial)

`HedgeAdapter` is a structural Protocol with `buy(coin, notional_usd) -> Fill` and `sell(coin, size) -> Fill`. `PaperHedgeAdapter` records intended hedges using a reference price callback.

- [ ] **Step 13.1: Write failing tests**

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hip3_bot.execution import Fill, PaperHedgeAdapter


@pytest.mark.asyncio
async def test_paper_hedge_buy_uses_reference_price():
    ref = AsyncMock(return_value=80.0)
    adapter = PaperHedgeAdapter(ref)
    fill = await adapter.buy("WTI", 8_000.0)
    assert fill.price == 80.0
    assert fill.size == pytest.approx(100.0)
    ref.assert_awaited_once_with("WTI")


@pytest.mark.asyncio
async def test_paper_hedge_sell_uses_reference_price():
    ref = AsyncMock(return_value=80.0)
    adapter = PaperHedgeAdapter(ref)
    fill = await adapter.sell("WTI", 100.0)
    assert fill.price == 80.0
    assert fill.size == 100.0


@pytest.mark.asyncio
async def test_paper_hedge_buy_zero_price_returns_zero_size():
    ref = AsyncMock(return_value=0.0)
    adapter = PaperHedgeAdapter(ref)
    fill = await adapter.buy("WTI", 8_000.0)
    assert fill.size == 0.0


def test_fill_dataclass_defaults():
    f = Fill(price=10.0, size=5.0)
    assert f.fees_paid_usd == 0.0
```

- [ ] **Step 13.2: Run — expect ImportError**

- [ ] **Step 13.3: Implement initial `hip3_bot/execution.py`**

```python
"""Layer 3 — order routing for HIP-3 short leg + hedge long leg."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from .models import HedgeVenue

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
    """Records intended hedges without sending orders."""

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
```

- [ ] **Step 13.4: Run — expect 4 passed**

- [ ] **Step 13.5: Commit**

```bash
git add hip3_bot/execution.py tests/test_execution.py
git commit -m "execution: HedgeAdapter Protocol + PaperHedgeAdapter"
```

---

## Task 14: HL native + IBKR hedge adapters

**Files:**
- Modify: `hip3_bot/execution.py` (append `HLNativeHedgeAdapter`, `IBKRHedgeAdapter`, `_parse_hl_fill`)
- Modify: `tests/test_execution.py` (append HL native parse tests)

We unit-test the HL native adapter's fill parsing. IBKR is integration-tested manually in Task 24 because it requires TWS/IB Gateway running.

- [ ] **Step 14.1: Append failing tests**

```python
from hip3_bot.execution import _parse_hl_fill


def test_parse_hl_fill_success():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [
            {"filled": {"avgPx": "80.5", "totalSz": "10"}}
        ]}},
    }
    fill = _parse_hl_fill(result, fallback_price=0.0, fallback_size=0.0)
    assert fill.price == 80.5
    assert fill.size == 10.0


def test_parse_hl_fill_falls_back_on_error():
    fill = _parse_hl_fill({"status": "err"}, fallback_price=80.0,
                          fallback_size=10.0)
    assert fill.price == 80.0
    assert fill.size == 10.0


def test_parse_hl_fill_falls_back_on_missing_filled():
    result = {"status": "ok",
              "response": {"data": {"statuses": [{"resting": {"oid": 1}}]}}}
    fill = _parse_hl_fill(result, fallback_price=80.0, fallback_size=10.0)
    assert fill.price == 80.0
    assert fill.size == 10.0
```

- [ ] **Step 14.2: Run — expect ImportError**

- [ ] **Step 14.3: Append to `hip3_bot/execution.py`**

```python
import asyncio


class HLNativeHedgeAdapter:
    """Hedge using a Hyperliquid native (non-HIP-3) commodity perp.

    Used when CME is closed or as a fallback when IBKR is unreachable.
    """

    venue = HedgeVenue.HL_NATIVE

    DEFAULT_MAP: dict[str, str] = {
        "WTI": "OIL",
        "BRENT": "OIL",
    }

    def __init__(self, exchange, info,
                 hedge_coin_map: dict[str, str] | None = None):
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
        "WTI": "USO", "BRENT": "BNO", "SILVER": "SLV", "GOLD": "GLD",
        "COPPER": "CPER", "PLATINUM": "PPLT", "PALLADIUM": "PALL",
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


def _parse_hl_fill(result, fallback_price: float,
                   fallback_size: float) -> Fill:
    try:
        if not result or result.get("status") != "ok":
            return Fill(fallback_price, fallback_size)
        statuses = result["response"]["data"]["statuses"]
        filled = statuses[0].get("filled") if statuses else None
        if not filled:
            return Fill(fallback_price, fallback_size)
        return Fill(price=float(filled["avgPx"]),
                    size=float(filled["totalSz"]))
    except (KeyError, IndexError, ValueError, TypeError):
        return Fill(fallback_price, fallback_size)


def _resting_oid(result) -> int | None:
    try:
        return result["response"]["data"]["statuses"][0]["resting"]["oid"]
    except (KeyError, IndexError, TypeError):
        return None
```

- [ ] **Step 14.4: Run — expect 7 passed in `test_execution.py`**

- [ ] **Step 14.5: Commit**

```bash
git add hip3_bot/execution.py tests/test_execution.py
git commit -m "execution: HLNative + IBKR hedge adapters + HL fill parser"
```

---

## Task 15: OrderRouter — open delta-neutral

**Files:**
- Modify: `hip3_bot/execution.py` (append `OrderRouter` class with `open_delta_neutral` and helpers)
- Modify: `tests/test_execution.py` (append router open tests using paper hedge)

In dry-run mode the router constructs a paper position; we test that path. Live HL leg-A flow uses limit-then-slide-to-market; we cover the helpers separately.

- [ ] **Step 15.1: Append failing tests**

```python
from unittest.mock import MagicMock

from hip3_bot.execution import OrderRouter
from hip3_bot.models import HedgeVenue


@pytest.mark.asyncio
async def test_open_delta_neutral_dry_run_creates_paper_position(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(cfg, exchange=None, info=info,
                         hedge=PaperHedgeAdapter(ref))

    pos = await router.open_delta_neutral("WTI", notional_usd=8_000.0,
                                          entry_apr_pct=25.0)
    assert pos is not None
    assert pos.coin == "WTI"
    assert pos.hedge_venue == HedgeVenue.PAPER
    assert pos.hip3_size < 0  # short
    assert pos.hedge_size > 0  # long
    assert abs(abs(pos.hip3_size) - pos.hedge_size) < 1e-9
    assert pos.notional_usd == 8_000.0
    assert pos.entry_apr_pct == 25.0


@pytest.mark.asyncio
async def test_open_delta_neutral_returns_none_when_no_mid(cfg):
    info = MagicMock()
    info.all_mids.return_value = {}
    ref = AsyncMock(return_value=0.0)
    router = OrderRouter(cfg, exchange=None, info=info,
                         hedge=PaperHedgeAdapter(ref))
    assert await router.open_delta_neutral("WTI", 8_000.0, 25.0) is None
```

- [ ] **Step 15.2: Run — expect ImportError**

- [ ] **Step 15.3: Append to `hip3_bot/execution.py`**

```python
import uuid
from datetime import datetime

from .config import Config
from .models import Position


class OrderRouter:
    """Coordinates the two-leg open/close/rebalance flow."""

    def __init__(self, cfg: Config, exchange, info, hedge: HedgeAdapter):
        self.cfg = cfg
        self._exchange = exchange
        self._info = info
        self._hedge = hedge

    async def open_delta_neutral(
        self, coin: str, notional_usd: float, entry_apr_pct: float,
    ) -> Position | None:
        mids = await asyncio.to_thread(self._info.all_mids)
        mark = float(mids.get(coin, 0.0))
        if mark <= 0:
            logger.error("no mid for %s", coin)
            return None
        size = notional_usd / mark

        if self.cfg.dry_run or self._exchange is None:
            return self._paper_position(coin, size, mark, notional_usd,
                                        entry_apr_pct)

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

    async def _short_hip3(self, coin: str, size: float,
                          mark: float) -> Fill:
        result = await asyncio.to_thread(
            self._exchange.order, coin, False, size, mark,
            {"limit": {"tif": "Gtc"}}, False,
        )
        oid = _resting_oid(result)
        if oid is None:
            return _parse_hl_fill(result, mark, size)

        wallet_addr = getattr(getattr(self._exchange, "wallet", None),
                              "address", None)
        for _ in range(LIMIT_FILL_TIMEOUT_SEC):
            await asyncio.sleep(1.0)
            if not wallet_addr:
                break
            try:
                status = await asyncio.to_thread(
                    self._info.query_order_by_oid, wallet_addr, oid,
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
            self._exchange.market_open, coin, False, size, None,
            DEFAULT_SLIPPAGE,
        )
        return _parse_hl_fill(result2, mark, size)

    async def _unwind_partial(self, coin: str, leg_a, leg_b) -> None:
        if isinstance(leg_a, Fill) and leg_a.size > 0:
            try:
                await asyncio.to_thread(
                    self._exchange.market_close, coin, leg_a.size, None,
                    DEFAULT_SLIPPAGE,
                )
            except Exception:
                logger.exception("partial unwind A failed")
        if isinstance(leg_b, Fill) and leg_b.size > 0:
            try:
                await self._hedge.sell(coin, leg_b.size)
            except Exception:
                logger.exception("partial unwind B failed")

    def _paper_position(self, coin, size, mark, notional, apr):
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
```

- [ ] **Step 15.4: Run — expect 9 passed in `test_execution.py`**

- [ ] **Step 15.5: Commit**

```bash
git add hip3_bot/execution.py tests/test_execution.py
git commit -m "execution: OrderRouter.open_delta_neutral with limit-then-slide HIP-3 leg"
```

---

## Task 16: OrderRouter — close delta-neutral

**Files:**
- Modify: `hip3_bot/execution.py` (append `close_delta_neutral` and `_cover_hip3`)
- Modify: `tests/test_execution.py` (append close test)

- [ ] **Step 16.1: Append failing test**

```python
@pytest.mark.asyncio
async def test_close_delta_neutral_dry_run_is_noop(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(cfg, exchange=None, info=info,
                         hedge=PaperHedgeAdapter(ref))
    pos = await router.open_delta_neutral("WTI", 8_000.0, 25.0)
    assert pos is not None
    # In dry-run there's nothing to assert beyond "doesn't raise".
    await router.close_delta_neutral(pos)
```

- [ ] **Step 16.2: Run — expect AttributeError on `close_delta_neutral`**

- [ ] **Step 16.3: Append to `OrderRouter` in `hip3_bot/execution.py`**

```python
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

    async def _cover_hip3(self, p: Position) -> Fill:
        size = abs(p.hip3_size)
        result = await asyncio.to_thread(
            self._exchange.market_close, p.coin, size, None, DEFAULT_SLIPPAGE
        )
        return _parse_hl_fill(result, p.hip3_entry_price, size)
```

- [ ] **Step 16.4: Run — expect 10 passed**

- [ ] **Step 16.5: Commit**

```bash
git add hip3_bot/execution.py tests/test_execution.py
git commit -m "execution: OrderRouter.close_delta_neutral two-leg market close"
```

---

## Task 17: OrderRouter — rebalance hedge

**Files:**
- Modify: `hip3_bot/execution.py` (append `rebalance_hedge`)
- Modify: `tests/test_execution.py` (append rebalance test)

- [ ] **Step 17.1: Append failing test**

```python
@pytest.mark.asyncio
async def test_rebalance_hedge_dry_run_returns_fill(cfg):
    info = MagicMock()
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(cfg, exchange=None, info=info,
                         hedge=PaperHedgeAdapter(ref))
    from .conftest import make_position

    p = make_position(hedge_size=125.0)
    fill = await router.rebalance_hedge(p, target_size=120.0)
    assert fill is not None
    assert fill.size == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_rebalance_hedge_no_op_when_target_matches(cfg):
    info = MagicMock()
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(cfg, exchange=None, info=info,
                         hedge=PaperHedgeAdapter(ref))
    from .conftest import make_position

    p = make_position(hedge_size=125.0)
    assert await router.rebalance_hedge(p, target_size=125.0) is None
```

- [ ] **Step 17.2: Run — expect AttributeError**

- [ ] **Step 17.3: Append to `OrderRouter`**

```python
    async def rebalance_hedge(
        self, p: Position, target_size: float,
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
```

- [ ] **Step 17.4: Run — expect 12 passed in `test_execution.py`**

- [ ] **Step 17.5: Commit**

```bash
git add hip3_bot/execution.py tests/test_execution.py
git commit -m "execution: OrderRouter.rebalance_hedge for P3 drift correction"
```

---

## Task 18: Daily report

**Files:**
- Create: `hip3_bot/reporting.py`
- Create: `tests/test_reporting.py`

- [ ] **Step 18.1: Write failing tests**

```python
from __future__ import annotations

from datetime import datetime, timedelta

from hip3_bot.db import Database
from hip3_bot.models import ExitReason
from hip3_bot.reporting import daily_report

from .conftest import make_position


def test_daily_report_no_positions(cfg):
    db = Database(cfg.db_path)
    report = daily_report(db, now=datetime(2026, 5, 9, 12, 0))
    assert "Daily Report" in report
    assert "Open positions: 0" in report


def test_daily_report_lists_open_position(cfg):
    db = Database(cfg.db_path)
    p = make_position()
    p.opened_at = datetime(2026, 5, 9, 0, 0)
    db.upsert_position(p)
    report = daily_report(db, now=datetime(2026, 5, 9, 12, 0))
    assert "WTI" in report
    assert "$10,000" in report


def test_daily_report_summarizes_closed(cfg):
    db = Database(cfg.db_path)
    p = make_position()
    p.closed_at = datetime.utcnow()
    p.exit_reason = ExitReason.FUNDING_FLIP
    p.realized_pnl_usd = 42.0
    db.upsert_position(p)
    report = daily_report(db)
    assert "Closed (24h): 1" in report
    assert "$42" in report
```

- [ ] **Step 18.2: Run — expect ImportError**

- [ ] **Step 18.3: Implement `hip3_bot/reporting.py`**

```python
"""Layer 5 — daily APR realized vs. projected report."""
from __future__ import annotations

from datetime import datetime

from .db import Database
from .risk import realized_apr_pct


def daily_report(db: Database, now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    open_positions = db.open_positions()
    closed = db.closed_in_last_day(now)

    lines = [f"📊 *Daily Report* — {now:%Y-%m-%d %H:%M}Z"]
    lines.append(f"Open positions: {len(open_positions)}")

    for p in open_positions:
        held_h = (now - p.opened_at).total_seconds() / 3600.0
        realized = realized_apr_pct(p, held_h)
        lines.append(
            f"  • {p.coin}: ${p.notional_usd:,.0f}  "
            f"projected {p.entry_apr_pct:.1f}%  "
            f"realized {realized:.1f}%  held {held_h:.1f}h"
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

- [ ] **Step 18.4: Run — expect 3 passed**

- [ ] **Step 18.5: Commit**

```bash
git add hip3_bot/reporting.py tests/test_reporting.py
git commit -m "reporting: daily realized vs projected APR report"
```

---

## Task 19: Bot orchestrator — entry/exit handling

**Files:**
- Create: `hip3_bot/bot.py` (initial — `__init__`, `_handle_snapshot`, `_evaluate_entry`, `_evaluate_exit`, `_close`, `_refresh_capital`)

The orchestrator wires everything together. We do NOT unit-test it heavily — instead we rely on the layer tests and a manual testnet run in Task 24. Still, write the class with clean seams so the loops are obvious.

- [ ] **Step 19.1: Write `hip3_bot/bot.py` (initial — class skeleton + entry/exit handlers)**

```python
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
    HedgeAdapter, HLNativeHedgeAdapter, IBKRHedgeAdapter,
    OrderRouter, PaperHedgeAdapter,
)
from .models import ExitReason, FundingSnapshot, Position
from .reporting import daily_report
from .risk import (
    delta_drift, evaluate_exit, needs_rebalance,
    realized_apr_pct, target_hedge_size,
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
        self.router = OrderRouter(cfg, self.exchange, self.info,
                                  self._build_hedge())
        self._capital_usd: float = 0.0
        self._deployer_halted: dict[str, bool] = {}

    def _build_hl_clients(self):
        from hyperliquid.info import Info

        url = ("https://api.hyperliquid-testnet.xyz"
               if self.cfg.hl_use_testnet else self.cfg.hl_api_url)
        info = Info(url, skip_ws=True)
        if self.cfg.dry_run or not self.cfg.hl_private_key:
            return None, info
        from eth_account import Account
        from hyperliquid.exchange import Exchange

        wallet = Account.from_key(self.cfg.hl_private_key)
        exchange = Exchange(wallet, url,
                            account_address=self.cfg.hl_account_address)
        return exchange, info

    def _build_hedge(self) -> HedgeAdapter:
        venue = self.cfg.hedge_venue.lower()
        if venue == "ibkr" and not self.cfg.dry_run:
            try:
                from ib_insync import IB

                ib = IB()
                ib.connect(self.cfg.ibkr_host, self.cfg.ibkr_port,
                           clientId=self.cfg.ibkr_client_id)
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

    async def _refresh_capital(self) -> None:
        if not self.cfg.hl_account_address:
            self._capital_usd = 100_000.0
            return
        try:
            state = await asyncio.to_thread(
                self.info.user_state, self.cfg.hl_account_address,
            )
            self._capital_usd = float(
                state.get("marginSummary", {}).get("accountValue", 100_000.0)
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
        size_usd = kelly_size_usd(snap.annualized_apr_pct, history,
                                  self._capital_usd, self.cfg)
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
            snap.coin, size_usd, snap.annualized_apr_pct,
        )
        if position is None:
            await self.alerter.send(f"⚠️ entry failed for {snap.coin}")
            return
        self.db.upsert_position(position)
        self.db.log_event("entry", {
            "coin": snap.coin, "size_usd": size_usd,
            "apr": snap.annualized_apr_pct, "position_id": position.id,
        })

    async def _evaluate_exit(
        self, p: Position, snap: FundingSnapshot,
    ) -> None:
        decision = evaluate_exit(
            p, snap,
            deployer_halted=self._deployer_halted.get(snap.coin, False),
            cfg=self.cfg,
        )
        if decision.should_exit and decision.reason is not None:
            await self._close(p, decision.reason, decision.note)

    async def _close(self, p: Position, reason: ExitReason,
                     note: str) -> None:
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
        self.db.log_event("exit", {
            "coin": p.coin, "reason": reason.value,
            "pnl_usd": p.realized_pnl_usd,
            "realized_apr_pct": realized_apr_pct(p, held_h),
            "held_hours": held_h,
        })
```

- [ ] **Step 19.2: Smoke import** (`python -c "from hip3_bot.bot import Bot; print('ok')"`)

- [ ] **Step 19.3: Commit**

```bash
git add hip3_bot/bot.py
git commit -m "bot: orchestrator skeleton with entry/exit/close handlers"
```

---

## Task 20: Bot orchestrator — rebalance loop

**Files:**
- Modify: `hip3_bot/bot.py` (append `_rebalance_loop`, `_rebalance_all`)

- [ ] **Step 20.1: Append to `Bot` in `hip3_bot/bot.py`**

```python
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
                    self.db.log_event("rebalance", {
                        "coin": p.coin, "drift": drift,
                        "new_hedge_size": target,
                    })
            except Exception:
                logger.exception("rebalance %s failed", p.coin)
```

- [ ] **Step 20.2: Smoke import**

- [ ] **Step 20.3: Commit**

```bash
git add hip3_bot/bot.py
git commit -m "bot: P3 delta-drift rebalance loop"
```

---

## Task 21: Bot orchestrator — deployer watch + daily report loops

**Files:**
- Modify: `hip3_bot/bot.py` (append `_deployer_watch_loop`, `_daily_report_loop`)

- [ ] **Step 21.1: Append to `Bot`**

```python
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
        """Poll meta for delisted markets — proxy for deployer halt.

        The HL meta endpoint exposes deployer addresses on HIP-3 markets.
        Until a contract-event API is exposed, we treat a market vanishing
        from `universe` (or being marked ``isDelisted``) as a halt signal.
        """
        while True:
            await asyncio.sleep(self.cfg.deployer_poll_sec)
            try:
                meta = await asyncio.to_thread(self.info.meta)
                live_coins = {
                    u.get("name") for u in meta.get("universe", [])
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
```

- [ ] **Step 21.2: Smoke import**

- [ ] **Step 21.3: Commit**

```bash
git add hip3_bot/bot.py
git commit -m "bot: deployer watch + daily report background loops"
```

---

## Task 22: Bot orchestrator — `run` method

**Files:**
- Modify: `hip3_bot/bot.py` (append `run`)

`run` fans out into four concurrent loops: feed → handler, rebalance, deployer watch, daily report.

- [ ] **Step 22.1: Append to `Bot`**

```python
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
```

- [ ] **Step 22.2: Smoke import**

- [ ] **Step 22.3: Commit**

```bash
git add hip3_bot/bot.py
git commit -m "bot: run() fans out the four concurrent loops"
```

---

## Task 23: Process entry point

**Files:**
- Create: `hip3_bot/main.py`

- [ ] **Step 23.1: Write `hip3_bot/main.py`**

```python
"""Process entry point."""
from __future__ import annotations

import asyncio
import logging
import signal

from .bot import Bot
from .config import Config


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run() -> None:
    cfg = Config.from_env()
    _setup_logging(cfg.log_level)
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
            pass  # Windows doesn't support add_signal_handler for SIGTERM.

    run_task = asyncio.create_task(bot.run())
    stop_task = asyncio.create_task(stop.wait())
    _, pending = await asyncio.wait(
        {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()


def cli() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    cli()
```

- [ ] **Step 23.2: Run full test suite — expect all green**

```bash
pytest tests/ -v
```

Expected: 30+ passed.

- [ ] **Step 23.3: Commit**

```bash
git add hip3_bot/main.py
git commit -m "main: asyncio entry point with SIGINT/SIGTERM handling"
```

---

## Task 24: Testnet smoke test (Phase 1 deliverable)

**Files:**
- Modify: `.env` (local only, not committed)

Goal: confirm Phase 1 of the spec — "Scanner bot that alerts you when APR > 20%". This task validates wiring against a live testnet, not unit tests.

- [ ] **Step 24.1: Configure `.env`**

```bash
cp .env.example .env
# Edit .env:
#   HL_USE_TESTNET=true
#   DRY_RUN=true
#   HEDGE_VENUE=paper
#   TELEGRAM_BOT_TOKEN=<your bot token, optional>
#   TELEGRAM_CHAT_ID=<your chat id, optional>
#   MIN_ENTRY_APR_PCT=5      # lower threshold for testnet to see signals
```

- [ ] **Step 24.2: Run for 5 minutes**

```bash
python -m hip3_bot.main
```

Expected log output:
- `hip3-bot starting (dry_run=True, testnet=True, hedge=paper)` once at startup.
- A scan loop every 30s emitting funding snapshots into the DB.
- Zero exceptions.
- If any HIP-3 market clears the lowered APR gate, an `Entry signal` alert and a `[paper hedge] BUY ...` log line.

- [ ] **Step 24.3: Inspect SQLite**

```bash
sqlite3 hip3_bot.db "SELECT coin, COUNT(*) FROM funding_history GROUP BY coin;"
sqlite3 hip3_bot.db "SELECT coin, notional_usd, entry_apr_pct, opened_at FROM positions;"
```

Expected: at least one row in `funding_history`. Positions only if a signal triggered.

- [ ] **Step 24.4: Stop with Ctrl+C and confirm clean shutdown** (no traceback).

- [ ] **Step 24.5: Reset thresholds to spec defaults in `.env`** (`MIN_ENTRY_APR_PCT=20`).

- [ ] **Step 24.6: Commit operational docs** (only if you've added a README — do not generate one unless asked).

```bash
git status   # confirm only .env (gitignored) changed
```

---

## Task 25: Phase 2 — paper trading loop validation

**Files:** none

Goal: validate Phase 2 of the spec — "Full paper trading bot on HL testnet" — by force-firing an entry on testnet under `DRY_RUN=true`.

- [ ] **Step 25.1: Lower thresholds in `.env`**

```
MIN_ENTRY_APR_PCT=1
LONG_SKEW_THRESHOLD=0.0
MIN_BOOK_DEPTH_USD=0
CONSECUTIVE_POSITIVE_FUNDING=1
```

- [ ] **Step 25.2: Run for 10 minutes**

```bash
python -m hip3_bot.main
```

Expected:
- An `Entry signal` alert.
- An open position recorded in `positions` table with `hedge_venue='paper'`.
- After ~15 minutes, a rebalance log entry if drift > 5%.

- [ ] **Step 25.3: Force exit by raising `EXIT_APR_PCT` above current APR**

Stop the bot, edit `.env`:
```
EXIT_APR_PCT=99
```
Restart. The next snapshot should trigger P2 APR decay and close the position.

```bash
sqlite3 hip3_bot.db "SELECT coin, exit_reason, realized_pnl_usd FROM positions WHERE closed_at IS NOT NULL;"
```

Expected: row with `exit_reason='P2_apr_decay'`.

- [ ] **Step 25.4: Reset `.env` to spec defaults.**

---

## Phase 3 / 4 follow-ups (not in this plan)

Follow-up plans (write after Phase 2 validates) should cover:

- **IBKR live integration:** end-to-end test placing a real ETF order on IBKR paper account; verify ETF map covers the HIP-3 markets you intend to trade.
- **Funding accrual poller:** a fifth concurrent loop calling `info.user_funding(account, since)` every funding interval and incrementing `Position.funding_received_usd`. Without this, `realized_pnl_usd` is stuck at -fees.
- **WebSocket data feed:** replace REST polling with HL `subscribe()` for sub-second mark/funding updates.
- **Deployer event subscription:** when the SDK exposes contract events, replace the `isDelisted` proxy with a true halt watcher.
- **Multi-market rotation (Phase 4):** scan-and-rank logic to rotate from a 25%-APR position into a 50%-APR alternative when realized APR exceeds the entry threshold.
- **Production observability:** structured logs (JSON), Prometheus metrics, and a P&L dashboard.

---

## Self-Review Checklist (completed before saving)

**Spec coverage:**
- ✅ Layer 1 data: Task 8
- ✅ Layer 2 signals: Tasks 5–7
- ✅ Layer 3 execution: Tasks 13–17
- ✅ Layer 4 risk: Tasks 10–12, 21 (deployer)
- ✅ Layer 5 reporting: Tasks 4 (db), 9 (telegram), 18 (daily report)
- ✅ Entry gate four conditions: Task 6
- ✅ Fee drag formula: Task 5
- ✅ Kelly + size cap + new-market haircut: Task 7
- ✅ Two-leg open with limit-then-slide: Task 15
- ✅ Two-leg close: Task 16
- ✅ Delta rebalance every 15min: Tasks 17, 20
- ✅ P0–P2 priority exits: Tasks 10, 19
- ✅ Weekend HL native fallback: Task 14 (`HLNativeHedgeAdapter`)
- ✅ Daily report: Task 18
- ✅ Phase 1 deliverable validation: Task 24
- ✅ Phase 2 deliverable validation: Task 25
- Phase 3 (live IBKR + small size) and Phase 4 (scale + rotation) deferred to follow-up plans (called out above).

**Placeholder scan:** No "TBD", "TODO", "implement later", or vague handwave steps. Every code step has complete code.

**Type/name consistency:** `Config`, `Database`, `HLDataFeed`, `OrderRouter`, `HedgeAdapter`, `PaperHedgeAdapter`, `HLNativeHedgeAdapter`, `IBKRHedgeAdapter`, `Fill`, `Position`, `FundingSnapshot`, `ExitDecision`, `EntryDecision`, and `ExitReason` enum values used consistently across tasks.
