"""Generate synthetic OHLC tapes and write them as CSV so :class:`CsvSource`
can be exercised with NO code changes (just set ``data.source: csv``).

Usage:
    python scripts/make_synthetic.py --config config/default.yaml --out data/ohlc
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xau import set_global_seed
from xau.config import load_config
from xau.data.source import SyntheticSource


def main() -> None:
    ap = argparse.ArgumentParser(description="Write synthetic OHLC CSVs.")
    ap.add_argument("--config", default="config/default.yaml")
    ap.add_argument("--out", default="data/ohlc")
    ap.add_argument("--timeframe", default=None, help="override config timeframe")
    args = ap.parse_args()

    cfg = load_config(args.config)
    set_global_seed(cfg.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tf = args.timeframe or cfg.data.timeframe
    src = SyntheticSource(cfg)
    for sym in cfg.universe:
        df = src.load(sym, tf, cfg.data.start, cfg.data.end)
        path = out_dir / f"{sym}_{tf}.csv"
        df.to_csv(path, index_label="time")
        print(f"wrote {path}  ({len(df)} bars, close "
              f"{df.close.min():.4f}..{df.close.max():.4f})")


if __name__ == "__main__":
    main()
