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
                (
                    snap.coin,
                    snap.funding_8h,
                    snap.annualized_apr_pct,
                    snap.mark_price,
                    snap.open_interest,
                    snap.long_skew,
                    snap.book_depth_usd,
                    snap.timestamp.isoformat(),
                ),
            )

    def recent_funding(self, coin: str, limit: int = 10) -> list[float]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT funding_8h FROM funding_history WHERE coin=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (coin, limit),
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
                "SELECT * FROM positions "
                "WHERE coin=? AND closed_at IS NULL LIMIT 1",
                (coin,),
            ).fetchone()
        return _row_to_position(row) if row else None

    def closed_in_last_day(self, now: datetime | None = None) -> list[Position]:
        now = now or datetime.utcnow()
        cutoff = (now - timedelta(days=1)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM positions "
                "WHERE closed_at IS NOT NULL AND closed_at >= ?",
                (cutoff,),
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
                (
                    p.id,
                    p.coin,
                    p.hedge_venue.value,
                    p.hip3_size,
                    p.hedge_size,
                    p.hip3_entry_price,
                    p.hedge_entry_price,
                    p.notional_usd,
                    p.entry_apr_pct,
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
        hedge_venue=HedgeVenue(r["hedge_venue"]),
        hip3_size=r["hip3_size"],
        hedge_size=r["hedge_size"],
        hip3_entry_price=r["hip3_entry_price"],
        hedge_entry_price=r["hedge_entry_price"],
        notional_usd=r["notional_usd"],
        entry_apr_pct=r["entry_apr_pct"],
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
