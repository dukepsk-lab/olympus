# STATUS

**Last updated:** 2026-06-25
**Data source:** REAL — IUX Markets demo (H4, 2021-11-29 → 2026-06-25, ~6.6k bars/symbol)
**State:** Validation engine complete; validated end-to-end on live broker tape. No config yet **PROMOTED** — by design (skeptical gate).

> Verdict vocabulary is **PROMOTED / REJECTED** with evidence. Nothing here guarantees profit. All metrics are **net of spread + commission + slippage**; fills on **bid/ask only** (no mid).

> **Cost model (IUX, updated 2026-06-25):** commission **$7/lot round-turn** ($3.5/side, charged on entry AND exit) on every symbol; **swap = 0** (IUX swap-free, not modelled); **spread** uses a real per-bar `spread` column when the feed provides one, else the base-spread assumption. ⚠️ The committed CSVs have **no `spread` column yet** (the older `fetch_mt5` dropped it) — a one-time MT5 re-fetch is needed to populate real spread; until then the base-spread fallback is in effect. `net return` is **total (cumulative)**; the report now also prints **annualised (CAGR)**.

---

## Current results (real IUX tape, net of cost)

### Focal symbol — XAUUSD trend
| metric | value |
|---|---|
| Sharpe (ann.) | **+0.72** |
| Net return (total) | **+40.8%** |
| Annualised return (CAGR) | **+8.95%** |
| Max drawdown | 18.7% |
| Win rate | 27.9% |
| Profit factor | 1.19 |
| Expectancy | +0.149 R |
| Trades | 319 |
| **Verdict** | **REJECTED** |

Failed checks: DSR 0.923 < 0.95 · t-stat 1.42 < 3.0 · PBO 0.263 > 0.20 · CPCV+ 62% < 70% · profitable in 2/4 regimes. Edge concentrated in the gold bull regime (Sharpe 0.94). **Real edge, correct shape, not yet statistically conclusive for one symbol.**

### Universe — single-symbol trend (net total return, $7 RT commission)
| symbol | net return | verdict |
|---|---|---|
| XAUUSD | +40.8% | REJECTED |
| USDJPY | +45.4% | REJECTED |
| BTCUSD | +47.8% | REJECTED |
| US30 | +4.4% | REJECTED |
| EURUSD | -10.8% | REJECTED |
| GBPUSD | -19.1% | REJECTED |

### Diversified basket (equal-fraction)
| metric | value |
|---|---|
| Sharpe (ann.) | +0.54 |
| Net return (total) | +18.1% |
| Annualised return (CAGR) | +3.3% |
| Max drawdown | **8.2%** |
| CPCV paths positive | **80%** |
| **Verdict** | **REJECTED** |

Failed checks: PBO 0.672 > hard-reject 0.5 · DSR (deflated by the 6 universe trials) · t-stat < 3.0. Diversification works (8.2% max DD) but FX pairs dragged returns and path-to-path variance flags overfit risk. (Inverse-vol weighting was tested as a fix and made it **worse** — see "Portfolio weighting" below.)

---

