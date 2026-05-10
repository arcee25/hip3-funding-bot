from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hip3_bot.ostium_feed import OstiumDataFeed


def _fake_client(market_payload):
    client = AsyncMock()
    client.get_market.return_value = market_payload
    return client


@pytest.mark.asyncio
async def test_snapshot_listed_market(cfg):
    payload = {
        "listed": True,
        "funding_8h": 0.00005,
        "mark_price": 80.1,
        "lp_long_usd": 120_000.0,
    }
    feed = OstiumDataFeed(cfg, client=_fake_client(payload))
    snap = await feed.snapshot("WTI")
    assert snap.listed is True
    assert snap.funding_8h == pytest.approx(0.00005)
    assert snap.annualized_apr_pct == pytest.approx(
        0.00005 * 3 * 365 * 100
    )
    assert snap.mark_price == 80.1
    assert snap.lp_liquidity_usd == 120_000.0
    assert snap.coin == "WTI"


@pytest.mark.asyncio
async def test_snapshot_unlisted_returns_listed_false(cfg):
    feed = OstiumDataFeed(cfg, client=_fake_client(None))
    snap = await feed.snapshot("UNKNOWN")
    assert snap.listed is False
    assert snap.lp_liquidity_usd == 0.0
    assert snap.funding_8h == 0.0


@pytest.mark.asyncio
async def test_snapshot_handles_client_error(cfg):
    client = AsyncMock()
    client.get_market.side_effect = RuntimeError("rpc down")
    feed = OstiumDataFeed(cfg, client=client)
    snap = await feed.snapshot("WTI")
    assert snap.listed is False
