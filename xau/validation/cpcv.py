"""Combinatorial Purged K-Fold (CPCV) -- Lopez de Prado, AFML ch.7/12.

Implemented from scratch (no ``mlfinlab`` dependency). CPCV holds out every
combination of ``n_test_groups`` out of ``n_splits`` contiguous groups, giving
``C(n_splits, n_test_groups)`` IS/OOS combinations. Two leakage guards are
applied to every TRAIN set:

  * PURGE: drop any training observation whose forward-looking label span
    ``[t0, t1]`` overlaps a test group's time window. (Triple-barrier labels look
    forward by definition; without purging they leak test-period information
    into training.)
  * EMBARGO: drop training observations within ``embargo_pct`` of the bars
    immediately FOLLOWING each test block, killing the serial-correlation
    leakage at the train/test boundary.

``n_backtest_paths`` = ``C(n_splits, n_test_groups)``: each combination's OOS
test fold is one reconstructable backtest path.
"""
from __future__ import annotations

from itertools import combinations
from typing import Iterator

import numpy as np
import pandas as pd


def _n_choose_k(n: int, k: int) -> int:
    k = min(k, n - k)
    num = 1
    den = 1
    for i in range(k):
        num *= (n - i)
        den *= (i + 1)
    return num // den


class CombinatorialPurgedKFold:
    def __init__(self, n_splits: int = 10, n_test_groups: int = 2,
                 embargo_pct: float = 0.01):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if not 1 <= n_test_groups < n_splits:
            raise ValueError("need 1 <= n_test_groups < n_splits")
        self.n_splits = n_splits
        self.n_test_groups = n_test_groups
        self.embargo_pct = float(embargo_pct)

    @property
    def n_combinations(self) -> int:
        return _n_choose_k(self.n_splits, self.n_test_groups)

    @property
    def n_backtest_paths(self) -> int:
        return self.n_combinations

    def _group_bounds(self, n_obs: int) -> np.ndarray:
        """Return (n_splits+1,) array of position boundaries (contiguous groups)."""
        return np.array_split(np.arange(n_obs), self.n_splits)

    def _contiguous_blocks(self, test_positions: np.ndarray) -> list[tuple[int, int]]:
        """Collapse a sorted position array into [start, end] inclusive runs."""
        if test_positions.size == 0:
            return []
        blocks = []
        start = prev = int(test_positions[0])
        for p in test_positions[1:]:
            if p == prev + 1:
                prev = p
            else:
                blocks.append((start, prev))
                start = prev = p
        blocks.append((start, prev))
        return blocks

    def split(self, X: pd.DataFrame, t1: pd.Series,
              y: object = None) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield ``(train_positions, test_positions)`` for each combination.

        Parameters
        ----------
        X : pd.DataFrame
            Feature frame; only its index length and times are used.
        t1 : pd.Series
            Label end-times aligned to ``X.index``. The span of observation *i*
            is ``[X.index[i], t1.iloc[i]]``. ``NaT``/NaN spans are treated as
            zero-length (entry only) so they never trigger a purge.

        Each combination yields a NEW object so callers can store references.
        """
        idx = X.index
        n = len(idx)
        if len(t1) != n:
            raise ValueError("t1 length must match X")
        if isinstance(idx, pd.DatetimeIndex):
            t0_ns = idx.asi8.astype(np.int64)
        else:
            t0_ns = np.arange(n, dtype=np.int64)
        # t1 aligned to idx; NaT -> use t0 (zero-length span, never overlaps)
        t1_aligned = t1.reindex(idx)
        t1_ts = t1_aligned.apply(lambda x: pd.Timestamp(x) if pd.notna(x) else pd.NaT)
        if isinstance(idx, pd.DatetimeIndex):
            t1_ns = np.where(
                t1_ts.notna().to_numpy(),
                pd.DatetimeIndex(t1_ts.fillna(idx[0])).asi8,
                t0_ns,
            )
        else:
            t1_ns = t0_ns.copy()

        groups = self._group_bounds(n)             # list of position arrays
        group_starts = np.array([g[0] for g in groups], dtype=np.int64)
        group_ends = np.array([g[-1] for g in groups], dtype=np.int64)
        embargo_n = int(np.ceil(self.embargo_pct * n))

        all_positions = np.arange(n, dtype=np.int64)
        for combo in combinations(range(self.n_splits), self.n_test_groups):
            test_pos = np.concatenate([groups[g] for g in combo])
            test_pos.sort()
            test_mask = np.zeros(n, dtype=bool)
            test_mask[test_pos] = True

            train_mask = ~test_mask

            # --- PURGE: remove train obs whose [t0,t1] overlaps a test block ---
            for gs, ge in zip(group_starts[list(combo)], group_ends[list(combo)]):
                block_t0 = t0_ns[gs]
                block_t1 = t0_ns[ge]
                # overlap of train span [t0_i, t1_i] with [block_t0, block_t1]:
                #   t0_i <= block_t1 AND t1_i >= block_t0
                overlaps = (t0_ns <= block_t1) & (t1_ns >= block_t0)
                train_mask &= ~overlaps

            # --- EMBARGO: remove train obs just AFTER each contiguous test block ---
            blocks = self._contiguous_blocks(test_pos)
            for (bs, be) in blocks:
                emb_start = be + 1
                emb_end = min(be + embargo_n, n - 1)
                if emb_start <= emb_end:
                    train_mask[emb_start : emb_end + 1] = False

            train_idx = all_positions[train_mask]
            yield train_idx, test_pos


__all__ = ["CombinatorialPurgedKFold"]
