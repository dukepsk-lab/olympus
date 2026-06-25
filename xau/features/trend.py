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
    n_lb = len(lookbacks)
    # weight slower lookbacks higher (research: lean to the slow end)
    weights = np.array([1.0 / np.sqrt(L) for L in lookbacks])
    weights = weights / weights.sum()

    score = np.zeros(len(close))
    for w, L in zip(weights, lookbacks):
        past_ret = close / close.shift(L) - 1.0
        score += w * np.sign(past_ret.fillna(0.0)).to_numpy()
    # require simple majority-ish agreement -> side; conviction = |score|
    side = np.sign(score).astype(int)
    # only fire when at least ~half the weighted mass agrees
    min_agree = min(0.34, weights.max())
    conviction = np.where(np.abs(score) >= min_agree, np.abs(score), 0.0)
    side = np.where(conviction > 0, side, 0)

    # D1 slow filter: only trade in the direction of the higher-TF trend.
    if d1_df is not None and cfg.d1_lookbacks and len(d1_df):
        d1_close = d1_df["close"]
        d1_score = np.zeros(len(d1_close))
        dw = np.array([1.0 / np.sqrt(L) for L in cfg.d1_lookbacks])
        dw = dw / dw.sum()
        for w, L in zip(dw, cfg.d1_lookbacks):
            d1_score += w * np.sign((d1_close / d1_close.shift(L) - 1.0).fillna(0.0)).to_numpy()
        d1_sign = pd.Series(np.sign(d1_score), index=d1_close.index)
        # use the PREVIOUS completed daily bar's sign (no intraday look-ahead)
        d1_sign = d1_sign.shift(1).ffill()
        # map daily sign onto the H4 index by the H4 bar's date
        d1_by_date = d1_sign.groupby(d1_sign.index.date).last()
        h4_dates = pd.Series(df.index.date, index=df.index)
        mapped = h4_dates.map(d1_by_date).to_numpy()
        mapped = np.where(np.asarray(mapped, dtype=float) == 0.0, np.nan,
                          np.asarray(mapped, dtype=float))
        # zero out H4 signals that oppose the D1 trend (or where D1 is flat)
        agree = (np.sign(side) == np.sign(np.nan_to_num(mapped))) & (mapped != 0)
        side = np.where(agree, side, 0)
        conviction = np.where(agree, conviction, 0.0)

    # trend: WIDE target (let winners run to the vertical barrier) + wide disaster
    # stop. This is what produces the documented low-win-rate / high-payoff shape;
    # tight barriers here would whipsaw the directional edge to death.
    return _finalize(df, side, conviction, vol, pt_mult=10.0, sl_mult=3.0)


__all__ = ["tsmom_signal", "_empty", "_finalize"]
