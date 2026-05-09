from __future__ import annotations

import math

from hip3_bot.signals import (
    annualize_funding,
    evaluate_entry,
    kelly_size_usd,
    min_hold_hours,
)

from .conftest import make_snapshot


def test_annualize_funding_matches_spec_formula():
    # 0.0001 per 8h × 3 × 365 × 100 = 10.95% APR
    assert annualize_funding(0.0001) == 0.0001 * 3 * 365 * 100


def test_min_hold_hours_at_20_apr_18bps_is_about_79h():
    # 18 / 20 * 8760 / 100 ≈ 78.84 hours
    assert math.isclose(min_hold_hours(20.0, 18.0), 78.84, abs_tol=0.01)


def test_min_hold_hours_zero_apr_is_infinite():
    assert min_hold_hours(0.0, 18.0) == float("inf")


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


def test_kelly_size_capped_at_max_pct(cfg):
    capital = 100_000
    history = [0.0001] * 10  # near-constant funding → tiny variance
    size = kelly_size_usd(50.0, history, capital, cfg)
    assert size <= capital * cfg.max_position_pct + 1e-6


def test_kelly_size_zero_below_threshold(cfg):
    assert kelly_size_usd(15.0, [0.0001] * 5, 100_000, cfg) == 0.0


def test_kelly_size_haircut_for_new_market(cfg):
    big = kelly_size_usd(50.0, [0.0001] * 5, 100_000, cfg, market_age_days=60)
    young = kelly_size_usd(
        50.0, [0.0001] * 5, 100_000, cfg, market_age_days=10
    )
    assert young < big


def test_kelly_size_zero_capital_returns_zero(cfg):
    assert kelly_size_usd(50.0, [0.0001] * 5, 0, cfg) == 0.0
