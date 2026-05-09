# HIP-3 Funding Rate Farming Bot — Full Specification

**Strategy:** Delta-neutral yield extraction on Hyperliquid HIP-3 perpetual markets  
**Version:** 1.1 (crypto-native hedge via Ostium; replaces v1.0 IBKR/CME hedge)  
**Tags:** `Delta-Neutral` `Fully Automated` `HIP-3 Native` `Crypto-Native Hedge` `Python 3.11+`

---

## Overview

This bot continuously scans all active HIP-3 perpetual markets on Hyperliquid, identifies funding rate anomalies caused by crowded retail positioning (predominantly longs in commodities like WTI, Brent, Silver), and enters delta-neutral positions to extract funding yield with near-zero directional market exposure. The 2x HIP-3 fee structure is accounted for in all entry/exit thresholds.

### Key Parameters

| Parameter | Value |
|---|---|
| Minimum Entry APR | 20% annualized |
| Maximum Position Size | 10% of capital |
| Round-Trip Fee Drag | 28 bps (HL HIP-3 18 bps + Ostium hedge ~10 bps) |
| Scan Interval | 30 seconds (WebSocket) |
| Target APR Range | 20–40% annualized |

---

## System Architecture

### Layer 1 — Data
- Hyperliquid WebSocket feed (funding rates, mark prices, OI)
- REST API poller (fallback, 1s interval)
- Ostium perp feed via Pyth oracle on Arbitrum (hedge mark price + funding rate)

### Layer 2 — Signal Engine
- Funding rate normalizer (8h → annualized APR)
- Crowding detector (OI skew, long/short ratio)
- Entry threshold evaluator (net APR after fees)
- Position sizing calculator (Kelly-fraction)

### Layer 3 — Execution
- Order router (HIP-3 perp short leg)
- Delta hedge router (Ostium perp on Arbitrum)
- Slippage estimator pre-trade
- Cross-margin account manager

### Layer 4 — Risk Monitor
- Funding flip detector (exit trigger)
- Delta drift monitor (rebalance trigger)
- Deployer halt watcher (emergency exit)
- P&L tracker + fee drag calculator

### Layer 5 — Reporting
- Telegram alert bot (mode-tagged: `[DRY-RUN]` prefix in `scanner`/`paper`)
- SQLite trade log (separate tables: `trade_log` for live fills, `simulated_trade_log` for `scanner`/`paper`)
- Daily APR realized vs. projected report (consumes both tables)

---

## Runtime Modes

The bot supports three runtime modes via config flag (`mode: scanner | paper | live`). All modes share the same code paths — the difference is what happens at order-placement time and which storage table receives the fill record.

| Mode | Data Feeds | Signal Engine | Order Placement | Storage |
|---|---|---|---|---|
| `scanner` | Mainnet (HL + Ostium) | Full evaluation including `entry_ok` | **None** — log would-be entry as JSON event | `simulated_trade_log` |
| `paper` | Testnet (HL testnet + Ostium Sepolia) | Full evaluation | Real testnet API calls | `simulated_trade_log` |
| `live` | Mainnet (HL + Ostium) | Full evaluation | Real mainnet API calls with capital at risk | `trade_log` |

**Key invariants:**
- `scanner` and `paper` produce the same daily APR report format, fed from `simulated_trade_log`. This lets you compare projected vs. realized APR against a parallel `live` run.
- A bot configured for `live` may be started in `scanner` or `paper` first to verify health before flipping the flag — same binary, same config, different mode.
- Mode is fixed at process start. Switching modes requires a clean restart to prevent half-state mid-trade.
- `mode: live` requires an explicit `--confirm-live` CLI flag at startup to prevent accidental capital deployment.
- Telegram alerts fire in all modes; alerts in `scanner`/`paper` are tagged `[DRY-RUN]` so they're visually distinct from live execution.
- Exit triggers (P0/P1/P1b/P2/P3/P4) are evaluated in all modes — in `scanner` they fire as logged "would-have-exited" events; in `paper` they execute against testnet; in `live` they execute against mainnet.

---

## Signal & Entry Logic

### Step 01 — Funding Rate Scan

Poll all HIP-3 markets every 30s via WebSocket. Normalize raw 8-hour funding rate to annualized APR:

```python
annualized_apr = funding_8h * 3 * 365 * 100
```

### Step 02 — Fee Drag Calculation

HIP-3 taker fee = 9 bps (2x standard); round-trip = 18 bps. Ostium taker fee ≈ 5 bps (verify against current Ostium fee schedule); round-trip = 10 bps. Combined two-leg round-trip = 28 bps. Minimum net APR threshold must exceed break-even holding period.

