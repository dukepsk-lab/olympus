# STATUS

**Last updated:** 2026-06-25
**Data source:** REAL — IUX Markets demo (H4, 2021-11-29 → 2026-06-25, ~6.6k bars/symbol)
**State:** Validation engine complete; validated end-to-end on live broker tape. No config yet **PROMOTED** — by design (skeptical gate).

> Verdict vocabulary is **PROMOTED / REJECTED** with evidence. Nothing here guarantees profit. All metrics are **net of spread + commission + slippage**; fills on **bid/ask only** (no mid).

---

## Current results (real IUX tape, net of cost)

### Focal symbol — XAUUSD trend
| metric | value |
|---|---|
| Sharpe (ann.) | **+0.71** |
| Net return | **+40.4%** |
| Max drawdown | 18.7% |
| Win rate | 27.9% |
| Profit factor | 1.19 |
| Expectancy | +0.149 R |
| Trades | 319 |
| **Verdict** | **REJECTED** |

Failed checks: DSR 0.923 < 0.95 · t-stat 1.42 < 3.0 · PBO 0.263 > 0.20 · CPCV+ 62% < 70% · profitable in 2/4 regimes. Edge concentrated in the gold bull regime (Sharpe 0.94). **Real edge, correct shape, not yet statistically conclusive for one symbol.**

### Universe — single-symbol trend
| symbol | net return | verdict |
|---|---|---|
| XAUUSD | +40.4% | REJECTED |
| USDJPY | +45.1% | REJECTED |
| BTCUSD | +48.8% | REJECTED |
| US30 | +6.3% | REJECTED |
| EURUSD | -11.2% | REJECTED |
| GBPUSD | -19.4% | REJECTED |

### Diversified basket (equal-fraction)
| metric | value |
|---|---|
| Sharpe (ann.) | +0.55 |
| Net return | +18.4% |
| Max drawdown | **8.1%** |
| CPCV paths positive | **80%** |
| Median Calmar (paths) | 0.86 |
| **Verdict** | **REJECTED** |

Failed checks: PBO 0.673 > hard-reject 0.5 · DSR 0.447 (deflated by the 6 universe trials) · t-stat 1.25 < 3.0. Diversification works (8.1% max DD) but FX pairs dragged returns and path-to-path variance flags overfit risk.

---

## Done
- Full 17-module pipeline (scaffold → `run_research.py`), config-driven.
- **37 tests green** incl. CPCV no-leakage, no-mid-fill & ledger-dedup guards.
- `SyntheticSource` / `CsvSource` / `MT5Source` — swap needs zero code change.
- `scripts/fetch_mt5.py` — live MT5 fetch; pulled full universe from IUX demo.
- Reproducible (deterministic seed; `zlib.crc32` stable hash).
- Validated on real broker tape (IUX) — XAUUSD trend confirmed profitable net-of-cost.
- Bugs caught & fixed: `hash()` non-determinism; `point_value` vs `contract_size` (100× gold error); `max_drawdown` sign; DSR per-obs vs annualised units.
- **Ledger dedup hardening:** DSR `n_trials` (and the trial-Sharpe variance) now count **distinct config signatures**, not raw appends — re-running the same config no longer drifts the DSR. The XAUUSD-trend DSR 0.924 above reproduces exactly on a clean ledger. (`xau/validation/ledger.py`, `tests/test_ledger_dedup.py`.)

## In progress
- (none active)

## Next (priority order)
1. **Extend the real tape pre-2021** — fill the empty `covid_shock` regime bucket (more regime coverage + statistical power).
2. **D1 slow-trend overlay** — TSMOM edge is strongest at slower frequencies (config hooks exist).
3. **Gate-threshold calibration** — XAUUSD sits at DSR 0.92, close; tune only with logged rationale.
4. **Robustness sweep** — vary `f`, barrier mults, lookback → `TrialLedger` → re-check DSR/PBO stability.
5. **Portfolio weighting** — vol-target / inverse-vol (FX pairs dragged the basket).
6. **Hygiene** — `ruff` lint (GitHub Actions CI live: pytest + synthetic smoke-test).

## Out of scope (by design)
- Live order routing (research-only).
- ML alpha (edge here is rules-based TSMOM).
- Hardcoded macro rules (gold↔real-yield etc.).
