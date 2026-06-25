"""Fetch OHLC bars from a live MetaTrader5 terminal (e.g. IUX Markets) and write
them as CSV so :class:`CsvSource` can be exercised with NO code changes (just
set ``data.source: csv``).

The terminal must be installed and logged in. Credentials/login are optional --
``initialize()`` reuses the last-logged-in account; pass ``--login/--password/
--server`` (or ``--mt5-path``) to override.

Usage:
    python scripts/fetch_mt5.py --config config/default.yaml --out data/ohlc
    python scripts/fetch_mt5.py --symbol XAUUSD --timeframe H4 --out data/ohlc
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from xau.config import load_config
from xau.data.source import OHLC_COLS


_TF_MAP = {
    "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch OHLC CSVs from a live MT5 terminal.")
    ap.add_argument("--config", default="config/default.yaml")
    ap.add_argument("--out", default="data/ohlc")
    ap.add_argument("--symbol", action="append", help="override universe (repeatable)")
    ap.add_argument("--timeframe", default=None, help="override config timeframe")
    ap.add_argument("--start", default=None, help="ISO start (default: config.data.start)")
    ap.add_argument("--end", default=None, help="ISO end (default: now)")
    ap.add_argument("--mt5-path", default=None, help="terminal exe path")
    ap.add_argument("--login", type=int, default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--server", default=None)
    args = ap.parse_args()

    import MetaTrader5 as mt5  # lazy

    cfg = load_config(args.config)
    tf = args.timeframe or cfg.data.timeframe
    universe = args.symbol or cfg.universe
    start = args.start or cfg.data.start
    end = args.end or pd.Timestamp.utcnow().isoformat()

    init_kwargs = {"path": args.mt5_path} if args.mt5_path else {}
    for k in ("login", "password", "server"):
        v = getattr(args, k)
        if v is not None:
            init_kwargs[k] = v
    if not mt5.initialize(**init_kwargs):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")

    term = mt5.terminal_info()
    acc = mt5.account_info()
    print(f"MT5 connected: terminal={getattr(term, 'name', '?')} | "
          f"account={getattr(acc, 'login', '?')} @ {getattr(acc, 'server', '?')} "
          f"({getattr(acc, 'company', '?')})")
    print(f"fetching {tf} bars {start} -> {end} for {len(universe)} symbol(s)\n")

    mt5tf = getattr(mt5, _TF_MAP.get(tf.upper(), "TIMEFRAME_H4"))
    tf_from = int(pd.Timestamp(start, tz="UTC").timestamp())
    tf_to = int(pd.Timestamp(end, tz="UTC").timestamp())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_ok = 0
    for sym in universe:
        info = mt5.symbol_info(sym)
        if info is None:
            print(f"  SKIP {sym}: symbol not found on this server")
            continue
        if not info.visible:
            mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_range(sym, mt5tf, tf_from, tf_to)
        if rates is None or len(rates) == 0:
            rates = mt5.copy_rates_from_pos(sym, mt5tf, 0, cfg.data.bars)
        if rates is None or len(rates) == 0:
            print(f"  SKIP {sym}: no rates returned")
            continue
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time").sort_index()
        col = "tick_volume" if "tick_volume" in df.columns else "volume"
        df = df.rename(columns={col: "volume"})
        # Keep MT5's per-bar `spread` (in POINTS) when present -- the cost model
        # uses the REAL spread instead of the base-spread assumption. This is the
        # "real spread that comes with the OHLC"; a re-fetch is needed once to
        # populate it into existing CSVs (older fetches dropped this column).
        keep = list(OHLC_COLS) + (["spread"] if "spread" in df.columns else [])
        df = df[keep]
        df.index.name = "time"
        path = out_dir / f"{sym}_{tf}.csv"
        df.to_csv(path, index_label="time")
        print(f"  wrote {path}  ({len(df)} bars)  "
              f"{df.index[0]} -> {df.index[-1]}  close {df.close.min():.5f}..{df.close.max():.5f}")
        n_ok += 1

    mt5.shutdown()
    print(f"\ndone: {n_ok}/{len(universe)} symbol(s) written to {out_dir}/")


if __name__ == "__main__":
    main()
