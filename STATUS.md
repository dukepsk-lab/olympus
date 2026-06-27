# STATUS

**Last updated:** 2026-06-25
**Data source:** REAL — IUX Markets demo (H4). XAUUSD/EUR/GBP/JPY/US30/BTC run **2018-01-02 → 2026-06-25** (~13.5k bars); the 3 breadth additions (AUDUSD/XAGUSD/USOIL, fetched 2026-06-26) start **2021-11** (~5.6-6.7k bars — IUX history limit for those symbols).
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

### Universe — single-symbol trend (real IUX tape, commission-free account, net of cost)
| symbol | net return | CAGR | Sharpe | trades | regimes+ | verdict |
|---|---:|---:|---:|---:|:--:|---|
| BTCUSD | +185.8% | +8.7% | +0.54 | 938 | 3/4 | REJECTED |
| XAUUSD | +79.7% | +6.5% | +0.54 | 730 | 3/4 | REJECTED |
| USDJPY | −6.1% | −0.7% | +0.02 | 699 | 2/4 | REJECTED |
| XAGUSD | −4.8% | −1.1% | −0.02 | 328 | 0/4 | REJECTED |
| US30 | −23.3% | −3.5% | −0.19 | 554 | 2/4 | REJECTED |
| EURUSD | −24.9% | −3.0% | −0.17 | 651 | 2/4 | REJECTED |
| GBPUSD | −29.3% | −3.7% | −0.22 | 698 | 2/4 | REJECTED |
| USOIL | −30.5% | −9.0% | −0.64 | 303 | 1/4 | REJECTED |
| AUDUSD | −47.9% | −13.3% | −1.09 | 299 | 1/4 | REJECTED |

Only **XAUUSD and BTCUSD** carry a positive trend edge net of cost — both with the textbook convex signature (win rate 26%/31%, PF 1.16/1.30). Note USDJPY, which looked positive (+45%) on the shorter 2021-only tape, **flipped to ~flat (−6%)** once 2018-2020 was added — a clean reminder that short samples flatter non-edges. The 3 breadth additions (AUDUSD/XAGUSD/USOIL, fetched 2026-06-26) all have **no** trend edge here — even silver, which usually co-trends with gold, is flat net of cost on this retail-CFD tape.

### Diversified basket — 9 symbols vs original 6 (equal-fraction, real tape)
| metric | 6-symbol | 9-symbol (current default) |
|---|---:|---:|
| Sharpe (ann.) | +0.31 | **+0.17** |
| Net return (total) | +30.3% | +11.0% |
| Annualised return (CAGR) | +2.1% | +0.8% |
| Max drawdown | 19.9% | **13.5%** |
| CPCV paths positive | 69% | 60% |
| t-stat | — | 0.62 |
| PBO | 0.274 | 0.289 |
| median Calmar | — | 0.126 |
| **Verdict** | **REJECTED** | **REJECTED** |

**Breadth expansion — honest negative result.** The literature lever (diversify across more uncorrelated markets) was tested with *real* tape, not synthetic: AUDUSD, XAGUSD, USOIL added to the universe. It **lowered max drawdown (19.9% → 13.5%, diversification working as advertised) but cut returns/Sharpe and pushed t-stat the wrong way (→ 0.62, further from the 3.0 bar).** The reason is the crucial caveat to "breadth helps": TSMOM's ~50-market result assumes each market *carries* the trend edge. These three **don't** net of cost, so equal-weighting them just dilutes the two genuine trenders (XAU, BTC) with flat-to-negative votes. The verdict stays REJECTED, now bound by t-stat 0.62 < 3.0 and median Calmar 0.126. **Lesson, consistent with the inverse-vol and gate-aware experiments: cheap broad diversification only pays when the added markets actually trend — it cannot manufacture an edge from markets that have none.** The 3 specs + tape are kept; whether to run the 9-symbol or 6-symbol universe is a documented choice, not an auto-promotion.

---

## Done
- Full 17-module pipeline (scaffold → `run_research.py`), config-driven.
- **71 tests green** incl. CPCV no-leakage, no-mid-fill, ledger-dedup, sweep, weighting, selection, real-spread & volume-filter guards.
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

## Volume-confirmation filter — tested, kept OFF (inconclusive, default unchanged)

Added an opt-in veto to `tsmom_signal` (`xau/features/trend.py`, `TrendConfig.
volume_filter_enabled`): a bar only fires if its volume is ≥ `volume_min_ratio`
times its own trailing rolling median (causal; warmup bars fail closed). OFF by
default — it never changes existing behaviour unless explicitly enabled. Caveat:
MT5/broker "volume" on FX/CFD is **tick volume** (a participation proxy), not a
real exchange print count.

Swept `volume_min_ratio` on XAUUSD (real IUX tape, same gate as the focal table):

