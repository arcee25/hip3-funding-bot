from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hip3_bot.data_feed import HLDataFeed, is_hip3_market


def test_is_hip3_by_explicit_flag():
    assert is_hip3_market("BTC", {"isHip3": True}) is True


def test_is_hip3_by_coin_hint():
    assert is_hip3_market("WTI") is True
    assert is_hip3_market("WTI-PERP") is True
    assert is_hip3_market("SILVER") is True
    assert is_hip3_market("BTC") is False


def _fake_info(meta_ctx, l2_response=None):
    info = MagicMock()
    info.meta_and_asset_ctxs.return_value = meta_ctx
    info.l2_snapshot.return_value = l2_response or {
        "levels": [
            [{"px": "80.0", "sz": "1000"}],
            [{"px": "80.1", "sz": "1000"}],
        ]
    }
    return info


@pytest.mark.asyncio
async def test_snapshot_all_filters_to_hip3_only(cfg):
    meta_ctx = [
        {
            "universe": [
                {"name": "WTI", "isHip3": True},
                {"name": "BTC"},
            ]
        },
        [
            {
                "funding": "0.001",
                "markPx": "80",
                "openInterest": "100",
                "premium": "0.005",
                "dayNtlVlm": "100000000",
            },
            {
                "funding": "0.00005",
                "markPx": "70000",
                "openInterest": "1000",
                "premium": "0",
                "dayNtlVlm": "200000000",
            },
        ],
    ]
    feed = HLDataFeed(cfg, info=_fake_info(meta_ctx))
    snaps = await feed.snapshot_all()

    assert {s.coin for s in snaps} == {"WTI"}
    wti = snaps[0]
    assert wti.funding_8h == pytest.approx(0.001)
    assert wti.annualized_apr_pct == pytest.approx(0.001 * 3 * 365 * 100)
    assert wti.long_skew > 0.5
    assert wti.book_depth_usd > 0


@pytest.mark.asyncio
async def test_snapshot_skips_book_depth_for_low_apr(cfg):
    # Funding 0.0001 → ~10.95% APR, below default 20% min → no L2 fetch.
    meta_ctx = [
        {"universe": [{"name": "WTI", "isHip3": True}]},
        [
            {
                "funding": "0.0001",
                "markPx": "80",
                "openInterest": "100",
                "premium": "0",
                "dayNtlVlm": "0",
            }
        ],
    ]
    info = _fake_info(meta_ctx)
    feed = HLDataFeed(cfg, info=info)
    await feed.snapshot_all()

    info.l2_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_handles_empty_meta(cfg):
    feed = HLDataFeed(cfg, info=_fake_info([]))
    assert await feed.snapshot_all() == []
