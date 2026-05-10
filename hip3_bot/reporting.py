"""Layer 5 — daily realized vs projected APR report."""
from __future__ import annotations

from datetime import datetime

from .db import Database
from .models import Mode
from .risk import realized_apr_pct


def daily_report(
    db: Database, mode: Mode, now: datetime | None = None
) -> str:
    now = now or datetime.utcnow()
    open_positions = db.open_positions(mode)
    closed = db.closed_in_last_day(mode, now)

    lines = [
        f"📊 Daily Report ({mode.value}) — {now:%Y-%m-%d %H:%M}Z"
    ]
    lines.append(f"Open positions: {len(open_positions)}")

    for p in open_positions:
        held_h = (now - p.opened_at).total_seconds() / 3600.0
        realized = realized_apr_pct(p, held_h)
        lines.append(
            f"  • {p.coin}: ${p.notional_usd:,.0f}  "
            f"projected {p.entry_net_apr_pct:.1f}%  "
            f"realized {realized:.1f}%  "
            f"held {held_h:.1f}h"
        )

    if closed:
        total_pnl = sum(p.realized_pnl_usd for p in closed)
        lines.append("")
        lines.append(f"Closed (24h): {len(closed)}, total ${total_pnl:,.2f}")
        for p in closed:
            lines.append(
                f"  • {p.coin}: ${p.realized_pnl_usd:+,.2f}  "
                f"reason {p.exit_reason.value if p.exit_reason else '-'}"
            )
    return "\n".join(lines)
