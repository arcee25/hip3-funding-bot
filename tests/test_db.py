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