## Done
- Full 17-module pipeline (scaffold → `run_research.py`), config-driven.
- **66 tests green** incl. CPCV no-leakage, no-mid-fill, ledger-dedup, sweep, weighting, selection & real-spread guards.
- `SyntheticSource` / `CsvSource` / `MT5Source` — swap needs zero code change.
- `scripts/fetch_mt5.py` — live MT5 fetch; pulled full universe from IUX demo.
- Reproducible (deterministic seed; `zlib.crc32` stable hash).
- Validated on real broker tape (IUX) — XAUUSD trend confirmed profitable net-of-cost.
- Bugs caught & fixed: `hash()` non-determinism; `point_value` vs `contract_size` (100× gold error); `max_drawdown` sign; DSR per-obs vs annualised units.
- **Ledger dedup hardening:** DSR `n_trials` (and the trial-Sharpe variance) now count **distinct config signatures**, not raw appends — re-running the same config no longer drifts the DSR. The XAUUSD-trend DSR 0.924 above reproduces exactly on a clean ledger. (`xau/validation/ledger.py`, `tests/test_ledger_dedup.py`.)
- **Robustness sweep** (`scripts/robustness_sweep.py`, roadmap #4): the focal edge is a **plateau, not a spike**. See below.

## Robustness sweep — XAUUSD trend (real IUX tape, net of cost)

16-point grid over `lookbacks × D1-filter` (the two knobs that demonstrably move
the trend backtest), each a distinct ledger trial through the same gate:

| metric | value |
|---|---|
| net-Sharpe > 0 | **16/16 (100%)** |
| Sharpe median / min / max | +0.84 / +0.24 / +1.24 |
| Sharpe IQR (P25..P75) | +0.65 .. +1.09 |
| net-return median / range | +51% / +5.8% .. +89.5% |
| PBO median / max | 0.45 / 0.63 |
| PROMOTED | 0/16 (gate stays strict) |

**Reads as a genuine edge:** every perturbation stays net-positive — the sign
never flips. The shipped default (`(20,60,120)` + `d1(20,50)`, +0.72 Sharpe /
+40.8%) sits in the **lower half** of the plateau, so the headline number is
**conservative, not cherry-picked**. The one soft spot is `mid` lookbacks with
the slowest D1 filter (+5.8%, 50% DD). PBO stays elevated (~0.45) across the
grid — consistent with the gate's single-symbol REJECT: robustly profitable, but
still overfit-prone on one instrument.

### Two code findings surfaced by the sweep (now resolved)
- **`vol_target_annual` was dead config** — parsed in `config.py`, consumed
  nowhere. **Removed** (2026-06-25): trend vol-targeting is structural via
  `stop_distance` (= `sl_mult * vol * price`) feeding fixed-fractional sizing, so
  no behaviour changed.
- **Trend ignores `labeling.pt_sl`** — `tsmom_signal` hardcodes `pt_mult=10,
  sl_mult=3` (intentional: wide target lets winners run), and the engine prefers
  the signal's own barrier columns. So `labeling.pt_sl` is inert *for trend*
  (it does drive breakout/reversion). The sweep therefore varies `lookbacks` and
  the `D1` filter, **not** `pt_sl`, to keep the DSR trial count honest.

## Portfolio weighting — inverse-vol tested, kept OFF (honest negative result)

Added causal **inverse-volatility (risk-parity-lite)** allocation as an option
(`xau/mm/portfolio.py`, `--weighting inverse_vol`). Weights come from each
symbol's `1/sigma` over a **leading** window (no look-ahead). Head-to-head on the
real IUX tape, diversified trend:

| metric | equal (default) | inverse_vol |
|---|---:|---:|
| Sharpe (ann.) | **+0.556** | +0.356 |
| net return | **+18.6%** | +12.7% |
| max drawdown | **8.1%** | 11.0% |
| CPCV paths positive | **80%** | 69% |
| PBO | **0.673** | 0.928 |

**Inverse-vol UNDERperforms here, and the reason is the useful lesson:** it
overweights the *calm* FX pairs (EUR/GBP → ~23–24% each) — which were the basket's
**losers** (−10.8%, −19.1%) — and starves the *high-vol* BTC/gold (→ 2%/16%), which
were the genuine diversifying **winners** (+48.8%, +40.8%). Risk-parity equalises
risk, it does **not** down-weight losers; "weight by vol" ≠ "weight down the drag."
The roadmap's hoped-for fix (cut the FX drag) actually needs a *different* lever —
e.g. gating out symbols that fail their own single-symbol check, or
return/Sharpe-aware weights (which invite look-ahead/overfitting and must clear
the gate). **`equal` stays the default;** `inverse_vol` ships as a documented,
test-covered option. Negative results are results.

## Gate-aware basket — selection on trailing performance, also OFF (2nd negative)

Added a **gate-aware** basket (`--basket-mode gate_aware`): pick symbols by their
**causal train-slice** net Sharpe (default first 30% of the tape), then evaluate
the kept basket strictly **out-of-sample** on the remaining 70% — a real
train/test split so selection can't peek at the eval window. Same OOS window is
also run on the full universe as a baseline.

On the IUX tape the split is select-on `[2020, 2023-06)`, evaluate `[2023-06, 2025]`:

| symbol | train Sharpe | kept? | OOS return |
|---|---:|:--:|---:|
| XAUUSD | +0.19 | keep | +37.3% |
| EURUSD | +0.38 | keep | −16.9% |
| GBPUSD | +0.17 | keep | −17.7% |
| USDJPY | +1.08 | keep | +16.4% |
| US30 | −0.51 | **drop** | +11.9% |
| BTCUSD | −0.08 | **drop** | **+46.8%** |

**OOS: gate-aware +4.7% (REJECT) vs all-symbols +13.0% (REJECT).** Selection
*hurt*. It dropped US30 and BTC for weak 2020–23 Sharpe — and BTC was the single
biggest 2023–25 winner, while the kept FX pairs kept bleeding. This is
performance-chasing under non-stationarity: **trailing Sharpe did not persist.**

**Combined verdict on the basket experiments:** both proposed fixes for the "FX
drag" — inverse-vol weighting *and* gate-aware selection — **underperform plain
equal-weight diversification** on this tape. That is not a disappointment; it is
the research thesis holding up: broad, cheap diversification is hard to beat, and
clever symbol selection/weighting is fragile. **Default stays `all` + `equal`.**

## D1 slow-trend overlay — `merge` mode tested, `filter` (veto) stays default

Roadmap #2. The daily trend was already used as a **veto filter** (trade H4 only
when the daily trend agrees). Added a second mode, **`merge`** (`--d1-mode merge`,
`features.trend.d1_mode`), that folds the daily trend in as an extra weighted
momentum **vote** — adding to both direction and conviction — per the research
that slower-horizon trend is the cleaner signal. Causal (previous completed daily
bar); `filter` default reproduces byte-for-byte.

