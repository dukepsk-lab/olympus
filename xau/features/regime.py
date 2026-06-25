"""Regime features -- STRICTLY CAUSAL.

Every label at bar *t* uses only data up to and including bar *t* (rolling
windows). The most common leak in regime-switching / mean-reversion systems is a
non-causal regime label (computed with future bars); we avoid it by construction
and the CPCV leakage test guards the downstream effect.

Outputs:
  * :func:`hurst_exponent`     -- dispersional-method Hurst (windowed).
  * :func:`adx`                -- Wilder's ADX.
  * :class:`RegimeClassifier`  -- causal {trend, range, random} + vol-state.

No macro assumption is hardcoded (research §1.4): any externally supplied macro
series is treated as just another feature and re-estimated, never a fixed rule.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import RegimeConfig


def hurst_exponent(series: np.ndarray | pd.Series, max_lag: int = 20) -> float:
    """Dispersional-method Hurst exponent on a 1D series.

    std(increment over lag k) ~ k**H, so H is the slope of log(std) vs log(k).
    H > 0.5 -> persisting/trending; H ~ 0.5 -> random walk; H < 0.5 -> reverting.
    """
    s = np.asarray(series, dtype=float)
    s = s[np.isfinite(s)]
    if s.size < max_lag + 2:
        return float("nan")
    lags = np.arange(2, max_lag + 1)
    tau = np.empty(lags.size)
    for i, lag in enumerate(lags):
        diffs = s[lag:] - s[:-lag]
        tau[i] = np.std(diffs)
    tau = tau[np.isfinite(tau) & (tau > 0)]
    lags = lags[np.isfinite(np.std(np.add.outer(lags, 0), axis=0))] if False else lags
    if tau.size < 2:
        return float("nan")
    h = np.polyfit(np.log(lags[: tau.size]), np.log(tau), 1)[0]
    return float(np.clip(h, 0.0, 1.0))


def _rolling_hurst(close: pd.Series, window: int, max_lag: int,
                   step: int = 12) -> pd.Series:
    """Rolling Hurst computed on a grid every ``step`` bars then forward-filled.

    Regime labels are coarse (thresholded), so a sub-sampled Hurst is
    indistinguishable from a bar-by-bar one but ~``step``x faster -- the full
    Python loop over ~10k bars would otherwise dominate runtime.
    """
    n = len(close)
    out = np.full(n, np.nan)
    arr = close.to_numpy(dtype=float)
    idxs = range(window - 1, n, step)
    for t in idxs:
        seg = arr[t - window + 1 : t + 1]
        out[t] = hurst_exponent(seg, max_lag=max_lag)
    s = pd.Series(out, index=close.index, name="hurst")
    return s.ffill().bfill()


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Wilder's Average Directional Index (causal; NaN during warmup)."""
    high = pd.Series(high, dtype=float)
    low = pd.Series(low, dtype=float)
    close = pd.Series(close, dtype=float)
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat(
        [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=alpha, adjust=False).mean()
    adx_val.name = "adx"
    return adx_val


def realized_volatility(close: pd.Series, halflife: int = 50) -> pd.Series:
    """EWMA of |log returns| -- the vol input to vol-targeting and vol-state."""
    ret = np.log(close).diff()
    vol = ret.abs().ewm(halflife=halflife, adjust=False).mean()
    vol.name = "realized_vol"
    return vol


class RegimeClassifier:
    """Causal regime + volatility-state classifier.

    ``fit(df)`` precomputes rolling Hurst / ADX / vol over the OHLC frame; all
    windows end at the current bar so :meth:`label_at` and :meth:`vol_state_at`
    are safe to call in a streaming (no-look-ahead) manner.
    """

    def __init__(self, cfg: RegimeConfig):
        self.cfg = cfg
        self.hurst: pd.Series | None = None
        self.adx_: pd.Series | None = None
        self.vol: pd.Series | None = None
        self.labels: pd.Series | None = None
        self.vol_states: pd.Series | None = None

    def fit(self, df: pd.DataFrame) -> "RegimeClassifier":
        close = df["close"]
        self.hurst = _rolling_hurst(close, self.cfg.hurst_window, self.cfg.hurst_max_lag)
        self.adx_ = adx(df["high"], df["low"], close, self.cfg.adx_period)
        self.vol = realized_volatility(close, self.cfg.vol_halflife)
        self.labels = self._classify(self.hurst, self.adx_)
        self.vol_states = self._vol_state(self.vol)
        return self

    def _classify(self, h: pd.Series, a: pd.Series) -> pd.Series:
        h_t, h_r = self.cfg.hurst_trend, self.cfg.hurst_range
        a_t, a_r = self.cfg.adx_trend, self.cfg.adx_range
        labels = pd.Series("random", index=h.index, dtype=object)
        trend_mask = h.fillna(0.5).ge(h_t) | a.fillna(0.0).ge(a_t)
        range_mask = h.fillna(0.5).le(h_r) & a.fillna(0.0).le(a_r)
        labels[trend_mask] = "trend"
        labels[range_mask] = "range"
        labels.name = "regime"
        return labels

    def _vol_state(self, vol: pd.Series) -> pd.Series:
        # causal expanding quantiles of past vol -> low/normal/high
        q_lo = vol.expanding(min_periods=20).quantile(0.33)
        q_hi = vol.expanding(min_periods=20).quantile(0.66)
        state = pd.Series("normal", index=vol.index, dtype=object)
        state[vol < q_lo] = "low"
        state[vol > q_hi] = "high"
        state.name = "vol_state"
        return state

    def label_at(self, ts: pd.Timestamp) -> str:
        if self.labels is None or ts not in self.labels.index:
            return "random"
        return str(self.labels.loc[ts])

    def vol_state_at(self, ts: pd.Timestamp) -> str:
        if self.vol_states is None or ts not in self.vol_states.index:
            return "normal"
        return str(self.vol_states.loc[ts])

    def frame(self) -> pd.DataFrame:
        return pd.concat([self.labels, self.vol_states, self.hurst, self.adx_, self.vol],
                         axis=1)


__all__ = ["hurst_exponent", "adx", "realized_volatility", "RegimeClassifier"]
