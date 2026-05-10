from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hip3_bot.execution import (
    Fill,
    OrderRouter,
    _parse_hl_fill,
    _resting_oid,
)
from hip3_bot.models import Mode
from hip3_bot.ostium_adapter import OstiumHedgeAdapter

from .conftest import make_position


def test_parse_hl_fill_success():
    result = {
        "status": "ok",
        "response": {
            "data": {
                "statuses": [{"filled": {"avgPx": "80.5", "totalSz": "10"}}]
            }
        },
    }
    fill = _parse_hl_fill(result, fallback_price=0.0, fallback_size=0.0)
    assert fill.price == 80.5
    assert fill.size == 10.0


def test_parse_hl_fill_falls_back_on_error():
    fill = _parse_hl_fill(
        {"status": "err"}, fallback_price=80.0, fallback_size=10.0
    )
    assert fill.price == 80.0
    assert fill.size == 10.0


def test_resting_oid_extracts_oid():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [{"resting": {"oid": 42}}]}},
    }
    assert _resting_oid(result) == 42


def test_resting_oid_returns_none_when_filled():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [{"filled": {"avgPx": "1"}}]}},
    }
    assert _resting_oid(result) is None


def test_fill_dataclass_defaults():
    f = Fill(price=10.0, size=5.0)
    assert f.fees_paid_usd == 0.0


def _ostium_adapter_returning(price: float, size: float) -> OstiumHedgeAdapter:
    client = AsyncMock()
    client.open_long.return_value = {
        "fill_price": price,
        "size": size,
        "fees_usd": 0.0,
        "trade_index": 7,
    }
    client.close_long.return_value = {
        "fill_price": price,
        "size": size,
        "fees_usd": 0.0,
    }
    return OstiumHedgeAdapter(client, max_slippage_bps=30.0)


@pytest.mark.asyncio
async def test_open_delta_neutral_scanner_creates_synthetic_position(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    pos = await router.open_delta_neutral(
        "WTI", notional_usd=8_000.0, entry_net_apr_pct=20.0
    )
    assert pos is not None
    assert pos.mode is Mode.SCANNER
    assert pos.hip3_size < 0
    assert pos.ostium_size > 0
    assert abs(abs(pos.hip3_size) - pos.ostium_size) < 1e-9


@pytest.mark.asyncio
async def test_open_delta_neutral_returns_none_when_no_mid(cfg):
    info = MagicMock()
    info.all_mids.return_value = {}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    assert await router.open_delta_neutral("WTI", 8_000.0, 20.0) is None


@pytest.mark.asyncio
async def test_close_delta_neutral_scanner_is_noop(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    pos = await router.open_delta_neutral("WTI", 8_000.0, 20.0)
    assert pos is not None
    await router.close_delta_neutral(pos)


@pytest.mark.asyncio
async def test_rebalance_hedge_scanner_returns_fill(cfg):
    info = MagicMock()
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    p = make_position(ostium_size=125.0, mode=Mode.SCANNER)
    fill = await router.rebalance_hedge(p, target_size=120.0)
    assert fill is not None
    assert fill.size == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_rebalance_hedge_no_op_when_target_matches(cfg):
    info = MagicMock()
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    p = make_position(ostium_size=125.0, mode=Mode.SCANNER)
    assert await router.rebalance_hedge(p, target_size=125.0) is None


@pytest.mark.asyncio
async def test_ostium_adapter_buy_returns_trade_index():
    adapter = _ostium_adapter_returning(price=80.0, size=100.0)
    fill = await adapter.buy("WTI", 8_000.0)
    assert fill.price == 80.0
    assert fill.size == 100.0
    assert fill.trade_index == 7


@pytest.mark.asyncio
async def test_ostium_adapter_sell_requires_trade_index():
    adapter = _ostium_adapter_returning(price=80.0, size=100.0)
    with pytest.raises(RuntimeError, match="trade_index is required"):
        await adapter.sell("WTI", 100.0, None)


@pytest.mark.asyncio
async def test_ostium_adapter_sell_uses_trade_index():
    adapter = _ostium_adapter_returning(price=80.0, size=100.0)
    fill = await adapter.sell("WTI", 100.0, trade_index=7)
    assert fill.price == 80.0
    assert fill.size == 100.0


@pytest.mark.asyncio
async def test_scanner_position_has_no_trade_index(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    router = OrderRouter(cfg, exchange=None, info=info, ostium=None)
    pos = await router.open_delta_neutral("WTI", 8_000.0, 20.0)
    assert pos is not None
    assert pos.ostium_trade_index is None
