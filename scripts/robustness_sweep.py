"""Robustness sweep (research roadmap #4).

Stress-test the focal XAUUSD trend edge against parameter perturbation. The
question is NOT "what is the best parameter set" (that is curve-fitting) but
"does the edge survive being knocked around its defaults?" A genuine edge is a
broad plateau in parameter space; an overfit one is a lonely spike.

For each (lookback-set x pt_sl) grid point we run the SAME net-of-cost pipeline
and gate as ``run_research.py`` -- backtest -> CPCV/DSR/PBO -> regime buckets ->
PromotionGate -- and record every trial to the shared TrialLedger (so the DSR
deflation honestly reflects how many configs were tried; the ledger dedupes by
signature, and the trend signature now records lookbacks + the D1 filter).

    python scripts/robustness_sweep.py --config config/csv.yaml --symbol XAUUSD

Output: a per-combo stability table + a dispersion summary, written to stdout
and to ``reports/robustness_<symbol>.md``. Nothing here guarantees profit;
the verdict vocabulary stays PROMOTED/REJECTED.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from xau import set_global_seed
from xau.config import load_config
from xau.data.source import make_source
from xau.gate import PromotionGate
from xau.metrics.perf import compute_performance
from xau.validation.ledger import TrialLedger

# run_research is a sibling script, not a package module; import its helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_research import run_one  # noqa: E402


# Perturbation grid. Defaults sit INSIDE the grid (not on an edge) so we can see
# whether the chosen config is on a plateau or a spike. Both axes are knobs that
# DEMONSTRABLY move the trend backtest: the momentum lookbacks (faster -> slower;
# research says trend is strongest slow) and the D1 higher-TF filter (incl. OFF).
# We deliberately do NOT sweep pt_sl: the trend signal hardcodes its barrier
# mults, so pt_sl is inert for trend -- sweeping it would fake the trial count,
# not stress the edge. (vol_target_annual was dead config and has been removed.)
LOOKBACK_SETS = {
    "fast(10,30,60)":   (10, 30, 60),
    "mid(15,40,80)":    (15, 40, 80),
    "default(20,60,120)": (20, 60, 120),
    "slow(40,120,240)": (40, 120, 240),
}
D1_SETS = {
    "off":          None,
    "d1(20,50)":    (20, 50),   # default
    "d1(10,30)":    (10, 30),
    "d1(50,100)":   (50, 100),
}


def _perturb(config, lookbacks, d1_lookbacks):
    """Return a copy of ``config`` with trend lookbacks + D1 filter swapped.

    ``d1_lookbacks=None`` turns the D1 overlay OFF (``data.d1_overlay=False``),
    so ``run_one`` passes ``d1=None`` and the higher-TF filter is bypassed.
    Config dataclasses are frozen, so we rebuild via ``dataclasses.replace`` --
    no mutation, fully reproducible.
    """
    d1_on = d1_lookbacks is not None
    trend_kw = {"lookbacks": tuple(lookbacks)}
    if d1_on:
        trend_kw["d1_lookbacks"] = tuple(d1_lookbacks)
    trend = dataclasses.replace(config.features.trend, **trend_kw)
    features = dataclasses.replace(config.features, trend=trend)
    data = dataclasses.replace(config.data, d1_overlay=d1_on)
    return dataclasses.replace(config, features=features, data=data)


def main() -> int:
    ap = argparse.ArgumentParser(description="XAUUSD trend robustness sweep")
    ap.add_argument("--config", default="config/csv.yaml")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--ledger", default="trial_ledger.jsonl")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    base = load_config(args.config)
    set_global_seed(base.seed)
    source = make_source(base)
    ledger = TrialLedger(args.ledger)
    ann = base.backtest.annual_bars

    print(f"=== Robustness sweep | {args.symbol} trend | source={base.data.source} "
          f"| {len(LOOKBACK_SETS)}x{len(D1_SETS)} grid ===")
    print("Same gate as run_research. Each combo is a distinct ledger trial.\n")

    rows = []
    for lb_name, lb in LOOKBACK_SETS.items():
        for d1_name, d1 in D1_SETS.items():
            cfg = _perturb(base, lb, d1)
            g2 = PromotionGate(cfg)
            result, gr, _rb, _rep = run_one(
                cfg, source, args.symbol, "trend", ledger, g2,
                f_sweep_result=None, start=cfg.data.start, end=cfg.data.end,
            )
            perf = compute_performance(result.bar_returns.to_numpy(),
                                       result.trade_pnl(), result.trade_r(), ann)
            ev = gr.evidence
            rows.append({
                "lookbacks": lb_name, "d1": d1_name,
                "trades": int(result.n_trades),
                "net_return": perf.net_return,
                "sharpe": perf.sharpe,
                "max_dd": perf.max_drawdown,
                "dsr": float(ev.get("dsr", 0.0)),
                "pbo": float(ev.get("pbo", 1.0)),
                "cpcv_pos": float(ev.get("cpcv_positive_frac", 0.0)),
                "tstat": float(ev.get("t_stat", 0.0)),
                "verdict": gr.verdict,
            })
            print(f"  {lb_name:<20} {d1_name:<10}  "
                  f"ret {perf.net_return*100:+6.1f}%  Sh {perf.sharpe:+5.2f}  "
                  f"DD {perf.max_drawdown*100:4.1f}%  PBO {ev.get('pbo',1):.2f}  "
                  f"CPCV+ {ev.get('cpcv_positive_frac',0)*100:4.0f}%  "
                  f"t {ev.get('t_stat',0):+4.2f}  {gr.verdict}")

    # ---- dispersion summary: is the edge a plateau or a spike? ----
    sharpes = np.array([r["sharpe"] for r in rows], float)
    rets = np.array([r["net_return"] for r in rows], float)
    pbos = np.array([r["pbo"] for r in rows], float)
    n = len(rows)
    pos = int(np.sum(sharpes > 0))
    promoted = sum(1 for r in rows if r["verdict"] == "PROMOTED")

    def _pct(x):
        return f"{x*100:.1f}%"

    summary = [
        "",
        "-- Robustness summary (the edge must be a PLATEAU, not a spike) --",
        f"  grid points                : {n}",
        f"  net-Sharpe > 0             : {pos}/{n} ({_pct(pos/n)})",
        f"  Sharpe  median / min / max : {np.median(sharpes):+.2f} / "
        f"{sharpes.min():+.2f} / {sharpes.max():+.2f}",
        f"  Sharpe  IQR (P25..P75)     : {np.percentile(sharpes,25):+.2f} .. "
        f"{np.percentile(sharpes,75):+.2f}",
        f"  net-return median / min/max: {_pct(np.median(rets))} / "
        f"{_pct(rets.min())} / {_pct(rets.max())}",
        f"  PBO median / max           : {np.median(pbos):.2f} / {pbos.max():.2f}",
        f"  PROMOTED configs           : {promoted}/{n}",
        f"  distinct ledger trials     : {ledger.n_unique_signatures()} "
        f"(rows logged: {ledger.n_trials})",
        "",
        "  Read: a high net-Sharpe>0 fraction with a TIGHT positive IQR = robust",
        "  plateau. A single bright spike amid negatives = overfit. PROMOTED=0 is",
        "  expected -- the gate stays strict; this measures STABILITY, not a pass.",
    ]
    print("\n".join(summary))

    # ---- markdown artifact ----
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = [f"# Robustness sweep -- {args.symbol} trend ({base.data.source} tape)",
          "",
          "All metrics NET of spread + commission + slippage. PROMOTED/REJECTED only.",
          "",
          "| lookbacks | D1 filter | trades | net ret | Sharpe(ann) | maxDD | DSR | PBO | CPCV+ | t-stat | verdict |",
          "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
    for r in rows:
        md.append(
            f"| {r['lookbacks']} | {r['d1']} | {r['trades']} | "
            f"{r['net_return']*100:+.1f}% | {r['sharpe']:+.2f} | "
            f"{r['max_dd']*100:.1f}% | {r['dsr']:.3f} | {r['pbo']:.2f} | "
            f"{r['cpcv_pos']*100:.0f}% | {r['tstat']:+.2f} | {r['verdict']} |"
        )
    md += ["", "## Summary", ""] + [s for s in summary if s and not s.startswith("--")]
    art = out_dir / f"robustness_{args.symbol}.md"
    art.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nWrote {art}. Nothing here guarantees profit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
