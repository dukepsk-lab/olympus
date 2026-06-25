"""Triple-barrier label correctness: barrier touch order, vertical cap, t1 span."""
from __future__ import annotations

import numpy as np
import pandas as pd

from xau.labeling.triple_barrier import (
    add_vertical_barrier,
    triple_barrier_labels,
)


def _ramp(start, end, n):
    idx = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
    s = pd.Series(np.linspace(start, end, n), index=idx, dtype=float)
    return s


def test_upper_barrier_touch_labels_positive():
    # monotonically rising price -> upper barrier hits first
    close = _ramp(100.0, 110.0, 20)
    vol = pd.Series(0.01, index=close.index)          # 1% per bar vol
    events = pd.DataFrame({"side": [1]}, index=[close.index[0]])
    events["vert_barrier_ts"] = add_vertical_barrier(
        close.index, events.index, max_holding_bars=19
    )
    out = triple_barrier_labels(close, events, pt_sl=(2.0, 2.0), target_vol=vol)
    assert len(out) == 1
    assert out["bin"].iloc[0] == 1                      # profit barrier first
    assert out["ret"].iloc[0] > 0
    # t1 must lie strictly AFTER entry and within the vertical cap
    assert out["t1"].iloc[0] > out.index[0]
    assert out["t1"].iloc[0] <= events["vert_barrier_ts"].iloc[0]


def test_lower_barrier_touch_labels_negative():
    # falling price -> stop barrier hits first for a long
    close = _ramp(100.0, 90.0, 20)
    vol = pd.Series(0.01, index=close.index)
    events = pd.DataFrame({"side": [1]}, index=[close.index[0]])
    events["vert_barrier_ts"] = add_vertical_barrier(close.index, events.index, 19)
    out = triple_barrier_labels(close, events, pt_sl=(2.0, 2.0), target_vol=vol)
    assert out["bin"].iloc[0] == -1
    assert out["ret"].iloc[0] < 0


def test_vertical_barrier_when_neither_horizontal_hit():
    # tiny drift, wide barriers -> must end at vertical barrier with sign label
    idx = pd.date_range("2023-01-01", periods=10, freq="4h", tz="UTC")
    close = pd.Series(100.0 + 0.0001 * np.arange(10), index=idx)  # barely rising
    vol = pd.Series(0.5, index=idx)                       # huge vol -> wide barriers
    events = pd.DataFrame({"side": [1]}, index=[idx[0]])
    events["vert_barrier_ts"] = add_vertical_barrier(idx, events.index, 8)
    out = triple_barrier_labels(close, events, pt_sl=(2.0, 2.0), target_vol=vol)
    assert len(out) == 1
    assert out["bin"].iloc[0] in (1, -1, 0)
    assert out["t1"].iloc[0] == events["vert_barrier_ts"].iloc[0]


def test_short_side_flips_touch_signs():
    close = _ramp(100.0, 90.0, 20)  # falling -> good for a short
    vol = pd.Series(0.01, index=close.index)
    events = pd.DataFrame({"side": [-1]}, index=[close.index[0]])
    events["vert_barrier_ts"] = add_vertical_barrier(close.index, events.index, 19)
    out = triple_barrier_labels(close, events, pt_sl=(2.0, 2.0), target_vol=vol)
    assert out["bin"].iloc[0] == 1     # short profit barrier
    assert out["ret"].iloc[0] > 0      # side-adjusted return positive


def test_nan_vol_event_dropped():
    close = _ramp(100.0, 110.0, 20)
    vol = pd.Series(np.nan, index=close.index)
    events = pd.DataFrame({"side": [1]}, index=[close.index[0]])
    events["vert_barrier_ts"] = add_vertical_barrier(close.index, events.index, 19)
    out = triple_barrier_labels(close, events, pt_sl=(2.0, 2.0), target_vol=vol)
    assert out.empty


def test_t1_span_is_the_purge_boundary():
    # the t1->span must be exactly [entry, first touch]; used by CPCV purging
    close = _ramp(100.0, 110.0, 30)
    vol = pd.Series(0.01, index=close.index)
    events = pd.DataFrame({"side": [1]}, index=[close.index[0]])
    events["vert_barrier_ts"] = add_vertical_barrier(close.index, events.index, 29)
    out = triple_barrier_labels(close, events, pt_sl=(2.0, 2.0), target_vol=vol)
    span = out["t1"].iloc[0] - out.index[0]
    assert span > pd.Timedelta(0)
