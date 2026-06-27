"""Volume-confirmation veto on the TSMOM signal.

Default OFF (`volume_filter_enabled=False`) must be a strict no-op vs. the
existing behaviour; when enabled it must veto low-participation bars without
look-ahead (the rolling median ends at the current bar, warmup bars fail closed).
"""
from __future__ import annotations

import dataclasses

import numpy as np

from xau.config import load_config
from xau.data.source import make_source
from xau.features.trend import _volume_confirm_mask, tsmom_signal


def _frames():
    cfg = load_config("config/default.yaml")  # synthetic source
    src = make_source(cfg)
    df = src.load("XAUUSD", "H4")
    return cfg, df


def test_disabled_by_default_is_a_no_op():
    cfg, df = _frames()
    assert cfg.features.trend.volume_filter_enabled is False
    assert _volume_confirm_mask(df, cfg.features.trend) is None
    s = tsmom_signal(df, cfg.features.trend, cfg.labeling)
    t_enabled = dataclasses.replace(cfg.features.trend, volume_filter_enabled=False)
    s_again = tsmom_signal(df, t_enabled, cfg.labeling)
    assert (s["side"].to_numpy() == s_again["side"].to_numpy()).all()


def test_enabled_vetoes_some_low_volume_bars():
    cfg, df = _frames()
    t_on = dataclasses.replace(
        cfg.features.trend, volume_filter_enabled=True, volume_min_ratio=1.0
    )
    s_off = tsmom_signal(df, cfg.features.trend, cfg.labeling)
    s_on = tsmom_signal(df, t_on, cfg.labeling)
    # the filter can only ever REMOVE trades (veto to 0), never add new ones
    off_active = s_off["side"].to_numpy() != 0
    on_active = s_on["side"].to_numpy() != 0
    assert (on_active <= off_active).all()
    assert on_active.sum() < off_active.sum()


def test_mask_is_causal_and_fails_closed_during_warmup():
    cfg, df = _frames()
    t_on = dataclasses.replace(cfg.features.trend, volume_filter_enabled=True,
                               volume_window=20)
    mask = _volume_confirm_mask(df, t_on)
    assert mask is not None
    assert not mask[: t_on.volume_window - 1].any()


def test_extreme_min_ratio_vetoes_everything():
    cfg, df = _frames()
    t_on = dataclasses.replace(cfg.features.trend, volume_filter_enabled=True,
                               volume_min_ratio=1e9)
    s = tsmom_signal(df, t_on, cfg.labeling)
    assert (s["side"].to_numpy() == 0).all()
