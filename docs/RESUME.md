# Resume Guide

How to pick this project up in a future Claude Code session.

## State at last checkpoint

- **Repo:** https://github.com/arcee25/hip3-funding-bot (branch `main`, 74 tests passing)
- **Local:** `D:\work\hip3-funding-bot`
- **Plans:**
  - `docs/superpowers/plans/2026-05-09-hip3-funding-bot.md` — v1.0 plan (superseded)
  - `docs/superpowers/plans/2026-05-10-hip3-funding-bot-v1.1-migration.md` ✅ done
  - `docs/superpowers/plans/2026-05-10-hip3-funding-bot-phase3-ostium.md` — Tasks 1-5, 7 done; **Task 6 is the next checkpoint**
- **Blocker:** `OstiumRouterClient` (`hip3_bot/_ostium_router.py`) ships with best-effort field-name candidates (`FUNDING_FIELDS`, `LP_FIELDS`) that need verification against a live Arbitrum Sepolia subgraph response. Until verified, paper/live entries fail closed (LP=0 always trips entry-gate condition #5).

## Resume prompt

Open `D:\work\hip3-funding-bot` in a fresh Claude Code session and paste:

> Resume the Phase 3 Ostium plan at `docs/superpowers/plans/2026-05-10-hip3-funding-bot-phase3-ostium.md`. Tasks 1-5 and 7 landed on `main` (commits `da40dcc` through `0baa38f`). Next up is Task 6 — Sepolia smoke verification of `FUNDING_FIELDS` / `LP_FIELDS` in `hip3_bot/_ostium_router.py`. My Sepolia credentials are in `.env`. Run the inspection script per the plan, update field names if needed, and continue. After Task 6, the deferred Phase-3 work is the pre-funded margin guardrail and order-receipt fee/size parsing — list those as a follow-up plan, don't auto-execute.

## Sepolia credentials checklist

Collect before resuming:

- **RPC URL** — free tier from Alchemy / Infura / QuickNode (any Arbitrum Sepolia endpoint) → `OSTIUM_RPC_URL`
- **Funded testnet wallet:**
  ```bash
  python -c "from eth_account import Account; a = Account.create(); print(a.key.hex(), a.address)"
  ```
  Private key → `OSTIUM_PRIVATE_KEY`, address → `OSTIUM_ACCOUNT_ADDRESS`
- **Sepolia ETH for gas** — public faucet (Alchemy / QuickNode / Chainlink Sepolia)
- **Test USDC** — Ostium testnet faucet, linked from https://docs.ostium.io/
- Set in `.env`: `MODE=paper`, `OSTIUM_USE_TESTNET=true`

## Health check on resume

```bash
git status              # only .env / .claude / *.db should be untracked
pip install -r requirements.txt
pytest tests/           # expect 74 passed
```

If those three pass, you're back where you left off.

## Deferred work (after Task 6)

From the Phase 3 plan's "Phase 3 Deferrals" section:

- Pre-funded margin guardrail (read HL `user_state` + Ostium account margin at startup; refuse `mode=live` if either is below an operator floor)
- Parse `fees_usd` and close-side `size` from real Ostium SDK receipts (currently both return `0.0`)
- TTL cache on `PairResolver.pair_record` (currently re-queries subgraph every snapshot)
- Phase 4: cross-venue capital auto-rebalance, multi-market rotation
