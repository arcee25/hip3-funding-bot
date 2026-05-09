"""Layer 4 — exit triggers and delta drift monitoring."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .models import ExitReason, FundingSnapshot, Position


@dataclass
class ExitDecision:
    should_exit: bool
    reason: ExitReason | None
    note: str = ""


def evaluate_exit(
    p: Position,
    snap: FundingSnapshot,
    deployer_halted: bool,
    cfg: Config,
) -> ExitDecision:
    """Priority-ordered exit check P0 → P2.

    P3 (delta drift) is handled separately via :func:`needs_rebalance`;
    it triggers a hedge-only rebalance, not a position close.
    P4 (planned rotation) is a strategy-level decision evaluated outside
    the per-snapshot exit path.
    """
    if deployer_halted:
        return ExitDecision(
            True,
            ExitReason.DEPLOYER_HALT,
            "deployer halt detected — emergency exit",
        )
    if snap.funding_8h < 0:
        return ExitDecision(
            True,
            ExitReason.FUNDING_FLIP,
            f"funding flipped negative: {snap.funding_8h:.6f}",
        )
    if snap.annualized_apr_pct < cfg.exit_apr_pct:
        return ExitDecision(
            True,
            ExitReason.APR_DECAY,
            f"APR decayed to {snap.annualized_apr_pct:.1f}%",
        )
    return ExitDecision(False, None)


def delta_drift(p: Position, hip3_mark: float, hedge_mark: float) -> float:
    """Net delta as a fraction of position notional (+long / -short)."""
    if p.notional_usd <= 0:
        return 0.0
    hip3_value = p.hip3_size * hip3_mark
    hedge_value = p.hedge_size * hedge_mark
    return (hip3_value + hedge_value) / p.notional_usd


def needs_rebalance(drift_frac: float, cfg: Config) -> bool:
    return abs(drift_frac) > cfg.delta_drift_threshold


def target_hedge_size(p: Position, hedge_mark: float) -> float:
    """Hedge size that neutralizes the HIP-3 leg at the current hedge mark."""
    if hedge_mark <= 0:
        return p.hedge_size
    target_notional = abs(p.hip3_size) * p.hip3_entry_price
    return target_notional / hedge_mark


def realized_apr_pct(p: Position, held_hours: float) -> float:
    if held_hours <= 0 or p.notional_usd <= 0:
        return 0.0
    fee_drag_usd = p.fees_paid_bps / 10_000.0 * p.notional_usd
    net_usd = p.funding_received_usd - fee_drag_usd
    return (net_usd / p.notional_usd) * (8760.0 / held_hours) * 100
