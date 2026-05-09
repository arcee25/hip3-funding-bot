"""Layer 2 — funding APR analysis, entry gate, fractional Kelly sizing."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .config import Config
from .models import FundingSnapshot


def annualize_funding(funding_8h: float) -> float:
    """Convert 8-hour funding rate to annualized APR (percent)."""
    return funding_8h * 3 * 365 * 100


def min_hold_hours(annualized_apr_pct: float, fee_drag_bps: float) -> float:
    """Minimum hold (hours) to recoup round-trip fees at the given APR."""
    if annualized_apr_pct <= 0:
        return float("inf")
    return (fee_drag_bps / annualized_apr_pct) * 8760 / 100


@dataclass
class EntryDecision:
    enter: bool
    reasons: list[str]
    snapshot: FundingSnapshot
    consecutive_positive: int


def evaluate_entry(
    snap: FundingSnapshot,
    recent_funding_8h: list[float],
    cfg: Config,
) -> EntryDecision:
    """Four-condition entry gate from the spec."""
    reasons: list[str] = []
    consecutive = _count_leading_positive(recent_funding_8h)

    if snap.annualized_apr_pct <= cfg.min_entry_apr_pct:
        reasons.append(
            f"APR {snap.annualized_apr_pct:.1f}% <= "
            f"{cfg.min_entry_apr_pct:.1f}%"
        )
    if consecutive < cfg.consecutive_positive_funding:
        reasons.append(
            f"{consecutive} consecutive positive funding intervals "
            f"(need {cfg.consecutive_positive_funding})"
        )
    if snap.long_skew <= cfg.long_skew_threshold:
        reasons.append(
            f"long skew {snap.long_skew:.2f} <= "
            f"{cfg.long_skew_threshold:.2f}"
        )
    if snap.book_depth_usd < cfg.min_book_depth_usd:
        reasons.append(
            f"book depth ${snap.book_depth_usd:,.0f} < "
            f"${cfg.min_book_depth_usd:,.0f}"
        )

    return EntryDecision(
        enter=not reasons,
        reasons=reasons,
        snapshot=snap,
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
    apr_pct: float,
    funding_history_8h: list[float],
    capital_usd: float,
    cfg: Config,
    market_age_days: int | None = None,
) -> float:
    """Fractional Kelly notional sizing in USD.

    edge = APR (decimal); variance = annualized variance of historical
    funding. Final fraction is clamped to ``cfg.max_position_pct`` and
    haircut for newly listed markets (<30 days).
    """
    if apr_pct <= cfg.min_entry_apr_pct or capital_usd <= 0:
        return 0.0

    edge = apr_pct / 100.0
    variance = _annualized_variance(funding_history_8h)
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
