"""Portfolio capital allocation across the universe.

The diversified basket previously used **equal capital** per symbol. That is a
fine default, but it lets a high-volatility symbol (BTCUSD) dominate the basket's
risk while a quiet FX pair contributes almost nothing -- so the "diversification"
is mostly nominal. This module adds **inverse-volatility (risk-parity-lite)**
allocation: weight each symbol by ``1/sigma`` so every symbol contributes a more
equal share of portfolio *risk*, not equal *dollars*.

Two hard rules keep this honest:

  * **Causal weights only.** Volatility is estimated from a LEADING warmup window
    (the first ``window`` bars), never the full sample -- using full-sample vol to
    set weights is look-ahead. The warmup span is excluded from no result by
    construction; it simply seeds the (static) weights held for the whole run.
  * **Scale-invariance makes this engine-free.** Sizing is fixed-fractional, so a
    symbol's equity path and per-trade R are invariant to its starting capital
    (only the $ PnL scales linearly). That means changing the *allocation* needs
    no change to the backtest engine: run each symbol, then combine its growth
    curve with weight ``w_i`` -- ``port_eq = E0 * sum_i w_i * growth_i``.

This is deliberately a *lite* risk-parity: static weights from a single warmup
window, no covariance term, no rebalancing. It is a documented assumption, not a
fit, and it still has to clear the same strict promotion gate.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

VALID_SCHEMES = ("equal", "inverse_vol")


def equal_weights(symbols: Sequence[str]) -> dict[str, float]:
    """Uniform 1/N allocation (the prior default)."""
    syms = list(symbols)
    if not syms:
        return {}
    w = 1.0 / len(syms)
    return {s: w for s in syms}


def inverse_vol_weights(vols: Mapping[str, float]) -> dict[str, float]:
    """Normalised ``1/sigma`` weights from a per-symbol volatility map.

    Symbols with a non-finite or non-positive vol are treated as missing and
    given the *mean* inverse-vol of the valid symbols (so a degenerate estimate
    neither explodes the weight nor silently drops the symbol). If no symbol has
    a usable vol, falls back to equal weights.
    """
    syms = list(vols.keys())
    if not syms:
        return {}
    inv: dict[str, float] = {}
    for s in syms:
        v = float(vols[s])
        if np.isfinite(v) and v > 0:
            inv[s] = 1.0 / v
    if not inv:
        return equal_weights(syms)
    fill = float(np.mean(list(inv.values())))
    inv_full = {s: inv.get(s, fill) for s in syms}
    total = sum(inv_full.values())
    if total <= 0:
        return equal_weights(syms)
    return {s: inv_full[s] / total for s in syms}


def leading_window_vol(prices: pd.Series, window: int) -> float:
    """Std of log-returns over the FIRST ``window`` bars (a causal risk proxy).

    Uses only the leading slice, so weights built from this never peek forward.
    Returns ``nan`` if there is not enough data (caller decides the fallback).
    """
    p = pd.Series(prices).astype(float).dropna()
    if len(p) < 3:
        return float("nan")
    seg = p.iloc[: max(int(window), 2)]
    logret = np.log(seg / seg.shift(1)).dropna()
    if len(logret) < 2:
        return float("nan")
    return float(logret.std(ddof=1))


def compute_portfolio_weights(
    scheme: str,
    symbols: Sequence[str],
    price_loader,
    window: int,
) -> dict[str, float]:
    """Resolve allocation weights for ``symbols`` under ``scheme``.

    ``price_loader(symbol) -> pd.Series`` returns that symbol's close series
    (already restricted to the run's date range). For ``inverse_vol`` the vol is
    measured on the leading ``window`` bars of each series.
    """
    if scheme not in VALID_SCHEMES:
        raise ValueError(f"unknown portfolio weighting scheme '{scheme}'; "
                         f"expected one of {VALID_SCHEMES}")
    syms = list(symbols)
    if scheme == "equal":
        return equal_weights(syms)
    vols: dict[str, float] = {}
    for s in syms:
        try:
            vols[s] = leading_window_vol(price_loader(s), window)
        except Exception:
            vols[s] = float("nan")
    return inverse_vol_weights(vols)


__all__ = [
    "VALID_SCHEMES",
    "equal_weights",
    "inverse_vol_weights",
    "leading_window_vol",
    "compute_portfolio_weights",
]
