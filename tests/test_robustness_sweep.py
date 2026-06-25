"""The robustness sweep must perturb only knobs that ACTUALLY move the trend
backtest (lookbacks + D1 filter) and must do so without mutating the frozen
base config. The grid axes are guarded here so a future refactor can't silently
reintroduce an inert dimension (which would fake the DSR trial count).
"""
from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path

from xau.config import load_config

_SPEC = importlib.util.spec_from_file_location(
    "robustness_sweep", Path(__file__).resolve().parents[1] / "scripts" / "robustness_sweep.py"
)
rs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rs)


def _base():
    return load_config("config/default.yaml")


def test_perturb_swaps_lookbacks_without_mutating_base():
    base = _base()
    before = tuple(base.features.trend.lookbacks)
    cfg = rs._perturb(base, (5, 15, 30), (20, 50))
    assert cfg.features.trend.lookbacks == (5, 15, 30)
    assert base.features.trend.lookbacks == before        # base untouched (frozen)
    assert cfg.data.d1_overlay is True
    assert cfg.features.trend.d1_lookbacks == (20, 50)


def test_perturb_none_turns_d1_overlay_off():
    cfg = rs._perturb(_base(), (20, 60, 120), None)
    assert cfg.data.d1_overlay is False


def test_grid_axes_are_nonempty_and_default_is_present():
    # defaults must sit INSIDE the grid (plateau vs spike test only works then)
    assert (20, 60, 120) in rs.LOOKBACK_SETS.values()
    assert (20, 50) in rs.D1_SETS.values()
    assert None in rs.D1_SETS.values()                    # an OFF row is required
    assert len(rs.LOOKBACK_SETS) >= 3 and len(rs.D1_SETS) >= 3


def test_perturb_is_frozen_safe():
    # dataclasses.replace on a frozen Config must not raise
    cfg = rs._perturb(_base(), (10, 30, 60), (10, 30))
    assert dataclasses.is_dataclass(cfg)
