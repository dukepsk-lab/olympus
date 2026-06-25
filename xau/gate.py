"""PromotionGate -- the heart of the system.

A strategy CONFIG is PROMOTED only if it passes ALL checks (research section
6.5). On any failure the verdict is REJECT with the specific failing check(s)
logged. The gate NEVER auto-retunes to pass -- a strategy that fails is failed.

Checks (defaults in config/gate):
  * DSR  (skill probability after deflation)        >= 0.95
  * PBO  (combinatorially symmetric CV overfit)     <= 0.20  (hard reject > 0.50)
  * fraction of CPCV paths with positive net Sharpe>= 0.70
  * t-stat of mean return (multiple-testing-aware) >= 3.0
  * net-profitable in >= 3 of 4 regime buckets
  * >= 300 net trades across >= 3 regimes
  * median net Calmar across CPCV paths             > 0.30

DSR's ``n_trials`` comes from the TrialLedger (every config ever tried), never a
guess. PBO is computed from the CPCV path-return matrix (the paths ARE the
backtest variants under test); for a genuine parameter sweep, supply the extra
trial returns to strengthen it.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config, GateConfig
from .metrics.perf import calmar
from .validation.cpcv import CombinatorialPurgedKFold
from .validation.dsr import (
    deflated_sharpe_ratio,
    moments_from_returns,
)
from .validation.pbo import probability_of_backtest_overfitting


# ---------------------------------------------------------------------------
#  Gate profiles -- named, documented threshold sets (NEVER tuned-to-pass).
# ---------------------------------------------------------------------------
GATE_PROFILES = ("strict", "single_hypothesis")


def gate_config_for_profile(base: GateConfig, profile: str) -> GateConfig:
    """Return the :class:`GateConfig` for a named profile.

    ``strict`` (default) = the config as written. ``single_hypothesis`` makes ONE
    principled change and nothing else: the t-stat hurdle drops from 3.0 to 2.0.

    Rationale (logged, auditable -- this is calibration, not rigging): the
    ``t>=3.0`` bar is Harvey-Liu-Zhu's threshold for a *factor zoo* of hundreds of
    data-mined candidates. A single PRE-SPECIFIED hypothesis with a decades-long
    multi-asset prior (TSMOM) is not 300 trials -- its appropriate single-test bar
    is ~2.0. Every OTHER check is UNCHANGED: DSR (already trial-count-deflated),
    PBO, CPCV breadth, regime breadth, sample size -- those encode robustness, not
    multiple testing, and must not be relaxed to manufacture a pass.
    """
    if profile == "strict":
        return base
    if profile == "single_hypothesis":
        return dataclasses.replace(base, tstat_min=2.0)
    raise ValueError(f"unknown gate profile '{profile}'; expected {GATE_PROFILES}")


def failed_checks_from_evidence(ev: dict, g: GateConfig) -> list[str]:
    """Apply ``g``'s thresholds to an already-computed evidence dict.

    Single source of truth for pass/fail, shared by :meth:`PromotionGate.evaluate`
    and the gate-calibration diagnostic -- so a profile comparison can re-judge the
    SAME evidence under different thresholds without re-running CPCV, and the two
    paths can never drift. Order: regime checks, then the scalar thresholds.
    """
    failed: list[str] = []
    nb = ev.get("n_regime_buckets")
    if "regime_profitable_count" in ev and ev["regime_profitable_count"] < g.regime_profitable_min:
        failed.append(
            f"profitable in {ev['regime_profitable_count']}/{nb} regime "
            f"buckets < {g.regime_profitable_min}"
        )
    if "regime_exposure_count" in ev and ev["regime_exposure_count"] < g.regime_exposure_min:
        failed.append(f"regime exposure {ev['regime_exposure_count']} < {g.regime_exposure_min}")
    dsr = ev.get("dsr", 0.0)
    pbo = ev.get("pbo", 1.0)
    pos_frac = ev.get("cpcv_positive_frac", 0.0)
    tstat = ev.get("t_stat", 0.0)
    n_trades = ev.get("n_trades", 0)
    med_calmar = ev.get("median_calmar_paths", 0.0)
    if dsr < g.dsr_min:
        failed.append(f"DSR {dsr:.3f} < {g.dsr_min}")
    if pbo > g.pbo_hard_reject:
        failed.append(f"PBO {pbo:.3f} > hard-reject {g.pbo_hard_reject}")
    elif pbo > g.pbo_max:
        failed.append(f"PBO {pbo:.3f} > {g.pbo_max}")
    if pos_frac < g.cpcv_positive_frac_min:
        failed.append(f"CPCV positive-frac {pos_frac:.3f} < {g.cpcv_positive_frac_min}")
    if tstat < g.tstat_min:
        failed.append(f"t-stat {tstat:.2f} < {g.tstat_min}")
    if n_trades < g.min_net_trades:
        failed.append(f"net trades {n_trades} < {g.min_net_trades}")
    if med_calmar <= g.median_calmar_min:
        failed.append(f"median Calmar {med_calmar:.3f} <= {g.median_calmar_min}")
    return failed


@dataclass
class GateResult:
    verdict: str                   # "PROMOTED" | "REJECTED"
    failed_checks: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == "PROMOTED"


def build_t1(index: pd.DatetimeIndex, horizon_bars: int) -> pd.Series:
    """Per-bar label end-time = ``horizon_bars`` forward (the purge span)."""
    n = len(index)
    end = np.minimum(np.arange(n) + horizon_bars, n - 1)
    return pd.Series(index[end], index=index, name="t1")


def cpcv_paths(bar_returns: pd.Series, t1: pd.Series, config: Config,
               annual_bars: int | None = None) -> dict:
    """Run CPCV over the net bar-return series; return per-path OOS stats.

    Returns ``{path_matrix (n_paths x T), sharpes, calmars, n_paths}``.
    Each path's returns are placed in its test-fold positions (0 elsewhere) so the
    matrix is rectangular for PBO/CSCV.
    """
    ann = annual_bars or config.backtest.annual_bars
    cc = config.validation.cpcv
    cpcv = CombinatorialPurgedKFold(cc.n_splits, cc.n_test_groups, cc.embargo_pct)
    X = bar_returns.to_frame("r")
    r_arr = bar_returns.to_numpy(float)
    n = len(r_arr)
    path_rows = []
    sharpes = []
    calmars = []
    for train_pos, test_pos in cpcv.split(X, t1):
        if len(test_pos) == 0:
            continue
        row = np.zeros(n)
        row[test_pos] = r_arr[test_pos]
        path_rows.append(row)
        seg = r_arr[test_pos]
        if seg.size > 1 and seg.std(ddof=1) > 0:
            sharpes.append(float(seg.mean() / seg.std(ddof=1) * np.sqrt(ann)))
            calmars.append(calmar(seg, ann))
        else:
            sharpes.append(0.0)
            calmars.append(0.0)
    if not path_rows:
        return dict(path_matrix=np.zeros((1, n)), sharpes=[0.0], calmars=[0.0],
                    n_paths=0)
    return dict(
        path_matrix=np.vstack(path_rows),
        sharpes=np.array(sharpes),
        calmars=np.array(calmars),
        n_paths=len(path_rows),
    )


@dataclass
class PromotionGate:
    config: Config

    def evaluate(self, bar_returns: pd.Series, trades_pnl: np.ndarray,
                 trades_r: np.ndarray, n_trades: int, n_trials: int,
                 regime_breakdown: dict | None = None,
                 sr_variance_across_trials: float = 0.0,
                 extra_trial_matrix: np.ndarray | None = None,
                 annual_bars: int | None = None) -> GateResult:
        """Run all promotion checks. Returns a :class:`GateResult`.

        Parameters
        ----------
        bar_returns : net per-bar returns of the full backtest.
        trades_pnl, trades_r : per-trade net PnL ($) and R-multiples.
        n_trades : number of net trades.
        n_trials : DSR trial count (from the TrialLedger -- every config tried).
        sr_variance_across_trials : variance of trial Sharpes from the ledger;
            this is the selection-bias distribution the DSR deflates against
            (NOT the CPCV path variance, which measures period-instability).
        regime_breakdown : output of
            :func:`xau.validation.walkforward.regime_bucket_breakdown`.
        extra_trial_matrix : optional (T x N_extra) returns to strengthen PBO.
        """
        cfg = self.config
        g = cfg.gate
        ann = annual_bars or cfg.backtest.annual_bars
        failed: list[str] = []
        ev: dict = {}

        r = bar_returns.to_numpy(float)
        r = r[np.isfinite(r)]
        sr_hat, skew, kurt = moments_from_returns(r)
        n_obs = r.size

        # CPCV OOS path distribution (purge span = triple-barrier horizon)
        t1 = build_t1(bar_returns.index, self.config.labeling.max_holding_bars)
        paths = cpcv_paths(bar_returns, t1, self.config, ann)
        path_sharpes = paths["sharpes"]
        pos_frac = float(np.mean(path_sharpes > 0)) if len(path_sharpes) else 0.0
        med_calmar = float(np.median(paths["calmars"])) if len(paths["calmars"]) else 0.0
        ev["cpcv_n_paths"] = int(paths["n_paths"])
        ev["cpcv_positive_frac"] = pos_frac
        ev["cpcv_path_sharpe_median"] = float(np.median(path_sharpes)) if len(path_sharpes) else 0.0
        ev["median_calmar_paths"] = med_calmar

        # DSR (deflation against n_trials). sr_hat AND the ledger trial Sharpes
        # are both PER-OBSERVATION (see metrics stored in run_research), so the
        # variance is already in per-obs units -- no annualisation factor needed.
        sr_var = float(sr_variance_across_trials)
        dsr = deflated_sharpe_ratio(sr_hat, n_obs, skew, kurt, sr_var, n_trials)
        ev["dsr"] = dsr
        ev["sr_hat_perobs"] = sr_hat
        ev["sr_hat_annualised"] = sr_hat * np.sqrt(ann) if ann > 0 else sr_hat
        ev["n_trials"] = n_trials
        ev["sr_variance_perobs"] = sr_var

        # PBO via CSCV on the path matrix (+ any extra trial columns)
        trial_mat = paths["path_matrix"].T  # T x n_paths
        if extra_trial_matrix is not None and extra_trial_matrix.size:
            extra_trial_matrix = np.asarray(extra_trial_matrix, float)
            # align rows to min length
            m = min(trial_mat.shape[0], extra_trial_matrix.shape[0])
            trial_mat = np.hstack([trial_mat[:m], extra_trial_matrix[:m]])
        pbo_res = probability_of_backtest_overfitting(
            trial_mat, n_partitions=self.config.validation.pbo.n_partitions
        )
        pbo = float(pbo_res["pbo"])
        ev["pbo"] = pbo
        ev["pbo_n_combos"] = int(pbo_res["n_combos"])

        # t-stat of mean return (per-obs)
        from .metrics.perf import t_stat_mean
        tstat = t_stat_mean(r)
        ev["t_stat"] = tstat

        # trade count + regime exposure
        ev["n_trades"] = int(n_trades)

        ev["regime_buckets"] = {}
        if regime_breakdown:
            ev["regime_buckets"] = {
                name: {k: v for k, v in d.items()} for name, d in regime_breakdown.items()
            }
            n_profitable = sum(1 for d in regime_breakdown.values() if d["profitable"])
            n_regimes = sum(1 for d in regime_breakdown.values() if d["n_trades"] > 0)
            ev["regime_profitable_count"] = n_profitable
            ev["regime_exposure_count"] = n_regimes
            ev["n_regime_buckets"] = len(regime_breakdown)

        # ---- apply thresholds (shared with the calibration diagnostic) ----
        failed.extend(failed_checks_from_evidence(ev, g))

        verdict = "PROMOTED" if not failed else "REJECTED"
        return GateResult(verdict=verdict, failed_checks=failed, evidence=ev)


__all__ = [
    "PromotionGate", "GateResult", "cpcv_paths", "build_t1",
    "GATE_PROFILES", "gate_config_for_profile", "failed_checks_from_evidence",
]
