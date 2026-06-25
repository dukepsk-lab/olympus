"""Probability of Backtest Overfitting (PBO) via Combinatorially Symmetric
Cross-Validation (CSCV) -- Bailey, Borwein, Lopez de Prado & Zhu (2014).

CSCV procedure:
  1. Given a (T periods x N strategies) returns matrix, split the rows into ``S``
     contiguous partitions.
  2. For every way of choosing S/2 partitions as in-sample (IS) and the rest as
     out-of-sample (OOS):
       * find the IS-best strategy n* (max IS Sharpe),
       * rank n*'s OOS performance among all N strategies (goodness r in (0,1),
         1 = best OOS),
       * logit lambda = ln(r / (1-r)).
  3. PBO = fraction of combinations with lambda <= 0, i.e. the IS-best lands in
     the BOTTOM HALF out-of-sample.

A high PBO means the IS winner was chosen by overfit noise; treat it as a stop
sign regardless of the in-sample equity curve.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
from scipy.stats import rankdata


def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray,
    n_partitions: int = 16,
    max_combos: int | None = 20000,
) -> dict:
    """Compute PBO via CSCV.

    Parameters
    ----------
    returns_matrix : (T, N) array
        T periods (rows) x N strategies/parameter-sets (columns).
    n_partitions : int
        Number of contiguous partitions S (must be >= 2; S/2 form the IS half).
    max_combos : int | None
        If C(S, S/2) exceeds this, sample combos deterministically to bound cost.

    Returns
    -------
    dict with ``pbo`` (float in [0,1]), ``logits`` (ndarray), ``n_combos`` (int).
    Fail-safe: PBO = 1.0 (overfit assumed) when N < 2 or S < 2.

    Speed: per-partition performance is precomputed ONCE into an (S x N) matrix,
    so each IS/OOS combination is just a sum + rank over length-N vectors (the
    naive recompute-over-full-matrix approach is O(C(S,S/2) * T * N) and would
    dominate runtime for large T).
    """
    M = np.asarray(returns_matrix, dtype=float)
    if M.ndim != 2:
        raise ValueError("returns_matrix must be 2D (T x N)")
    T, N = M.shape
    if N < 2 or n_partitions < 2 or T < n_partitions * 2:
        return {"pbo": 1.0, "logits": np.array([]), "n_combos": 0}

    S = int(n_partitions)
    blocks = np.array_split(np.arange(T), S)
    # per-partition, per-path mean return (NaN-treated) -- (S x N)
    block_perf = np.empty((S, N))
    for i, b in enumerate(blocks):
        seg = M[b]
        with np.errstate(all="ignore"):
            block_perf[i] = np.nanmean(seg, axis=0)
    block_perf = np.nan_to_num(block_perf, nan=0.0)

    is_half = S // 2
    all_combos = list(combinations(range(S), is_half))
    if max_combos is not None and len(all_combos) > max_combos:
        rng = np.random.default_rng(0)
        sel = np.sort(rng.choice(len(all_combos), size=max_combos, replace=False))
        all_combos = [all_combos[i] for i in sel]

    eps = 1e-6
    logits = np.empty(len(all_combos))
    all_idx = set(range(S))
    for k, is_blocks in enumerate(all_combos):
        oos_blocks = tuple(all_idx - set(is_blocks))
        is_perf = block_perf[list(is_blocks)].sum(axis=0)
        oos_perf = block_perf[list(oos_blocks)].sum(axis=0)
        n_star = int(np.argmax(is_perf))
        r_rank = rankdata(oos_perf)[n_star]          # 1=smallest perf .. N=largest
        r = (r_rank - 1.0) / max(N - 1, 1)
        r = float(np.clip(r, eps, 1.0 - eps))
        logits[k] = np.log(r / (1.0 - r))

    pbo = float(np.mean(logits <= 0.0)) if logits.size else 1.0
    return {"pbo": pbo, "logits": logits, "n_combos": len(all_combos)}


__all__ = ["probability_of_backtest_overfitting"]
