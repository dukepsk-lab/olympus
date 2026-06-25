# STATUS

**Last updated:** 2026-06-25
**Data source:** REAL — IUX Markets demo (H4, **2018-01-02 → 2026-06-25, ~13.5k bars/symbol**)
**State:** Validation engine complete; validated end-to-end on live broker tape. No config yet **PROMOTED** — by design (skeptical gate).

> Verdict vocabulary is **PROMOTED / REJECTED** with evidence. Nothing here guarantees profit. All metrics are **net of spread + commission + slippage**; fills on **bid/ask only** (no mid).

> **Cost model (IUX commission-free account, updated 2026-06-25):** commission **= 0** (the traded account prices cost into the spread, not a per-lot fee); **swap = 0** (IUX swap-free, not modelled); **spread** uses the real per-bar `spread` column the feed now carries. ⚠️ **A `spread == 0` is treated as MISSING, not a free crossing** — the backfilled 2018-2020 history shipped without per-bar spread (~43% of the tape), so those bars are charged the **base-spread assumption** (`base_spread × session/news`) rather than trading for free. A real instrument never has a zero spread, so a 0 in the feed is a data gap, and a data gap must not become a free lunch. (Charging real spread there cut the focal headline +89.7% → **+79.7%** — the ~10pp gap was phantom cost-free profit.) `net return` is **total (cumulative)**; the report also prints **annualised (CAGR)**.

---

## Current results (real IUX tape, net of cost)

### Focal symbol — XAUUSD trend (full 2018-2026 tape, net of cost)
| metric | value |
|---|---|
| Sharpe (ann.) | **+0.54** |
| Net return (total) | **+79.7%** |
| Annualised return (CAGR) | **+6.5%** |
| Max drawdown | 25.0% |
| Win rate | 26.0% |
| Profit factor | 1.16 |
| Expectancy | +0.067 R |
| Trades | 730 |
| **Verdict** | **REJECTED** |

Failed checks: DSR 0.9498 < 0.95 (razor-thin) · t-stat 1.64 < 3.0 · PBO 0.336 > 0.20 · median Calmar 0.273 < 0.30. **Now passes** regime breadth (**3/4** profitable: covid_shock, fed_hiking, rally_2023-25) and CPCV+ (**71%** ≥ 70%) — both improved once the 2018-2020 history filled the previously-empty covid/fed buckets. **Real edge, correct convex shape, the longer tape strengthened it (2/4→3/4 regimes), but it is still not statistically conclusive for one symbol** — the binding rejections are now t-stat and PBO, not breadth.

### Universe — single-symbol trend (full tape, commission-free account, net of cost)
| symbol | net return | CAGR | Sharpe | trades | regimes+ | verdict |
|---|---:|---:|---:|---:|:--:|---|
| BTCUSD | +185.8% | +8.7% | +0.54 | 938 | 3/4 | REJECTED |
| XAUUSD | +79.7% | +6.5% | +0.54 | 730 | 3/4 | REJECTED |
| USDJPY | −6.1% | −0.7% | +0.02 | 699 | 2/4 | REJECTED |
| US30 | −23.3% | −3.5% | −0.19 | 554 | 2/4 | REJECTED |
| EURUSD | −24.9% | −3.0% | −0.17 | 651 | 2/4 | REJECTED |
| GBPUSD | −29.3% | −3.7% | −0.22 | 698 | 2/4 | REJECTED |

Only **XAUUSD and BTCUSD** carry a positive trend edge on the full tape — both with the textbook convex signature (win rate 26%/31%, PF 1.16/1.30). Note USDJPY, which looked positive (+45%) on the shorter 2021-only tape, **flipped to ~flat (−6%)** once 2018-2020 was added — a clean reminder that short samples flatter non-edges. The FX pairs and US30 have **no** trend edge net of cost.

### Diversified basket (equal-fraction, full tape)
| metric | value |
|---|---|
| Sharpe (ann.) | +0.31 |
| Net return (total) | +30.3% |
| Annualised return (CAGR) | +2.1% |
| Max drawdown | 19.9% |
| CPCV paths positive | 69% |
| PBO | 0.274 |
| **Verdict** | **REJECTED** |

Failed checks: PBO 0.274 > 0.20 · DSR (deflated by the 6 universe trials) · t-stat < 3.0 · CPCV+ 69% < 70%. The equal-weight basket is dragged by the four non-trending symbols (EUR/GBP/US30/JPY) that the broad-diversification thesis still includes; max DD 19.9%. (Inverse-vol weighting and gate-aware selection were both tested as fixes and made it **worse** — see below.)

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
