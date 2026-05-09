from __future__ import annotations

from hip3_bot.models import ExitReason
from hip3_bot.risk import (
    delta_drift,
    evaluate_exit,
    needs_rebalance,
    realized_apr_pct,
    target_hedge_size,
)

from .conftest import make_position, make_snapshot


def _snap_with_funding(funding_8h: float, apr: float):
    snap = make_snapshot(apr_pct=apr)
    snap.funding_8h = funding_8h
    return snap


def test_p0_deployer_halt_takes_priority(cfg):
    decision = evaluate_exit(
        make_position(),
        _snap_with_funding(0.0001, 25.0),
        deployer_halted=True,
        cfg=cfg,
    )
    assert decision.should_exit
    assert decision.reason == ExitReason.DEPLOYER_HALT


def test_p1_funding_flip_negative(cfg):
    decision = evaluate_exit(
        make_position(),
        _snap_with_funding(-0.0001, 25.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert decision.should_exit
    assert decision.reason == ExitReason.FUNDING_FLIP


def test_p2_apr_decay_below_threshold(cfg):
    decision = evaluate_exit(
        make_position(),
        _snap_with_funding(0.0000001, 5.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert decision.should_exit
    assert decision.reason == ExitReason.APR_DECAY


def test_no_exit_when_healthy(cfg):
    decision = evaluate_exit(
        make_position(),
        _snap_with_funding(0.0001, 25.0),
        deployer_halted=False,
        cfg=cfg,
    )
    assert not decision.should_exit


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
    # If hedge mark doubles, half as many units neutralize the leg.
    assert abs(target_hedge_size(p, hedge_mark=160.0) - 62.5) < 1e-9


def test_realized_apr_pct_zero_for_zero_hold():
    p = make_position()
    assert realized_apr_pct(p, 0) == 0.0


def test_realized_apr_pct_positive_when_funding_exceeds_fees():
    p = make_position(notional_usd=10_000)
    p.funding_received_usd = 100.0  # $100 over period
    p.fees_paid_bps = 9.0           # 9 bps = $9 of $10k
    apr = realized_apr_pct(p, held_hours=24.0)
    assert apr > 0
