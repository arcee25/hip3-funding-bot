from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hip3_bot.execution import (
    Fill,
    OrderRouter,
    PaperHedgeAdapter,
    _parse_hl_fill,
)
from hip3_bot.models import HedgeVenue

from .conftest import make_position


# --- Task 13: PaperHedgeAdapter + Fill ---


@pytest.mark.asyncio
async def test_paper_hedge_buy_uses_reference_price():
    ref = AsyncMock(return_value=80.0)
    adapter = PaperHedgeAdapter(ref)
    fill = await adapter.buy("WTI", 8_000.0)
    assert fill.price == 80.0
    assert fill.size == pytest.approx(100.0)
    ref.assert_awaited_once_with("WTI")


@pytest.mark.asyncio
async def test_paper_hedge_sell_uses_reference_price():
    ref = AsyncMock(return_value=80.0)
    adapter = PaperHedgeAdapter(ref)
    fill = await adapter.sell("WTI", 100.0)
    assert fill.price == 80.0
    assert fill.size == 100.0


@pytest.mark.asyncio
async def test_paper_hedge_buy_zero_price_returns_zero_size():
    ref = AsyncMock(return_value=0.0)
    adapter = PaperHedgeAdapter(ref)
    fill = await adapter.buy("WTI", 8_000.0)
    assert fill.size == 0.0


def test_fill_dataclass_defaults():
    f = Fill(price=10.0, size=5.0)
    assert f.fees_paid_usd == 0.0


# --- Task 14: HL fill parser ---


def test_parse_hl_fill_success():
    result = {
        "status": "ok",
        "response": {
            "data": {
                "statuses": [
                    {"filled": {"avgPx": "80.5", "totalSz": "10"}}
                ]
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


def test_parse_hl_fill_falls_back_on_missing_filled():
    result = {
        "status": "ok",
        "response": {"data": {"statuses": [{"resting": {"oid": 1}}]}},
    }
    fill = _parse_hl_fill(result, fallback_price=80.0, fallback_size=10.0)
    assert fill.price == 80.0
    assert fill.size == 10.0


# --- Task 15: OrderRouter.open_delta_neutral ---


@pytest.mark.asyncio
async def test_open_delta_neutral_dry_run_creates_paper_position(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(
        cfg, exchange=None, info=info, hedge=PaperHedgeAdapter(ref)
    )

    pos = await router.open_delta_neutral(
        "WTI", notional_usd=8_000.0, entry_apr_pct=25.0
    )
    assert pos is not None
    assert pos.coin == "WTI"
    assert pos.hedge_venue == HedgeVenue.PAPER
    assert pos.hip3_size < 0
    assert pos.hedge_size > 0
    assert abs(abs(pos.hip3_size) - pos.hedge_size) < 1e-9
    assert pos.notional_usd == 8_000.0
    assert pos.entry_apr_pct == 25.0


@pytest.mark.asyncio
async def test_open_delta_neutral_returns_none_when_no_mid(cfg):
    info = MagicMock()
    info.all_mids.return_value = {}
    ref = AsyncMock(return_value=0.0)
    router = OrderRouter(
        cfg, exchange=None, info=info, hedge=PaperHedgeAdapter(ref)
    )
    assert await router.open_delta_neutral("WTI", 8_000.0, 25.0) is None


# --- Task 16: OrderRouter.close_delta_neutral ---


@pytest.mark.asyncio
async def test_close_delta_neutral_dry_run_is_noop(cfg):
    info = MagicMock()
    info.all_mids.return_value = {"WTI": "80.0"}
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(
        cfg, exchange=None, info=info, hedge=PaperHedgeAdapter(ref)
    )
    pos = await router.open_delta_neutral("WTI", 8_000.0, 25.0)
    assert pos is not None
    await router.close_delta_neutral(pos)


# --- Task 17: OrderRouter.rebalance_hedge ---


@pytest.mark.asyncio
async def test_rebalance_hedge_dry_run_returns_fill(cfg):
    info = MagicMock()
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(
        cfg, exchange=None, info=info, hedge=PaperHedgeAdapter(ref)
    )
    p = make_position(hedge_size=125.0)
    fill = await router.rebalance_hedge(p, target_size=120.0)
    assert fill is not None
    assert fill.size == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_rebalance_hedge_no_op_when_target_matches(cfg):
    info = MagicMock()
    ref = AsyncMock(return_value=80.0)
    router = OrderRouter(
        cfg, exchange=None, info=info, hedge=PaperHedgeAdapter(ref)
    )
    p = make_position(hedge_size=125.0)
    assert await router.rebalance_hedge(p, target_size=125.0) is None
