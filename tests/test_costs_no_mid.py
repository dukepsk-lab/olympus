"""CRITICAL invariant test: no fill ever equals the mid price.

If this test fails, a mid-price fill path has been introduced somewhere and the
net-of-cost guarantees of the whole system are void.
"""
from __future__ import annotations

import pytest

from xau.backtest.fills import fill_price
from xau.costs.model import CostModel
from xau.config import load_config


def test_fill_price_never_equals_mid():
    rng_bids = [1.0, 100.0, 1950.25, 0.0001, 38000.0]
    spreads = [0.0001, 0.5, 2.5, 0.00001, 100.0]
    for bid, sp in zip(rng_bids, spreads):
        ask = bid + sp
        mid = 0.5 * (bid + ask)
        # with ZERO slippage the fill still sits ON the ask/bid, never mid
        long_fill = fill_price(+1, bid, ask, 0.0, 1.0)
        short_fill = fill_price(-1, bid, ask, 0.0, 1.0)
        assert long_fill != pytest.approx(mid), "long fill hit mid!"
        assert short_fill != pytest.approx(mid), "short fill hit mid!"
        assert long_fill > mid, "long fill must be above mid (pay ask)"
        assert short_fill < mid, "short fill must be below mid (get bid)"
        assert long_fill == pytest.approx(ask), "zero-slip buy must equal ask"
        assert short_fill == pytest.approx(bid), "zero-slip sell must equal bid"

    # POSITIVE slippage must worsen the fill further from mid
    pos_slips = [1.0, 2.5, 5.0]
    for bid, sp, sl in zip(rng_bids[:3], spreads[:3], pos_slips):
        ask = bid + sp
        mid = 0.5 * (bid + ask)
        long_slip = fill_price(+1, bid, ask, sl, 1.0)
        short_slip = fill_price(-1, bid, ask, sl, 1.0)
        assert long_slip > ask, "slippage must push buy above ask"
        assert short_slip < bid, "slippage must push sell below bid"
        assert long_slip != pytest.approx(mid)
        assert short_slip != pytest.approx(mid)


def test_bid_ask_straddles_mid_and_never_coincide():
    cfg = load_config("config/default.yaml")
    cm = CostModel.from_config(cfg)
    import pandas as pd

    ts = pd.Timestamp("2023-06-01 13:00", tz="UTC")  # overlap session
    for sym in cfg.universe:
        mid = 100.0
        bid, ask = cm.bid_ask(mid, sym, ts, is_news_window=False)
        assert bid < mid < ask, f"{sym}: bid/ask must straddle mid"
        assert ask > bid, f"{sym}: spread must be positive"
        # news window widens further
        bid_n, ask_n = cm.bid_ask(mid, sym, ts, is_news_window=True)
        assert (ask_n - bid_n) > (ask - bid), f"{sym}: news must widen spread"


def test_zero_side_rejected():
    with pytest.raises(ValueError):
        fill_price(0, 1.0, 1.0002, 1.0, 0.0001)


def test_round_trip_cost_positive_and_news_inflated():
    cfg = load_config("config/default.yaml")
    cm = CostModel.from_config(cfg)
    import pandas as pd

    ts = pd.Timestamp("2023-06-01 13:00", tz="UTC")
    base = cm.round_trip_cost("XAUUSD", ts, 1.0, is_news_window=False)
    news = cm.round_trip_cost("XAUUSD", ts, 1.0, is_news_window=True)
    assert base > 0.0
    assert news > base  # news widening raises round-trip cost
