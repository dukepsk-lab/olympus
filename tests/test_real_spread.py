"""Real per-bar spread override: when the feed carries an actual `spread` (points)
the cost model must use it DIRECTLY (no synthetic session/news multiplier on top),
and fall back to the base-spread assumption when it is absent or degenerate.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from xau.config import load_config
from xau.costs.model import CostModel
from xau.data.source import CsvSource


def _cm():
    return CostModel.from_config(load_config("config/default.yaml"))


def test_real_spread_overrides_base_and_multipliers():
    cm = _cm()
    ts = pd.Timestamp("2023-06-01 03:00", tz="UTC")  # asian -> base would be widened
    base = cm.effective_spread("XAUUSD", ts, is_news_window=True)   # base * session * news
    real = cm.effective_spread("XAUUSD", ts, is_news_window=True,
                               real_spread_points=12.0)
    assert real == pytest.approx(12.0)        # used DIRECTLY, multipliers ignored
    assert real != pytest.approx(base)        # and it differs from the assumption


def test_real_spread_feeds_bid_ask_half_each_side():
    cm = _cm()
    ts = pd.Timestamp("2023-06-01 13:00", tz="UTC")
    mid = 1950.0
    bid, ask = cm.bid_ask(mid, "XAUUSD", ts, is_news_window=False,
                          real_spread_points=20.0)
    point = load_config("config/default.yaml").symbols["XAUUSD"].point
    assert (ask - bid) == pytest.approx(20.0 * point)   # full spread = 20 points
    assert bid < mid < ask


@pytest.mark.parametrize("bad", [None, 0.0, -5.0, float("nan")])
def test_degenerate_real_spread_falls_back_to_base(bad):
    cm = _cm()
    ts = pd.Timestamp("2023-06-01 13:00", tz="UTC")
    got = cm.effective_spread("XAUUSD", ts, is_news_window=False, real_spread_points=bad)
    base = cm.effective_spread("XAUUSD", ts, is_news_window=False)
    assert got == pytest.approx(base)   # bad/missing override -> assumption used


def test_csv_loader_carries_optional_spread_column(tmp_path):
    # a CSV with a `spread` column must survive the loader; one without must not
    idx = pd.date_range("2024-01-01", periods=10, freq="4h", tz="UTC")
    df = pd.DataFrame({
        "time": idx, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 1000, "spread": np.arange(10, dtype=float) + 5,
    })
    df.to_csv(tmp_path / "XAUUSD_H4.csv", index=False)

    cfg = load_config("config/default.yaml")
    cfg = dataclasses.replace(
        cfg, data=dataclasses.replace(cfg.data, source="csv", csv_dir=str(tmp_path)))
    out = CsvSource(cfg).load("XAUUSD", "H4")
    assert "spread" in out.columns
    assert out["spread"].iloc[0] == pytest.approx(5.0)

    # a plain OHLCV file (no spread) loads fine and simply has no spread column
    df.drop(columns="spread").to_csv(tmp_path / "EURUSD_H4.csv", index=False)
    out2 = CsvSource(cfg).load("EURUSD", "H4")
    assert "spread" not in out2.columns
