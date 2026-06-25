"""Portfolio weighting: inverse-vol allocation must be normalised, causal, and
degenerate-input-safe. The causality guard (weights use only a LEADING window)
is the one that matters most -- full-sample vol weights would be look-ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xau.mm.portfolio import (
    compute_portfolio_weights,
    equal_weights,
    inverse_vol_weights,
    leading_window_vol,
    select_by_score,
)


def test_equal_weights_sum_to_one():
    w = equal_weights(["A", "B", "C", "D"])
    assert pytest.approx(sum(w.values())) == 1.0
    assert all(v == pytest.approx(0.25) for v in w.values())


def test_inverse_vol_overweights_the_calmer_symbol():
    w = inverse_vol_weights({"calm": 0.01, "wild": 0.10})
    assert pytest.approx(sum(w.values())) == 1.0
    assert w["calm"] > w["wild"]
    # 1/0.01 : 1/0.10  ->  10 : 1  ->  ~0.909 : ~0.091
    assert w["calm"] == pytest.approx(10 / 11, rel=1e-6)


def test_inverse_vol_degenerate_vol_falls_back_to_mean_then_equal():
    # one bad (zero) vol -> filled with the mean inverse, never dropped/exploded
    w = inverse_vol_weights({"a": 0.02, "b": 0.0})
    assert set(w) == {"a", "b"}
    assert pytest.approx(sum(w.values())) == 1.0
    assert np.isfinite(list(w.values())).all()
    # all-bad -> equal
    w2 = inverse_vol_weights({"a": 0.0, "b": float("nan")})
    assert w2 == pytest.approx({"a": 0.5, "b": 0.5})


def test_leading_window_vol_is_causal():
    # calm first `window` bars, violent tail. A causal estimate must see only
    # the calm head, so it must be MUCH smaller than the full-sample vol.
    rng = np.random.default_rng(0)
    calm = 100 + np.cumsum(rng.normal(0, 0.1, 300))
    wild = calm[-1] + np.cumsum(rng.normal(0, 5.0, 300))
    prices = pd.Series(np.concatenate([calm, wild]))
    head_vol = leading_window_vol(prices, window=250)
    full_vol = float(np.log(prices / prices.shift(1)).dropna().std(ddof=1))
    assert head_vol < 0.5 * full_vol


def test_compute_weights_inverse_vol_via_loader():
    rng = np.random.default_rng(1)
    series = {
        "calm": pd.Series(100 + np.cumsum(rng.normal(0, 0.1, 300))),
        "wild": pd.Series(100 + np.cumsum(rng.normal(0, 2.0, 300))),
    }
    w = compute_portfolio_weights("inverse_vol", ["calm", "wild"],
                                  price_loader=lambda s: series[s], window=250)
    assert pytest.approx(sum(w.values())) == 1.0
    assert w["calm"] > w["wild"]


def test_unknown_scheme_raises():
    with pytest.raises(ValueError):
        compute_portfolio_weights("magic", ["A"], price_loader=lambda s: None, window=10)


def test_select_by_score_keeps_only_qualifiers_in_order():
    scores = {"XAU": 0.8, "EUR": -0.3, "GBP": -0.5, "BTC": 0.4}
    assert select_by_score(scores, 0.0) == ["XAU", "BTC"]
    assert select_by_score(scores, 0.5) == ["XAU"]


def test_select_by_score_falls_back_to_all_when_none_qualify():
    # an empty basket is useless -> hand the full set to the (strict) gate instead
    scores = {"A": -0.1, "B": -0.2}
    assert select_by_score(scores, 0.0) == ["A", "B"]


def test_select_by_score_ignores_nan_scores():
    scores = {"A": float("nan"), "B": 0.2}
    assert select_by_score(scores, 0.0) == ["B"]
