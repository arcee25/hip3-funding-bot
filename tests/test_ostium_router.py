from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hip3_bot._ostium_router import OstiumRouterClient, PairResolver


def _fake_sdk(pairs):
    sdk = MagicMock()
    sdk.subgraph = MagicMock()
    sdk.subgraph.get_pairs = AsyncMock(return_value=pairs)
    sdk.price = MagicMock()
    sdk.price.get_price = AsyncMock(return_value=(80.0, None, None))
    sdk.ostium = MagicMock()
    sdk.ostium.set_slippage_percentage = MagicMock()
    sdk.ostium.perform_trade = MagicMock(
        return_value={"transactionHash": "0xabc", "trade_index": 42}
    )
    sdk.ostium.close_trade = MagicMock(
        return_value={"transactionHash": "0xdef"}
    )
    return sdk


@pytest.mark.asyncio
async def test_pair_resolver_maps_ticker_to_pair_id():
    pairs = [
        {"id": 0, "from": "BTC", "to": "USD"},
        {"id": 1, "from": "ETH", "to": "USD"},
        {"id": 17, "from": "WTI", "to": "USD"},
    ]
    sdk = _fake_sdk(pairs)
    resolver = PairResolver(sdk)
    assert await resolver.pair_id("WTI") == 17
    assert await resolver.pair_id("BTC") == 0


@pytest.mark.asyncio
async def test_pair_resolver_returns_none_for_unknown():
    sdk = _fake_sdk([{"id": 0, "from": "BTC", "to": "USD"}])
    resolver = PairResolver(sdk)
    assert await resolver.pair_id("DOGECOIN-MOON") is None


@pytest.mark.asyncio
async def test_pair_resolver_caches_pairs():
    sdk = _fake_sdk([{"id": 0, "from": "BTC", "to": "USD"}])
    resolver = PairResolver(sdk)
    await resolver.pair_id("BTC")
    await resolver.pair_id("BTC")
    sdk.subgraph.get_pairs.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_get_market_returns_none_when_unlisted():
    sdk = _fake_sdk([{"id": 0, "from": "BTC", "to": "USD"}])
    client = OstiumRouterClient(sdk, default_collateral_usd=1_000.0)
    payload = await client.get_market("WTI")
    assert payload is None  # unlisted → fail closed


@pytest.mark.asyncio
async def test_router_get_market_listed_returns_payload():
    pair = {
        "id": 17, "from": "WTI", "to": "USD",
        "fundingRate": "0.00005",
        "longCollateral": "120000.0",
    }
    sdk = _fake_sdk([pair])
    client = OstiumRouterClient(sdk, default_collateral_usd=1_000.0)
    payload = await client.get_market("WTI")
    assert payload is not None
    assert payload["listed"] is True
    assert payload["mark_price"] == 80.0
    assert payload["funding_8h"] == pytest.approx(0.00005)
    assert payload["lp_long_usd"] == pytest.approx(120_000.0)


@pytest.mark.asyncio
async def test_router_open_long_sets_slippage_and_returns_index():
    pair = {"id": 17, "from": "WTI", "to": "USD"}
    sdk = _fake_sdk([pair])
    client = OstiumRouterClient(sdk, default_collateral_usd=1_000.0)
    res = await client.open_long(
        "WTI", notional_usd=10_000.0, max_slippage_bps=30.0
    )
    sdk.ostium.set_slippage_percentage.assert_called_once_with(0.3)
    sdk.ostium.perform_trade.assert_called_once()
    args, kwargs = sdk.ostium.perform_trade.call_args
    trade_params = args[0] if args else kwargs["trade_params"]
    assert trade_params["asset_type"] == 17
    assert trade_params["direction"] is True
    assert trade_params["order_type"] == "MARKET"
    assert res["trade_index"] == 42
    assert res["fill_price"] == 80.0


@pytest.mark.asyncio
async def test_router_open_long_raises_when_unlisted():
    sdk = _fake_sdk([{"id": 0, "from": "BTC", "to": "USD"}])
    client = OstiumRouterClient(sdk, default_collateral_usd=1_000.0)
    with pytest.raises(RuntimeError, match="not listed"):
        await client.open_long("WTI", 10_000.0, 30.0)


@pytest.mark.asyncio
async def test_router_close_long_calls_close_trade():
    pair = {"id": 17, "from": "WTI", "to": "USD"}
    sdk = _fake_sdk([pair])
    client = OstiumRouterClient(sdk, default_collateral_usd=1_000.0)
    res = await client.close_long("WTI", trade_index=42)
    sdk.ostium.close_trade.assert_called_once_with(17, 42)
    assert "fill_price" in res