Head-to-head on the real IUX tape (trend, net of cost):

| | XAUUSD filter | XAUUSD merge | basket filter | basket merge |
|---|---:|---:|---:|---:|
| net return (total) | **+40.8%** | +25.3% | **+18.1%** | +13.6% |
| Sharpe (ann.) | **+0.72** | +0.48 | **+0.54** | +0.42 |
| max drawdown | 18.7% | 21.5% | **8.2%** | 9.4% |
| PBO | — | — | **0.67** | 0.94 |
| trades (XAU) | 319 | 368 | — | — |

**`merge` is worse everywhere, and the reason is instructive:** the slow signal's
value here is as a **quality veto** that removes counter-trend H4 trades. Turning
it into a mere vote *loosens* entry (319→368 trades on gold; more whipsaw on the
choppy FX pairs), lifting PBO to 0.94. The research's "slower is better" is about
signal **horizon**, which the system already captures via the daily *filter* —
demoting it to a vote does not help. **`filter` stays default; `merge` ships as a
documented, test-covered option.** (Note: a true *standalone* D1 strategy can't
be validated on this 4.6-year tape — ~1,160 daily bars give far fewer than the
300-trade gate minimum; that needs the longer history parked on #1.)

## Gate calibration (#3) — diagnostic + documented profile, default stays strict

Done the integrity-preserving way (no tuning-to-pass). Added **named gate
profiles** (`xau/gate.py`): `strict` (the unchanged default) and
`single_hypothesis`, which makes **one principled change** — the t-stat bar
`3.0 → 2.0` — and **nothing else**. Rationale (logged): `t≥3.0` is Harvey-Liu-Zhu's
bar for a *factor zoo* of hundreds of data-mined candidates; a single
pre-specified TSMOM hypothesis with a multi-decade prior warrants the
single-test bar (~2.0). DSR (already trial-deflated), PBO, CPCV breadth, regime
breadth and sample size are **untouched** — they encode robustness, not multiple
testing. Selectable via `--gate-profile`; **nothing is promoted unless you pick it.**

**Diagnostic** (`scripts/gate_calibration.py`) computes the evidence once and
re-judges it under every profile (shared `failed_checks_from_evidence`, so it
can't drift from the live gate). On XAUUSD:

| check | value | strict | single_hyp |
|---|---:|:--:|:--:|
| DSR | 0.924 | fail ≥0.95 | fail ≥0.95 |
| PBO | 0.263 | fail ≤0.20 | fail ≤0.20 |
| CPCV+ | 0.622 | fail ≥0.70 | fail ≥0.70 |
| t-stat | 1.43 | fail ≥3.0 | **fail ≥2.0** |
| regimes profitable | 2/4 | fail ≥3 | fail ≥3 |

**The honest punchline: loosening cannot rescue XAUUSD.** Its t-stat (1.43) fails
even the relaxed 2.0 bar, and it *independently* fails regime breadth (2/4), DSR,
PBO and CPCV. A REJECT that fails on those is **not a t-stat artefact** — only
more independent evidence (more regimes/history/symbols) fixes it, not a
threshold. The `single_hypothesis` profile *would* flip a config that is strong
everywhere except a t-stat in (2.0, 3.0) — none exists here. **`strict` stays
default.**

## In progress
- (none active)

## Next (priority order)
1. **Extend the real tape pre-2021** — fill the empty `covid_shock` regime bucket (more regime coverage + statistical power).
2. ~~**D1 slow-trend overlay**~~ — **DONE**: added `merge` mode; underperforms the `filter` veto on this tape (see above). A *standalone* D1 strategy is data-starved here (~1,160 daily bars < 300-trade gate) — needs the longer history in #1.
3. ~~**Gate-threshold calibration**~~ — **DONE**: named profiles (strict default + documented single_hypothesis), diagnostic in scripts/gate_calibration.py. Loosening cannot rescue XAUUSD (multi-fail) — see above.
4. ~~**Robustness sweep**~~ — **DONE** (`scripts/robustness_sweep.py`; edge is a plateau, see above).
5. ~~**Portfolio weighting**~~ — **DONE** (inverse-vol tested; underperforms equal). ~~Follow-up: gate-aware basket~~ — **DONE** (selection on trailing Sharpe also underperforms; see above). Both confirm equal-weight diversification is the baseline to beat.
6. ~~**Hygiene**~~ — **DONE**: `ruff` clean (config in `pyproject.toml`, run in CI) + GitHub Actions (pytest + synthetic smoke-test).
7. ~~*(Cleanup)* dead `vol_target_annual`~~ — **DONE** (removed; vol-targeting is structural).

## Out of scope (by design)
- Live order routing (research-only).
- ML alpha (edge here is rules-based TSMOM).
- Hardcoded macro rules (gold↔real-yield etc.).
