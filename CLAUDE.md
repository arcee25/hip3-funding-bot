# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Delta-neutral funding rate farming bot for Hyperliquid HIP-3 perpetual markets. The bot scans HIP-3 markets for funding rate anomalies (crowded retail longs in commodities like WTI, Brent, Silver), enters delta-neutral positions (short HIP-3 perp + long hedge), and extracts funding yield. Python 3.11+.

## Architecture (5 Layers)

1. **Data Layer** — Hyperliquid WebSocket feed (funding rates, mark prices, OI) with REST API fallback at 1s interval. Ostium perp feed (Pyth-priced, on Arbitrum) for hedge mark price + funding.
2. **Signal Engine** — Funding rate normalization (8h → annualized APR), crowding detection (OI skew), entry threshold evaluation (net APR after 28bps combined round-trip fees), Kelly-fraction position sizing.
3. **Execution** — Two-leg order routing: Leg A shorts HIP-3 perp on Hyperliquid, Leg B longs the matching Ostium perp on Arbitrum. Delta target = 0 ± 2%, rebalanced every 15 min. Both venues pre-funded — no in-flight bridging.
4. **Risk Monitor** — Priority-ordered exit triggers: P0 deployer halt (5s polling), P1 HL funding flip negative, P1b Ostium hedge funding turns hostile, P2 net APR decay below 10%, P3 delta drift >5% rebalance, P4 planned rotation at 30%+ realized APR.
5. **Reporting** — Telegram alerts (mode-tagged `[DRY-RUN]` in non-live modes), SQLite with separate `trade_log` (live fills) and `simulated_trade_log` (scanner/paper) tables, daily realized vs. projected APR report consuming both.

## Key Libraries

- `hyperliquid-python-sdk` — HL order placement, account management, WebSocket
- `ostium-python-sdk` (or `web3.py` + Ostium contract ABIs) — Ostium perp on Arbitrum for hedge leg (WTI, Brent, XAU, XAG perps)
- `pandas` / `numpy` — funding rate analysis, Kelly calculation
- `aiohttp` / `asyncio` — async WebSocket + REST
- `python-telegram-bot` — alerts
- `APScheduler` — cron-style scheduling for rebalance/reporting
- `sqlite3` — persistence (built-in)

## Critical Business Rules

- **Entry gate** requires ALL six conditions: net APR (HL funding − Ostium funding) > 20%, 3+ consecutive positive HL funding intervals, OI long skew > 60% on HL, HL book depth > $50k, Ostium lists same underlying with LP liquidity > $50k long-side, basis |Ostium mark − HL mark| / HL mark < 0.5%
- **Combined fee drag**: HL HIP-3 round-trip = 18bps (taker = 9bps, 2x standard) + Ostium round-trip ≈ 10bps = **28bps total** — always pre-calculate before entry
- **Position sizing**: fractional Kelly (0.25x), capped at 10% of capital per position. Reduce for wide spreads or markets < 30 days old
- **No fallback hedge**: if Ostium can't cover the underlying cleanly (not listed, thin LP, basis > 50bps), skip the signal and Telegram-alert. Proxy hedges reintroduce directional risk the 28bps fee math can't absorb.
- **Pre-funded venues**: USDC margin lives on both Hyperliquid AND Ostium (default 50/50, operator-configurable). Bot never bridges capital in the entry hot path.
- **Per-venue counterparty cap**: max 50% of strategy capital on either Hyperliquid or Ostium at any time
- **Deployer halt**: monitor HIP-3 contract events every 5s — deployer can settle to mark price, must exit before settlement
- **Runtime modes**: bot runs in one of three modes via config (`mode: scanner | paper | live`), fixed at process start. `scanner` = mainnet feeds, no orders, would-be entries logged to `simulated_trade_log`. `paper` = HL testnet + Ostium Sepolia, real testnet API calls. `live` = mainnet with capital at risk, requires `--confirm-live` CLI flag. Same binary across modes — flip the flag, restart cleanly.

## APR Formulas

```python
hl_apr         = hl_funding_8h     * 3 * 365 * 100
ostium_apr     = ostium_funding_8h * 3 * 365 * 100
net_apr        = hl_apr - ostium_apr
fee_drag_bps   = 28  # HL 18 + Ostium ~10 (verify against current Ostium fees)
min_hold_hours = (fee_drag_bps / 100 / net_apr) * 8760
kelly_f        = edge / variance
size           = min(kelly_f * 0.25, 0.10) * capital
```

## Build Phases

The spec defines a phased rollout: Phase 1 (data layer + scanner + Telegram alerts), Phase 2 (paper trading on HL testnet + Ostium Sepolia testnet), Phase 3 (live with 5-10% capital, pre-funded HL + Ostium mainnet on Arbitrum), Phase 4 (scale + multi-market rotation + cross-venue capital auto-rebalance). See `hip3-funding-bot-spec.md` for full details.
