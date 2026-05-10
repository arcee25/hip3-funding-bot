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