```python
hl_round_trip_bps     = 18
ostium_round_trip_bps = 10  # verify against current Ostium fee schedule
fee_drag_bps          = hl_round_trip_bps + ostium_round_trip_bps  # 28
min_hold_hours        = (fee_drag_bps / 100 / net_apr) * 8760
```

### Step 03 — Entry Gate

Enter only if all six conditions are met:
1. Net APR (HL funding − Ostium funding) > 20%, with fee drag amortized via `min_hold_hours`
2. HL funding consistently positive for 3+ consecutive intervals
3. OI skew > 60% long on HL
4. HL top-of-book depth > $50,000
5. Ostium lists the same underlying with available LP liquidity > $50,000 in the long-hedge direction
6. Basis at entry: `|ostium_mark − hl_mark| / hl_mark < 0.005` (50 bps cap)

```python
hl_apr     = hl_funding_8h     * 3 * 365 * 100
ostium_apr = ostium_funding_8h * 3 * 365 * 100
net_apr    = hl_apr - ostium_apr  # fee drag amortized via min_hold_hours

entry_ok = (
    net_apr > 20 and
    consecutive_positive >= 3 and
    long_skew > 0.60 and
    hl_book_depth > 50_000 and
    ostium_listed and ostium_long_liquidity > 50_000 and
    abs(ostium_mark - hl_mark) / hl_mark < 0.005
)
```

If Ostium does not list the underlying, has insufficient LP liquidity, or basis exceeds 50 bps, **skip the signal and Telegram-alert**. No fallback hedge — the strategy depends on clean delta neutrality, and proxy hedges (e.g., HL native perp on a different underlying) reintroduce directional risk that the 28 bps fee math cannot absorb.

### Step 04 — Position Sizing

Use fractional Kelly. Max single position = 10% of capital. Reduce size if spread is wide or if market is newly listed (<30 days).

```python
kelly_f = edge / variance
size = min(kelly_f * 0.25, 0.10) * capital
```

---

## Trade Execution Flow

### Leg A — Short HIP-3 Perp

1. Place limit order at mid-price on HIP-3 market (e.g. WTI-PERP on Trade.XYZ)
2. If unfilled after 10s, slide to best ask − 1 tick
3. Record fill price, size, fee paid
4. Set stop-loss at entry + 3% (emergency only — not expected to trigger in delta-neutral setup)

### Leg B — Long Hedge (Ostium perp on Arbitrum)

1. Simultaneously submit a long market order on Ostium against the LP, in parallel with Leg A
2. Set max-slippage tolerance to 30 bps — Ostium reverts orders that exceed oracle-deviation bounds
3. If the order reverts due to oracle deviation, retry once after a 2s delay; otherwise abort and unwind Leg A
4. Target delta = 0 ± 2% at all times
5. Hedge ratio recalculated every 15 minutes — rebalance executed on Ostium only

**Pre-funding:** maintain USDC margin on both Hyperliquid AND Ostium (Arbitrum-deposited USDC), default 50/50 allocation, operator-configurable. The bot does NOT bridge capital in the entry hot path — bridge latency would break delta neutrality between the two legs. Cross-venue rebalance is a Phase 4 capability.

---

## Exit Triggers (Priority Order)

| Priority | Trigger | Action |
|---|---|---|
| **P0** | Deployer Halt Detected | Immediate market close both legs. Deployer can settle to mark price — exit before this happens. Monitor HIP-3 contract events every 5s. |
| **P1** | HL Funding Flips Negative | Close within next funding interval. Do not wait — negative funding means you now PAY instead of receive. 30-minute grace to find better price. |
| **P1b** | Ostium Hedge Funding Turns Hostile | Same urgency as P1 — close both legs within the next funding interval. Hostile = Ostium long-side funding > 50% of remaining HL short-side funding (yield drag exceeds tolerance). |
| **P2** | Net APR Decays Below 10% | Initiate graceful unwind over 2–4 hours using limit orders to minimize slippage. Not urgent. |
| **P3** | Delta Drift > 5% | Rebalance hedge leg only. Do not close position. Maintain delta neutrality. |
| **P4** | Planned Exit (APR Target Hit) | If realized APR over holding period exceeds 30% annualized, consider rotating capital to higher-APR market. |

---

## Implementation Stack

