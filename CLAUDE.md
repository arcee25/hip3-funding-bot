# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Delta-neutral funding rate farming bot for Hyperliquid HIP-3 perpetual markets. Hedge leg is Ostium perp on Arbitrum (Pyth oracle), not IBKR/CME ETFs. Strategy: scan HIP-3 markets for crowded retail longs (commodities — WTI, Brent, Silver), enter delta-neutral (short HIP-3 perp + long Ostium perp), extract net funding yield. Spec version: 1.1. Python 3.11+.

## Architecture (5 Layers)

1. **Data** — Hyperliquid WS/REST funding+mark+OI; Ostium perp feed over web3 (mark, funding, LP liquidity, listed status).
2. **Signal Engine** — Net APR (HL APR − Ostium APR), 6-condition entry gate, fractional-Kelly sizing.
3. **Execution** — Two-leg routing: Leg A short HIP-3 (limit-then-slide), Leg B long Ostium perp (max-slippage 30 bps, oracle-deviation retry once). Delta target 0 ± 2%, rebalance every 15 min on Ostium only.
4. **Risk Monitor** — P0 deployer halt > P1 HL funding flip > **P1b Ostium funding hostile (Ostium long > 50% HL short)** > P2 net APR < 10% > P3 delta drift > 5% > P4 planned rotation.
5. **Reporting** — Telegram (mode-tagged), SQLite (`trade_log` + `simulated_trade_log`), daily realized vs projected APR.

## Runtime Modes

`mode: scanner | paper | live` from config; fixed at process start.

| Mode | Feeds | Order Placement | Storage |
|---|---|---|---|
| `scanner` | mainnet | none — log would-be entries | `simulated_trade_log` |
| `paper` | testnet (HL testnet + Ostium Sepolia) | real testnet API | `simulated_trade_log` |
| `live` | mainnet | real mainnet | `trade_log` |

`live` requires explicit `--confirm-live` CLI flag at startup. Telegram alerts in `scanner`/`paper` are tagged `[DRY-RUN]`.

## Critical Business Rules

- **Net APR** = HL funding APR − Ostium funding APR. The signal threshold (20%) is on net, not raw HL.
- **Six-condition entry gate** (ALL required): net APR > 20%; ≥3 consec positive HL funding; HL OI long skew > 60%; HL top-of-book depth > $50k; **Ostium lists same underlying with LP > $50k long-direction**; **basis `|ostium_mark − hl_mark| / hl_mark < 0.005`**.
- **Round-trip fee drag = 28 bps** (HL 18 + Ostium 10). Pre-calculated before every entry.
- **Position sizing**: fractional Kelly (0.25×), capped 10% of capital per position. Haircut for markets < 30 days old.
- **No proxy hedges** — if Ostium doesn't list the underlying, has < $50k LP, or basis exceeds 50 bps: skip the signal and Telegram-alert. Spec line 123 forbids fallback hedges (HL native, ETF, etc.) — they reintroduce directional risk that 28 bps fee math cannot absorb.
- **Pre-funded margin** — USDC on both Hyperliquid AND Ostium (Arbitrum-deposited), default 50/50. The bot does NOT bridge in the entry hot path. Cross-venue rebalance is Phase 4.
- **Deployer halt** — monitor HIP-3 contract events every 5s; settle to mark before HL settles.

## Key Formulas

```python
hl_apr      = hl_funding_8h     * 3 * 365 * 100
ostium_apr  = ostium_funding_8h * 3 * 365 * 100
net_apr     = hl_apr - ostium_apr
fee_drag_bps    = 28          # HL 18 + Ostium 10
min_hold_hours  = (fee_drag_bps / 100 / net_apr) * 8760
size = min(kelly_f * 0.25, 0.10) * capital
```

## Key Libraries

- `hyperliquid-python-sdk` — HL order placement + WebSocket
- `web3.py` — Ostium contract calls on Arbitrum (until `ostium-python-sdk` is verified available)
- `pandas` / `numpy` — funding analysis, Kelly
- `aiohttp` / `asyncio` — async I/O
- `python-telegram-bot` — alerts
- `APScheduler` — rebalance/reporting cron
- `sqlite3` — persistence (built-in)

## Build Phases

Phase 1 (scanner mode + alerts) ✅; Phase 2 (paper trading on HL testnet + Ostium Sepolia) — code complete, pending live Sepolia smoke; Phase 3 (live with 5-10% capital + `--confirm-live` flag) — Ostium SDK now wired (`hip3_bot._ostium_router.OstiumRouterClient` over `ostium-python-sdk`); pre-funded margin guardrail still TODO; Phase 4 (multi-market rotation + cross-venue capital auto-rebalance) deferred.

## Where the Ostium leg is wired

- `hip3_bot/_ostium_router.py` — `OstiumRouterClient` (real, SDK-backed) + `PairResolver` (coin → pair_id, async-locked cache of `subgraph.get_pairs()`).
- `hip3_bot/ostium_feed.py` — async `OstiumDataFeed.snapshot(coin)` using the router client; the `OstiumClient` Protocol is async-only.
- `hip3_bot/ostium_adapter.py` — async `OstiumHedgeAdapter.buy/sell`; `Fill.trade_index` is returned from `buy`, required on `sell`.
- `hip3_bot/execution.py` — `OrderRouter` persists `trade_index` on `Position.ostium_trade_index` from the open's `Fill`, and threads it back into `close_delta_neutral`, `_unwind_partial`, and `rebalance_hedge` calls.
- Field names for funding rate (`FUNDING_FIELDS`) and LP liquidity (`LP_FIELDS`) on the Ostium subgraph payload are best-effort candidates pending Sepolia smoke verification (see `docs/superpowers/plans/2026-05-10-hip3-funding-bot-phase3-ostium.md` Task 6).