| filter | net% | Sharpe | maxDD% | trades | t-stat | DSR | PBO | CPCV+% | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| OFF (baseline) | +79.7 | 0.54 | 25.0 | 730 | 1.64 | 0.950 | 0.336 | 71 | REJECTED |
| ratio ≥ 0.8 | +73.1 | 0.51 | 22.6 | 712 | 1.56 | 0.941 | 0.366 | 64 | REJECTED |
| ratio ≥ 1.0 | +61.6 | 0.46 | 26.3 | 687 | 1.39 | 0.918 | 0.381 | 58 | REJECTED |
| ratio ≥ 1.2 | -4.1 | 0.11 | 55.1 | 629 | 0.35 | 0.626 | 0.679 | 60 | REJECTED |
| ratio ≥ 1.5 | +99.9 | 0.67 | 19.0 | 553 | 2.05 | 0.980 | 0.362 | 80 | REJECTED |

**Honest read: no monotonic relationship, no rescue.** `ratio≥1.2` collapses
(Sharpe 0.11) while the *more* restrictive `ratio≥1.5` looks best on most
metrics (Sharpe 0.67, t-stat 2.05, DSR 0.98) — that non-monotonic bounce across
a 5-point grid is itself the multiple-testing trap the gate guards against:
picking "1.5 because it's the best of 5" without paying for those 5 trials would
be exactly the kind of post-hoc cherry-pick the `TrialLedger`/PBO exist to catch.
Even the best point still fails PBO (0.362 > 0.20 hard max). **Default stays
OFF**; the filter is available for anyone who wants to spend a ledger trial on
it deliberately, not folded into the headline config.

## In progress
- (none active)

## Why not just throw ML at it?
XAUUSD's REJECT is bound by **t-stat 1.64 < 3.0** and **PBO 0.336 > 0.20** — a
statistical-power / sample-size problem, not a "the model isn't smart enough"
problem (the edge already has the right convex shape and clears 3/4 regimes).
A more flexible model on the same ~730-trade single-symbol sample can only make
this *worse*: more fitted parameters inflates PBO, and the honest `TrialLedger`
deflates DSR harder per extra trial. The principled fix is **more independent
evidence**, not more model capacity — hence breadth (more uncorrelated markets)
and history (more bars) are next, not a model swap.

## Next (priority order)
1. ~~**Extend the real tape pre-2021**~~ — **DONE**: tape now runs 2018-01-02 →
   2026-06-25 (~13.5k bars/symbol), filling the `covid_shock`/`fed_hiking`
   regime buckets. Lifted XAUUSD regime breadth 2/4 → 3/4 and CPCV+ to 71%.
1b. ~~**Breadth expansion**~~ — **DONE (honest negative)**: fetched real IUX tape
   for **AUDUSD, XAGUSD, USOIL** (NAS100 is not served under that name on the IUX
   server — needs the correct symbol, e.g. `USTEC`/`US100`) and added them to the
   universe. The result drags the basket (Sharpe 0.31 → 0.17, t-stat → 0.62)
   while lowering max DD (19.9% → 13.5%) — see "Breadth expansion" above. None of
   the three carry a trend edge net of cost, so diversifying into them dilutes
   rather than strengthens. Confirms breadth only pays when the added markets
   actually trend.
2. ~~**D1 slow-trend overlay**~~ — **DONE**: added `merge` mode; underperforms the `filter` veto on this tape (see above). A *standalone* D1 strategy is data-starved here (~1,160 daily bars < 300-trade gate) — needs the longer history in #1.
3. ~~**Gate-threshold calibration**~~ — **DONE**: named profiles (strict default + documented single_hypothesis), diagnostic in scripts/gate_calibration.py. Loosening cannot rescue XAUUSD (multi-fail) — see above.
4. ~~**Robustness sweep**~~ — **DONE** (`scripts/robustness_sweep.py`; edge is a plateau, see above).
5. ~~**Portfolio weighting**~~ — **DONE** (inverse-vol tested; underperforms equal). ~~Follow-up: gate-aware basket~~ — **DONE** (selection on trailing Sharpe also underperforms; see above). Both confirm equal-weight diversification is the baseline to beat.
6. ~~**Hygiene**~~ — **DONE**: `ruff` clean (config in `pyproject.toml`, run in CI) + GitHub Actions (pytest + synthetic smoke-test).
7. ~~*(Cleanup)* dead `vol_target_annual`~~ — **DONE** (removed; vol-targeting is structural).
8. ~~**Volume-confirmation filter**~~ — **DONE (inconclusive, OFF by default)**: see above; non-monotonic across the ratio sweep, best point still fails PBO.
9. **Macro features (DXY, US Treasury yields)** — NOT started. No exogenous-series ingestion exists yet (`make_source()` only loads single-symbol OHLCV+spread); would need (a) a new data path for an external index/yield series, (b) a re-estimated causal feature (e.g. rolling z-score/correlation, never a fixed gold↔real-yield rule — see README §1.4), (c) the same CPCV/PBO/DSR gate, no shortcut. Blocked on confirming whether IUX serves a DXY/yield-proxy symbol at all.

## Out of scope (by design)
- Live order routing (research-only).
- ML alpha (edge here is rules-based TSMOM).
- Hardcoded macro rules (gold↔real-yield etc.).