| Library | Purpose | Install |
|---|---|---|
| `hyperliquid-python-sdk` | Official SDK for order placement, account management, WebSocket feeds | `pip install hyperliquid-python` |
| `ostium-python-sdk` (or `web3.py` + Ostium contract ABIs) | Ostium perp order submission, position queries, funding-rate reads on Arbitrum | `pip install ostium-python-sdk` (verify package name; fall back to raw `web3.py` if SDK is unavailable) |
| `pandas / numpy` | Funding rate time-series analysis, Kelly calculation | `pip install pandas numpy` |
| `aiohttp / asyncio` | Async WebSocket feed management + REST fallback | `pip install aiohttp` |
| `python-telegram-bot` | Real-time alerts: entry, exit, errors, daily P&L | `pip install python-telegram-bot` |
| `sqlite3` | Trade log, funding history, position state persistence | built-in |
| `APScheduler` | Cron-style scheduling for delta rebalance, reporting | `pip install apscheduler` |

---

## Risk Matrix

| Risk | Severity | Probability | Mitigation |
|---|---|---|---|
| Deployer halts market | HIGH | LOW | Monitor contract events every 5s, P0 emergency exit protocol |
| Oracle manipulation / lag | MED | MED | Only trade top-5 HIP-3 markets by OI (deepest oracles), validate mark vs. external price |
| Funding flips suddenly | MED | MED | P1 exit trigger, trailing funding monitor, never hold through funding without check |
| Ostium outage / Arbitrum sequencer downtime | MED | LOW | Skip new entries; existing positions remain delta-neutral until sequencer recovers; documented manual unwind playbook for prolonged outages |
| Ostium funding turns hostile mid-hold | MED | MED | P1b exit trigger; never enter when Ostium funding exceeds 50% of HL funding |
| Ostium oracle deviation rejects orders | LOW | MED | Retry once with 2s delay; if persistent, skip signal and Telegram-alert |
| Ostium LP liquidity / basis widens vs HL mark | LOW | MED | 50 bps basis check at entry; minimum LP liquidity $50k for long-direction |
| Counterparty concentration on Ostium | MED | LOW | Cap per-venue exposure at 50% of strategy capital |
| 2x fee drag eats yield | MED | HIGH | Hard min APR threshold (20%), fee drag pre-calculated before every entry |
| Regulatory action on RWA perps | HIGH | LOW | Position limits, rapid unwind capability, monitor news feed |
| Slippage on thin books | LOW | MED | Book depth check ($50k min), limit orders only, size cap 10% capital |
| Operator launches with wrong mode flag (live when scan/paper intended) | MED | LOW | Loud startup banner showing active mode; `mode: live` requires explicit `--confirm-live` CLI flag; Telegram startup alert with mode and capital allocation |

---

## Phased Build Roadmap

### Phase 1 — Data Layer + Scanner (Week 1–2)

**Tasks:**
- Connect HL WebSocket feed
- Build funding rate normalizer
- Store history in SQLite
- Build Telegram alerter for high-APR signals

**Deliverable:** Scanner bot that alerts you when APR > 20% — runs as `mode: scanner` against mainnet feeds, no order placement, all signals logged to `simulated_trade_log`

---

### Phase 2 — Paper Trading Execution (Week 3–4)

**Tasks:**
- Integrate HL SDK order placement (testnet)
- Build delta-neutral entry logic
- Simulate hedge leg against Ostium testnet (Arbitrum Sepolia)
- Log all simulated trades + P&L

**Deliverable:** Full paper trading bot — runs as `mode: paper` against HL testnet + Ostium Sepolia, all fills logged to `simulated_trade_log`, daily APR report produced

---

### Phase 3 — Live Execution, Small Size (Week 5–6)

**Tasks:**
- Connect Ostium SDK for hedge leg on Arbitrum mainnet
- Pre-fund both Hyperliquid and Ostium (default 50/50 USDC allocation)
- Go live with 5–10% of capital max
- Validate delta drift + rebalance logic
- Tune APR thresholds from real data

**Deliverable:** Live bot — runs as `mode: live` (requires `--confirm-live` startup flag) against mainnet, small size, all exits tested. `mode: scanner` and `mode: paper` remain available on the same binary for validation runs.

---

### Phase 4 — Scale + Optimize (Week 7+)

**Tasks:**
- Increase position sizes as confidence grows
- Add multi-market rotation (WTI → Silver → Gold)
- Optimize fee tier via volume accumulation
- Add P&L dashboard
- Add cross-venue capital auto-rebalance between Hyperliquid and Ostium as sizes scale

**Deliverable:** Full production bot, multi-market

---

*HIP-3 Funding Rate Farming Bot Spec — v1.1*
