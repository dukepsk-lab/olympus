"""Data ingestion behind a single :class:`DataSource` interface.

Three concrete sources, selected by config with NO code changes elsewhere:
  * :class:`SyntheticSource` -- deterministic regime-switching generator (tests +
    smoke runs; needs no live connection).
  * :class:`CsvSource`       -- CSV / Parquet fallback (your own OHLC tape).
  * :class:`MT5Source`       -- MetaTrader5 (lazy import; live MT5/IUX only).

OHLC contract: ``load`` returns a DataFrame indexed by a tz-aware UTC
``DatetimeIndex`` with columns ``["open","high","low","close","volume"]``.
These are MID-reference prices. BID/ASK are NEVER stored here -- they are derived
downstream from the :class:`~xau.costs.model.CostModel` spread so that fill logic
cannot accidentally read a mid price (see :mod:`xau.backtest.fills`). This keeps
the "no mid fills" invariant localised to the cost + fill layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import zlib

import numpy as np
import pandas as pd

from .. import make_rng
from ..config import Config, SymbolSpec


def _stable_hash(*parts: str) -> int:
    """Deterministic hash (Python's built-in hash() is randomised per-process
    via PYTHONHASHSEED, which would break reproducibility)."""
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    return zlib.crc32(payload) % (2**31)

OHLC_COLS = ("open", "high", "low", "close", "volume")

# Map a timeframe string to a pandas offset alias used to build the bar index.
_TIMEFRAME_FREQ = {
    "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h", "H4": "4h", "D1": "D",
}


def timeframe_to_freq(tf: str) -> str:
    try:
        return _TIMEFRAME_FREQ[tf.upper()]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"unsupported timeframe '{tf}'") from exc


def timeframe_to_hours(tf: str) -> float:
    """Approximate hours per bar (used for annualisation of synthetic vol)."""
    return {"M5": 5 / 60, "M15": 0.25, "M30": 0.5, "H1": 1.0, "H4": 4.0, "D1": 24.0}.get(
        tf.upper(), 4.0
    )


# ----------------------------------------------------------------------------
#  Synthetic per-symbol base characteristics.
#  These are deliberate, documented assumptions (NOT fit to any real tape) so the
#  pipeline is runnable end-to-end. They encode realistic price LEVELS and annual
#  volatilities; regime-switching dynamics are layered on top.
# ----------------------------------------------------------------------------
SYNTH_BASE: dict[str, dict] = {
    "XAUUSD": dict(price=1950.0, ann_vol=0.15, drift=0.04),
    "EURUSD": dict(price=1.08, ann_vol=0.08, drift=0.0),
    "GBPUSD": dict(price=1.27, ann_vol=0.09, drift=0.0),
    "USDJPY": dict(price=150.0, ann_vol=0.10, drift=0.02),
    "US30":   dict(price=38000.0, ann_vol=0.16, drift=0.06),
    "BTCUSD": dict(price=60000.0, ann_vol=0.65, drift=0.20),
}

# Regime segments shared across the universe (risk-off correlation is real and the
# correlated-risk cap must have something to bite on). Weights roughly mirror the
# research MM model (trend ~45%, range ~40%, crisis ~15%).
# ``momentum_phi`` injects AR(1) return persistence -- this is what makes a trend
# regime a genuine TREND (positively-autocorrelated returns), which is exactly
# what time-series momentum exploits. Range regimes are mildly mean-reverting
# (phi<0). This is realistic microstructure, not a fit.
_REGIMES = {
    "trend_up":   dict(weight=0.275, drift_mult=3.0, vol_mult=1.1, momentum_phi=0.18),
    "trend_down": dict(weight=0.175, drift_mult=-3.0, vol_mult=1.2, momentum_phi=0.18),
    "range":      dict(weight=0.40,  drift_mult=0.0,  vol_mult=0.7, momentum_phi=-0.12),
    "crisis":     dict(weight=0.15,  drift_mult=-1.0, vol_mult=2.4, momentum_phi=0.05),
}


@dataclass(frozen=True)
class DataSource(ABC):
    """Abstract data interface. Concrete classes implement :meth:`_load_mid`."""

    config: Config

    def load(self, symbol: str, timeframe: str | None = None,
             start: str | None = None, end: str | None = None) -> pd.DataFrame:
        tf = timeframe or self.config.data.timeframe
        df = self._load_mid(symbol, tf, start, end)
        if df.empty:
            return df
        missing = [c for c in OHLC_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"{symbol}: missing OHLC columns {missing}")
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df[list(OHLC_COLS)].astype(float)

    def load_d1(self, symbol: str, start: str | None = None,
                end: str | None = None) -> pd.DataFrame:
        """Daily series for the slow-trend overlay. Defaults to resampling H4."""
        if not self.config.data.d1_overlay:
            return pd.DataFrame(columns=list(OHLC_COLS))
        try:
            h4 = self.load(symbol, "H4", start, end)
        except Exception:
            return pd.DataFrame(columns=list(OHLC_COLS))
        if h4.empty:
            return h4
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        d1 = h4[list(agg)].resample("1D").agg(agg).dropna()
        d1["volume"] = 0.0
        return d1[list(OHLC_COLS)]

    @abstractmethod
    def _load_mid(self, symbol: str, timeframe: str,
                  start: str | None, end: str | None) -> pd.DataFrame:
        ...


# ----------------------------------------------------------------------------
#  SyntheticSource
# ----------------------------------------------------------------------------
class SyntheticSource(DataSource):
    """Deterministic regime-switching OHLC generator.

    Generates a shared regime timeline across the universe so correlated-risk
    behaviour is exercisable, then per-symbol idiosyncratic shocks. Trends are
    genuine so a slow trend-follower has real (not guaranteed) edge net of cost;
    range/crisis segments keep the gate honest.
    """

    def __init__(self, config: Config, regime_seed_offset: int = 0):
        super().__init__(config)
        self._regime_seed_offset = regime_seed_offset
        self._regime_cache: np.ndarray | None = None
        self._drift_cache: np.ndarray | None = None
        self._n_bars: int | None = None

    def _shared_regimes(self, n_bars: int) -> np.ndarray:
        """Build (and cache) one regime timeline for the whole universe."""
        if self._regime_cache is not None and len(self._regime_cache) >= n_bars:
            return self._regime_cache[:n_bars]
        rng = make_rng(10_000 + self._regime_seed_offset)
        names = list(_REGIMES)
        weights = np.array([_REGIMES[n]["weight"] for n in names], float)
        weights /= weights.sum()
        regimes = np.empty(n_bars, dtype=object)
        i = 0
        while i < n_bars:
            seg_len = int(rng.integers(80, 360))
            seg_len = min(seg_len, n_bars - i)
            name = names[int(rng.choice(len(names), p=weights))]
            regimes[i : i + seg_len] = name
            i += seg_len
        self._regime_cache = regimes
        self._n_bars = n_bars
        return regimes

    def _shared_drift(self, n_bars: int) -> np.ndarray:
        """A single slow AR(1) trend-drift shared across the universe.

        Creates correlated trending/ranging phases (risk-off correlation) that the
        correlated-risk cap can bite on. Cached like the regime timeline.
        """
        if self._drift_cache is not None and len(self._drift_cache) >= n_bars:
            return self._drift_cache[:n_bars]
        rng = make_rng(20_000 + self._regime_seed_offset)
        base = 0.0042  # ~ per-bar sigma for XAUUSD H4
        phi = 0.988
        innov = rng.standard_normal(n_bars) * (0.18 * base) * np.sqrt(1 - phi**2)
        mu = np.empty(n_bars)
        prev = 0.0
        for j in range(n_bars):
            prev = phi * prev + innov[j]
            mu[j] = prev
        self._drift_cache = mu
        return mu

    def _fat_tailed_z(self, rng: np.random.Generator, n: int) -> np.ndarray:
        """Student-t-ish shocks: normal / sqrt(chi2/df) for fat tails."""
        z = rng.standard_normal(n)
        df = 6.0
        scale = np.sqrt(df / rng.chisquare(df, size=n))
        return z * scale

    def _load_mid(self, symbol: str, timeframe: str,
                  start: str | None, end: str | None) -> pd.DataFrame:
        spec = self._spec(symbol)
        base = SYNTH_BASE.get(symbol, dict(price=100.0, ann_vol=0.20, drift=0.0))
        price0 = float(base["price"])
        ann_vol = float(base["ann_vol"])
        drift_ann = float(base["drift"])

        n_bars, index = self._bar_index(timeframe, start, end)
        regimes = self._shared_regimes(n_bars)
        hours = timeframe_to_hours(timeframe)
        # FX/metals/crypto trade ~24h/day, 5 days/week -> ~6240 trading hours/yr.
        dt = hours / 6240.0
        bar_vol = ann_vol * np.sqrt(dt)

        rng = make_rng(_stable_hash(symbol, timeframe))
        z = self._fat_tailed_z(rng, n_bars)
        # Persistent TREND DRIFT: a slow AR(1) per symbol (with a shared component
        # so the universe is correlated in risk-off). This is what makes a trend a
        # TREND -- returns stay autocorrelated well beyond the signal lookback,
        # which is the precise condition time-series momentum needs to work.
        # Regimes now only scale VOLATILITY (crisis = high vol); the drift itself
        # meanders between trend and range via the AR(1), which the RegimeClassifier
        # (Hurst/ADX) labels causally downstream.
        shared = self._shared_drift(n_bars)           # (n_bars,) shared trend
        drift_phi = 0.988                              # ~half-life 57 bars
        drift_sig = 0.18 * bar_vol                     # trend magnitude vs noise
        mu = np.empty(n_bars)
        mu_prev = 0.0
        drift_innov = rng.standard_normal(n_bars) * drift_sig * np.sqrt(1 - drift_phi**2)
        for j in range(n_bars):
            mu_prev = drift_phi * mu_prev + drift_innov[j]
            mu[j] = 0.6 * mu_prev + 0.4 * shared[j]    # blend idiosyncratic + shared
        ret = np.empty(n_bars)
        for j, rname in enumerate(regimes):
            rdef = _REGIMES[rname]
            sig = bar_vol * rdef["vol_mult"]
            ret[j] = mu[j] - 0.5 * sig**2 + sig * z[j]

        logp = np.log(price0) + np.cumsum(ret)
        close = np.exp(logp)
        open_ = np.empty(n_bars)
        open_[0] = price0
        open_[1:] = close[:-1]
        # intrabar high/low from |return| scaled by a random excursion
        bar_range = np.abs(np.diff(np.r_[np.log(price0), logp]))
        excursion = rng.uniform(0.6, 1.6, size=n_bars) * bar_range + 1e-9
        high = np.maximum(open_, close) * np.exp(excursion * rng.uniform(0.4, 1.0, n_bars))
        low = np.minimum(open_, close) * np.exp(-excursion * rng.uniform(0.4, 1.0, n_bars))
        volume = rng.integers(100, 1000, size=n_bars).astype(float)

        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=index,
        )
        df.index.name = "time"
        return df

    def _spec(self, symbol: str) -> SymbolSpec:
        if symbol not in self.config.symbols:
            raise KeyError(f"no symbol spec for '{symbol}'")
        return self.config.symbols[symbol]

    def _bar_index(self, timeframe: str, start: str | None,
                   end: str | None) -> tuple[int, pd.DatetimeIndex]:
        cfg = self.config.data
        freq = timeframe_to_freq(timeframe)
        if start and end:
            idx = pd.date_range(start=start, end=end, freq=freq, tz="UTC")
            n = len(idx)
            if n == 0:
                n = cfg.bars
                idx = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
        else:
            n = cfg.bars
            idx = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None).floor("h"),
                                periods=n, freq=freq, tz="UTC")
        return n, idx


# ----------------------------------------------------------------------------
#  CsvSource
# ----------------------------------------------------------------------------
class CsvSource(DataSource):
    """CSV / Parquet fallback.

    Expects one file per symbol named ``{SYMBOL}_{TF}.{csv|parquet}`` under
    ``config.data.csv_dir`` (case-insensitive extension). The file must carry a
    parseable timestamp column (``time``/``date``/``timestamp`` or the index) and
    OHLC(V) columns. Timestamps are coerced to UTC.
    """

    def _load_mid(self, symbol: str, timeframe: str,
                  start: str | None, end: str | None) -> pd.DataFrame:
        d = Path(self.config.data.csv_dir)
        for ext in (".csv", ".parquet", ".pq"):
            cand = d / f"{symbol}_{timeframe}{ext}"
            if cand.exists():
                return self._read(cand, start, end)
            cand2 = d / f"{symbol}{ext}"
            if cand2.exists():
                return self._read(cand2, start, end)
        raise FileNotFoundError(
            f"no CSV/Parquet for {symbol} {timeframe} under {d} "
            f"(expected {symbol}_{timeframe}.csv)"
        )

    def _read(self, path: Path, start: str | None, end: str | None) -> pd.DataFrame:
        if path.suffix.lower() in (".parquet", ".pq"):
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        # find timestamp column
        ts_col = None
        for c in ("time", "date", "timestamp", "datetime", "gmt"):
            if c in df.columns:
                ts_col = c
                break
        if ts_col is not None:
            df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
            df = df.set_index(ts_col).sort_index()
        else:
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
            df = df.sort_index()
        df.columns = [str(c).lower() for c in df.columns]
        if "volume" not in df.columns:
            df["volume"] = 0.0
        if start:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return df[list(OHLC_COLS)]


# ----------------------------------------------------------------------------
#  MT5Source
# ----------------------------------------------------------------------------
class MT5Source(DataSource):
    """MetaTrader5 source. Imports the ``MetaTrader5`` package lazily so the rest
    of the system runs without a live terminal.

    Set ``mt5_path`` to the terminal exe if needed. Connection errors propagate;
    tests never instantiate this (they use SyntheticSource).
    """

    def __init__(self, config: Config, mt5_path: str | None = None,
                 login: int | None = None, password: str | None = None,
                 server: str | None = None):
        super().__init__(config)
        self._mt5_path = mt5_path
        self._creds = dict(login=login, password=password, server=server)
        self._mt5 = None
        self._connected = False

    def _connect(self):  # pragma: no cover - requires live terminal
        if self._connected:
            return
        import MetaTrader5 as mt5  # type: ignore[import-not-found]

        if not mt5.initialize(self._mt5_path, **{k: v for k, v in self._creds.items() if v}):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self._mt5 = mt5
        self._connected = True

    def _symbol_mt5(self, symbol: str) -> str:  # pragma: no cover
        # broker-specific mapping e.g. XAUUSD -> "XAUUSD.iux"
        return symbol

    def _load_mid(self, symbol: str, timeframe: str,
                  start: str | None, end: str | None) -> pd.DataFrame:  # pragma: no cover
        self._connect()
        mt5 = self._mt5
        info = mt5.symbol_info(self._symbol_mt5(symbol))
        if info is None:
            raise RuntimeError(f"MT5: symbol {symbol} not found")
        if not info.visible:
            mt5.symbol_select(self._symbol_mt5(symbol), True)
        tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                  "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
        mt5tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_H4)
        kwargs = {}
        if start and end:
            kwargs["time_from"] = int(pd.Timestamp(start, tz="UTC").timestamp())
            kwargs["time_to"] = int(pd.Timestamp(end, tz="UTC").timestamp())
        else:
            kwargs["count"] = self.config.data.bars
        rates = mt5.copy_rates_range(self._symbol_mt5(symbol), mt5tf,
                                     kwargs.get("time_from", 0), kwargs.get("time_to", 0))
        if rates is None or len(rates) == 0:
            rates = mt5.copy_rates_from_pos(self._symbol_mt5(symbol), mt5tf, 0,
                                            kwargs.get("count", self.config.data.bars))
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time").sort_index()
        return df[list(OHLC_COLS)]


def make_source(config: Config, **kwargs) -> DataSource:
    """Factory: pick the concrete source from ``config.data.source``."""
    kind = config.data.source.lower()
    if kind == "synthetic":
        return SyntheticSource(config, **kwargs)
    if kind == "csv":
        return CsvSource(config)
    if kind == "mt5":
        return MT5Source(config, **kwargs)
    raise ValueError(f"unknown data source '{kind}'")


__all__ = [
    "DataSource", "SyntheticSource", "CsvSource", "MT5Source", "make_source",
    "SYNTH_BASE", "timeframe_to_freq", "timeframe_to_hours", "OHLC_COLS",
]
