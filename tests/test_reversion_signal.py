"""`reversion_signal` enabled path -- regression guard.

The enabled path previously crashed (`_finalize` called with only `pt_mult`,
missing `sl_mult`) because it was never exercised by a test: `enabled=False`
is the config default, so the path is dead unless explicitly turned on.
"""
from __future__ import annotations

import dataclasses

from xau.config import load_config
from xau.data.source import make_source
from xau.features.regime import RegimeClassifier
from xau.features.reversion import reversion_signal


def _frames():
    cfg = load_config("config/default.yaml")  # synthetic source
    src = make_source(cfg)
    df = src.load("XAUUSD", "H4")
    return cfg, df


def test_disabled_returns_all_flat():
    cfg, df = _frames()
    s = reversion_signal(df, cfg.features.reversion, cfg.labeling)
    assert (s["side"].to_numpy() == 0).all()


def test_enabled_runs_without_error_and_fires_only_in_range_regime():
    cfg, df = _frames()
    rev = dataclasses.replace(cfg.features.reversion, enabled=True)
    regime = RegimeClassifier(cfg.features.regime).fit(df)
    s = reversion_signal(df, rev, cfg.labeling, regime)
    active = s["side"].to_numpy() != 0
    labels = regime.labels.reindex(df.index).fillna("random").to_numpy()
    assert (labels[active] == "range").all()


def test_enabled_without_regime_fails_closed():
    cfg, df = _frames()
    rev = dataclasses.replace(cfg.features.reversion, enabled=True)
    s = reversion_signal(df, rev, cfg.labeling, regime=None)
    assert (s["side"].to_numpy() == 0).all()
