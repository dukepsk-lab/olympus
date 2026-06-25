"""Gate-calibration diagnostic (roadmap #3).

Runs a config ONCE, then re-judges the SAME evidence under every named gate
profile -- so you can see exactly which checks bind and what (if anything) a
principled threshold change would promote. It does NOT tune anything: the
profiles are fixed and documented in ``xau/gate.py`` (`gate_config_for_profile`),
and the strict profile stays the system default. Re-judging reuses the gate's own
`failed_checks_from_evidence`, so this can never drift from the real gate.

    python scripts/gate_calibration.py --config config/csv.yaml --symbol XAUUSD

The honest point of this tool is usually to show that loosening does NOT rescue a
config -- a REJECT that fails on regime breadth / CPCV / DSR is not a t-stat
artefact, and no defensible profile change fixes it. Nothing here guarantees
profit; verdicts stay PROMOTED/REJECTED.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xau import set_global_seed
from xau.config import load_config
from xau.data.source import make_source
from xau.gate import (
    GATE_PROFILES,
    PromotionGate,
    failed_checks_from_evidence,
    gate_config_for_profile,
)
from xau.validation.ledger import TrialLedger

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_research import run_one  # noqa: E402


# (label, evidence key, gate-config attr, comparator) -- comparator is how the
# VALUE relates to the THRESHOLD to PASS.
_CHECKS = [
    ("DSR",                "dsr",                     "dsr_min",                ">="),
    ("PBO",                "pbo",                     "pbo_max",                "<="),
    ("CPCV+ frac",         "cpcv_positive_frac",      "cpcv_positive_frac_min", ">="),
    ("t-stat",             "t_stat",                  "tstat_min",              ">="),
    ("regimes profitable", "regime_profitable_count", "regime_profitable_min",  ">="),
    ("regime exposure",    "regime_exposure_count",   "regime_exposure_min",    ">="),
    ("net trades",         "n_trades",                "min_net_trades",         ">="),
    ("median Calmar",      "median_calmar_paths",     "median_calmar_min",      ">"),
]


def _passes(value: float, thr: float, comp: str) -> bool:
    if comp == ">=":
        return value >= thr
    if comp == ">":
        return value > thr
    return value <= thr  # "<="


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate-calibration diagnostic")
    ap.add_argument("--config", default="config/csv.yaml")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--strategy", default="trend")
    ap.add_argument("--ledger", default="trial_ledger.jsonl")
    args = ap.parse_args()

    cfg = load_config(args.config)
    set_global_seed(cfg.seed)
    source = make_source(cfg)
    ledger = TrialLedger(args.ledger)
    gate = PromotionGate(cfg)

    print(f"=== Gate calibration | {args.symbol} {args.strategy} "
          f"| source={cfg.data.source} ===")
    print("Evidence is computed ONCE; each profile re-judges the same numbers.\n")

    _res, gr, _rb, _rep = run_one(cfg, source, args.symbol, args.strategy, ledger,
                                  gate, None, cfg.data.start, cfg.data.end)
    ev = gr.evidence

    # header
    profiles = list(GATE_PROFILES)
    gconfs = {p: gate_config_for_profile(cfg.gate, p) for p in profiles}
    head = f"  {'check':<20}{'value':>10}  " + "  ".join(
        f"{p[:14]:>14}" for p in profiles)
    print(head)
    print("  " + "-" * (len(head) - 2))
    for label, ekey, attr, comp in _CHECKS:
        if ekey not in ev:
            continue
        val = float(ev[ekey])
        cells = []
        for p in profiles:
            thr = getattr(gconfs[p], attr)
            ok = _passes(val, thr, comp)
            cells.append(f"{('PASS' if ok else 'fail')} {comp}{thr:g}".rjust(14))
        print(f"  {label:<20}{val:>10.3f}  " + "  ".join(cells))

    print()
    for p in profiles:
        failed = failed_checks_from_evidence(ev, gconfs[p])
        verdict = "PROMOTED" if not failed else "REJECTED"
        binding = ", ".join(f.split(" <")[0].split(" >")[0] for f in failed) or "(none)"
        print(f"  profile {p:<18} -> {verdict}"
              + ("" if not failed else f"   binding: {binding}"))

    print("\n  NOTE: profiles are fixed & documented (xau/gate.py), never tuned to")
    print("  pass. `strict` stays the default. A REJECT that still fails on regime")
    print("  breadth / CPCV / DSR is NOT a t-stat artefact -- only more independent")
    print("  evidence (more regimes/history/symbols) can fix that, not a threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
