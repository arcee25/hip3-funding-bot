from __future__ import annotations

from datetime import datetime

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
