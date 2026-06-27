"""Signals produce a CAUSAL per-bar intent frame.

Output contract (all three signal modules share it) -- a DataFrame indexed like
the OHLC frame with columns:
  * ``side``          : int in {-1, 0, +1} (direction to enter at NEXT bar open).
  * ``conviction``    : float in [0,1] (directional agreement; scales risk).
  * ``stop_distance`` : float, price units -- the vol-scaled stop distance used
                        by MM to size the position (this is HOW vol-targeting
                        happens: stop_distance is proportional to volatility, so
                        fixed-fractional sizing implicitly targets constant risk).
  * ``vol``           : per-bar volatility sigma (used for triple-barrier labels).

Timing: a value at bar *t* uses only data <= bar *t* close; the engine fills it
at bar *t+1* open. No signal peeks forward.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import TrendConfig, LabelingConfig
from ..labeling.triple_barrier import ewma_vol


def _empty(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    return pd.DataFrame(
        {"side": np.zeros(n, dtype=int),
         "conviction": np.zeros(n),
         "stop_distance": np.full(n, np.nan),
         "vol": np.full(n, np.nan),
         "pt_mult": np.full(n, np.nan),
         "sl_mult": np.full(n, np.nan)},
        index=df.index,
    )


def _finalize(df: pd.DataFrame, side: np.ndarray, conviction: np.ndarray,
              vol: pd.Series, pt_mult: float, sl_mult: float) -> pd.DataFrame:
    """Assemble the signal frame.

    ``pt_mult``/``sl_mult`` are the PROFIT-TAKE / STOP multiples of per-bar vol
    for THIS signal family (trend uses a wide target + wide disaster stop so
    winners run to the vertical barrier; breakout/reversion use tighter ones).
    ``stop_distance`` (price) = sl_mult * vol * price.
    """
    out = _empty(df)
    price = df["close"].to_numpy()
    out["side"] = side.astype(int)
    out["conviction"] = conviction
    out["vol"] = vol.to_numpy()
    out["pt_mult"] = np.full(len(df), float(pt_mult))
    out["sl_mult"] = np.full(len(df), float(sl_mult))
    out["stop_distance"] = float(sl_mult) * vol.to_numpy() * price
    return out


def _d1_sign_per_bar(df: pd.DataFrame, d1_df: pd.DataFrame | None,
                     cfg: TrendConfig) -> np.ndarray | None:
    """Daily trend sign mapped causally onto each H4 bar (or ``None``).

    The daily momentum sign uses the PREVIOUS completed daily bar (``shift(1)``)
    so there is no intraday look-ahead. Values are ``+1``/``-1`` where the daily
    trend is defined and ``nan`` where it is flat/unknown -- the caller decides
    whether to veto (filter mode) or add it as a vote (merge mode).
    """
    if d1_df is None or not cfg.d1_lookbacks or not len(d1_df):
        return None
    d1_close = d1_df["close"]
    d1_score = np.zeros(len(d1_close))
    dw = np.array([1.0 / np.sqrt(L) for L in cfg.d1_lookbacks])
    dw = dw / dw.sum()
    for w, L in zip(dw, cfg.d1_lookbacks):
        d1_score += w * np.sign((d1_close / d1_close.shift(L) - 1.0).fillna(0.0)).to_numpy()
    d1_sign = pd.Series(np.sign(d1_score), index=d1_close.index)
    d1_sign = d1_sign.shift(1).ffill()                    # previous completed day
    d1_by_date = d1_sign.groupby(d1_sign.index.date).last()
    h4_dates = pd.Series(df.index.date, index=df.index)
    mapped = h4_dates.map(d1_by_date).to_numpy()
    mapped = np.where(np.asarray(mapped, dtype=float) == 0.0, np.nan,
                      np.asarray(mapped, dtype=float))
    return mapped


def _volume_confirm_mask(df: pd.DataFrame, cfg: TrendConfig) -> np.ndarray | None:
    """Causal volume-confirmation mask, or ``None`` if the filter is off.

    A bar passes when its volume is at least ``volume_min_ratio`` times the
    trailing rolling median volume (rolling window ends at the current bar, so
    no look-ahead). Bars in the warmup window (insufficient history) fail closed
    (``False``) rather than trading on an undefined ratio.
    """
    if not cfg.volume_filter_enabled or "volume" not in df.columns:
        return None
    vol = df["volume"].astype(float)
    roll_med = vol.rolling(cfg.volume_window, min_periods=cfg.volume_window).median()
    ratio = vol / roll_med.replace(0.0, np.nan)
    return (ratio >= cfg.volume_min_ratio).fillna(False).to_numpy()


def tsmom_signal(df: pd.DataFrame, cfg: TrendConfig, labeling: LabelingConfig,
                 d1_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Time-series momentum: sign of past return over multiple lookbacks,
    combined (slower lookbacks weighted higher), with an optional D1 slow filter.

    The edge is the CONVEX payoff from staying with trends; conviction reflects
    lookback agreement and is NOT a win-rate fixer.
    """
    close = df["close"]
    vol = ewma_vol(close, halflife=cfg.vol_halflife)
    lookbacks = tuple(cfg.lookbacks)
    # weight slower lookbacks higher (research: lean to the slow end)
    weights = np.array([1.0 / np.sqrt(L) for L in lookbacks])
    weights = weights / weights.sum()

    score = np.zeros(len(close))
    for w, L in zip(weights, lookbacks):
        past_ret = close / close.shift(L) - 1.0
        score += w * np.sign(past_ret.fillna(0.0)).to_numpy()
    min_agree = min(0.34, weights.max())

    # D1 higher-timeframe trend mapped causally onto each H4 bar (or None).
    mapped = _d1_sign_per_bar(df, d1_df, cfg)

    if cfg.d1_mode == "merge" and mapped is not None:
        # MERGE: the daily trend is an extra weighted momentum vote -- it adds to
        # both direction AND conviction (sizing). Flat/unknown days contribute 0.
        d1_vote = np.nan_to_num(np.sign(mapped), nan=0.0)
        score = score + float(cfg.d1_weight) * d1_vote
        side = np.sign(score).astype(int)
        conviction = np.where(np.abs(score) >= min_agree,
                              np.minimum(np.abs(score), 1.0), 0.0)
        side = np.where(conviction > 0, side, 0)
    else:
        # FILTER (default): H4 side/conviction, then VETO any bar the daily trend
        # opposes (or where the daily trend is flat). Unchanged legacy behaviour.
        side = np.sign(score).astype(int)
        conviction = np.where(np.abs(score) >= min_agree, np.abs(score), 0.0)
        side = np.where(conviction > 0, side, 0)
        if mapped is not None:
            agree = (np.sign(side) == np.sign(np.nan_to_num(mapped))) & (mapped != 0)
            side = np.where(agree, side, 0)
            conviction = np.where(agree, conviction, 0.0)

    vol_mask = _volume_confirm_mask(df, cfg)
    if vol_mask is not None:
        side = np.where(vol_mask, side, 0)
        conviction = np.where(vol_mask, conviction, 0.0)

    # trend: WIDE target (let winners run to the vertical barrier) + wide disaster
    # stop. This is what produces the documented low-win-rate / high-payoff shape;
    # tight barriers here would whipsaw the directional edge to death.
    return _finalize(df, side, conviction, vol, pt_mult=10.0, sl_mult=3.0)


__all__ = ["tsmom_signal", "_empty", "_finalize"]
