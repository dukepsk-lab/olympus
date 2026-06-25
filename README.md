# xau_research — skeptical research & validation engine (XAUUSD focal)

A reproducible, **net-of-cost** research-and-validation engine for a multi-symbol
FX/metals/index/crypto trading system with **XAUUSD (spot gold)** as the focal
instrument. The system is **skeptical by construction**: its primary job is to
**reject overfit strategies, not to bless them**. A config that fails the
promotion gate is rejected with a logged reason — never quietly tuned until it
passes.

All reported metrics are **after spread + commission + slippage**. There is **no
gross mode** and **no mid-price fill path** anywhere in the codebase.

## What this embodies

The system encodes an evidence-graded research conclusion (see the parent
`XAUUSD_Strategy_Research_Report.md`):

1. **Time-series momentum / trend-following is the primary edge** — the only
   family with peer-reviewed, multi-century, multi-asset support. Strongest
   **diversified** and at the **slower** end. Low win rate (~35–45%) + high
   payoff — the convexity *is* the edge; do not "fix" the win rate.
2. **Volatility/session breakout is a convex satellite, not a standalone** — the
   equity ORB edge is stock-in-play specific and does **not** transfer to gold;
   shipped only with strict false-break filters.
3. **Regime-gated mean reversion is an optional overlay, OFF by default** —
   short-horizon "reversion" is largely bid-ask bounce and dies net of retail
   spread; fires only inside a **causally**-computed range regime.
4. **Macro regime inputs decay** — no hardcoded gold↔real-yield rule; any macro
   series is a re-estimated feature, never a fixed assumption.
5. **Risk of ruin is controlled by the per-trade risk fraction `f`, not by
   withdrawal** — under fixed-fractional sizing % drawdown is scale-free;
   withdrawal banks irreversible cash and cuts total-wealth variance.

Default universe: `XAUUSD EURUSD GBPUSD USDJPY US30 BTCUSD`. Default TF: `H4`
with an optional `D1` slow-trend overlay. Everything is config-driven.

## Hard constraints (violating any is a bug)

- **NET OF COST ONLY.** No gross mode.
- **NO MID-PRICE FILLS, EVER.** Fills land on the correct side of bid/ask with
  explicit news/session spread widening (`backtest/fills.py`).
- **NO LOOK-AHEAD.** Signals at bar *t* use data ≤ bar *t*; triple-barrier labels
  are forward-looking by design and are **purged/embargoed** out of training
  (`validation/cpcv.py`, tested in `tests/test_cpcv_no_leakage.py`).
- **CPCV / DSR / PBO are hard promotion gates** (`gate.py`).
- **Honest trial counting.** A persistent `TrialLedger` records every config
  evaluated; the DSR `n_trials` comes from it, never a guess.

## Quick start

```bash
pip install -r requirements.txt

# end-to-end on synthetic data for the focal symbol (acceptance test):
python scripts/run_research.py --config config/default.yaml --symbol XAUUSD

# diversified trend across the whole universe (where the edge actually lives):
python scripts/run_research.py --config config/default.yaml --symbol universe --strategies trend

# write synthetic OHLC to CSV (then set data.source: csv in the config):
python scripts/make_synthetic.py --config config/default.yaml --out data/ohlc

pytest                         # 33 tests incl. CPCV no-leakage & no-mid-fill
```

Swapping `data.source` between `synthetic | csv | mt5` in the YAML requires **no
code changes**. `MT5Source` imports `MetaTrader5` lazily and is never exercised by
tests.

## Repository layout

```
xau_research/
├── config/default.yaml             # universe, costs, MM params, gate thresholds
├── xau/
│   ├── config.py                   # typed config loader (dataclasses)
│   ├── data/{source,sessions,news}.py
│   ├── costs/model.py              # spread/commission/slippage + news widening
│   ├── features/{trend,breakout,reversion,regime}.py
│   ├── labeling/triple_barrier.py  # triple-barrier labels + t1 (purge span)
│   ├── backtest/{engine,fills}.py  # event-driven bid/ask; NO mid fills
│   ├── mm/money.py                 # sizing + withdrawal + correlated cap + f-sweep
│   ├── validation/{cpcv,dsr,pbo,walkforward,ledger}.py
│   ├── metrics/perf.py             # Sharpe/Sortino/Calmar/maxDD/PF/win%/expectancy
│   ├── report/build.py             # net metrics + regime table + f-sweep + plots
│   └── gate.py                     # PromotionGate -> PROMOTED | REJECTED + reasons
├── scripts/{run_research,make_synthetic}.py
└── tests/                          # CPCV no-leakage, no-mid-fill, DSR monotonic, ...
```

## The promotion gate (defaults)

A config is **PROMOTED** only if it passes **all** of:

| check | default |
|---|---|
| DSR (skill prob, deflated by trial count) | ≥ 0.95 |
| PBO (combinatorial overfit) | ≤ 0.20 (hard reject > 0.50) |
| CPCV paths with positive net Sharpe | ≥ 0.70 |
| t-stat of mean return (multiple-testing-aware) | ≥ 3.0 |
| net-profitable regime buckets | ≥ 3 of 4 |
| net trades / regime exposure | ≥ 300 / ≥ 3 |
| median net Calmar across CPCV paths | > 0.30 |

These are **deliberately strict**. On the shipped synthetic data the gate
**rejects** every single-symbol config and even the diversified basket fails to
clear DSR/PBO — which is the intended skeptical behaviour. The verdict vocabulary
is **PROMOTED / REJECTED**, with evidence; nothing here guarantees profit.

## Notes on the synthetic generator

`SyntheticSource` is a documented **assumption**, not a fit: realistic price
levels + annual vols, a shared slow **AR(1) trend drift** (genuine return
autocorrelation — the condition TSMOM needs), regime-scaled volatility, and fat
tails. It is deterministic (single global seed; `hash()` is avoided because
Python randomises it per-process). Validate against your **own broker tape**
before risking capital.
