"""Regime-gated mean reversion -- LOWEST conviction, filter-gated overlay.

Research §1.3: short-horizon "reversion" is largely bid-ask bounce and usually
dies net of retail spread. We include it for completeness but:
  * it is OFF by default (``features.reversion.enabled``),
  * it fires ONLY when a CAUSAL RegimeClassifier labels the bar ``"range"``,
  * it can be trivially disabled and never fires outside a genuine range.

It is NOT a win-rate strategy; if it cannot clear the full promotion gate net of
cost (which it usually won't), it must be dropped rather than dressed up.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ReversionConfig, LabelingConfig
from ..features.regime import RegimeClassifier
from ..labeling.triple_barrier import ewma_vol
from ._helpers import rsi
from .trend import _finalize


def reversion_signal(df: pd.DataFrame, cfg: ReversionConfig,
                     labeling: LabelingConfig,
                     regime: RegimeClassifier | None = None) -> pd.DataFrame:
    close = df["close"]
    vol = ewma_vol(close, halflife=labeling.vol_halflife)
    side = np.zeros(len(df), dtype=int)
    conviction = np.zeros(len(df))

    if not cfg.enabled:
        return _finalize(df, side, conviction, vol,
                         pt_mult=labeling.pt_sl[0], sl_mult=labeling.pt_sl[1])

    # z-score of close over a rolling window (causal)
    mu = close.rolling(cfg.zscore_window).mean()
    sd = close.rolling(cfg.zscore_window).std()
    z = (close - mu) / sd.replace(0, np.nan)
    rsi_ = rsi(close, cfg.rsi_window)

    long_entry = (z <= -cfg.zscore_entry) | (rsi_ <= 30)
    short_entry = (z >= cfg.zscore_entry) | (rsi_ >= 70)
    side = np.where(long_entry, 1, np.where(short_entry, -1, 0)).astype(int)
    conviction = np.where(side != 0, 0.5, 0.0)

    # GATE: zero out anything outside a causal "range" regime
    if regime is not None and regime.labels is not None:
        is_range = regime.labels.reindex(df.index).fillna("random").eq("range").to_numpy()
        side = np.where(is_range, side, 0)
        conviction = np.where(is_range, conviction, 0.0)
    else:
        # no regime filter available -> refuse to fire (fail safe)
        side[:] = 0
        conviction[:] = 0.0

    return _finalize(df, side, conviction, vol,
                     pt_mult=labeling.pt_sl[0], sl_mult=labeling.pt_sl[1])


__all__ = ["reversion_signal"]
