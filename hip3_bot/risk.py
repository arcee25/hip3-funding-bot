"""Layer 4 — exit triggers (P0 → P1 → P1b → P2) + delta drift."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .models import ExitReason, FundingSnapshot, OstiumSnapshot, Position


@dataclass
class ExitDecision:
    should_exit: bool
    reason: ExitReason | None
    note: str = ""


def evaluate_exit(
    p: Position,
    hl: FundingSnapshot,
    ostium: OstiumSnapshot,
    deployer_halted: bool,
    cfg: Config,
) -> ExitDecision:
    """Priority-ordered exit check P0 → P1 → P1b → P2."""
    if deployer_halted:
        return ExitDecision(
            True,
            ExitReason.DEPLOYER_HALT,
            "deployer halt detected — emergency exit",
        )
    if hl.funding_8h < 0:
        return ExitDecision(
            True,
            ExitReason.FUNDING_FLIP,
            f"HL funding flipped negative: {hl.funding_8h:.6f}",
        )
    if _ostium_hostile(hl, ostium, cfg):
        return ExitDecision(
            True,
            ExitReason.OSTIUM_HOSTILE,
            "Ostium long funding > "
            f"{cfg.ostium_hostile_funding_ratio:.0%} of HL short funding",
        )
    net = hl.annualized_apr_pct - ostium.annualized_apr_pct
    if net < cfg.exit_apr_pct:
        return ExitDecision(
            True,
            ExitReason.APR_DECAY,
            f"net APR decayed to {net:.1f}%",
        )
    return ExitDecision(False, None)


def _ostium_hostile(
    hl: FundingSnapshot,
    ostium: OstiumSnapshot,
    cfg: Config,
) -> bool:
    """Spec § P1b: Ostium long > ratio × HL short funding."""
    if hl.funding_8h <= 0:
        # Without HL short yield to compare against, treat funding flip
        # as the primary trigger; P1b doesn't apply.
        return False
    return ostium.funding_8h > cfg.ostium_hostile_funding_ratio * hl.funding_8h


def delta_drift(p: Position, hip3_mark: float, ostium_mark: float) -> float:
    """Net delta as a fraction of position notional (+long / -short)."""
    if p.notional_usd <= 0:
        return 0.0
    hip3_value = p.hip3_size * hip3_mark
    hedge_value = p.ostium_size * ostium_mark
    return (hip3_value + hedge_value) / p.notional_usd


def needs_rebalance(drift_frac: float, cfg: Config) -> bool:
    return abs(drift_frac) > cfg.delta_drift_threshold


def target_hedge_size(p: Position, ostium_mark: float) -> float:
    """Ostium size that neutralizes the HIP-3 leg at the current Ostium mark."""
    if ostium_mark <= 0:
        return p.ostium_size
    target_notional = abs(p.hip3_size) * p.hip3_entry_price
    return target_notional / ostium_mark


def realized_apr_pct(p: Position, held_hours: float) -> float:
    if held_hours <= 0 or p.notional_usd <= 0:
        return 0.0
    fee_drag_usd = p.fees_paid_bps / 10_000.0 * p.notional_usd
    net_usd = p.funding_received_usd - fee_drag_usd
    return (net_usd / p.notional_usd) * (8760.0 / held_hours) * 100
