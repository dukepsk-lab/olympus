"""Regime-bucketed walk-forward + per-bucket breakdown.

The promotion gate requires the strategy to be net-profitable in >= 3 of 4 named
regime buckets (research section 6: an edge that only lives in one regime -- e.g.
the 2023-25 rally -- is fragile). Buckets are date ranges supplied in config and
are EDITABLE; nothing here is hardcoded to any macro assumption.

Because our signals are causal and parameter-light, walk-forward "re-fitting" is
just running the SAME causal signal on successive expanding windows -- the OOS
return is the signal's live behaviour on unseen bars. We also expose a direct
per-bucket net breakdown of a full-period BacktestResult for the gate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestResult
from ..config import Config
from ..metrics.perf import compute_performance, sharpe


def _bucket_mask(index: pd.DatetimeIndex, start: str, end: str) -> np.ndarray:
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC")
    return (index >= lo) & (index <= hi)


def regime_bucket_breakdown(result: BacktestResult, config: Config,
                            annual_bars: int | None = None) -> dict[str, dict]:
    """Net performance per configured regime bucket, from a full-period result.

    Trades are assigned to a bucket by their EXIT time. Returns
    ``{bucket_name: {net_pnl, n_trades, net_return, sharpe, profitable}}``.
    """
    ann = annual_bars or config.backtest.annual_bars
    buckets = config.validation.regime_buckets
    out: dict[str, dict] = {}
    trades = result.trades
    for b in buckets:
        if trades.empty:
            out[b.name] = dict(net_pnl=0.0, n_trades=0, net_return=0.0,
                               sharpe=0.0, profitable=False)
            continue
        exit_idx = pd.DatetimeIndex(trades["exit_time"])
        mask = _bucket_mask(exit_idx, b.start, b.end)
        bt = trades.loc[mask]
        net_pnl = float(bt["pnl"].sum()) if len(bt) else 0.0
        # per-bucket bar returns from the equity curve over the bucket window
        eq = result.equity
        emask = _bucket_mask(eq.index, b.start, b.end)
        seg = eq[emask]
        rets = seg.pct_change().fillna(0.0).to_numpy() if len(seg) else np.array([])
        out[b.name] = dict(
            net_pnl=net_pnl,
            n_trades=int(len(bt)),
            net_return=float((seg.iloc[-1] / seg.iloc[0] - 1.0)) if len(seg) else 0.0,
            sharpe=sharpe(rets, ann) if rets.size else 0.0,
            profitable=bool(net_pnl > 0.0),
        )
    return out


def walk_forward_oos(df: pd.DataFrame, signal: pd.DataFrame, config: Config,
                     symbol: str, train_bars: int | None = None,
                     step_bars: int | None = None,
                     news_mask: pd.Series | None = None) -> dict:
    """Rolling walk-forward: run the causal signal on successive windows and
    collect the OOS (out-of-sample) bar returns from each test window.

    Signals here are parameter-free and causal, so there is no in-sample fitting
    to leak; this function instead quantifies STABILITY across time windows
    (does the edge persist or collapse in some periods?).
    """
    from ..backtest.engine import run_backtest

    tb = train_bars or config.validation.walkforward.train_bars
    sb = step_bars or config.validation.walkforward.step_bars
    n = len(df)
    oos_returns = []
    window_sharpes = []
    start = tb
    while start < n:
        end = min(start + sb, n)
        seg = df.iloc[start - tb : end]
        sig_seg = signal.iloc[start - tb : end]
        nm = news_mask.iloc[start - tb : end] if news_mask is not None else None
        try:
            res = run_backtest(seg, sig_seg, config, symbol, news_mask=nm)
        except Exception:
            start += sb
            continue
        r = res.bar_returns.to_numpy()
        if r.size:
            oos_returns.append(r)
            window_sharpes.append(sharpe(r, config.backtest.annual_bars))
        start += sb
    if not oos_returns:
        return dict(oos_returns=np.array([]), window_sharpes=[],
                    frac_positive_windows=0.0)
    flat = np.concatenate(oos_returns)
    return dict(
        oos_returns=flat,
        window_sharpes=window_sharpes,
        frac_positive_windows=float(np.mean([s > 0 for s in window_sharpes])),
    )


__all__ = ["regime_bucket_breakdown", "walk_forward_oos"]
