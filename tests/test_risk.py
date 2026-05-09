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
