from __future__ import annotations

import math

import pytest

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


def test_min_hold_hours_zero_net_apr_is_infinite():
    assert min_hold_hours(0.0, 28.0) == float("inf")


def test_basis_pct():
    hl = make_snapshot()
    os = make_ostium_snapshot(mark_price=80.4)
    assert basis_pct(hl, os) == pytest.approx(0.005)


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
