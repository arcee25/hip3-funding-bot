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
    ostium_trade_index INTEGER,
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
        # Backwards compat: pre-Phase-3 DBs lack ostium_trade_index.
        for table in ("trade_log", "simulated_trade_log"):
            try:
                with self._conn() as c:
                    c.execute(
                        f"ALTER TABLE {table} ADD COLUMN "
                        "ostium_trade_index INTEGER"
                    )
            except sqlite3.OperationalError:
                pass  # column already exists

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
                f"SELECT * FROM {table} "
                "WHERE closed_at IS NULL AND mode=?",
                (mode.value,),
            ).fetchall()
        return [_row_to_position(r) for r in rows]

    def open_position_for(
        self, coin: str, mode: Mode
    ) -> Position | None:
        table = _table_for_mode(mode)
        with self._conn() as c:
            row = c.execute(
                f"SELECT * FROM {table} "
                "WHERE coin=? AND mode=? AND closed_at IS NULL LIMIT 1",
                (coin, mode.value),
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
                "WHERE mode=? AND closed_at IS NOT NULL AND closed_at >= ?",
                (mode.value, cutoff),
            ).fetchall()
        return [_row_to_position(r) for r in rows]

    def upsert_position(self, p: Position) -> None:
        table = _table_for_mode(p.mode)
        with self._conn() as c:
            c.execute(
                f"INSERT INTO {table}(id,coin,mode,hip3_size,ostium_size,"
                "ostium_trade_index,"
                "hip3_entry_price,ostium_entry_price,notional_usd,"
                "entry_net_apr_pct,fees_paid_bps,funding_received_usd,"
                "opened_at,closed_at,exit_reason,realized_pnl_usd) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "hip3_size=excluded.hip3_size,"
                "ostium_size=excluded.ostium_size,"
                "ostium_trade_index=excluded.ostium_trade_index,"
                "fees_paid_bps=excluded.fees_paid_bps,"
                "funding_received_usd=excluded.funding_received_usd,"
                "closed_at=excluded.closed_at,"
                "exit_reason=excluded.exit_reason,"
                "realized_pnl_usd=excluded.realized_pnl_usd",
                (
                    p.id, p.coin, p.mode.value,
                    p.hip3_size, p.ostium_size,
                    getattr(p, "ostium_trade_index", None),
                    p.hip3_entry_price, p.ostium_entry_price,
                    p.notional_usd, p.entry_net_apr_pct,
                    p.fees_paid_bps, p.funding_received_usd,
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
    pos = Position(
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
    # Tolerant of pre-Phase-3 rows: column may be NULL or (after Task 3)
    # the field exists on Position with a default. Position has no
    # __slots__, so we can set the attribute unconditionally; this works
    # both before Task 3 (attribute added dynamically) and after Task 3
    # (overwrites the default field value).
    pos.ostium_trade_index = dict(r).get("ostium_trade_index")
    return pos
