"""D1 higher-timeframe overlay modes.

`filter` (default) vetoes H4 trades the daily trend opposes; `merge` folds the
daily trend in as an extra weighted momentum vote. These guard that:
  * the default `filter` path is unchanged when there is no daily frame,
  * `merge` actually changes the signal (it is a real second mode, not a no-op),
  * the daily mapping is absent (None) when no daily frame is supplied,
all without look-ahead (the daily sign is shifted to the previous completed day
inside `_d1_sign_per_bar`, shared by both modes).
"""
from __future__ import annotations

import dataclasses

from xau.config import load_config
from xau.data.source import make_source
from xau.features.trend import _d1_sign_per_bar, tsmom_signal


def _frames():
    cfg = load_config("config/default.yaml")  # synthetic source
    src = make_source(cfg)
    df = src.load("XAUUSD", "H4")
    d1 = src.load_d1("XAUUSD")
    return cfg, df, d1


def test_merge_changes_the_signal_vs_filter():
    cfg, df, d1 = _frames()
    t_merge = dataclasses.replace(cfg.features.trend, d1_mode="merge")
    s_filter = tsmom_signal(df, cfg.features.trend, cfg.labeling, d1)
    s_merge = tsmom_signal(df, t_merge, cfg.labeling, d1)
    # the two modes must differ on a non-trivial number of bars
    diff = (s_filter["side"].to_numpy() != s_merge["side"].to_numpy()).sum()
    assert diff > 0, "merge mode produced an identical signal to filter"


def test_merge_without_daily_frame_equals_plain_h4():
    # with no D1 frame, both modes collapse to the bare H4 signal (no veto, no vote)
    cfg, df, _ = _frames()
    t_merge = dataclasses.replace(cfg.features.trend, d1_mode="merge")
    s_merge = tsmom_signal(df, t_merge, cfg.labeling, None)
    s_filter = tsmom_signal(df, cfg.features.trend, cfg.labeling, None)
    assert (s_merge["side"].to_numpy() == s_filter["side"].to_numpy()).all()


def test_d1_sign_per_bar_none_without_daily_frame():
    cfg, df, _ = _frames()
    assert _d1_sign_per_bar(df, None, cfg.features.trend) is None


def test_d1_weight_zero_merge_matches_unfiltered_h4_direction():
    # with d1_weight = 0 the merge vote contributes nothing, so the SIGN of the
    # signal must equal the bare H4 signal (no veto in merge mode)
    cfg, df, d1 = _frames()
    t0 = dataclasses.replace(cfg.features.trend, d1_mode="merge", d1_weight=0.0)
    s0 = tsmom_signal(df, t0, cfg.labeling, d1)
    s_h4 = tsmom_signal(df, cfg.features.trend, cfg.labeling, None)
    assert (s0["side"].to_numpy() == s_h4["side"].to_numpy()).all()
