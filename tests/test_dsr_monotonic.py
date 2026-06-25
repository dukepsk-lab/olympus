"""DSR monotonicity & sanity: more trials => higher bar => lower DSR (all else
equal). Also checks PSR/DSR basic behaviour and degenerate-input safety.
"""
from __future__ import annotations

import numpy as np
import pytest

from xau.validation.dsr import (
    deflated_sharpe_ratio,
    effective_n_trials,
    expected_max_sharpe,
    moments_from_returns,
    probabilistic_sharpe_ratio,
    sharpe_from_returns,
)


def test_dsr_decreases_as_n_trials_rises():
    sr_hat, n, skew, kurt = 0.05, 500, -0.3, 4.0
    var = 0.02**2  # variance of SR across trials
    trials = [2, 5, 10, 50, 200, 1000, 5000]
    dsrs = [deflated_sharpe_ratio(sr_hat, n, skew, kurt, var, t) for t in trials]
    for a, b in zip(dsrs, dsrs[1:]):
        assert b <= a + 1e-12, (
            f"DSR not monotonic decreasing in n_trials: "
            f"{dsrs}"
        )
    # and the gap from 1 -> many trials is strictly negative
    assert dsrs[-1] < dsrs[0]


def test_expected_max_sharpe_monotonic_in_n_trials():
    var = 0.02**2
    vals = [expected_max_sharpe(var, t) for t in [2, 5, 10, 50, 500]]
    for a, b in zip(vals, vals[1:]):
        assert b >= a
    assert expected_max_sharpe(var, 1) == 0.0
    assert expected_max_sharpe(0.0, 100) == 0.0


def test_psr_basics_and_safety():
    # a clearly-positive per-obs Sharpe over many obs -> high PSR vs 0
    assert probabilistic_sharpe_ratio(0.08, 1000, 0.0, 0.0) > 0.95
    # negative Sharpe -> low PSR
    assert probabilistic_sharpe_ratio(-0.08, 1000, 0.0, 0.0) < 0.05
    # degenerate / no-evidence cases
    assert probabilistic_sharpe_ratio(0.08, 1, 0.0, 0.0) == 0.0
    # zero observed SR vs zero benchmark (n_trials=1 => SR0=0) => exactly 0.5
    assert deflated_sharpe_ratio(0.0, 100, 0.0, 0.0, 1e-4, 1) == pytest.approx(0.5)
    # and adding many trials with zero edge pushes DSR below 0.5
    assert deflated_sharpe_ratio(0.0, 100, 0.0, 0.0, 1e-4, 1000) < 0.5


def test_moments_normal_returns():
    rng = np.random.default_rng(0)
    r = rng.standard_normal(100000) * 0.01
    sr, sk, kt = moments_from_returns(r)
    assert abs(sk) < 0.05
    assert abs(kt) < 0.05  # excess kurtosis ~ 0 for normal
    assert abs(sr) < 0.05


def test_sharpe_from_returns_constant_is_zero():
    assert sharpe_from_returns(np.zeros(50)) == 0.0
    assert sharpe_from_returns(np.array([0.01])) == 0.0


def test_effective_n_trials_reduces_for_correlated_strategies():
    rng = np.random.default_rng(1)
    base = rng.standard_normal((1, 2000))
    # 10 noisy copies of ONE underlying strategy -> high correlation
    correlated = base + 0.05 * rng.standard_normal((10, 2000))
    # 10 genuinely independent strategies
    independent = rng.standard_normal((10, 2000))
    n_eff_corr = effective_n_trials(correlated)
    n_eff_indep = effective_n_trials(independent)
    assert n_eff_corr <= n_eff_indep
    assert n_eff_corr >= 1
