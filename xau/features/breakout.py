"""Volatility / session breakout -- a CONVEX SATELLITE, not a standalone.

The equity opening-range-breakout edge is stock-in-play specific (research §1.2)
and does NOT transfer cleanly to spot gold. We ship it ONLY with the mandatory
false-break filters:
  * minimum range threshold (as a multiple of ATR),
  * volatility-expansion confirmation (bar range >= k * ATR),
  * a no-trade window around high-impact news,
and we mark direction as LOW conviction (the edge is convexity, not accuracy).

Timeframe note: on H4 a 5-hour London session holds only ~1 bar, so the naive
"first N bars of London" range is degenerate. The FX-correct analogue -- and the
one used here -- is the **Asian-range / London-NY-expansion** breakout: the thin
Asian session DEFINES the opening range, and the subsequent London/NY/overlap
sessions are eligible to trigger a break. This is timeframe-robust (the range is
"all bars of the range session that day", not a fixed count).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import BreakoutConfig, Config, LabelingConfig
from ..data.sessions import tag_sessions
from ..labeling.triple_barrier import ewma_vol
from ._helpers import atr
from .trend import _finalize


def opening_range_breakout(
    df: pd.DataFrame,
    cfg: BreakoutConfig,
    labeling: LabelingConfig,
    config: Config,
    news_mask: pd.Series | None = None,
) -> pd.DataFrame:
    close = df["close"]
    vol = ewma_vol(close, halflife=labeling.vol_halflife)
    atr_ = atr(df["high"], df["low"], close, period=14)
    sess = tag_sessions(df.index, config)
    side = np.zeros(len(df), dtype=int)
    conviction = np.zeros(len(df))
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    atr_arr = atr_.to_numpy()
    news = (news_mask.reindex(df.index).fillna(False).to_numpy()
            if news_mask is not None else np.zeros(len(df), dtype=bool))

    meta = pd.DataFrame(
        {"date": df.index.date, "session": sess.to_numpy(), "pos": np.arange(len(df))},
        index=df.index,
    )
    range_sess = cfg.range_session
    brk_sess = set(cfg.breakout_sessions)

    # group by day, then split range-session bars from breakout-session bars
    for day, sub in meta.groupby("date", sort=False):
        positions = sub["pos"].to_numpy()
        sessions_day = sub["session"].to_numpy()
        range_mask = sessions_day == range_sess
        brk_mask = np.array([s in brk_sess for s in sessions_day])
        range_pos = positions[range_mask]
        brk_pos = positions[brk_mask]
        if range_pos.size < max(1, min(cfg.opening_range_bars, range_pos.size)) or \
                range_pos.size < 1 or brk_pos.size == 0:
            continue
        or_high = high[range_pos].max()
        or_low = low[range_pos].min()
        or_width = or_high - or_low
        # ATR as of the first breakout bar (causal)
        atr0 = atr_arr[brk_pos[0]]
        if not np.isfinite(atr0) or atr0 <= 0:
            continue
        if or_width < cfg.min_range_atr_multiple * atr0:
            continue
        fired_long = fired_short = False
        for p in brk_pos:  # breakout bars in time order
            bar_range = high[p] - low[p]
            a = atr_arr[p]
            expand = np.isfinite(a) and a > 0 and bar_range >= cfg.expansion_atr_multiple * a
            if news[p]:
                continue
            if not fired_long and expand and high[p] > or_high:
                side[p] = 1
                conviction[p] = 0.5
                fired_long = True
            elif not fired_short and expand and low[p] < or_low:
                side[p] = -1
                conviction[p] = 0.5
                fired_short = True
    return _finalize(df, side, conviction, vol,
                     pt_mult=labeling.pt_sl[0], sl_mult=labeling.pt_sl[1])


__all__ = ["opening_range_breakout"]
