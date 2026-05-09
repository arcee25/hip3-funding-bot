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
