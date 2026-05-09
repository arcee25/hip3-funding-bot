"""Layer 2 — net APR + 6-condition entry gate + fractional Kelly sizing."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .config import Config
from .models import FundingSnapshot, OstiumSnapshot


def annualize_funding(funding_8h: float) -> float:
    """Convert 8-hour funding rate to annualized APR (percent)."""
    return funding_8h * 3 * 365 * 100


def net_apr_pct(
    hl: FundingSnapshot, ostium: OstiumSnapshot
) -> float:
    """Spec § Step 02: net APR = HL APR − Ostium APR."""
    return hl.annualized_apr_pct - ostium.annualized_apr_pct


def min_hold_hours(net_apr_pct_value: float, fee_drag_bps: float) -> float:
    """Minimum hold (hours) to recoup round-trip fees at the given net APR."""
    if net_apr_pct_value <= 0:
        return float("inf")
    return (fee_drag_bps / net_apr_pct_value) * 8760 / 100


def basis_pct(hl: FundingSnapshot, ostium: OstiumSnapshot) -> float:
    if hl.mark_price <= 0:
        return float("inf")
    return abs(ostium.mark_price - hl.mark_price) / hl.mark_price


@dataclass
class EntryDecision:
    enter: bool
    reasons: list[str]
    hl_snapshot: FundingSnapshot
    ostium_snapshot: OstiumSnapshot
    net_apr_pct: float
    consecutive_positive: int


def evaluate_entry(
    hl: FundingSnapshot,
    ostium: OstiumSnapshot,
    recent_hl_funding_8h: list[float],
    cfg: Config,
) -> EntryDecision:
    """Six-condition entry gate from spec v1.1 § Step 03."""
    reasons: list[str] = []
    consecutive = _count_leading_positive(recent_hl_funding_8h)
    net = net_apr_pct(hl, ostium)

    # 1) Net APR > threshold
    if net <= cfg.min_entry_apr_pct:
        reasons.append(
            f"net APR {net:.1f}% <= {cfg.min_entry_apr_pct:.1f}%"
        )
    # 2) Consecutive positive HL funding
    if consecutive < cfg.consecutive_positive_funding:
        reasons.append(
            f"{consecutive} consecutive positive HL funding intervals "
            f"(need {cfg.consecutive_positive_funding})"
        )
    # 3) HL OI long skew
    if hl.long_skew <= cfg.long_skew_threshold:
        reasons.append(
            f"long skew {hl.long_skew:.2f} <= "
            f"{cfg.long_skew_threshold:.2f}"
        )
    # 4) HL book depth
    if hl.book_depth_usd < cfg.min_book_depth_usd:
        reasons.append(
            f"HL book depth ${hl.book_depth_usd:,.0f} < "
            f"${cfg.min_book_depth_usd:,.0f}"
        )
    # 5) Ostium listed + LP liquidity
    if not ostium.listed:
        reasons.append(f"Ostium does not list {hl.coin}")
    elif ostium.lp_liquidity_usd < cfg.min_ostium_lp_usd:
        reasons.append(
            f"Ostium LP ${ostium.lp_liquidity_usd:,.0f} < "
            f"${cfg.min_ostium_lp_usd:,.0f}"
        )
    # 6) Basis check
    if ostium.listed:
        b = basis_pct(hl, ostium)
        if b >= cfg.max_basis_pct:
            reasons.append(
                f"basis {b:.4f} >= {cfg.max_basis_pct:.4f} "
                f"({b * 10_000:.0f} bps cap)"
            )

    return EntryDecision(
        enter=not reasons,
        reasons=reasons,
        hl_snapshot=hl,
        ostium_snapshot=ostium,
        net_apr_pct=net,
        consecutive_positive=consecutive,
    )


def _count_leading_positive(history: list[float]) -> int:
    n = 0
    for f in history:
        if f > 0:
            n += 1
        else:
            break
    return n


def kelly_size_usd(
    net_apr_pct_value: float,
    hl_funding_history_8h: list[float],
    capital_usd: float,
    cfg: Config,
    market_age_days: int | None = None,
) -> float:
    """Fractional Kelly notional in USD using NET APR as the edge."""
    if net_apr_pct_value <= cfg.min_entry_apr_pct or capital_usd <= 0:
        return 0.0

    edge = net_apr_pct_value / 100.0
    variance = _annualized_variance(hl_funding_history_8h)
    if variance <= 0:
        kelly_f = cfg.max_position_pct / cfg.kelly_fraction
    else:
        kelly_f = edge / variance

    fraction = min(kelly_f * cfg.kelly_fraction, cfg.max_position_pct)
    if market_age_days is not None and market_age_days < 30:
        fraction *= max(0.25, market_age_days / 30.0)
    return max(0.0, fraction) * capital_usd


def _annualized_variance(history: list[float]) -> float:
    if len(history) < 2:
        return 0.0
    annualized = [annualize_funding(f) / 100.0 for f in history]
    return statistics.pvariance(annualized)
