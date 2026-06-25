"""Triple-barrier labels (Lopez de Prado, AFML ch.3), implemented from scratch.

Why from scratch: ``mlfinlab`` licensing/version fragility (project constraint).
The label is forward-looking BY DESIGN: at entry bar *t0* we look forward until
the first barrier touches. That forward span ``[t0, t1]`` is exactly what CPCV
must PURGE out of training -- so ``t1`` is mandatory output here.

Columns returned:
  * ``t1``  : timestamp of the FIRST barrier touch (label end time).
  * ``ret`` : gross side-adjusted return to first touch (costs applied later in
              the backtester, never here).
  * ``bin`` : label in {-1, 0, +1}: +1 = profit barrier first, -1 = loss barrier
              first, 0 = vertical barrier reached with no horizontal touch.

Touching uses the bar CLOSE path (the standard research implementation), which
keeps ``ret`` unambiguous. The vertical barrier caps holding time so no label can
look further than ``vert_barrier_ts`` -- bounding the purge span downstream.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ewma_vol(close: pd.Series, halflife: int = 20) -> pd.Series:
    """Per-bar volatility = EWMA of absolute log returns (vol-targeting input)."""
    ret = np.log(close / close.shift(1))
    vol = ret.abs().ewm(halflife=halflife, adjust=False).mean()
    return vol.replace(0.0, np.nan)


def add_vertical_barrier(close_index: pd.DatetimeIndex,
                         t0_index: pd.DatetimeIndex,
                         max_holding_bars: int) -> pd.Series:
    """Map each entry ``t0`` to the timestamp ``max_holding_bars`` later.

    tz-awareness is preserved by indexing the DatetimeIndex directly (NOT via
    ``.values``, which silently strips the tz).
    """
    times = close_index
    t0_ns = pd.DatetimeIndex(t0_index).asi8
    pos = np.searchsorted(times.asi8, t0_ns, side="left")
    end_pos = np.clip(pos + max_holding_bars, 0, len(times) - 1)
    # index the DatetimeIndex to keep tz info
    vt_vals = times[end_pos]
    vt = pd.Series(vt_vals, index=t0_index, name="vert_barrier_ts")
    # entries with no forward room (vert barrier at/before entry) -> NaT
    vt = vt.where(vt > pd.DatetimeIndex(t0_index))
    return vt


def triple_barrier_labels(close: pd.Series,
                          events: pd.DataFrame,
                          pt_sl: tuple[float, float],
                          target_vol: pd.Series) -> pd.DataFrame:
    """Compute triple-barrier labels.

    Parameters
    ----------
    close : pd.Series
        Close prices, sorted ascending by tz-aware UTC time.
    events : pd.DataFrame
        Index = entry timestamps (must be a subset of ``close.index``).
        Required column ``side`` (+1/-1). Optional ``vert_barrier_ts`` (the
        vertical-barrier timestamp); if absent, the last available close is used.
    pt_sl : (float, float)
        (profit-take multiple, stop multiple) of ``target_vol`` at entry.
    target_vol : pd.Series
        Per-bar volatility estimate aligned to ``close.index``.

    Returns
    -------
    pd.DataFrame with columns ``['t1','ret','bin']``, indexed by entry time.
    Events whose ``target_vol`` at entry is non-positive/NaN are dropped (a
    degenerate vol cannot set a barrier).
    """
    pt, sl = float(pt_sl[0]), float(pt_sl[1])
    close = close.sort_index()
    times = close.index
    close_vals = close.to_numpy()

    out_t1: list = []
    out_ret: list = []
    out_bin: list = []
    out_idx: list = []

    for t0, ev in events.iterrows():
        side = int(ev["side"])
        if side == 0:
            continue
        if t0 not in target_vol.index or t0 not in close.index:
            continue
        sigma = target_vol.loc[t0]
        if not np.isfinite(sigma) or sigma <= 0:
            continue
        upper = pt * sigma
        lower = sl * sigma
        vert = ev.get("vert_barrier_ts", pd.NaT)
        if not pd.notna(vert):
            vert = times[-1]

        i0 = times.get_loc(t0)
        i_vert = times.get_loc(vert) if vert in times else len(times) - 1
        if i_vert <= i0:
            continue
        entry = close_vals[i0]
        seg = close_vals[i0 + 1 : i_vert + 1]
        if seg.size == 0:
            continue
        # side-adjusted return path; barriers in the same units
        side_ret = side * (seg / entry - 1.0)
        up_mask = side_ret >= upper
        dn_mask = side_ret <= -lower

        touch_up = np.argmax(up_mask) if up_mask.any() else -1
        touch_dn = np.argmax(dn_mask) if dn_mask.any() else -1

        if touch_up >= 0 and (touch_dn < 0 or touch_up <= touch_dn):
            j = touch_up
            bin_ = 1
        elif touch_dn >= 0:
            j = touch_dn
            bin_ = -1
        else:
            # vertical barrier: label by sign of realised return (may be 0)
            j = seg.size - 1
            r_end = side_ret[j]
            bin_ = int(np.sign(r_end))

        touch_price = seg[j]
        ret = side * (touch_price / entry - 1.0)
        t1 = times[i0 + 1 + j]
        out_t1.append(t1)
        out_ret.append(float(ret))
        out_bin.append(bin_)
        out_idx.append(t0)

    res = pd.DataFrame(
        {"t1": out_t1, "ret": out_ret, "bin": out_bin},
        index=pd.DatetimeIndex(out_idx, name="time"),
    )
    return res


__all__ = ["triple_barrier_labels", "ewma_vol", "add_vertical_barrier"]
