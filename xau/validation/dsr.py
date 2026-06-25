"""Probabilistic & Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2012/2014).

Implemented from scratch. All Sharpe quantities are PER-OBSERVATION (not
annualised) -- the PSR formula needs ``n``, ``skew``, ``kurt`` and the Sharpe in
the same sampling units. Convert an annualised Sharpe to per-observation before
calling, or use :func:`moments_from_returns`.

Key relationships:
  * PSR estimates P(true SR > benchmark) after correcting for non-normality.
  * ``expected_max_sharpe`` is the extreme-value expectation of the max SR across
    ``n_trials`` under the null -- this is the selection-bias hurdle.
  * DSR = PSR evaluated against SR0 = expected_max_sharpe(...). It is the
    probability the observed SR reflects skill AFTER correcting for both
    non-normality and the number of trials tried.

The ``n_trials`` fed to DSR MUST come from the :class:`TrialLedger` (every config
ever evaluated), never a guess -- an under-counted n_trials is the classic way a
DSR is faked into passing.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

_EULER_GAMMA = 0.5772156649015329


def sharpe_from_returns(returns: np.ndarray) -> float:
    """Per-observation Sharpe ratio of a return array (NaN/inf-safe)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd <= 0:
        return 0.0
    return float(r.mean() / sd)


def moments_from_returns(returns: np.ndarray) -> tuple[float, float, float]:
    """Return ``(sharpe_per_obs, skew, excess_kurtosis)``."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 3:
        return 0.0, 0.0, 0.0
    mu = r.mean()
    sd = r.std(ddof=1)
    sharpe = mu / sd if sd > 0 else 0.0
    s = ((r - mu) ** 3).mean() / (sd**3) if sd > 0 else 0.0
    k = ((r - mu) ** 4).mean() / (sd**4) - 3.0 if sd > 0 else 0.0
    return float(sharpe), float(s), float(k)


def probabilistic_sharpe_ratio(sr_hat: float, n: int, skew: float, kurt: float,
                                sr_benchmark: float = 0.0) -> float:
    """P(true Sharpe > ``sr_benchmark``) given the observed ``sr_hat``.

    Parameters
    ----------
    sr_hat, n, skew : float / int
        Per-observation Sharpe, sample size, skewness.
    kurt : float
        EXCESS kurtosis (Fisher; normal == 0). Internally converted to the
        non-excess form the Bailey-LdP formula expects: the variance term is
        ``1 - skew*SR + (kurt_excess + 2)/4 * SR^2`` (which reduces to
        ``1 + 0.5*SR^2`` for normal returns, matching Lo 2002).

    Returns
    -------
    float
        Probability in ``[0,1]``. Degenerate inputs return 0.0 (fail safe).
    """
    if n <= 2 or not np.isfinite(sr_hat):
        return 0.0
    denom_sq = 1.0 - skew * sr_hat + 0.25 * (kurt + 2.0) * sr_hat * sr_hat
    if denom_sq <= 0:
        return 0.0
    z = (sr_hat - sr_benchmark) * np.sqrt(n - 1) / np.sqrt(denom_sq)
    return float(norm.cdf(z))


def expected_max_sharpe(sr_variance_across_trials: float, n_trials: int) -> float:
    """Expected maximum SR under the null over ``n_trials`` independent trials.

    Bailey-LdP extreme-value approximation:
        E[max SR] = sigma_SR * [ (1-gamma) * Phi^-1(1-1/N) + gamma * Phi^-1(1-1/(N e)) ]
    where sigma_SR = sqrt(variance of SR across trials) and gamma is
    Euler-Mascheroni. For N<=1 there is no selection -> 0.
    """
    if n_trials <= 1:
        return 0.0
    sigma = float(np.sqrt(max(sr_variance_across_trials, 0.0)))
    if sigma <= 0:
        return 0.0
    n = int(n_trials)
    term = ((1 - _EULER_GAMMA) * norm.ppf(1 - 1.0 / n)
            + _EULER_GAMMA * norm.ppf(1 - 1.0 / (n * np.e)))
    return float(sigma * term)


def deflated_sharpe_ratio(sr_hat: float, n_obs: int, skew: float, kurt: float,
                          sr_variance_across_trials: float, n_trials: int) -> float:
    """DSR = PSR evaluated against SR0 = ``expected_max_sharpe(...)``.

    The probability the observed ``sr_hat`` reflects genuine skill after
    correcting for non-normality AND selection bias from ``n_trials`` trials.
    """
    sr0 = expected_max_sharpe(sr_variance_across_trials, n_trials)
    return probabilistic_sharpe_ratio(sr_hat, n_obs, skew, kurt, sr_benchmark=sr0)


def effective_n_trials(trial_returns: np.ndarray, max_clusters: int = 16) -> int:
    """Estimate the EFFECTIVE number of independent trials via correlation
    clustering (an ONC-style approximation using KMeans on the correlation
    structure).

    Parameters
    ----------
    trial_returns : (n_trials, n_obs) array
        Per-trial return series (rows = trials). Constant or too-short rows are
        dropped.
    max_clusters : int
        Upper bound on clusters searched.

    Returns
    -------
    int
        Effective trial count >= 1. Falls back to the raw count if clustering is
        degenerate.
    """
    M = np.asarray(trial_returns, dtype=float)
    if M.ndim != 2 or M.shape[0] < 2:
        return max(int(M.shape[0]) if M.ndim == 2 else 1, 1)
    # keep only trials with variance
    sd = M.std(axis=1)
    keep = np.isfinite(sd) & (sd > 0)
    M = M[keep]
    if M.shape[0] < 2:
        return max(M.shape[0], 1)
    if M.shape[1] < 2:
        return M.shape[0]
    corr = np.corrcoef(M)
    corr = np.nan_to_num(corr, nan=0.0)
    # distance = sqrt(0.5*(1-corr))
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, None))
    np.fill_diagonal(dist, 0.0)

    from sklearn.cluster import KMeans

    best_k, best_score = 1, -np.inf
    upper = min(max_clusters, M.shape[0])
    for k in range(2, upper + 1):
        try:
            km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(dist)
        except Exception:
            break
        labels = km.labels_
        # silhouette-lite: within-cluster mean correlation (higher is better)
        score = 0.0
        cnt = 0
        for c in range(k):
            members = np.where(labels == c)[0]
            if members.size > 1:
                score += corr[np.ix_(members, members)].mean()
                cnt += 1
        score = score / cnt if cnt else 0.0
        if score > best_score:
            best_score, best_k = score, k
    return max(best_k, 1)


__all__ = [
    "sharpe_from_returns",
    "moments_from_returns",
    "probabilistic_sharpe_ratio",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "effective_n_trials",
]
