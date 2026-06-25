"""Performance metrics -- all NET of cost.

Inputs are either a per-bar return series (for path metrics) or a per-trade PnL/R
array (for trade metrics). Costs are NEVER subtracted here -- the engine applies
them at fill time, so anything reaching this module is already net.

Conventions:
  * Sharpe/Sortino are annualised using ``annual_bars`` (H4 ~ 1460/yr).
  * Calmar = annualised geometric return / max drawdown.
  * ``R`` is a trade's PnL expressed in units of the risk it took (negative for
    losses). Expectancy in R is the mean R per trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_EPS = 1e-12


def equity_curve(returns: pd.Series | np.ndarray, start: float = 1.0) -> pd.Series:
    r = pd.Series(returns, dtype=float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return start * (1.0 + r).cumprod()


def max_drawdown(equity: pd.Series | np.ndarray) -> tuple[float, int, int]:
    """Return (max_dd_fraction, peak_pos, trough_pos). dd is in [0, 1]."""
    eq = pd.Series(equity, dtype=float).to_numpy()
    if eq.size == 0:
        return 0.0, -1, -1
    peak = np.maximum.accumulate(eq)
    # drawdown MAGNITUDE (>=0); argmax picks the deepest trough
    rel = np.where(peak > _EPS, (peak - eq) / peak, 0.0)
    idx = int(np.argmax(rel))
    peak_idx = int(np.argmax(eq[: idx + 1])) if idx >= 0 else 0
    return float(rel[idx]), peak_idx, idx


def sharpe(returns: pd.Series | np.ndarray, annual_bars: int = 1460) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd <= _EPS:
        return 0.0
    return float(r.mean() / sd * np.sqrt(annual_bars))


def sortino(returns: pd.Series | np.ndarray, annual_bars: int = 1460) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    downside = r[r < 0]
    if downside.size == 0:
        return 0.0
    dd_std = np.sqrt((downside**2).mean())
    if dd_std <= _EPS:
        return 0.0
    return float(r.mean() / dd_std * np.sqrt(annual_bars))


def annualised_return(returns: pd.Series | np.ndarray, annual_bars: int = 1460) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return 0.0
    total = float(np.prod(1.0 + r) - 1.0)
    years = r.size / annual_bars if annual_bars > 0 else 1.0
    if years <= 0 or (1.0 + total) <= 0:
        return total / years if years > 0 else total
    return float((1.0 + total) ** (1.0 / years) - 1.0)


def calmar(returns: pd.Series | np.ndarray, annual_bars: int = 1460) -> float:
    eq = equity_curve(returns)
    mdd, _, _ = max_drawdown(eq)
    if mdd <= _EPS:
        return 0.0
    return float(annualised_return(returns, annual_bars) / mdd)


def profit_factor(trade_pnl: np.ndarray) -> float:
    p = np.asarray(trade_pnl, dtype=float)
    p = p[np.isfinite(p)]
    gross_win = p[p > 0].sum()
    gross_loss = -p[p < 0].sum()
    if gross_loss <= _EPS:
        return float("inf") if gross_win > _EPS else 0.0
    return float(gross_win / gross_loss)


def win_rate(trade_pnl: np.ndarray) -> float:
    p = np.asarray(trade_pnl, dtype=float)
    p = p[np.isfinite(p)]
    if p.size == 0:
        return 0.0
    return float((p > 0).mean())


def expectancy(trade_pnl: np.ndarray, trade_r: np.ndarray | None = None) -> float:
    """Mean PnL per trade (or mean R if ``trade_r`` given)."""
    if trade_r is not None:
        r = np.asarray(trade_r, dtype=float)
        r = r[np.isfinite(r)]
        return float(r.mean()) if r.size else 0.0
    p = np.asarray(trade_pnl, dtype=float)
    p = p[np.isfinite(p)]
    return float(p.mean()) if p.size else 0.0


def recovery_factor(returns: pd.Series | np.ndarray) -> float:
    eq = equity_curve(returns)
    mdd, _, _ = max_drawdown(eq)
    net = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) else 0.0
    if mdd <= _EPS:
        return float("inf") if net > _EPS else 0.0
    return float(net / mdd)


def t_stat_mean(returns: np.ndarray) -> float:
    """t-stat of the mean return (multiple-testing-aware hurdle target ~3.0)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd <= _EPS:
        return 0.0
    return float(r.mean() / (sd / np.sqrt(n)))


@dataclass
class Performance:
    n_trades: int = 0
    net_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    expectancy_r: float = 0.0
    expectancy_pnl: float = 0.0
    recovery_factor: float = 0.0
    t_stat: float = 0.0
    skew: float = 0.0
    excess_kurt: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "net_return": self.net_return,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "expectancy_r": self.expectancy_r,
            "expectancy_pnl": self.expectancy_pnl,
            "recovery_factor": self.recovery_factor,
            "t_stat": self.t_stat,
            "skew": self.skew,
            "excess_kurt": self.excess_kurt,
        }


def compute_performance(bar_returns: np.ndarray | None = None,
                        trade_pnl: np.ndarray | None = None,
                        trade_r: np.ndarray | None = None,
                        annual_bars: int = 1460) -> Performance:
    """Bundle all metrics. ``bar_returns`` drives path metrics (Sharpe/Calmar/...);
    ``trade_pnl``/``trade_r`` drive trade metrics (PF/win/expectancy)."""
    perf = Performance()
    if bar_returns is not None and len(bar_returns):
        r = np.asarray(bar_returns, dtype=float)
        perf.net_return = float(np.prod(1.0 + r[np.isfinite(r)]) - 1.0)
        perf.sharpe = sharpe(r, annual_bars)
        perf.sortino = sortino(r, annual_bars)
        perf.calmar = calmar(r, annual_bars)
        eq = equity_curve(r)
        perf.max_drawdown, _, _ = max_drawdown(eq)
        perf.recovery_factor = recovery_factor(r)
        perf.t_stat = t_stat_mean(r)
        rr = r[np.isfinite(r)]
        if rr.size >= 3 and rr.std(ddof=1) > _EPS:
            mu = rr.mean(); sd = rr.std(ddof=1)
            perf.skew = float(((rr - mu) ** 3).mean() / sd**3)
            perf.excess_kurt = float(((rr - mu) ** 4).mean() / sd**4 - 3.0)
    if trade_pnl is not None and len(trade_pnl):
        perf.n_trades = int(np.sum(np.isfinite(trade_pnl)))
        perf.profit_factor = profit_factor(trade_pnl)
        perf.win_rate = win_rate(trade_pnl)
        perf.expectancy_pnl = expectancy(trade_pnl)
        perf.expectancy_r = expectancy(trade_pnl, trade_r) if trade_r is not None else 0.0
    return perf


__all__ = [
    "Performance", "compute_performance", "equity_curve", "max_drawdown",
    "sharpe", "sortino", "calmar", "annualised_return", "profit_factor",
    "win_rate", "expectancy", "recovery_factor", "t_stat_mean",
]
